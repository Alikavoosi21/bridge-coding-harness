"""Two repairs per task; reconnect/restart cannot replenish the counter.

The existing SQLite command receipts commit with the counter in one transaction.
No agent loop lives here. The controller claims only after acquiring its worker.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from server.errors import ApiError
from server.storage import journal


class RepairBudget:
    def __init__(self, store):
        self.store=store

    def read(self, task_id: str) -> dict[str,Any]:
        self.store.task(task_id)
        with self.store.db.read() as db:
            return dict(db.execute('SELECT * FROM repair_budgets WHERE task_id=?',(task_id,)).fetchone())

    def claim(self, task_id: str, *, key: str, expected_revision: int, reason: str) -> dict[str,Any]:
        return self._change(task_id,key,expected_revision,'claim',reason)

    def replay_claim(self,task_id: str, *, key: str, reason: str) -> dict[str,Any] | None:
        """A checkpoint may replay a final-answer node after the counter advanced."""
        with self.store.db.read() as db:
            receipt=db.execute('SELECT request_hash,response_body FROM command_request_keys WHERE key=?',(f'repair:{task_id}:{key}',)).fetchone()
        if not receipt or not receipt['response_body']:return None
        result=json.loads(receipt['response_body'])
        body={'task_id':task_id,'kind':'claim','revision':result['revision']-1,'reason':reason}
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return result if fingerprint==receipt['request_hash'] else None

    def extend(self, task_id: str, *, key: str, expected_revision: int) -> dict[str,Any]:
        """Human-only endpoint adds one; it does not schedule or run a repair."""
        return self._change(task_id,key,expected_revision,'extend','')

    def _change(self, task_id: str, key: str, expected_revision: int, kind: str, reason: str):
        if not key or len(key)>200:
            raise ApiError('invalid_request','A bounded stable request key is required.',status_code=422)
        receipt_key=f'repair:{task_id}:{key}'
        body={'task_id':task_id,'kind':kind,'revision':expected_revision,'reason':reason}
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        now=time.time()
        with self.store.db.write() as db:
            receipt=db.execute('SELECT request_hash,response_body FROM command_request_keys WHERE key=?',(receipt_key,)).fetchone()
            if receipt:
                if receipt['request_hash']!=fingerprint:
                    raise ApiError('idempotency_conflict','Repair request key changed.',status_code=409)
                return json.loads(receipt['response_body'])
            task=db.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not task:raise ApiError('not_found','Task not found.',status_code=404)
            budget=dict(db.execute('SELECT * FROM repair_budgets WHERE task_id=?',(task_id,)).fetchone())
            if budget['revision']!=expected_revision:
                raise ApiError('budget_revision_mismatch','Repair budget changed.',status_code=409,current_revision=budget['revision'])
            if kind=='claim':
                if task['status'] not in {'verifying','repairing'}:
                    raise ApiError('conflict','A repair requires an active verification segment.',status_code=409)
                if budget['total_attempts']>=budget['allowed']:
                    raise ApiError('budget_exhausted','Two repairs are used; a human decision is required.',status_code=409)
                budget['total_attempts']+=1
                journal.append(db,task_id,'repair_started',{'repair_index':budget['total_attempts'],'reason':reason})
            else:
                if task['status']!='awaiting_decision' or budget['total_attempts']<budget['allowed']:
                    raise ApiError('conflict','An extension requires an exhausted repair budget awaiting a human.',status_code=409)
                budget['allowed']+=1
            budget['revision']+=1
            db.execute('UPDATE repair_budgets SET allowed=?,total_attempts=?,revision=? WHERE task_id=?',(budget['allowed'],budget['total_attempts'],budget['revision'],task_id))
            db.execute('INSERT INTO command_request_keys(key,request_hash,status_code,response_body,created_at,completed_at) VALUES(?,?,?,?,?,?)',(receipt_key,fingerprint,200,json.dumps(budget),now,now))
            return budget
