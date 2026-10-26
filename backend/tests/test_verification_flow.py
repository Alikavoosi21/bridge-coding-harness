"""Durable repair allowance; no model, fake check success, or host shell."""
import httpx
import pytest

from harness.verification.budget import RepairBudget
from server.app import create_app
from server.errors import ApiError
from server.storage import Database,Store,migrate


@pytest.fixture
def fixture(tmp_path):
    db=Database(tmp_path/'product.db');migrate(db);store=Store(db)
    ws=store.upsert_workspace(str(tmp_path/'project'))
    task=store.create_task(workspace_id=ws['id'],prompt='fixture')
    store.set_task_status(task['id'],'verifying')
    return store,task,RepairBudget(store)


def test_two_repairs_survive_restart_and_replay_does_not_spend_a_third(fixture):
    store,task,budgets=fixture
    first=budgets.claim(task['id'],key='first',expected_revision=1,reason='failed assertions')
    restarted=RepairBudget(Store(Database(store.db.path)))
    assert restarted.claim(task['id'],key='first',expected_revision=1,reason='failed assertions')==first
    assert restarted.read(task['id'])['total_attempts']==1
    second=restarted.claim(task['id'],key='second',expected_revision=2,reason='still failing')
    assert second['allowed']==second['total_attempts']==2
    with pytest.raises(ApiError) as failure:
        restarted.claim(task['id'],key='third',expected_revision=3,reason='still failing')
    assert failure.value.code=='budget_exhausted'
    events=[e for e in store.events(task['id'])['items'] if e['type']=='repair_started']
    assert [e['payload']['repair_index'] for e in events]==[1,2]


def test_extension_is_explicit_revision_bound_and_does_not_reset_consumption(fixture):
    store,task,budgets=fixture
    with pytest.raises(ApiError):budgets.extend(task['id'],key='too-early',expected_revision=1)
    budgets.claim(task['id'],key='one',expected_revision=1,reason='failed')
    budgets.claim(task['id'],key='two',expected_revision=2,reason='failed')
    store.set_task_status(task['id'],'awaiting_decision')
    extended=budgets.extend(task['id'],key='human-one-more',expected_revision=3)
    assert extended['total_attempts']==2 and extended['allowed']==3 and extended['revision']==4
    assert budgets.extend(task['id'],key='human-one-more',expected_revision=3)==extended
    assert store.task(task['id'])['status']=='awaiting_decision'
    with pytest.raises(ApiError) as stale:budgets.extend(task['id'],key='stale',expected_revision=3)
    assert stale.value.code=='budget_revision_mismatch'
    with pytest.raises(ApiError) as conflict:budgets.extend(task['id'],key='human-one-more',expected_revision=4)
    assert conflict.value.code=='idempotency_conflict'
    store.set_task_status(task['id'],'repairing')
    assert budgets.claim(task['id'],key='three',expected_revision=4,reason='human extension')['total_attempts']==3


