from dataclasses import replace
from types import SimpleNamespace
import time

import pytest
from langchain_core.messages import ToolMessage

from harness.network_access import allow,current,revoke
from harness.gateway import ToolGateway
from harness.runtime.docker import ContainerConfig,DockerRuntime,ExecResult,RuntimeUnavailable,build_run_args
from harness.task_runtime import open_task_runtime
from harness.workspace import Workspace
from server.errors import ApiError
from server.storage import Store,Database,migrate


class Runtime:
    def __init__(self):self.config=ContainerConfig();self.calls=[]
    def pin_image(self):self.config=replace(self.config,image='sha256:'+'a'*64);return self.config.image
    def set_lease(self,lease):self.lease=lease
    def cancel_all(self):pass
    def execute(self,command,**kwargs):
        self.lease.check('network fixture')
        self.calls.append(kwargs)
        return ExecResult(kwargs['exec_id'],0,'fixture only',operation_id=kwargs['exec_id'])


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    store=Store(Database());migrate(store.db)
    ws=store.upsert_workspace(str(workspace.root));task=store.create_task(workspace_id=ws['id'],prompt='network fixture',mode='auto')
    plan=store.save_plan(task['id'],steps=[{'title':'review exact command'}]);store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    store.set_task_status(task['id'],'paused',reason='fixture idle')
    return store,workspace,task


async def test_network_permission_does_not_approve_command_and_deadline_reaches_runtime(fixture):
    store,workspace,task=fixture;runtime=Runtime()
    assembly=open_task_runtime(workspace,store,task['id'],read_only=False,max_seconds=60,runtime=runtime)
    try:
        backend=assembly.backend.default
        gateway=ToolGateway(store,task['id'],workspace.rules_file,runtime_available=True,runtime_id=assembly.runtime_id,backend=backend)
        call={'id':'network-command','name':'execute','args':{'command':'echo reviewed-command'}}
        offline,_=gateway.evaluate(call)
        with pytest.raises(ApiError):allow(store,task['id'],expected_revision=store.task(task['id'])['revision'],duration_seconds=60)
        permission=allow(store,task['id'],expected_revision=store.task(task['id'])['revision'],duration_seconds=60,confirm=True)
        context,access=gateway.evaluate(call)
        assert access=='ask' and context.fingerprint()!=offline.fingerprint()
        assert gateway.review_details(context)['sandbox_network']
        request=SimpleNamespace(tool_call=call)
        async def execute(_):
            response=backend.execute(call['args']['command'])
            return ToolMessage(content=response.output,tool_call_id=call['id'])
        assert (await gateway.dispatch(request,execute)).status=='error' and not runtime.calls
        assert gateway.requires_review(request)
        review=gateway.approvals.list(task['id'])[-1]
        gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve')
        await gateway.dispatch(request,execute)
        assert runtime.calls[0]['network_until']==permission['expiry']
        await gateway.dispatch(request,execute);assert len(runtime.calls)==1
        revoke(store,task['id']);assert current(store,task['id']) is None
        offline_again,_=gateway.evaluate({**call,'id':'offline-again'})
        assert offline_again.environment_profile.startswith('offline')
        assert backend._network_until.get() is None # ContextVar did not leak
    finally:assembly.close()


def test_permission_is_task_only_expires_and_readonly_cannot_enable(fixture):
    store,_,task=fixture
    grant=allow(store,task['id'],expected_revision=store.task(task['id'])['revision'],duration_seconds=30,confirm=True)
    other=store.create_task(workspace_id=task['workspace_id'],prompt='different task',read_only=True)
    assert current(store,other['id']) is None
    with pytest.raises(ApiError):allow(store,other['id'],expected_revision=other['revision'],duration_seconds=60,confirm=True)
    with store.db.write() as db:db.execute('UPDATE grants SET expiry=? WHERE id=?',(time.time()-1,grant['id']))
    assert current(store,task['id']) is None
    with pytest.raises(ApiError):allow(store,task['id'],expected_revision=store.task(task['id'])['revision'],duration_seconds=601,confirm=True)


def test_docker_remains_offline_by_default_and_rejects_expired_permission(tmp_path):
    offline=build_run_args(ContainerConfig(),tmp_path,'offline','echo test')
    online=build_run_args(ContainerConfig(),tmp_path,'online','echo test',network=True)
    assert offline[offline.index('--network')+1]=='none'
    assert online[online.index('--network')+1]=='bridge'
    calls=[]
    runtime=DockerRuntime(run=lambda *args,**kwargs:calls.append(args))
    with pytest.raises(RuntimeUnavailable):runtime.execute('echo test',snapshot=tmp_path,network_until=time.time()-1)
    assert calls==[]
