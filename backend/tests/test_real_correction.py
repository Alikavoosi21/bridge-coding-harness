"""Real Docker tools and correction; scripted model, explicitly not provider proof."""
import json
import shutil
import pytest
from langchain_core.messages import AIMessage
from harness import Runner,RunRequest,ModelSpec,Workspace
from harness.demo_model import ScriptedChatModel,call
from harness.hooks.plan import PlanGate
from harness.runtime.docker import DockerRuntime
from harness.task_runtime import task_directory,runtime_descriptor
from harness.verification.observe import current_quality
from harness.verification.budget import RepairBudget
from server.storage import Store,Database,migrate
from server.storage.approvals import ApprovalStore


async def test_real_docker_failed_test_edit_repair_and_verified_output(tmp_path,monkeypatch):
    if shutil.which('docker') is None:pytest.skip('Real Docker CLI unavailable; correction execution not verified.')
    if not DockerRuntime().capability().available:pytest.skip('Real Docker sandbox image unavailable; correction execution not verified.')
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'main.py').write_text('value = 1\n',encoding='utf8')
    (workspace.root/'check.py').write_text('from main import value\nassert value == 2, f"expected 2, got {value}"\nprint("real test passed")\n',encoding='utf8')
    store=Store(Database());migrate(store.db)
    profile={'profile_hash':'real-python-profile','commands':[{'id':'test','command':'python check.py','source':'check.py','required':True}]}
    ws=store.upsert_workspace(str(workspace.root),profile=json.dumps(profile))
    task=store.create_task(workspace_id=ws['id'],prompt='Fix value so the approved check passes.',mode='auto',read_only=False)
    plan=store.save_plan(task['id'],steps=[{'title':'Run baseline and repair main.py'}],scope=['main.py'],checks=['python check.py'],profile_hash=profile['profile_hash'])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    def invoke(name,**args):return AIMessage(content='',tool_calls=[call(name,**args)])
    model=ScriptedChatModel(script=[
        invoke('execute',command='python check.py'),
        invoke('read_file',file_path='/main.py'),
        invoke('edit_file',file_path='/main.py',old_string='value = 1',new_string='value = 3'),
        invoke('execute',command='python check.py'),AIMessage(content='first attempt'),
        invoke('read_file',file_path='/main.py'),
        invoke('edit_file',file_path='/main.py',old_string='value = 3',new_string='value = 2'),
        invoke('execute',command='python check.py'),AIMessage(content='done'),
    ])
    monkeypatch.setattr('harness.core.build_chat_model',lambda spec:model)
    request=RunRequest(thread_id=task['thread_id'],prompt=task['prompt'],model=ModelSpec('test','scripted','demo://','scripted'),mode='auto',phase='execute')
    runner=Runner(workspace);gate=PlanGate(store,task['id'])
    events=[event async for event in runner.start(request,plan_gate=gate)]
    assert events[-1].data['stop_reason']=='awaiting_approval',events[-1].data
    pending=[row for row in ApprovalStore(store).list(task['id']) if row['state']=='pending']
    assert len(pending)==1
    review=pending[0]
    ApprovalStore(store).decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve')
    events=[event async for event in runner.resume(request,[],plan_gate=gate)]
    assert events[-1].data['stop_reason']=='completed',events[-1].data
    working=task_directory(store,task['id'])/'working';descriptor=runtime_descriptor(store,task['id'])
    assert current_quality(store,task['id'],working,descriptor['runtime_id'])['quality_status']=='verified_snapshot'
    assert RepairBudget(store).read(task['id'])['total_attempts']==1
    assert (working/'main.py').read_text(encoding='utf8')=='value = 2\n'
    assert (workspace.root/'main.py').read_text(encoding='utf8')=='value = 1\n'
    assert store.worker_lease() is None
