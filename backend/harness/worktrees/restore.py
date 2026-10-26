"""Hash-conditional restoration of known applied files, never repository reset."""
import hashlib
import json
import os

from server.errors import ApiError
from .apply import operation_result
from .diff import changes,review_context,MAX_REVIEW_BYTES
from .file_lock import locked_regular_file,delete_locked_file
from .guard import locked_copy
from .snapshot import build,_is_link_path
from ..verification.observe import snapshot_hash


def restore_preview(store,task_id,operation_id):
    operation=operation_result(store,task_id,operation_id)
    _,_,_,original,_=review_context(store,task_id)
    snapshot=build(original);current=snapshot.by_path()
    unsupported={row['path'] for row in snapshot.excluded}
    files=[]
    for row in operation['files']:
        now=current.get(row['path']);digest=now.sha256 if now else None
        files.append({**row,'observed_hash':digest,'restorable':row['state']=='applied' and digest==row['after_hash'] and row['path'] not in unsupported})
    return {'operation_id':operation_id,'state':operation['state'],'original_manifest_hash':snapshot_hash(snapshot),'files':files}


def restore_operation(store,task_id,operation_id,*,key,paths,expected_original_hash,expected_working_revision,expected_working_hash,confirm=False):
    if not confirm or not paths or len(paths)!=len(set(paths)):
        raise ApiError('action_not_approved','Explicit confirmation of distinct restore paths is required.',status_code=409)
    body={'apply':operation_id,'paths':sorted(paths),'original':expected_original_hash,'working':expected_working_hash,'revision':expected_working_revision}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    invocation='restore:'+key
    prior=store.action_by_invocation(task_id,invocation)
    if prior:
        if prior['args_hash']!=digest:raise ApiError('idempotency_conflict','Restore key was used for another request.',status_code=409)
        if prior['state']=='succeeded':return json.loads(prior['result_ref'])
        if prior['state']!='pending':raise ApiError('recovery_required','This restore needs reconciliation; no automatic replay.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_working_revision,expected_manifest_hash=expected_working_hash,kind='restore',recovery_operation=operation_id) as held:
        preview=restore_preview(store,task_id,operation_id)
        if preview['state'] not in {'applied','partial','reconciled'}:
            raise ApiError('recovery_required','Only known applied files can be restored; reconcile unknown effects first.',status_code=409)
        if preview['original_manifest_hash']!=expected_original_hash:
            raise ApiError('selection_stale','The original changed since restore preview.',status_code=409)
        rows={row['path']:row for row in preview['files']}
        if any(path not in rows or not rows[path]['restorable'] for path in paths):
            raise ApiError('selection_stale','A selected file changed after apply; it will not be overwritten.',status_code=409)
        folder=held['directory']/'apply-journals'/operation_id
        if _is_link_path(folder.parent) or _is_link_path(folder):
            raise ApiError('recovery_required','Apply journal unavailable.',status_code=409)
        if _is_link_path(folder/'prepare.json'):raise ApiError('recovery_required','Apply journal metadata is unavailable.',status_code=409)
        try:
            metadata=json.loads((folder/'prepare.json').read_text(encoding='utf8'))
            indices={row['path']:index for index,row in enumerate(metadata['files'])}
            if any(path not in indices for path in paths):raise ValueError('missing restore path')
        except (OSError,ValueError,KeyError,TypeError):raise ApiError('recovery_required','Apply journal cannot be read.',status_code=409) from None
        before_images={}
        for path in paths:
            row=rows[path]
            if row['before_hash'] is None:continue
            image=folder/f'{indices[path]}-before.bin'
            if _is_link_path(image):raise ApiError('recovery_required','Before-image is a link.',status_code=409)
            with image.open('rb') as file:data=file.read(MAX_REVIEW_BYTES+1)
            if len(data)>MAX_REVIEW_BYTES or hashlib.sha256(data).hexdigest()!=row['before_hash']:
                raise ApiError('recovery_required','Before-image changed; restoration refused.',status_code=409)
            before_images[path]=data
        action=store.ensure_action(task_id,invocation,digest)
        if action['state']=='succeeded':return json.loads(action['result_ref'])
        if action['state']!='pending':raise ApiError('recovery_required','Restore already dispatched.',status_code=409)
        # Durable claim includes the exact paths and image hashes. A crash after
        # this point leaves a non-replayable action even if no byte was changed.
        state={'apply_operation_id':operation_id,'requested_paths':list(paths),'expected_original_hash':expected_original_hash,'files':[]}
        store.set_action_state(action['operation_id'],'dispatching',result_ref=json.dumps(state))
        for path in paths:
            row=rows[path];writing=False
            try:
                held['lease'].check('restore file')
                with locked_regular_file(held['original'],path,create_new=row['after_hash'] is None,delete_access=row['before_hash'] is None) as file:
                    current=file.read(MAX_REVIEW_BYTES+1)
                    if row['after_hash'] is not None and hashlib.sha256(current).hexdigest()!=row['after_hash']:
                        raise ApiError('selection_stale','A file changed immediately before restoration.',status_code=409)
                    writing=True
                    if row['before_hash'] is None:delete_locked_file(file)
                    else:
                        file.seek(0);file.write(before_images[path]);file.truncate();file.flush();os.fsync(file.fileno())
                    held['lease'].check('confirm restoration')
                state['files'].append({'path':path,'state':'restored','hash':row['before_hash']})
                store.set_action_state(action['operation_id'],'running',result_ref=json.dumps(state))
            except BaseException as error:
                unknown=writing or row['after_hash'] is None
                state['files'].append({'path':path,'state':'unknown' if unknown else 'conflict'})
                state['state']='unknown' if unknown else 'partial'
                store.set_action_state(action['operation_id'],'unknown' if unknown else 'failed',result_ref=json.dumps(state),error='Restore did not finish for all selected files.')
                if unknown:store.set_task_status(task_id,'recovery_required',reason='restore_unknown')
                if not isinstance(error,Exception):raise
                return {**state,'operation_id':action['operation_id']}
        result={**state,'operation_id':action['operation_id'],'state':'restored'}
        store.set_action_state(action['operation_id'],'succeeded',result_ref=json.dumps(result))
        return result


def inspect_interrupted_restore(store,task_id,restore_id):
    from .diff import changes,review_context
    action=store.action(restore_id)
    if action['task_id']!=task_id or not action['invocation_key'].startswith('restore:'):raise ApiError('not_found','Restore not found.',status_code=404)
    state=json.loads(action['result_ref'] or '{}');apply_id=state.get('apply_operation_id')
    if not apply_id:raise ApiError('recovery_required','Restore journal is incomplete.',status_code=409)
    with store.db.read() as db:
        rows=[dict(row) for row in db.execute('SELECT path,before_hash,after_hash FROM apply_files WHERE operation_id=?',(apply_id,))]
    report=changes(store,task_id);original=review_context(store,task_id)[3]
    entries=build(original).by_path()
    unsupported={row['path'] for row in build(original).excluded}
    files=[]
    for row in rows:
        if row['path'] not in state.get('requested_paths',[]):continue
        entry=entries.get(row['path']);digest=entry.sha256 if entry else None
        files.append({'path':row['path'],'observed_hash':digest,'state':'unsupported' if row['path'] in unsupported else 'restored' if digest==row['before_hash'] else 'not_restored' if digest==row['after_hash'] else 'kept_current'})
    return {'operation_id':restore_id,'action_state':action['state'],'apply_operation_id':apply_id,'files':files,**{key:report[key] for key in ('original_manifest_hash','working_revision','working_manifest_hash')}}


def accept_interrupted_restore(store,task_id,restore_id,*,expected_original_hash,expected_working_revision,expected_working_hash,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Review the current original files explicitly.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_working_revision,expected_manifest_hash=expected_working_hash,kind='restore_reconcile',recovery_operation=restore_id):
        preview=inspect_interrupted_restore(store,task_id,restore_id)
        if preview['action_state']!='unknown' or preview['original_manifest_hash']!=expected_original_hash:raise ApiError('selection_stale','Restore or original bytes changed; inspect again.',status_code=409)
        result={**preview,'state':'reconciled','resolution':'kept_current'}
        store.set_action_state(restore_id,'failed',result_ref=json.dumps(result))
        store.clear_plan_approval(task_id,reason='restore_current_accepted')
        store.set_task_status(task_id,'paused',reason='restore_current_accepted_unverified')
        return result
