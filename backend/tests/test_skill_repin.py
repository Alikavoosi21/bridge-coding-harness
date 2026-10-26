import json

import pytest

from harness.skills_registry import SkillRegistry
from harness.skill_repin import preview,repin,marker,finish_replan,reset_checkpoint_cache
from harness.task_runtime import open_task_runtime,task_directory
from harness.workspace import Workspace
from server.errors import ApiError
from server.storage import Database,Store,migrate


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'main.py').write_text('original',encoding='utf8')
    store=Store(Database());migrate(store.db)
    ws=store.upsert_workspace(str(workspace.root));task=store.create_task(workspace_id=ws['id'],prompt='repin fixture',read_only=True)
    source=tmp_path/'skill';source.mkdir()
    text='---\nname: check-code\ndescription: OLD DESCRIPTION\n---\n\nOLD BODY\n'
    (source/'SKILL.md').write_text(text,encoding='utf8')
    registry=SkillRegistry(store);registered=registry.register(source,scope='personal')
    registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
    assembly=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60);assembly.close()
    store.set_task_status(task['id'],'paused',reason='fixture stopped')
    plan=store.save_plan(task['id'],steps=[{'title':'Old plan','status':'pending'}],scope=['main.py'],checks=[])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    (source/'SKILL.md').write_text(text.replace('OLD','NEW'),encoding='utf8')
    changed=registry.detail(registered['id']);registry.enable(registered['id'],expected_hash=changed['current_hash'],confirm=True)
    proposal=preview(store,task['id'])
    args={'key':'repin-once','expected_revision':proposal['task_revision'],'expected_working_revision':proposal['working_revision'],'expected_working_hash':proposal['working_manifest_hash'],'expected_pins_hash':proposal['pins_hash'],'confirm':True}
    return store,workspace,task,args,assembly


def test_legacy_skill_migration_archives_bytes_and_rejects_changed_preview(fixture):
    store,workspace,task,args,_=fixture
    root=task_directory(store,task['id'])/'knowledge'/'skills'
    legacy=root/'legacy-helper';legacy.mkdir()
    (legacy/'SKILL.md').write_text('unreviewed legacy bytes',encoding='utf8')
    first=preview(store,task['id'])
    assert first['legacy_entries']==['legacy-helper']
    args={**args,'expected_pins_hash':first['pins_hash']}
    (legacy/'SKILL.md').write_text('changed legacy bytes',encoding='utf8')
    with pytest.raises(ApiError) as stale:repin(store,task['id'],**args)
    assert stale.value.code=='selection_stale'
    fresh=preview(store,task['id'])
    result=repin(store,task['id'],**{**args,'expected_pins_hash':fresh['pins_hash']})
    archived=task_directory(store,task['id'])/'skill-repins'/result['operation_id']/'previous-skills'/'legacy-helper'/'SKILL.md'
    assert archived.read_text(encoding='utf8')=='changed legacy bytes'
    assert not legacy.exists() and store.task(task['id'])['read_only']


def test_repin_requires_confirmation_invalidates_plan_and_never_grants_writes(fixture):
    store,workspace,task,args,_=fixture
    with pytest.raises(ApiError):repin(store,task['id'],**{**args,'confirm':False})
    result=repin(store,task['id'],**args)
    assert repin(store,task['id'],**args)==result
    assert store.task(task['id'])['status']=='awaiting_plan'
    assert store.task(task['id'])['read_only']
    assert store.plan(task['id'])['approved_revision'] is None
    assert 'NEW BODY' in (task_directory(store,task['id'])/'knowledge'/'skills'/'check-code'/'SKILL.md').read_text(encoding='utf8')
    assert (workspace.root/'main.py').read_text(encoding='utf8')=='original'
    with pytest.raises(ApiError) as approve:store.decide_plan(task['id'],expected_revision=store.plan(task['id'])['revision'],approve=True)
    assert approve.value.code=='action_not_approved'
    with store.db.read() as db:assert db.execute('SELECT COUNT(*) FROM grants').fetchone()[0]==0


