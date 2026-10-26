"""Task-scoped human receipts in the existing product database.

No runtime is dispatched here. A committed decision is checked again at the
tool boundary; an HTTP response alone cannot authorize a changed invocation.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from typing import Any

from harness.policy import ActionContext
from ..errors import ApiError
from . import journal
from .repository import Store


def _refuse(code='selection_stale', message='This approval is no longer current.'):
    raise ApiError(code, message, status_code=409)


def _public(row) -> dict[str, Any]:
    result = dict(row)
    result['request'] = json.loads(result.pop('request_json') or 'null')
    if result['request']:
        result['request'].pop('script',None)  # renderer needs the fingerprint, not megabytes of source hex
    return result


class ApprovalStore:
    def __init__(self, store: Store):
        self.store = store

    def request(self, task_id: str, invocation_key: str, context: ActionContext, *, origin_run_id: str | None = None, review_details: dict[str,Any] | None = None) -> dict[str, Any]:
        fingerprint = context.fingerprint()
        operation = self.store.ensure_action(task_id, invocation_key, fingerprint, origin_run_id=origin_run_id)
        payload = asdict(context)
        payload['script'] = context.script.hex()
        if review_details is not None:payload['review']=review_details
        now = time.time()
        with self.store.db.write() as db:
            task = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
            plan = db.execute('SELECT revision,approved_revision FROM plans WHERE task_id=?', (task_id,)).fetchone()
            if task['status'] in {'closed','failed','cancelled','recovery_required'} or not plan or plan['revision'] != context.plan_revision or plan['approved_revision'] != context.plan_revision:
                _refuse()
            action = db.execute('SELECT * FROM actions WHERE operation_id=?', (operation['operation_id'],)).fetchone()
            if action['state'] in {'dispatching','running','succeeded','failed','denied','unknown'}:
                _refuse('conflict', 'This operation cannot request another approval.')
            old = db.execute('SELECT * FROM approvals WHERE action_id=? ORDER BY revision DESC LIMIT 1', (operation['operation_id'],)).fetchone()
            if old:
                if old['action_hash'] != fingerprint or old['request_json'] is None:
                    _refuse()
                return _public(old)
            approval_id = 'approval_' + uuid.uuid4().hex[:16]
            db.execute('UPDATE actions SET plan_revision=?,state=? WHERE operation_id=?', (context.plan_revision,'awaiting_approval',operation['operation_id']))
            db.execute('INSERT INTO approvals(id,task_id,action_id,action_hash,revision,state,created_at,request_json) VALUES(?,?,?,?,1,?,?,?)', (approval_id,task_id,operation['operation_id'],fingerprint,'pending',now,json.dumps(payload,ensure_ascii=False)))
            journal.append(db,task_id,'approval_required',{'approval_id':approval_id,'operation_id':operation['operation_id'],'action_hash':fingerprint,'tool':context.tool,'scope':[]},run_id=origin_run_id)
            return _public(db.execute('SELECT * FROM approvals WHERE id=?',(approval_id,)).fetchone())

    def list(self, task_id: str) -> list[dict[str, Any]]:
        self.store.task(task_id)
        with self.store.db.read() as db:
            return [_public(row) for row in db.execute('SELECT * FROM approvals WHERE task_id=? ORDER BY created_at,id',(task_id,))]

    def edit(self, task_id: str, approval_id: str, *, fingerprint: str, revision: int, context: ActionContext, review_details: dict[str,Any] | None = None) -> dict[str, Any]:
        """Human-only replacement before dispatch; it always needs a fresh decision."""
        payload=asdict(context);payload['script']=context.script.hex()
        if review_details is not None:payload['review']=review_details
        new_hash=context.fingerprint();now=time.time()
        with self.store.db.write() as db:
            row=db.execute('SELECT * FROM approvals WHERE id=? AND task_id=?',(approval_id,task_id)).fetchone()
            if row is None or row['request_json'] is None:_refuse()
            action=db.execute('SELECT * FROM actions WHERE operation_id=?',(row['action_id'],)).fetchone()
            latest=db.execute('SELECT MAX(revision) FROM approvals WHERE action_id=?',(row['action_id'],)).fetchone()[0]
            task=db.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()
            plan=db.execute('SELECT revision,approved_revision FROM plans WHERE task_id=?',(task_id,)).fetchone()
            original=json.loads(row['request_json'])
            if row['state'] not in {'pending','decided'} or action['state'] not in {'pending','awaiting_approval'} or row['action_hash']!=fingerprint or row['revision']!=revision or revision!=latest:
                _refuse()
            if task['status'] in {'closed','failed','cancelled','recovery_required'} or not plan or plan['revision']!=context.plan_revision or plan['approved_revision']!=context.plan_revision:
                _refuse()
            if context.tool!=original['tool'] or context.cwd!=original['cwd'] or context.runtime!=original['runtime'] or context.shell!=original['shell'] or context.environment_profile!=original['environment_profile']:
                _refuse('invalid_request','Only arguments may be edited in this request.')
            db.execute("UPDATE approvals SET state='superseded',decision='edit',decided_at=? WHERE id=?",(now,approval_id))
            db.execute('UPDATE actions SET args_hash=?,state=?,updated_at=? WHERE operation_id=?',(new_hash,'awaiting_approval',now,row['action_id']))
            db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND capability=? AND revoked_at IS NULL',(now,task_id,'operation:'+row['action_id']))
            identifier='approval_'+uuid.uuid4().hex[:16]
            db.execute('INSERT INTO approvals(id,task_id,action_id,action_hash,revision,state,created_at,request_json) VALUES(?,?,?,?,?,?,?,?)',(identifier,task_id,row['action_id'],new_hash,revision+1,'pending',now,json.dumps(payload,ensure_ascii=False)))
            journal.append(db,task_id,'approval_decided',{'approval_id':approval_id,'operation_id':row['action_id'],'decision':'edit'})
            journal.append(db,task_id,'approval_required',{'approval_id':identifier,'operation_id':row['action_id'],'action_hash':new_hash,'tool':context.tool,'scope':[]})
            return _public(db.execute('SELECT * FROM approvals WHERE id=?',(identifier,)).fetchone())

    def change_access(self, task_id: str, *, expected_revision: int, mode: str, read_only: bool | None = None) -> dict[str, Any]:
        if mode not in {'ask','grant','auto'}:
            raise ApiError('invalid_request','Unknown access mode.',status_code=422)
        now=time.time()
        with self.store.db.write() as db:
            task=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not task:raise ApiError('not_found','Task not found.',status_code=404)
            if task['revision']!=expected_revision or task['status'] in {'closed','failed','cancelled','recovery_required'}:_refuse()
            changing_read_only=read_only is not None and bool(task['read_only'])!=read_only
            if changing_read_only and task['status'] in {'planning','executing','verifying','repairing','stopping'}:
                _refuse('workspace_busy','Wait for the current action to stop before changing editing access.')
            if task['mode']==mode and not changing_read_only:return self.store.task(task_id)
            db.execute('UPDATE tasks SET mode=?,read_only=?,revision=revision+1,updated_at=? WHERE id=?',(mode,int(read_only) if read_only is not None else task['read_only'],now,task_id))
            if changing_read_only:db.execute('UPDATE plans SET approved_revision=NULL WHERE task_id=?',(task_id,))
            db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL',(now,task_id))
            db.execute("UPDATE approvals SET state='cancelled' WHERE task_id=? AND action_id IN (SELECT operation_id FROM actions WHERE task_id=? AND state IN ('pending','awaiting_approval'))",(task_id,task_id))
            db.execute("UPDATE actions SET state='denied',updated_at=? WHERE task_id=? AND state IN ('pending','awaiting_approval')",(now,task_id))
            next_status='paused' if task['status']=='queued' else task['status']
            if next_status!=task['status']:db.execute('UPDATE tasks SET status=? WHERE id=?',(next_status,task_id))
            journal.append(db,task_id,'task_state_changed',{'state':next_status,'reason':'access_changed','mode':mode,'revision':expected_revision+1})
        return self.store.task(task_id)

    def decide(self, task_id: str, approval_id: str, *, fingerprint: str, revision: int, decision: str, grant: bool = False, expires_at: float | None = None, reason: str = '') -> dict[str, Any]:
        if decision not in {'approve','reject'}:
            raise ApiError('invalid_request','Unsupported decision.',status_code=422)
        now=time.time()
        if expires_at is not None and expires_at <= now:
            _refuse('invalid_request','Grant expiry must be in the future.')
        with self.store.db.write() as db:
            approval=db.execute('SELECT * FROM approvals WHERE id=? AND task_id=?',(approval_id,task_id)).fetchone()
            if not approval:
                raise ApiError('not_found','Approval not found.',status_code=404)
            action=db.execute('SELECT * FROM actions WHERE operation_id=?',(approval['action_id'],)).fetchone()
            task=db.execute('SELECT status,mode FROM tasks WHERE id=?',(task_id,)).fetchone()
            plan=db.execute('SELECT revision,approved_revision FROM plans WHERE task_id=?',(task_id,)).fetchone()
            if task['status'] in {'closed','failed','cancelled','recovery_required'} or not plan or plan['revision'] != action['plan_revision'] or plan['approved_revision'] != action['plan_revision']:
                _refuse()
            if approval['request_json'] is None or approval['action_hash'] != fingerprint or action['args_hash'] != fingerprint or approval['revision'] != revision:
                _refuse()
            if action['state'] in {'unknown','dispatching','running','succeeded','failed'}:
                _refuse('conflict','This operation is no longer eligible for approval.')
            if approval['state'] != 'pending':
                # A double click returns its canonical receipt, never dispatches again.
                if approval['decision'] != decision:
                    _refuse('conflict','This approval already has a different decision.')
                return _public(approval)
            if action['state'] != 'awaiting_approval':
                _refuse('conflict','This operation is not waiting for approval.')
            if grant and (decision != 'approve' or task['mode'] != 'grant'):
                _refuse('invalid_request','Task grants require grant mode and approval.')
            db.execute('UPDATE approvals SET state=?,decision=?,decided_at=? WHERE id=?',('decided',decision,now,approval_id))
            if decision=='reject' and reason:
                payload=json.loads(approval['request_json']);payload['rejection_reason']=reason[:1000]
                db.execute('UPDATE approvals SET request_json=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),approval_id))
            db.execute('UPDATE actions SET state=?,updated_at=? WHERE operation_id=?',('pending' if decision=='approve' else 'denied',now,action['operation_id']))
            if grant:
                db.execute('INSERT INTO grants(id,task_id,capability,fingerprint,expiry,created_at) VALUES(?,?,?,?,?,?)',('grant_'+uuid.uuid4().hex[:16],task_id,'operation:'+action['operation_id'],fingerprint,expires_at,now))
            journal.append(db,task_id,'approval_decided',{'approval_id':approval_id,'operation_id':action['operation_id'],'decision':decision,'action_hash':fingerprint})
            return _public(db.execute('SELECT * FROM approvals WHERE id=?',(approval_id,)).fetchone())

    def has_grant(self, task_id: str, operation_id: str, fingerprint: str) -> bool:
        with self.store.db.read() as db:
            return db.execute("SELECT 1 FROM grants g JOIN tasks t ON t.id=g.task_id JOIN actions a ON a.operation_id=? JOIN plans p ON p.task_id=t.id WHERE g.task_id=? AND a.task_id=t.id AND t.mode='grant' AND t.status NOT IN ('closed','failed','cancelled','recovery_required') AND a.state NOT IN ('unknown','denied','failed') AND a.args_hash=? AND a.plan_revision=p.revision AND p.approved_revision=p.revision AND g.capability=? AND g.fingerprint=? AND g.revoked_at IS NULL AND (g.expiry IS NULL OR g.expiry>?)",(operation_id,task_id,fingerprint,'operation:'+operation_id,fingerprint,time.time())).fetchone() is not None

    def grants(self, task_id: str) -> list[dict[str, Any]]:
        """Display the same effective task-scoped grants that dispatch checks."""
        self.store.task(task_id)
        with self.store.db.read() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM grants WHERE task_id=? ORDER BY created_at DESC',(task_id,)).fetchall()]
        for row in rows:
            if row['capability']=='sandbox_network':
                from harness.network_access import current
                permission=current(self.store,task_id)
                row['active']=bool(permission and permission['id']==row['id'])
                continue
            operation = row['capability'].removeprefix('operation:')
            row['active'] = row['capability'].startswith('operation:') and self.has_grant(task_id, operation, row['fingerprint'])
        return rows

    def revoke(self, task_id: str) -> None:
        """Revoke repeat-operation grants; networking has its own stop-aware API."""
        self.store.task(task_id)
        with self.store.db.write() as db:
            db.execute("UPDATE grants SET revoked_at=? WHERE task_id=? AND capability!='sandbox_network' AND revoked_at IS NULL",(time.time(),task_id))

    def matching_grant(self, task_id: str, fingerprint: str) -> bool:
        """A new deliberate invocation may use the same task-scoped capability.

        The grant remains bound to the approved source operation. The new call
        still receives its own operation_id and never replays the source effect.
        """
        with self.store.db.read() as db:
            rows=db.execute('SELECT capability FROM grants WHERE task_id=? AND fingerprint=? AND revoked_at IS NULL',(task_id,fingerprint)).fetchall()
        return any(row['capability'].startswith('operation:') and self.has_grant(task_id,row['capability'].removeprefix('operation:'),fingerprint) for row in rows)

    def has_consent(self, task_id: str, fingerprint: str) -> bool:
        with self.store.db.read() as db:
            return db.execute("SELECT 1 FROM approvals r JOIN actions a ON a.operation_id=r.action_id JOIN tasks t ON t.id=r.task_id JOIN plans p ON p.task_id=t.id WHERE r.task_id=? AND r.action_hash=? AND r.state='decided' AND r.decision='approve' AND a.plan_revision=p.revision AND p.approved_revision=p.revision AND t.status NOT IN ('closed','failed','cancelled','recovery_required') LIMIT 1",(task_id,fingerprint)).fetchone() is not None
