"""Task assembly with real copies/leases and a fake container adapter.

These prove integration and original-file preservation, not Docker confinement.
"""
from dataclasses import replace
from types import SimpleNamespace
import asyncio

import pytest

from harness.backends.container import ContainerBackend
from harness.core import available_tools
from harness.runtime.docker import ContainerConfig, ExecResult, RuntimeUnavailable
from harness.task_runtime import open_task_runtime
from harness.workspace import Workspace
from harness.worktrees.lease import LeaseLost
from server.errors import ApiError
from server.storage import Database,Store,migrate


class FakeRuntime:
    def __init__(self):
        self.config=ContainerConfig();self.ids=[];self.lease=None
    def pin_image(self):
        image='sha256:'+'a'*64
        self.config=replace(self.config,image=image)
        return image
    def set_lease(self,lease):self.lease=lease
    def cancel_all(self):pass
    def execute(self,command,*,snapshot,exec_id,**kwargs):
        self.lease.check('execute')
        self.ids.append(exec_id)
        return ExecResult(exec_id,0,command,operation_id=exec_id)


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'note.txt').write_text('baseline',encoding='utf8')
    (workspace.root/'.env').write_text('fixture-secret',encoding='utf8')
    (workspace.root/'data.csv').write_text('value\n123\n',encoding='utf8')
    db=Database(tmp_path/'home'/'product.db');migrate(db);store=Store(db)
    row=store.upsert_workspace(str(workspace.root))
    task=store.create_task(workspace_id=row['id'],prompt='fixture')
    return store,workspace,task,tmp_path


def test_read_only_copy_excludes_secrets_and_resume_never_overwrites_working_edits(fixture):
    store,workspace,task,_=fixture
    first=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    working=first.workspace.root
    assert working!=workspace.root and not (working/'.env').exists()
    assert first.backend.read('/note.txt').file_data['content']=='baseline'
    assert first.backend.write('/note.txt','forbidden').error
    assert (working/'.harness'/'skills'/'coding-checks'/'SKILL.md').exists()
    first.close();assert store.worker_lease() is None
    (working/'note.txt').write_text('agent edit',encoding='utf8')
    (workspace.root/'note.txt').write_text('user edit',encoding='utf8')
    second=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    try:
        assert second.backend.read('/note.txt').file_data['content']=='agent edit'
        assert (workspace.root/'note.txt').read_text(encoding='utf8')=='user edit'
    finally:second.close()


def test_real_skills_middleware_reads_reviewed_pin_not_changed_live_source(fixture):
    import json
    from deepagents.middleware.skills import SkillsMiddleware
    from harness.skills import skill_sources
    from harness.skills_registry import SkillRegistry
    store,workspace,task,_=fixture
    source=workspace.skills_dir/'check-code';source.mkdir()
    (source/'SKILL.md').write_text('---\nname: check-code\ndescription: Check requested code.\n---\n\nOLD PRIVATE SKILL BODY\n',encoding='utf8')
    registry=SkillRegistry(store)
    registered=registry.register(source,scope='project',workspace_id=task['workspace_id'])
    registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
    first=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    try:
        middleware=SkillsMiddleware(backend=first.backend,sources=skill_sources(workspace))
        metadata=middleware.before_agent({},None,{})
        assert any(row['name']=='check-code' for row in metadata['skills_metadata'])
        assert 'OLD PRIVATE SKILL BODY' not in json.dumps(metadata)
        assert 'OLD PRIVATE SKILL BODY' in first.backend.read('/.harness/skills/check-code/SKILL.md').file_data['content']
        assert first.backend.write('/.harness/skills/check-code/SKILL.md','tampered').error
        assert 'execute' not in available_tools(first.workspace,first.backend)
    finally:first.close()
    (source/'SKILL.md').write_text('---\nname: check-code\ndescription: Changed live source.\n---\n\nNEW BODY MUST NOT LOAD\n',encoding='utf8')
    registry.disable(registered['id'])
    second=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    try:
        body=second.backend.read('/.harness/skills/check-code/SKILL.md').file_data['content']
        assert 'OLD PRIVATE SKILL BODY' in body and 'NEW BODY' not in body
        middleware=SkillsMiddleware(backend=second.backend,sources=skill_sources(workspace))
        assert middleware.before_agent(metadata,None,{}) is None # SDK checkpoint metadata is reused
    finally:second.close()


