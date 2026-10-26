"""Human repair-budget decisions; extending never starts an agent or a command."""
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse
import time
from pydantic import BaseModel,Field

from harness.verification.budget import RepairBudget
from harness.verification.results import CheckResults
from harness.verification.observe import manifest_hash,current_quality
from harness.command_context import saved_profile
from harness.task_runtime import task_directory,runtime_descriptor
from server.storage import Store
from server.storage import journal
from server.errors import ApiError

router=APIRouter(tags=['checks'])


@router.get('/tasks/{task_id}/checks')
def checks(task_id: str):
    store=Store();task=store.task(task_id);results=CheckResults(store)
    profile=saved_profile(store,task)
    required=[str(row.get('id') or row.get('name') or row['command']) for row in profile.get('commands',[]) if row.get('required')]
    working=task_directory(store,task_id)/'working'
    runtime=runtime_descriptor(store,task_id)
    quality={'quality_status':'not_verified','check_refs':[]}
    current_hash=None
    if working.is_dir() and runtime and profile.get('profile_hash'):
        current_hash=manifest_hash(working)
    observed=current_quality(store,task_id,working if working.is_dir() else None,runtime['runtime_id'] if runtime else 'unavailable',input_hash=current_hash)
    if observed is not None:quality={key:value for key,value in observed.items() if key!='commands'}
    return {'items':results.list(task_id),'quality':quality,'required':required,'input_manifest_hash':current_hash,'profile_hash':profile.get('profile_hash'),'runtime_fingerprint':runtime['runtime_id'] if runtime else None,'repair_budget':RepairBudget(store).read(task_id),'execution_budget':store.budget(task_id)}


class RepairExtension(BaseModel):
    idempotency_key: str=Field(min_length=1,max_length=200)
    expected_revision: int=Field(ge=1)


@router.get('/tasks/{task_id}/repair-budget')
def repair_budget(task_id: str):
    return RepairBudget(Store()).read(task_id)


@router.post('/tasks/{task_id}/repair-extensions')
def extend(task_id: str, body: RepairExtension):
    return RepairBudget(Store()).extend(task_id,key=body.idempotency_key,expected_revision=body.expected_revision)


@router.post('/tasks/{task_id}/quality-endings')
def end_unverified(task_id: str, body: RepairExtension, request: Request):
    """End an idle quality decision without applying files or claiming success."""
    store=Store()
    def handler():
        task=store.task(task_id)
        if request.app.state.harness.is_running(task['thread_id']):
            raise ApiError('workspace_busy','Stop the active run before ending this task.',status_code=409)
        now=time.time()
        with store.db.write() as db:
            current=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if current['status']=='closed' and current['outcome']=='user_ended_unverified' and current['revision']==body.expected_revision+1:
                return 200,{'task':store.task(task_id)}
            if current['revision']!=body.expected_revision or current['status']!='awaiting_decision':
                raise ApiError('selection_stale','The quality decision changed.',status_code=409,current_revision=current['revision'])
            if db.execute("SELECT 1 FROM actions WHERE task_id=? AND state IN ('dispatching','running','unknown') LIMIT 1",(task_id,)).fetchone():
                raise ApiError('recovery_required','An operation still needs reconciliation.',status_code=409)
            db.execute("UPDATE tasks SET status='closed',outcome='user_ended_unverified',revision=revision+1,updated_at=? WHERE id=?",(now,task_id))
            db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL',(now,task_id))
            db.execute("UPDATE approvals SET state='cancelled' WHERE task_id=? AND state='pending'",(task_id,))
            db.execute("UPDATE actions SET state='denied',updated_at=? WHERE task_id=? AND state IN ('pending','awaiting_approval')",(now,task_id))
            journal.append(db,task_id,'task_state_changed',{'state':'closed','outcome':'user_ended_unverified','reason':'user_ended_unverified','revision':body.expected_revision+1})
        return 200,{'task':store.task(task_id)}
    status,result,replayed=store.run_idempotent('quality-end:'+task_id+':'+body.idempotency_key,{'task_id':task_id,'revision':body.expected_revision},handler)
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)
