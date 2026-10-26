"""Check evidence bound to an exact target, profile, runtime and input manifest.

Storage and classification only; commands must use the existing runtime/gateway.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

from server.errors import ApiError
from server.storage.contract import VERIFICATION_OUTCOMES


@dataclass(frozen=True)
class CheckTarget:
    kind: str
    manifest_hash: str
    profile_hash: str
    runtime_fingerprint: str
    selection_id: str | None = None

    def __post_init__(self):
        if self.kind not in {'working_copy','apply_candidate'} or (self.kind=='apply_candidate') != bool(self.selection_id):
            raise ValueError('Candidate evidence requires its selection; working evidence has no selection.')
        if not all((self.manifest_hash,self.profile_hash,self.runtime_fingerprint)):
            raise ValueError('Evidence requires manifest, profile and runtime identities.')


class CheckResults:
    def __init__(self,store):self.store=store

    def list(self,task_id: str) -> list[dict]:
        self.store.task(task_id)
        with self.store.db.read() as db:
            rows=db.execute('SELECT * FROM verification_results WHERE task_id=? ORDER BY created_at,id',(task_id,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item['details']=json.loads(item.pop('output_ref') or '{}')
            result.append(item)
        return result

    def record(self,task_id: str, *, target: CheckTarget, check_id: str, outcome: str, command: str, output: str='', phase: str='current', failure_kind: str|None=None, output_truncated: bool=False) -> dict:
        if outcome not in VERIFICATION_OUTCOMES or phase not in {'baseline','current'} or not check_id:
            raise ValueError('Invalid verification evidence.')
        if failure_kind not in {None,'assertion','installation','network','runtime'}:
            raise ValueError('Invalid failure classification.')
        self.store.task(task_id)
        encoded=output.encode('utf-8')
        details={'check_id':check_id,'command':command,'phase':phase,'output':encoded[:65536].decode('utf-8',errors='ignore'),'truncated':output_truncated or len(encoded)>65536,'failure_kind':failure_kind}
        identifier='check_'+uuid.uuid4().hex[:16]
        with self.store.db.write() as db:
            if target.selection_id:
                selection=db.execute('SELECT * FROM apply_selections WHERE id=? AND task_id=?',(target.selection_id,task_id)).fetchone()
                if not selection or (selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'])!=(target.manifest_hash,target.profile_hash,target.runtime_fingerprint):
                    raise ApiError('selection_stale','Candidate no longer matches this check target.',status_code=409)
            db.execute('INSERT INTO verification_results(id,task_id,target_kind,selection_id,profile_hash,input_manifest_hash,runtime_fingerprint,outcome,output_ref,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,task_id,target.kind,target.selection_id,target.profile_hash,target.manifest_hash,target.runtime_fingerprint,outcome,json.dumps(details,ensure_ascii=False),time.time()))
        return {'id':identifier,'outcome':outcome,**details}

    def quality(self,task_id: str, *, target: CheckTarget, required: list[str]) -> dict:
        """Only latest current evidence for every required check can be green."""
        self.store.task(task_id)
        with self.store.db.read() as db:
            if target.selection_id:
                selection=db.execute('SELECT * FROM apply_selections WHERE id=? AND task_id=?',(target.selection_id,task_id)).fetchone()
                if not selection or (selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'])!=(target.manifest_hash,target.profile_hash,target.runtime_fingerprint):
                    return {'quality_status':'stale','check_refs':[]}
            rows=db.execute('SELECT * FROM verification_results WHERE task_id=? AND target_kind=? AND selection_id IS ? ORDER BY created_at DESC,rowid DESC',(task_id,target.kind,target.selection_id)).fetchall()
        latest={}
        for row in rows:
            details=json.loads(row['output_ref'])
            if details['phase']=='current':latest.setdefault(details['check_id'],row)
        refs=[];status='verified_snapshot' if required else 'not_verified'
        for check in required:
            row=latest.get(check)
            if row is None:
                if status!='failed':status='not_verified'
                continue
            refs.append(row['id'])
            if (row['input_manifest_hash'],row['profile_hash'],row['runtime_fingerprint'])!=(target.manifest_hash,target.profile_hash,target.runtime_fingerprint):
                return {'quality_status':'stale','check_refs':refs}
            if row['outcome']=='failed':status='failed'
            elif row['outcome']!='passed' and status!='failed':status='not_verified'
        return {'quality_status':status,'check_refs':refs}