async def test_budget_http_read_has_no_effect_and_extension_never_dispatches(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        await api.post('/workspace',json={'path':str(tmp_path/'project')})
        task=(await api.post('/tasks',json={'prompt':'fixture'})).json()['task']
        base=f"/tasks/{task['id']}"
        read=await api.get(base+'/repair-budget')
        assert read.status_code==200 and read.json()['allowed']==2 and read.json()['total_attempts']==0
        checks=await api.get(base+'/checks')
        assert checks.status_code==200 and checks.json()['items']==[]
        assert checks.json()['quality']['quality_status']=='not_verified'
        store=Store();store.set_task_status(task['id'],'verifying');budget=RepairBudget(store)
        budget.claim(task['id'],key='one',expected_revision=1,reason='failed')
        budget.claim(task['id'],key='two',expected_revision=2,reason='failed')
        store.set_task_status(task['id'],'awaiting_decision')
        body={'expected_revision':3,'idempotency_key':'human-extension'}
        for _ in range(2):
            response=await api.post(base+'/repair-extensions',json=body)
            assert response.status_code==200 and response.json()['allowed']==3
        assert store.task(task['id'])['status']=='awaiting_decision'
        assert len(store.task(task['id'])['runs'])==1
        assert (await api.get(base+'/repair-budget')).json()['total_attempts']==2


@pytest.mark.parametrize('unknown',[False,True])
async def test_human_ending_is_idempotent_unverified_and_refuses_unknown_operations(tmp_path,monkeypatch,unknown):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        root=tmp_path/'project';root.mkdir();original=root/'original.py';original.write_text('user data',encoding='utf8')
        await api.post('/workspace',json={'path':str(root)})
        task=(await api.post('/tasks',json={'prompt':'fixture'})).json()['task']
        store=Store();store.set_task_status(task['id'],'awaiting_decision')
        current=store.task(task['id']);body={'expected_revision':current['revision'],'idempotency_key':'human-end'}
        if unknown:
            action=store.ensure_action(task['id'],'unknown-fixture','hash')
            store.set_action_state(action['operation_id'],'unknown')
        endpoint=f"/tasks/{task['id']}/quality-endings"
        response=await api.post(endpoint,json=body)
        if unknown:
            assert response.status_code==409 and response.json()['code']=='recovery_required'
            assert store.task(task['id'])['status']=='awaiting_decision'
        else:
            assert response.status_code==200 and response.json()['task']['outcome']=='user_ended_unverified'
            replay=await api.post(endpoint,json=body)
            assert replay.status_code==200 and replay.headers['Idempotent-Replayed']=='true'
            assert response.json()['task']['revision']==replay.json()['task']['revision']
            stale=await api.post(endpoint,json={**body,'idempotency_key':'stale','expected_revision':1})
            assert stale.status_code==409
        assert original.read_text(encoding='utf8')=='user data'
        assert len(store.task(task['id'])['runs'])==1


def test_receipt_failure_rolls_back_counter_and_repair_event_together(fixture):
    import sqlite3
    store,task,budgets=fixture
    with store.db.write() as db:
        db.execute("CREATE TRIGGER fail_repair_receipt BEFORE INSERT ON command_request_keys WHEN NEW.key LIKE 'repair:%' BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        budgets.claim(task['id'],key='one',expected_revision=1,reason='failed')
    assert budgets.read(task['id'])['total_attempts']==0
    assert not any(event['type']=='repair_started' for event in store.events(task['id'])['items'])
    with store.db.write() as db:db.execute('DROP TRIGGER fail_repair_receipt')
    assert budgets.claim(task['id'],key='one',expected_revision=1,reason='failed')['total_attempts']==1


def test_quality_requires_current_exact_manifest_profile_runtime_and_all_checks(fixture):
    from dataclasses import replace
    from harness.verification.results import CheckResults,CheckTarget
    store,task,_=fixture
    results=CheckResults(store);target=CheckTarget('working_copy','manifest-one','profile-one','runtime-one')
    def record(check,outcome='passed',**kwargs):
        return results.record(task['id'],target=target,check_id=check,outcome=outcome,command='fixture-only',**kwargs)
    record('tests',phase='baseline')
    assert results.quality(task['id'],target=target,required=['tests'])['quality_status']=='not_verified'
    first=record('tests',output='س'*40000)
    assert first['truncated'] and len(first['output'].encode())==65536
    assert results.quality(task['id'],target=target,required=['tests','lint'])['quality_status']=='not_verified'
    record('lint')
    assert results.quality(task['id'],target=target,required=['tests','lint'])['quality_status']=='verified_snapshot'
    for changed in [replace(target,manifest_hash='new'),replace(target,profile_hash='new'),replace(target,runtime_fingerprint='new')]:
        assert results.quality(task['id'],target=changed,required=['tests','lint'])['quality_status']=='stale'
    record('tests','failed',failure_kind='assertion')
    assert results.quality(task['id'],target=target,required=['tests','missing'])['quality_status']=='failed'
    assert results.quality(task['id'],target=target,required=[])['quality_status']=='not_verified'
    for outcome in ['skipped','stopped','timed_out','not_configured']:
        record('tests',outcome)
        assert results.quality(task['id'],target=target,required=['tests'])['quality_status']=='not_verified'


def test_whole_working_copy_success_cannot_certify_a_candidate(fixture):
    from harness.verification.results import CheckResults,CheckTarget
    store,task,_=fixture;results=CheckResults(store)
    working=CheckTarget('working_copy','same-bytes','profile','runtime')
    results.record(task['id'],target=working,check_id='tests',outcome='passed',command='fixture')
    candidate=CheckTarget('apply_candidate','same-bytes','profile','runtime','selection-missing')
    assert results.quality(task['id'],target=candidate,required=['tests'])['quality_status']=='stale'
    with pytest.raises(ApiError) as stale:
        results.record(task['id'],target=candidate,check_id='tests',outcome='passed',command='fixture')
    assert stale.value.code=='selection_stale'
    with store.db.write() as db:
        db.execute('INSERT INTO apply_selections(id,task_id,revision,working_revision,file_ids,original_manifest_hash,candidate_manifest_hash,profile_hash,runtime_fingerprint,quality_status,created_at) VALUES(?,?,1,1,?,?,?,?,?,?,0)',('selection-missing',task['id'],'[]','original','same-bytes','profile','runtime','not_verified'))
    assert results.quality(task['id'],target=candidate,required=['tests'])['quality_status']=='not_verified'
    results.record(task['id'],target=candidate,check_id='tests',outcome='passed',command='fixture')
    assert results.quality(task['id'],target=candidate,required=['tests'])['quality_status']=='verified_snapshot'
    with store.db.write() as db:db.execute("UPDATE apply_selections SET candidate_manifest_hash='changed' WHERE id='selection-missing'")
    assert results.quality(task['id'],target=candidate,required=['tests'])['quality_status']=='stale'
    with pytest.raises(ValueError):CheckTarget('apply_candidate','manifest','profile','runtime')


def quality_hook_fixture(fixture,tmp_path):
    import json
    from types import SimpleNamespace
    from harness.verification.observe import manifest_hash
    from harness.verification.results import CheckResults,CheckTarget
    store,task,budget=fixture
    root=tmp_path/'working';root.mkdir();(root/'main.py').write_text('fixture',encoding='utf-8')
    profile={'profile_hash':'profile','commands':[{'id':'tests','command':'python -m pytest','required':True}]}
    with store.db.write() as db:db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps(profile),task['workspace_id']))
    plan=store.save_plan(task['id'],steps=[{'title':'fixture check'}])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    gateway=SimpleNamespace(store=store,task_id=task['id'],script_root=root,runtime_id='runtime',read_only=False)
    tracker=lambda:SimpleNamespace(stop_reason=None,model_calls=1,emit=lambda *args,**kwargs:None)
    target=CheckTarget('working_copy',manifest_hash(root),'profile','runtime')
    CheckResults(store).record(task['id'],target=target,check_id='tests',outcome='passed',command='python -m pytest',phase='baseline')
    return gateway,tracker,CheckResults(store),target,budget


