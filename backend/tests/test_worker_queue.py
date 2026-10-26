import asyncio
from types import SimpleNamespace
import pytest
from harness.recovery import recover_startup
from server.state import AppState
from server.storage import Store


async def test_fifo_across_workspaces_releases_slot_at_human_wait_and_preserves_identity(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    store=Store();store.ensure_schema();app=AppState()
    workspaces=[store.upsert_workspace(str(tmp_path/name)) for name in ['one','two']]
    tasks=[store.create_task(workspace_id=workspaces[i%2]['id'],prompt=str(i),read_only=True) for i in range(3)]
    releases=[asyncio.Event() for _ in tasks];started=[]
    managers={workspace['root']:SimpleNamespace(_tasks={},is_running=lambda thread:False) for workspace in workspaces}
    for manager in managers.values():
        manager.is_running=lambda thread,m=manager:thread in m._tasks and not m._tasks[thread].done()
    app._managers=managers
    def dispatch(phase,task_id,instruction):
        task=store.task(task_id);index=next(i for i,item in enumerate(tasks) if item['id']==task_id)
        manager=managers[store.workspace(task['workspace_id'])['root']]
        async def work():
            worker=store.acquire_worker('task:'+task_id)
            writer=store.acquire_workspace_lease(task['workspace_id'],'task:'+task_id,'fixture')
            started.append(task_id);store.set_task_status(task_id,'planning')
            await releases[index].wait()
            store.release_workspace_lease(writer.id,writer.fencing_token);store.release_worker(worker.id,worker.fencing_token)
            store.set_task_status(task_id,'awaiting_action',reason='fixture human wait')
        manager._tasks[task['thread_id']]=asyncio.create_task(work())
        return task
    monkeypatch.setattr(app,'_dispatch',dispatch)
    async def until(predicate):
        for _ in range(100):
            if predicate():return
            await asyncio.sleep(.02)
        raise AssertionError('queue did not settle')
    try:
        app.submit('plan',tasks[0]['id']);await until(lambda:len(started)==1)
        assert app.submit('plan',tasks[1]['id'])['status']=='queued'
        assert app.submit('plan',tasks[2]['id'])['status']=='queued'
        releases[0].set();await until(lambda:len(started)==2)
        assert store.task(tasks[0]['id'])['status']=='awaiting_action'
        releases[1].set();await until(lambda:len(started)==3)
        releases[2].set();await until(lambda:store.worker_lease() is None)
        assert started==[task['id'] for task in tasks]
        assert [store.task(task['id'])['thread_id'] for task in tasks]==[task['thread_id'] for task in tasks]
        assert all(store.budget(task['id'])['tool_calls']==0 for task in tasks)
    finally:
        for event in releases:event.set()
        if app._queue_task:await app._queue_task
        await asyncio.gather(*(task for manager in managers.values() for task in manager._tasks.values()),return_exceptions=True)


def test_restart_pauses_queued_requests_instead_of_dispatching(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    store=Store();store.ensure_schema();ws=store.upsert_workspace(str(tmp_path/'project'))
    task=store.create_task(workspace_id=ws['id'],prompt='queued')
    action=store.ensure_action(task['id'],'queue:fixture','hash')
    recover_startup(store)
    assert store.task(task['id'])['status']=='paused'
    assert store.action(action['operation_id'])['state']=='denied'
    assert len(store.task(task['id'])['runs'])==1


async def test_shutdown_pauses_queue_and_never_dispatches_on_exit(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    store=Store();store.ensure_schema();ws=store.upsert_workspace(str(tmp_path/'project'))
    task=store.create_task(workspace_id=ws['id'],prompt='shutdown queue')
    action=store.ensure_action(task['id'],'queue:shutdown','hash')
    app=AppState()
    result=await app.shutdown(timeout=.01)
    assert result['stopped'] and not app.closing
    assert store.task(task['id'])['status']=='paused'
    assert store.action(action['operation_id'])['state']=='denied'
    assert len(store.task(task['id'])['runs'])==1