def test_discovered_project_skill_is_disabled_and_bundled_disable_is_not_undone(fixture):
    from harness.skills_registry import SkillRegistry
    store,workspace,task,_=fixture
    registry=SkillRegistry(store);registry.bootstrap(task['workspace_id'])
    listed=registry.list(task['workspace_id'])
    bundled=next(row for row in listed if row['scope']=='bundled')
    project=next(row for row in listed if row['scope'].startswith('project:'))
    assert bundled['enabled'] and not project['enabled']
    registry.disable(bundled['id']);registry.bootstrap(task['workspace_id'])
    assert not registry.detail(bundled['id'])['enabled']
    assembly=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    try:
        assert assembly.backend.read('/.harness/skills/coding-checks/SKILL.md').error
    finally:assembly.close()


async def test_pinned_script_uses_gateway_approval_fingerprint_and_container_mount(fixture):
    from harness.gateway import ToolGateway
    from harness.skills_registry import SkillRegistry
    from harness.worktrees.snapshot import UnsafePath
    from langchain_core.messages import ToolMessage
    store,workspace,task,_=fixture
    source=workspace.skills_dir/'check-code';source.mkdir()
    (source/'SKILL.md').write_text('---\nname: check-code\ndescription: Run a reviewed check when asked.\n---\n\nNo permission grants.\n',encoding='utf8')
    (source/'helper.py').write_text('print("reviewed")',encoding='utf8')
    registry=SkillRegistry(store);registered=registry.register(source,scope='personal')
    registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
    with store.db.write() as db:db.execute("UPDATE tasks SET mode='auto' WHERE id=?",(task['id'],))
    plan=store.save_plan(task['id'],steps=[{'title':'Run approved skill script'}]);store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    runtime=FakeRuntime();assembly=open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=runtime)
    try:
        backend=assembly.backend.default
        gateway=ToolGateway(store,task['id'],workspace.rules_file,runtime_available=True,runtime_id=assembly.runtime_id,backend=backend)
        call={'id':'skill-script-once','name':'execute','args':{'command':'python /skills/check-code/helper.py'}}
        request=SimpleNamespace(tool_call=call)
        context,access=gateway.evaluate(call)
        assert access=='ask' and gateway.review_details(context)['reason']=='skill_script'
        async def execute(_):
            result=backend.execute(call['args']['command'])
            return ToolMessage(content=result.output,tool_call_id=call['id'])
        assert (await gateway.dispatch(request,execute)).status=='error'
        assert runtime.ids==[]
        assert gateway.requires_review(request)
        review=gateway.approvals.list(task['id'])[-1]
        gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve')
        await gateway.dispatch(request,execute)
        assert len(runtime.ids)==1
        await gateway.dispatch(request,execute)
        assert len(runtime.ids)==1 # durable receipt, no second script execution
        with pytest.raises(UnsafePath):gateway.evaluate({**call,'args':{'command':'python .harness/skills/check-code/helper.py'}})
        original=context.fingerprint()
        pinned=backend.skills_root/'check-code'/'helper.py'
        pinned.write_text('tampered after review',encoding='utf8')
        with pytest.raises(ApiError) as corrupt:gateway.evaluate({**call,'id':'another-script'})
        assert corrupt.value.code=='recovery_required'
        assert context.fingerprint()==original
    finally:assembly.close()


async def test_writes_and_custom_tools_use_copy_and_execute_uses_pinned_operation(fixture):
    store,workspace,task,_=fixture
    runtime=FakeRuntime()
    assembly=open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=runtime)
    backend=assembly.backend.default
    try:
        assert not backend.write('/new.txt','agent').error
        assert (assembly.workspace.root/'new.txt').read_text(encoding='utf8')=='agent'
        assert not (workspace.root/'new.txt').exists()
        (workspace.root/'data.csv').write_text('value\n999999\n',encoding='utf8')
        result=await available_tools(assembly.workspace,assembly.backend)['read_table'].ainvoke({'path':'/data.csv'})
        assert '123' in str(result) and '999999' not in str(result)
        with backend.operation_scope('op_fixture'):
            result=await backend.aexecute('fixture-no-real-shell')
            assert result.exit_code==0 and backend.last_receipt.operation_id=='op_fixture'
        assert runtime.ids==['op_fixture']
        # Metadata cannot be changed through the composite filesystem backend.
        assert assembly.backend.write('/.harness/skills/coding-checks/SKILL.md','changed').error
    finally:assembly.close()
    assert store.worker_lease() is None and store.workspace_lease(task['workspace_id']) is None
    with pytest.raises(LeaseLost):backend.write('/late.txt','late')


