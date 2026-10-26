"""Restart discovery never resumes a graph or repeats an unknown operation."""
import time

from server.storage import journal


def recover_startup(store):
    now=time.time()
    with store.db.write() as db:
        pending=db.execute("SELECT DISTINCT task_id FROM actions WHERE invocation_key LIKE 'queue:%' AND state='pending'").fetchall()
        for row in pending:
            db.execute("UPDATE tasks SET status='paused',revision=revision+1,updated_at=? WHERE id=? AND status='queued'",(now,row['task_id']))
            journal.append(db,row['task_id'],'task_state_changed',{'state':'paused','reason':'queue_needs_explicit_resume_after_restart'},occurred_at=now)
        db.execute("UPDATE actions SET state='denied',updated_at=? WHERE invocation_key LIKE 'queue:%' AND state='pending'",(now,))
        interrupted=db.execute("SELECT id FROM tasks WHERE status IN ('planning','executing','verifying','repairing','stopping') OR id IN (SELECT task_id FROM actions WHERE state IN ('dispatching','running','unknown')) OR id IN (SELECT task_id FROM apply_operations WHERE state IN ('prepared','applying','unknown','partial')) OR EXISTS (SELECT 1 FROM worker_leases w WHERE w.state='active' AND instr(w.owner,tasks.id)>0)").fetchall()
        for row in interrupted:
            task_id=row['id']
            db.execute("UPDATE actions SET state='unknown',updated_at=? WHERE task_id=? AND state IN ('dispatching','running')",(now,task_id))
            db.execute("UPDATE apply_operations SET state='unknown',updated_at=? WHERE task_id=? AND state IN ('prepared','applying')",(now,task_id))
            db.execute("UPDATE tasks SET status='recovery_required',revision=revision+1,updated_at=? WHERE id=? AND status!='recovery_required'",(now,task_id))
            db.execute("UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL",(now,task_id))
            journal.append(db,task_id,'task_state_changed',{'state':'recovery_required','reason':'engine_restart','automatic_replay':False},occurred_at=now)
        db.execute("UPDATE workspace_leases SET state='quarantined' WHERE state='active'")
        # A stale heartbeat is not stop proof. Leave the shared slot blocked
        # until the explicit process reconciliation has confirmed termination.
    return {'interrupted_tasks':[row['id'] for row in interrupted]}


def inspect_recovery(store,task_id):
    from .task_runtime import task_directory
    from .verification.observe import manifest_hash
    from .worktrees.snapshot import _is_link_path
    task=store.task(task_id);root=task_directory(store,task_id);working=root/'working'
    with store.db.read() as db:
        actions=[dict(row) for row in db.execute("SELECT operation_id,invocation_key,state,runtime_exec_id FROM actions WHERE task_id=? AND state IN ('unknown','dispatching','running') ORDER BY operation_id",(task_id,))]
        applies=[dict(row) for row in db.execute("SELECT id,state FROM apply_operations WHERE task_id=? AND state IN ('prepared','applying','unknown','partial')",(task_id,))]
        proofs=db.execute("SELECT payload FROM events WHERE task_id=? AND type='recovery_required' ORDER BY sequence DESC",(task_id,)).fetchall()
    import json
    ids=[row['operation_id'] for row in actions]
    worker=store.worker_lease()
    owned_worker=bool(worker and task_id in worker['owner'])
    filesystem_only=all(row['invocation_key'].startswith(('manual-edit:','restore:','skill-repin:')) and not row['runtime_exec_id'] for row in actions)
    stopped=(filesystem_only and not owned_worker) or any((value:=json.loads(row['payload'])).get('phase')=='processes_stopped' and value.get('operations')==ids for row in proofs)
    available=working.is_dir() and not _is_link_path(root) and not _is_link_path(working)
    digest=manifest_hash(working) if available else None
    from .worktrees.state import observe
    working_revision=observe(store,task_id,digest)['revision'] if digest else None
    skills=root/'knowledge'/'skills'
    skill_hash=manifest_hash(skills) if skills.is_dir() and not _is_link_path(skills) and not _is_link_path(skills.parent) else None
    from .worktrees.snapshot import load_manifest,manifest_path
    try:
        saved=None if _is_link_path(manifest_path(working)) else load_manifest(manifest_path(working))
        from pathlib import Path
        identity_valid=saved is not None and saved.root.resolve()==Path(store.workspace(task['workspace_id'])['root']).resolve()
    except (OSError,ValueError,KeyError,TypeError):identity_valid=False
    baseline=root/'baseline'
    baseline_hash=manifest_hash(baseline) if baseline.is_dir() and not _is_link_path(baseline) else None
    return {'task_id':task_id,'revision':task['revision'],'status':task['status'],'actions':actions,'apply_operations':applies,'processes_stopped':stopped,'working_hash':digest,'working_revision':working_revision,'skill_hash':skill_hash,'working_available':available,'snapshot_identity_valid':identity_valid,'baseline_hash':baseline_hash}


