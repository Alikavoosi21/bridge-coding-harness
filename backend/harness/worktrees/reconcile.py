"""Human acknowledgement of current original bytes after an interrupted apply.

Inspection and acknowledgement never write a file, replay pending files, or
infer success from a former request. The user accepts the inspected snapshot.
"""
import time
import json

from server.errors import ApiError
from server.storage import journal
from .apply import operation_result
from .diff import changes,review_context
from .guard import locked_copy
from .snapshot import build
from ..verification.observe import snapshot_hash
from ..verification.results import CheckResults,CheckTarget
from ..command_context import saved_profile,profile_identity
from ..task_runtime import runtime_descriptor


def inspect_apply(store,task_id,operation_id):
    operation=operation_result(store,task_id,operation_id)
    task,directory,_,original,_=review_context(store,task_id)
    snapshot=build(original);entries=snapshot.by_path()
    unsupported={row['path'] for row in snapshot.excluded}
    files=[]
    for row in operation['files']:
        entry=entries.get(row['path']);digest=entry.sha256 if entry else None
        comparison='unsupported' if row['path'] in unsupported else 'after' if digest==row['after_hash'] else 'before' if digest==row['before_hash'] else 'other'
        files.append({**row,'observed_hash':digest,'comparison':comparison})
    working=changes(store,task_id)
    with store.db.read() as db:
        selection=dict(db.execute('SELECT * FROM apply_selections WHERE id=?',(operation['selection_id'],)).fetchone())
        restore_actions=db.execute("SELECT operation_id,state,result_ref FROM actions WHERE task_id=? AND invocation_key LIKE 'restore:%' ORDER BY created_at",(task_id,)).fetchall()
    restores=[]
    for action in restore_actions:
        try:detail=json.loads(action['result_ref'] or '{}')
        except (ValueError,TypeError):continue
        if detail.get('apply_operation_id')==operation_id:
            restores.append({'id':action['operation_id'],'state':detail.get('state') or action['state'],'files':detail.get('files',[])})
    profile=saved_profile(store,task);runtime=runtime_descriptor(store,task_id)
    required=[str(row.get('id') or row.get('name') or row['command']) for row in profile.get('commands',[]) if row.get('required')]
    target=CheckTarget('apply_candidate',selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'],selection['id'])
    quality=CheckResults(store).quality(task_id,target=target,required=required)
    from .snapshot import _is_link_path
    capture=directory/'selections'/selection['id']
    if profile_identity(profile)!=selection['profile_hash'] or not runtime or runtime['runtime_id']!=selection['runtime_fingerprint'] or _is_link_path(capture.parent) or _is_link_path(capture) or snapshot_hash(build(capture))!=selection['candidate_manifest_hash']:
        quality={**quality,'quality_status':'stale'}
    original_hash=snapshot_hash(snapshot)
    return {**operation,'files':files,'restore_operations':restores,'original_manifest_hash':original_hash,'working_revision':working['working_revision'],'working_manifest_hash':working['working_manifest_hash'],'candidate_quality':quality,'original_matches_candidate':original_hash==selection['candidate_manifest_hash'],'original_quality_status':quality['quality_status'] if original_hash==selection['candidate_manifest_hash'] else 'not_verified'}


def keep_current_apply(store,task_id,operation_id,*,expected_original_hash,expected_revision,expected_working_hash,accept_current=False):
    if not accept_current:raise ApiError('action_not_approved','Explicit acceptance of the inspected current original is required.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_working_hash,kind='apply_reconcile',recovery_operation=operation_id) as held:
        preview=inspect_apply(store,task_id,operation_id)
        if preview['state'] not in {'prepared','applying','partial','unknown'}:
            raise ApiError('selection_stale','This apply is not awaiting reconciliation.',status_code=409)
        if preview['original_manifest_hash']!=expected_original_hash:
            raise ApiError('selection_stale','The original changed after inspection; inspect it again.',status_code=409)
        held['lease'].check('keep inspected original')
        now=time.time()
        with store.db.write() as db:
            for row in preview['files']:
                state='applied' if row['comparison']=='after' else 'not_applied' if row['comparison']=='before' else 'kept_current'
                db.execute('UPDATE apply_files SET state=?,current_hash=? WHERE operation_id=? AND path=?',(state,row['observed_hash'],operation_id,row['path']))
            db.execute("UPDATE apply_operations SET state='reconciled',updated_at=? WHERE id=?",(now,operation_id))
            current=db.execute('SELECT status FROM tasks WHERE id=?',(task_id,)).fetchone()
            if current['status']=='recovery_required':
                db.execute("UPDATE tasks SET status='paused',revision=revision+1,updated_at=? WHERE id=?",(now,task_id))
                journal.append(db,task_id,'task_state_changed',{'state':'paused','reason':'apply_current_accepted'})
            journal.append(db,task_id,'recovery_required',{'operation_id':operation_id,'reason':'current_original_accepted','reconcile_required':False})
        return {**operation_result(store,task_id,operation_id),'resolution':'kept_current','accepted_original_manifest_hash':expected_original_hash}