def test_final_answer_requires_current_checks_and_does_not_spend_repairs_for_missing_evidence(fixture,tmp_path):
    from langchain_core.messages import AIMessage
    from harness.hooks.verify import VerifyHook
    gateway,tracker,results,target,budget=quality_hook_fixture(fixture,tmp_path)
    run=tracker();hook=VerifyHook(run,sensors=[],gateway=gateway)
    state={'messages':[AIMessage(content='done',id='missing')]}
    assert hook.after_model(state,None)['jump_to']=='model'
    assert budget.read(gateway.task_id)['total_attempts']==0
    assert hook.after_model(state,None)['jump_to']=='model'
    assert hook.after_model(state,None) is None and run.stop_reason=='quality_decision'
    results.record(gateway.task_id,target=target,check_id='tests',outcome='passed',command='python -m pytest')
    assert VerifyHook(tracker(),sensors=[],gateway=gateway).after_model(state,None) is None


def test_two_repairs_are_shared_by_fresh_hooks_and_human_extension_allows_only_one_more(fixture,tmp_path):
    from langchain_core.messages import AIMessage
    from harness.hooks.verify import VerifyHook
    from harness.task_controller import TaskController
    gateway,tracker,results,target,budget=quality_hook_fixture(fixture,tmp_path)
    results.record(gateway.task_id,target=target,check_id='tests',outcome='failed',command='python -m pytest')
    for identity in ['attempt-one','attempt-two']:
        hook=VerifyHook(tracker(),sensors=[],gateway=gateway)
        state={'messages':[AIMessage(content='done',id=identity)]}
        assert hook.after_model(state,None)['jump_to']=='model'
        # Same checkpoint final-answer node can replay without spending twice.
        assert VerifyHook(tracker(),sensors=[],gateway=gateway).after_model(state,None)['jump_to']=='model'
    assert budget.read(gateway.task_id)['total_attempts']==2
    run=tracker();hook=VerifyHook(run,sensors=[],gateway=gateway)
    assert hook.after_model({'messages':[AIMessage(content='done',id='third')]},None) is None
    assert run.stop_reason=='quality_decision'
    TaskController(None,gateway.store,model_resolver=lambda:None)._finish(gateway.task_id,phase='execute',stop_reason=run.stop_reason)
    assert gateway.store.task(gateway.task_id)['status']=='awaiting_decision'
    revision=budget.read(gateway.task_id)['revision']
    budget.extend(gateway.task_id,key='human-one-more',expected_revision=revision)
    assert VerifyHook(tracker(),sensors=[],gateway=gateway).after_model({'messages':[AIMessage(content='done',id='extended')]},None)['jump_to']=='model'
    assert budget.read(gateway.task_id)['total_attempts']==3


