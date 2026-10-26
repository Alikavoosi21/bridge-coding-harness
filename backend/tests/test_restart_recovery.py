import pytest
from harness.recovery import recover_startup,inspect_recovery,stop_orphans,keep_current
from harness.task_runtime import open_task_runtime,task_directory
from harness.workspace import Workspace
from server.storage import Database,Store,migrate
from server.errors import ApiError


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'main.py').write_text('original',encoding='utf8')
    store=Store(Database());migrate(store.db)
    ws=store.upsert_workspace(str(workspace.root));task=store.create_task(workspace_id=ws['id'],prompt='restart test',read_only=True)
    runtime=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60);runtime.close()
    return store,workspace,task


def test_restart_keeps_identity_budgets_and_requires_real_stop_before_releasing_slot(fixture):
    store,workspace,task=fixture
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    worker=store.acquire_worker('task:'+task['id'])
    writer=store.acquire_workspace_lease(task['workspace_id'],'task:'+task['id'],'execute')
    store.consume(task['id'],tool_calls=2,active_ms=123)
    action=store.ensure_action(task['id'],'fixture-command','hash')
    store.set_action_state(action['operation_id'],'running',runtime_exec_id='fixture-exec')
    store.set_task_status(task['id'],'executing')
    before=store.task(task['id'])
    recovered=recover_startup(store)
    assert task['id'] in recovered['interrupted_tasks']
    assert store.action(action['operation_id'])['state']=='unknown'
    assert store.worker_lease()['id']==worker.id
    hits=[]
    class Unavailable:
        def reconcile(self,ids):hits.extend(ids);return {'resolved':[],'unresolved':ids}
    with pytest.raises(ApiError):stop_orphans(store,task['id'],confirm=True,runtime_factory=Unavailable)
    assert store.worker_lease()['id']==worker.id
    class Stopped:
        def reconcile(self,ids):hits.extend(ids);return {'resolved':ids,'unresolved':[]}
    state=stop_orphans(store,task['id'],confirm=True,runtime_factory=Stopped)
    assert state['processes_stopped'] and store.worker_lease() is None
    # The unrelated workspace can use the global slot; this workspace stays quarantined.
    other=store.acquire_worker('task:other');store.release_worker(other.id,other.fencing_token)
    current=task_directory(store,task['id'])/'working'/'main.py';current.write_text('kept bytes',encoding='utf8')
    with pytest.raises(ApiError):keep_current(store,task['id'],expected_revision=state['revision'],expected_working_hash=state['working_hash'],confirm=True)
    fresh=inspect_recovery(store,task['id'])
    result=keep_current(store,task['id'],expected_revision=fresh['revision'],expected_working_hash=fresh['working_hash'],confirm=True)
    assert result['thread_id']==before['thread_id'] and result['status']=='paused'
    assert result['budget']['tool_calls']==2 and result['budget']['active_ms']==123
    assert current.read_text(encoding='utf8')=='kept bytes'
    assert store.action(action['operation_id'])['state']=='failed' and hits==['fixture-exec','fixture-exec']
    assert (workspace.root/'main.py').read_text(encoding='utf8')=='original'


def test_missing_capture_identity_never_rebuilds_existing_working_bytes(fixture):
    from harness.worktrees.snapshot import manifest_path
    from harness.runtime.docker import RuntimeUnavailable
    store,workspace,task=fixture
    working=task_directory(store,task['id'])/'working'
    (working/'main.py').write_text('unsaved legacy work',encoding='utf8')
    manifest_path(working).unlink()
    with pytest.raises(RuntimeUnavailable):open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=60)
    assert (working/'main.py').read_text(encoding='utf8')=='unsaved legacy work'
    from harness.recovery import inspect_recovery,migrate_snapshot
    from harness.worktrees.diff import changes
    current=inspect_recovery(store,task['id'])
    assert not current['snapshot_identity_valid'] and current['baseline_hash']
    migrate_snapshot(store,task['id'],expected_working_hash=current['working_hash'],expected_baseline_hash=current['baseline_hash'],confirm=True)
    assert (working/'main.py').read_text(encoding='utf8')=='unsaved legacy work'
    assert changes(store,task['id'])['items'][0]['path']=='main.py'
    assert store.task(task['id'])['status']=='paused'
