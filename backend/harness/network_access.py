"""Explicit, expiring task-only sandbox network permission using existing grants."""
import time
import uuid

from server.errors import ApiError


def current(store,task_id):
    task=store.task(task_id)
    if task['read_only'] or task['status'] in {'closed','failed','cancelled','recovery_required'}:return None
    with store.db.read() as db:
        row=db.execute("SELECT * FROM grants WHERE task_id=? AND capability='sandbox_network' AND revoked_at IS NULL AND expiry>? ORDER BY created_at DESC LIMIT 1",(task_id,time.time())).fetchone()
    return dict(row) if row else None


def allow(store,task_id,*,expected_revision,duration_seconds,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Explicit permission for sandbox networking is required.',status_code=409)
    if not 30<=duration_seconds<=600:raise ApiError('invalid_request','Network permission must last 30–600 seconds.',status_code=422)
    task=store.task(task_id)
    if task['read_only']:raise ApiError('runtime_unavailable','Read-only tasks cannot enable sandbox networking.',status_code=409)
    if task['revision']!=expected_revision:raise ApiError('selection_stale','Task changed; review networking again.',status_code=409)
    if task['status'] in {'queued','planning','executing','verifying','repairing','stopping','closed','failed','cancelled','recovery_required'}:
        raise ApiError('workspace_busy','Enable sandbox networking only while the task is idle.',status_code=409)
    now=time.time();identifier='grant_'+uuid.uuid4().hex[:16]
    with store.db.write() as db:
        row=db.execute('SELECT revision,status FROM tasks WHERE id=?',(task_id,)).fetchone()
        if row['revision']!=expected_revision or row['status']!=task['status']:raise ApiError('selection_stale','Task changed before granting networking.',status_code=409)
        db.execute("UPDATE grants SET revoked_at=? WHERE task_id=? AND capability='sandbox_network' AND revoked_at IS NULL",(now,task_id))
        db.execute('INSERT INTO grants(id,task_id,capability,fingerprint,expiry,created_at) VALUES(?,?,?,?,?,?)',(identifier,task_id,'sandbox_network',identifier,now+duration_seconds,now))
    return current(store,task_id)


def revoke(store,task_id):
    store.task(task_id)
    with store.db.write() as db:db.execute("UPDATE grants SET revoked_at=? WHERE task_id=? AND capability='sandbox_network' AND revoked_at IS NULL",(time.time(),task_id))
    return {'revoked':True,'task_id':task_id}