async def test_real_langgraph_cache_reset_is_durable_and_new_plan_must_be_written(fixture,tmp_path):
    from deepagents import create_deep_agent
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain_core.messages import AIMessage,HumanMessage
    from harness.demo_model import ScriptedChatModel
    store,workspace,task,args,assembly=fixture
    config={'configurable':{'thread_id':task['thread_id']}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'repin-checkpoints.db')) as saver:
        agent=create_deep_agent(model=ScriptedChatModel(script=[AIMessage(content='done')]),backend=assembly.backend,skills=['/.harness/skills/'],checkpointer=saver)
        await agent.ainvoke({'messages':[HumanMessage(content='Inspect metadata')]},config)
        old=await agent.aget_state(config)
        assert any(row['description']=='OLD DESCRIPTION' for row in old.values['skills_metadata'])
        repin(store,task['id'],**args)
        assert marker(store,task['id'])['cache_reset_pending']
        assert await reset_checkpoint_cache(agent,config,store,task['id'])
        reset=await agent.aget_state(config)
        assert reset.values['skills_metadata'] is None
        assert len(reset.values['messages'])==len(old.values['messages'])+1
        assert reset.values['messages'][-1].id.startswith('skill-repin:')
        assert not await reset_checkpoint_cache(agent,config,store,task['id'])
        finish_replan(store,task['id'])
        assert marker(store,task['id'])['needs_replan'] # old plan is insufficient
        await agent.ainvoke({'messages':[HumanMessage(content='Re-read after explicit repin')]},config)
        new=await agent.aget_state(config)
        assert any(row['description']=='NEW DESCRIPTION' for row in new.values['skills_metadata'])
        store.save_plan(task['id'],steps=[{'title':'Fresh read-only plan','status':'pending'}],scope=['main.py'],checks=[])
        finish_replan(store,task['id'])
        assert not marker(store,task['id'])['needs_replan']
        plan=store.plan(task['id']);assert store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)['approved_revision']==plan['revision']


def test_interrupted_repin_preserves_archive_and_cannot_resume_or_replay(fixture,monkeypatch):
    import harness.skill_repin as module
    from harness.runtime.docker import RuntimeUnavailable
    store,workspace,task,args,_=fixture
    original=module._write
    def interrupt(path,value):
        if path.name=='skill-repin.json' and value.get('status')=='applied':raise OSError('fixture interrupted after skill swap')
        return original(path,value)
    monkeypatch.setattr(module,'_write',interrupt)
    with pytest.raises(OSError):repin(store,task['id'],**args)
    assert store.task(task['id'])['status']=='recovery_required'
    assert list((task_directory(store,task['id'])/'skill-repins').glob('*/previous-skills/check-code/SKILL.md'))
    with pytest.raises(ApiError) as replay:repin(store,task['id'],**args)
    assert replay.value.code=='recovery_required'
    with pytest.raises(RuntimeUnavailable):open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    assert store.worker_lease() is None


def test_active_task_cannot_repin(fixture):
    store,_,task,args,_=fixture
    store.set_task_status(task['id'],'executing',reason='fixture active')
    with pytest.raises(ApiError) as busy:repin(store,task['id'],**args)
    assert busy.value.code=='workspace_busy'


def test_interrupted_repin_can_explicitly_roll_back_archive_without_replaying(fixture,monkeypatch):
    import harness.skill_repin as module
    from harness.recovery import inspect_recovery
    store,workspace,task,args,_=fixture
    original=module._write
    def interrupt(path,value):
        if path.name=='skill-repin.json' and value.get('status')=='applied':raise OSError('after swap')
        return original(path,value)
    monkeypatch.setattr(module,'_write',interrupt)
    with pytest.raises(OSError):repin(store,task['id'],**args)
    monkeypatch.setattr(module,'_write',original)
    current=inspect_recovery(store,task['id']);action=current['actions'][0]
    module.rollback_repin(store,task['id'],action['operation_id'],expected_working_revision=current['working_revision'],expected_working_hash=current['working_hash'],expected_skill_hash=current['skill_hash'],confirm=True)
    text=(task_directory(store,task['id'])/'knowledge'/'skills'/'check-code'/'SKILL.md').read_text(encoding='utf8')
    assert 'OLD BODY' in text and store.task(task['id'])['status']=='awaiting_plan'
    assert store.plan(task['id'])['approved_revision'] is None
    assert store.action(action['operation_id'])['state']=='failed'
    assert list((task_directory(store,task['id'])/'skill-repins').glob('*/abandoned-skills/check-code/SKILL.md'))


async def test_repin_http_is_explicit_and_retries_same_receipt(fixture):
    import httpx
    from server.app import create_app
    from server import settings
    store,workspace,task,args,_=fixture
    settings.save({**settings.load(),'current_workspace':str(workspace.root),'workspaces':[str(workspace.root)]})
    base='/tasks/'+task['id']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        proposed=await api.get(base+'/skill-repin-preview')
        assert proposed.status_code==200 and proposed.json()['pins_hash']==args['expected_pins_hash']
        body={**args,'idempotency_key':args['key']};del body['key']
        assert (await api.post(base+'/skill-repins',json={**body,'confirm':False})).status_code==409
        first=await api.post(base+'/skill-repins',json=body)
        assert first.status_code==200,first.json()
        assert first.json()['needs_replan']
        assert (await api.post(base+'/skill-repins',json=body)).json()==first.json()
    assert store.task(task['id'])['read_only']