async def test_real_agent_graph_stops_after_two_repairs_instead_of_accepting_done(fixture,tmp_path):
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from harness.demo_model import ScriptedChatModel
    from harness.hooks.verify import VerifyHook
    gateway,tracker,results,target,budget=quality_hook_fixture(fixture,tmp_path)
    results.record(gateway.task_id,target=target,check_id='tests',outcome='failed',command='python -m pytest')
    model=ScriptedChatModel(script=[AIMessage(content='done one',id='graph-one'),AIMessage(content='done two',id='graph-two'),AIMessage(content='done three',id='graph-three')])
    run=tracker()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'quality-checkpoints.db')) as saver:
        agent=create_agent(model,tools=[],middleware=[VerifyHook(run,sensors=[],gateway=gateway)],checkpointer=saver)
        result=await agent.ainvoke({'messages':[HumanMessage(content='fixture task')]},{'configurable':{'thread_id':'quality-fixture'}})
        assert len([message for message in result['messages'] if isinstance(message,AIMessage)])==3
    assert run.stop_reason=='quality_decision'
    assert budget.read(gateway.task_id)['total_attempts']==2
    assert len([event for event in gateway.store.events(gateway.task_id)['items'] if event['type']=='repair_started'])==2


def test_controller_refuses_completed_without_real_current_check_evidence(fixture,tmp_path):
    from harness.task_controller import TaskController
    gateway,_,_,_,_=quality_hook_fixture(fixture,tmp_path)
    controller=TaskController(None,gateway.store,model_resolver=lambda:None)
    controller._finish(gateway.task_id,phase='execute',stop_reason='completed')
    assert gateway.store.task(gateway.task_id)['status']=='awaiting_decision'
    assert gateway.store.task(gateway.task_id)['outcome'] is None


