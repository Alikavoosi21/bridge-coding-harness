"""Permission waits must never become automatic repair loops."""
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage

from harness.hooks.verify import VerifyHook
from harness.task_controller import TaskController
from harness.events import Event
from harness.tracker import RunTracker
from harness.config import Limits,ModelSpec
from server.app import create_app
from server.storage import Store,Database,migrate


@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    db=Database();migrate(db)
    return Store(db)


@pytest.mark.parametrize('read_only,approved,blocked',[(True,True,False),(False,False,False),(False,True,True)])
def test_permission_and_plan_wait_do_not_trigger_repairs(read_only,approved,blocked):
    tracker=RunTracker('fixture',Limits(),ModelSpec('fixture','Fixture','demo://','demo'),lambda _:None)
    gateway=SimpleNamespace(read_only=read_only,permission_blocked=blocked,task_id='fixture',store=SimpleNamespace(plan=lambda _: {'revision':2,'approved_revision':2 if approved else None}))
    hook=VerifyHook(tracker,gateway=gateway)
    assert hook.after_model({'messages':[AIMessage(content='Waiting for permission.')],'todos':[{'content':'Create login.html','status':'pending'}]},None) is None
    assert hook.rounds==0
    assert tracker.stop_reason==('permission_required' if blocked else None)


async def test_finished_segment_has_an_end_receipt(store,tmp_path):
    ws=store.upsert_workspace(str(tmp_path/'project'));task=store.create_task(workspace_id=ws['id'],prompt='hello')
    controller=TaskController(None,store,model_resolver=lambda:None)
    async def stream():
        yield Event('text',task['thread_id'],{'text':'Hello'})
        yield Event('run_finished',task['thread_id'],{'stop_reason':'completed'})
    async for _ in controller._settle(task,phase='plan',stream=stream()):pass
    run=store.task(task['id'])['runs'][-1]
    assert run['state']=='closed' and run['started_at'] and run['ended_at']>=run['started_at']


async def test_enable_editing_checks_capability_and_revokes_old_plan(store,tmp_path,monkeypatch):
    ws=store.upsert_workspace(str(tmp_path/'project'));task=store.create_task(workspace_id=ws['id'],prompt='Create login.html',read_only=True)
    plan=store.save_plan(task['id'],steps=[{'title':'Create login.html'}]);store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    store.set_task_status(task['id'],'awaiting_plan')
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as api:
        from server.routes import tasks
        def refuse(_):
            from server.errors import ApiError
            raise ApiError('runtime_unavailable','No sandbox',status_code=409)
        monkeypatch.setattr(tasks,'_require_write_capability',refuse)
        payload={'mode':'auto','read_only':False,'expected_revision':store.task(task['id'])['revision']}
        response=await api.patch('/tasks/'+task['id']+'/access',json=payload)
        assert response.status_code==409 and store.task(task['id'])['read_only']
        monkeypatch.setattr(tasks,'_require_write_capability',lambda _:None)
        response=await api.patch('/tasks/'+task['id']+'/access',json=payload)
        assert response.status_code==200,response.text
        assert not response.json()['task']['read_only'] and response.json()['task']['mode']=='auto'
        assert store.plan(task['id'])['approved_revision'] is None
        assert (await api.patch('/tasks/'+task['id']+'/access',json=payload)).status_code==409