async def test_concurrent_execute_bindings_do_not_cross(fixture):
    store,workspace,task,_=fixture
    runtime=FakeRuntime()
    assembly=open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=runtime)
    backend=assembly.backend.default
    async def command(operation):
        with backend.operation_scope(operation):
            await asyncio.sleep(0)
            result=await asyncio.create_task(backend.aexecute(operation))
            assert backend.last_receipt.operation_id==operation
            return result.output
    try:
        assert await asyncio.gather(command('op_one'),command('op_two'))==['op_one','op_two']
        assert set(runtime.ids)=={'op_one','op_two'}
    finally:assembly.close()


def test_unknown_quarantines_writer_and_unavailable_runtime_has_no_fallback(fixture):
    store,workspace,task,_=fixture
    class Missing(FakeRuntime):
        def pin_image(self):raise RuntimeUnavailable('fixture unavailable')
    with pytest.raises(RuntimeUnavailable):open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=Missing())
    assert store.worker_lease() is None
    assembly=open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=FakeRuntime())
    action=store.ensure_action(task['id'],'lost','hash');store.set_action_state(action['operation_id'],'unknown')
    assembly.close()
    assert store.task(task['id'])['status']=='recovery_required'
    from harness.task_controller import TaskController
    TaskController(SimpleNamespace(),store,model_resolver=lambda:None)._finish(task['id'],phase='execute',stop_reason='completed')
    assert store.task(task['id'])['status']=='recovery_required'
    assert store.worker_lease() is None
    with pytest.raises(ApiError,match='Another writer'):store.acquire_workspace_lease(task['workspace_id'],'next','execute')


async def test_real_runner_releases_on_human_wait_and_reacquires_before_copy_write(fixture,monkeypatch):
    from langchain_core.messages import AIMessage
    from harness import Runner,RunRequest,ModelSpec
    from harness.demo_model import ScriptedChatModel,call
    from harness.hooks.plan import PlanGate
    from server.storage.approvals import ApprovalStore
    import harness.core as core
    import harness.task_runtime as task_runtime
    store,workspace,task,_=fixture
    plan=store.save_plan(task['id'],steps=[{'title':'write isolated copy'}])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    model=ScriptedChatModel(script=[AIMessage(content='',tool_calls=[call('write_file',file_path='/new.md',content='isolated')]),AIMessage(content='done')])
    monkeypatch.setattr(core,'build_chat_model',lambda spec:model)
    monkeypatch.setattr(task_runtime,'DockerRuntime',lambda config=None:FakeRuntime())
    request=RunRequest(thread_id=task['thread_id'],prompt='write fixture',model=ModelSpec('demo','demo','demo://','demo'),phase='execute')
    runner=Runner(workspace)
    gate=PlanGate(store,task['id'])
    events=[event async for event in runner.start(request,plan_gate=gate)]
    assert events[-1].data['stop_reason']=='awaiting_approval',events[-1].data
    consumed_before=store.budget(task['id'])
    assert consumed_before['model_calls']==events[-1].data['model_calls']>0
    assert events[-1].data['budget_recorded']
    assert store.worker_lease() is None and store.workspace_lease(task['workspace_id']) is None
    review=ApprovalStore(store).list(task['id'])[0]
    ApprovalStore(store).decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    events=[event async for event in runner.resume(request,[],plan_gate=gate)]
    assert events[-1].data['stop_reason']=='completed',events[-1].data
    consumed_after=store.budget(task['id'])
    assert consumed_after['model_calls']==consumed_before['model_calls']+events[-1].data['model_calls']
    assert consumed_after['tool_calls']==consumed_before['tool_calls']+events[-1].data['tool_calls']
    assert not (workspace.root/'new.md').exists()
    from harness.task_runtime import task_directory
    assert (task_directory(store,task['id'])/'working'/'new.md').read_text(encoding='utf8')=='isolated'
    assert store.worker_lease() is None and store.workspace_lease(task['workspace_id']) is None
    assert store.action(review['action_id'])['state']=='succeeded'
