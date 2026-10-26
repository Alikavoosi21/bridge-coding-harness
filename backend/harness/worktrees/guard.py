"""Shared leases and version checks for human changes to an idle working copy.

This guard prepares a write; it does not itself modify or replace any file.
"""
from contextlib import contextmanager
import uuid

from server.errors import ApiError
from ..verification.observe import manifest_hash
from .diff import review_context
from .lease import WriterLease
from .state import observe
from .coordination import exclusive_entry


@contextmanager
def locked_copy(store,task_id,*,expected_revision,expected_manifest_hash,kind='manual_edit',recovery_operation=None):
    with exclusive_entry():
        with _locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_manifest_hash,kind=kind,recovery_operation=recovery_operation) as held:
            yield held


@contextmanager
def _locked_copy(store,task_id,*,expected_revision,expected_manifest_hash,kind,recovery_operation):
    task=store.task(task_id)
    if task['read_only'] and kind not in {'skill_repin','skill_repin_recovery'}:
        raise ApiError('runtime_unavailable','This task is read-only.',status_code=409)
    if task['status'] in {'queued','planning','executing','verifying','repairing','stopping'} or (task['status']=='recovery_required' and not recovery_operation):
        raise ApiError('workspace_busy','Wait until the task is idle before editing its copy.',status_code=409)
    with store.db.read() as db:
        if db.execute("SELECT 1 FROM actions WHERE task_id=? AND state IN ('dispatching','running','unknown') AND operation_id!=? LIMIT 1",(task_id,recovery_operation or '')).fetchone():
            raise ApiError('recovery_required','A previous operation needs reconciliation.',status_code=409)
        if db.execute("SELECT 1 FROM apply_operations WHERE task_id=? AND state IN ('prepared','applying','unknown','partial') AND id!=? LIMIT 1",(task_id,recovery_operation or '')).fetchone():
            raise ApiError('recovery_required','A previous apply needs reconciliation.',status_code=409)
    owner=kind+':'+task_id+':'+uuid.uuid4().hex
    if recovery_operation:
        from ..recovery import inspect_recovery
        if not inspect_recovery(store,task_id)['processes_stopped']:
            raise ApiError('recovery_required','Confirm previous process termination before recovering files.',status_code=409)
        # This entry lock still excludes every in-process writer. Replace the
        # quarantined lease only for this explicit, journal-specific recovery.
        with store.db.write() as db:db.execute("UPDATE workspace_leases SET state='released' WHERE workspace_id=? AND state='quarantined'",(task['workspace_id'],))
    worker=store.acquire_worker(owner);writer=None
    try:
        writer=store.acquire_workspace_lease(task['workspace_id'],owner,kind,ttl_s=120)
        lease=WriterLease(task['workspace_id'],writer.id,writer.fencing_token,store.workspace_lease)
        _,directory,working,original,baseline=review_context(store,task_id)
        current=observe(store,task_id,manifest_hash(working))
        if current['revision']!=expected_revision or current['manifest_hash']!=expected_manifest_hash:
            raise ApiError('selection_stale','The working copy changed since it was opened.',status_code=409,current_revision=current['revision'])
        lease.check(kind)
        yield {'task':task,'directory':directory,'working':working,'original':original,'baseline':baseline,'lease':lease,'version':current}
    finally:
        try:
            if writer:store.release_workspace_lease(writer.id,writer.fencing_token)
        finally:store.release_worker(worker.id,worker.fencing_token)