def stop_orphans(store,task_id,*,confirm=False,runtime_factory=None):
    from server.errors import ApiError
    from .runtime.docker import DockerRuntime
    if not confirm:raise ApiError('action_not_approved','Explicit orphan stop consent is required.',status_code=409)
    state=inspect_recovery(store,task_id)
    if state['status']!='recovery_required':raise ApiError('conflict','Task does not require recovery.',status_code=409)
    task=store.task(task_id)
    ids=[] if task['read_only'] else [row['runtime_exec_id'] or row['operation_id'] for row in state['actions'] if row['runtime_exec_id'] or not row['invocation_key'].startswith(('manual-edit:','restore:','skill-repin:'))]
    if ids:
        result=(runtime_factory or DockerRuntime)().reconcile(ids)
        if result['unresolved']:raise ApiError('runtime_unavailable','Previous container termination could not be confirmed; nothing was replayed.',status_code=409)
    with store.db.write() as db:
        # Workspace remains quarantined until its bytes are reviewed, but a
        # proven stopped orphan must not block unrelated workspaces globally.
        worker=db.execute("SELECT * FROM worker_leases WHERE state='active'").fetchone()
        if worker:
            owner=worker['owner']
            if owner=='task:'+task_id or (task_id in owner and owner.split(':')[0] in {'candidate_check','skill_repin','manual_edit','restore','apply'}):
                db.execute("UPDATE worker_leases SET state='expired',released_at=? WHERE id=?",(time.time(),worker['id']))
        journal.append(db,task_id,'recovery_required',{'phase':'processes_stopped','reason':'previous_processes_stopped_files_need_review','operations':[row['operation_id'] for row in state['actions']],'automatic_replay':False})
    return inspect_recovery(store,task_id)


def keep_current(store,task_id,*,expected_revision,expected_working_hash,confirm=False):
    from server.errors import ApiError
    from .worktrees.coordination import exclusive_entry
    with exclusive_entry():
        state=inspect_recovery(store,task_id)
        if state['status']!='recovery_required' or not confirm or not state['processes_stopped']:raise ApiError('action_not_approved','Confirm termination and explicitly review current files first.',status_code=409)
        if any(row['state']!='unknown' for row in state['actions']):raise ApiError('recovery_required','An operation is still active; reconcile after confirmed shutdown.',status_code=409)
        if state['revision']!=expected_revision or not expected_working_hash or state['working_hash']!=expected_working_hash:
            raise ApiError('selection_stale','Working files changed; review recovery again.',status_code=409)
        specialized=any(row['invocation_key'].startswith(('restore:','skill-repin:','manual-edit:')) for row in state['actions'])
        if state['apply_operations'] or specialized:raise ApiError('recovery_required','Use the operation-specific recovery to preserve its file journal.',status_code=409)
        workspace_id=store.task(task_id)['workspace_id']
        with store.db.write() as db:
            db.execute("UPDATE actions SET state='failed',updated_at=? WHERE task_id=? AND state='unknown'",(time.time(),task_id))
            db.execute("UPDATE workspace_leases SET state='released' WHERE workspace_id=? AND state='quarantined'",(workspace_id,))
            db.execute("UPDATE approvals SET state='cancelled' WHERE task_id=? AND state='pending'",(task_id,))
        store.clear_plan_approval(task_id,reason='recovery_kept_current')
        store.set_task_status(task_id,'paused',reason='recovery_kept_current_unverified')
        return store.task(task_id)


def migrate_snapshot(store,task_id,*,expected_working_hash,expected_baseline_hash,confirm=False):
    from dataclasses import replace
    from pathlib import Path
    from server.errors import ApiError
    from .task_runtime import task_directory
    from .worktrees.coordination import exclusive_entry
    from .worktrees.snapshot import build,manifest_path
    from .worktrees.edit import _durable
    import json
    with exclusive_entry():
        state=inspect_recovery(store,task_id)
        if not confirm or not state['processes_stopped'] or state['actions'] or state['apply_operations'] or state['snapshot_identity_valid']:raise ApiError('action_not_approved','Snapshot migration requires stopped, reviewed legacy files and no unresolved operations.',status_code=409)
        if not expected_baseline_hash or state['working_hash']!=expected_working_hash or state['baseline_hash']!=expected_baseline_hash:raise ApiError('selection_stale','Legacy files changed or baseline is missing.',status_code=409)
        task=store.task(task_id);root=task_directory(store,task_id)
        source=Path(store.workspace(task['workspace_id'])['root'])
        snapshot=replace(build(root/'baseline'),root=source)
        from .verification.observe import snapshot_hash
        if snapshot_hash(snapshot)!=expected_baseline_hash:raise ApiError('selection_stale','The legacy baseline changed during migration.',status_code=409)
        path=manifest_path(root/'working')
        if path.exists():
            backup=path.with_name(path.name+'.legacy-backup')
            if backup.exists():raise ApiError('recovery_required','A previous migration backup needs review.',status_code=409)
            path.rename(backup)
        _durable(path,json.dumps(snapshot.manifest(),ensure_ascii=False).encode('utf8'))
        _durable(root/'legacy-snapshot-migration.json',json.dumps({'baseline_hash':expected_baseline_hash,'working_hash':expected_working_hash,'baseline_provenance':'legacy_unverified'}).encode())
        store.clear_plan_approval(task_id,reason='legacy_snapshot_migrated')
        store.set_task_status(task_id,'paused',reason='legacy_snapshot_migrated_unverified')
        return store.task(task_id)