@pytest.mark.parametrize('repair_succeeds',[False,True])
@pytest.mark.parametrize('multiple_checks',[False,True])
async def test_full_graph_baseline_mutation_checks_two_repairs_and_human_gate(fixture,tmp_path,repair_succeeds,multiple_checks):
    import json
    from langchain.agents import create_agent
    from langchain.agents.middleware import HumanInTheLoopMiddleware
    from langchain_core.messages import AIMessage,HumanMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command
    from harness.backends.container import ContainerBackend
    from harness.runtime.docker import ExecResult
    from harness.demo_model import ScriptedChatModel,call
    from harness.gateway import ToolGateway
    from harness.permissions import build_policy
    from harness.hooks.permission import PermissionHook
    from harness.hooks.verify import VerifyHook
    from harness.verification.observe import current_quality
    from harness.verification.results import CheckResults
    from types import SimpleNamespace

    store,task,budget=fixture
    root=tmp_path/'working';root.mkdir()
    (root/'main.py').write_text('baseline',encoding='utf8')
    (root/'check.py').write_text('# fixture check adapter, never executed on host',encoding='utf8')
    profile={'profile_hash':'profile','commands':[{'id':'tests','command':'python check.py','source':'check.py','required':True}]}
    if multiple_checks:profile['commands'].append({'id':'lint','command':'python check.py --lint','source':'check.py','required':True})
    from harness.worktrees.snapshot import build,write_manifest
    write_manifest(build(root),destination=root)
    with store.db.write() as db:
        db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps(profile),task['workspace_id']))
        db.execute("UPDATE tasks SET mode='auto' WHERE id=?",(task['id'],))
    plan=store.save_plan(task['id'],steps=[{'title':'fixture change'}]);store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    hits=[]
    class FixtureRuntime:
        def execute(self,command,*,snapshot,exec_id,**kwargs):
            assert command in [row['command'] for row in profile['commands']]
            if multiple_checks:(snapshot/'project.tsbuildinfo').write_text('generated incremental compiler cache',encoding='utf8')
            content=(snapshot/'main.py').read_text(encoding='utf8');hits.append(content)
            return ExecResult(exec_id,0 if content in {'baseline','fixed'} else 1,'fixture check: '+content,operation_id=exec_id)
    backend=ContainerBackend(root,FixtureRuntime())
    rules=tmp_path/'rules.yaml';rules.write_text('files: []\ntools: {}',encoding='utf8')
    gateway=ToolGateway(store,task['id'],rules,runtime_available=True,runtime_id='fixture',backend=backend)
    @tool('execute')
    async def execute(command:str)->str:
        """Run only the fixture check adapter; never a host shell."""
        return (await backend.aexecute(command)).output
    @tool('write_file')
    def write_file(file_path:str,content:str)->str:
        """Write only to the isolated test copy."""
        result=backend.write(file_path,content)
        assert not result.error
        return 'written'
    def invocation(name,**args):return AIMessage(content='',tool_calls=[call(name,**args)])
    script=[invocation('execute',command='python check.py'),invocation('write_file',file_path='/main.py',content='broken'),invocation('execute',command='python check.py'),AIMessage(content='done'),invocation('write_file',file_path='/main.py',content='repair-one'),invocation('execute',command='python check.py'),AIMessage(content='done'),invocation('write_file',file_path='/main.py',content='fixed' if repair_succeeds else 'repair-two'),invocation('execute',command='python check.py'),AIMessage(content='done')]
    if multiple_checks:
        script=[part for message in script for part in ([message,invocation('execute',command='python check.py --lint')] if message.tool_calls and message.tool_calls[0]['name']=='execute' else [message])]
    tracker=SimpleNamespace(stop_reason=None,model_calls=1,emit=lambda *args,**kwargs:None)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/'full-graph.db')) as saver:
        agent=create_agent(ScriptedChatModel(script=script),tools=[execute,write_file],checkpointer=saver,middleware=[PermissionHook(build_policy({'files':[],'tools':{}},'auto'),gateway),VerifyHook(tracker,sensors=[],gateway=gateway),HumanInTheLoopMiddleware(interrupt_on=gateway.interrupt_on(['execute','write_file']))])
        config={'configurable':{'thread_id':task['thread_id']},'recursion_limit':100}
        pending=await agent.ainvoke({'messages':[HumanMessage(content='fixture task')]},config,durability='sync')
        assert pending.get('__interrupt__') and hits==[]
        assert (root/'main.py').read_text(encoding='utf8')=='baseline'
        review=gateway.approvals.list(task['id'])[0]
        assert review['request']['review']['reason']=='first_verifier'
        gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
        final=await agent.ainvoke(Command(resume={'decisions':[]}),config,durability='sync')
        if multiple_checks:
            assert final.get('__interrupt__') and hits==['baseline']
            review=next(row for row in gateway.approvals.list(task['id']) if row['state']=='pending')
            gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve')
            final=await agent.ainvoke(Command(resume={'decisions':[]}),config,durability='sync')
        assert not final.get('__interrupt__')
    expected=['baseline','broken','repair-one','fixed' if repair_succeeds else 'repair-two']
    assert hits==([value for value in expected for _ in range(2)] if multiple_checks else expected)
    assert budget.read(task['id'])['total_attempts']==2
    assert tracker.stop_reason==(None if repair_succeeds else 'quality_decision')
    assert current_quality(store,task['id'],root,'fixture')['quality_status']==('verified_snapshot' if repair_succeeds else 'failed')
    records=CheckResults(store).list(task['id'])
    assert len([row for row in records if row['details']['phase']=='baseline'])==(2 if multiple_checks else 1)
    assert len([row for row in records if row['details']['phase']=='current'])==(8 if multiple_checks else 4)
