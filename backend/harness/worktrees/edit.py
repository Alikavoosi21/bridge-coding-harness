"""Human edit of an existing UTF-8 working file, with durable before-image.

An interrupted write is unknown and is never retried automatically. This does
not mutate the user's original project or reset verification/repair history.
"""
import hashlib
import json
import os

from server.errors import ApiError
from ..verification.observe import manifest_hash
from .diff import MAX_REVIEW_BYTES
from .file_lock import locked_regular_file
from .guard import locked_copy
from .snapshot import validate_relative,excluded
from .state import observe


def _digest(data):return hashlib.sha256(data).hexdigest()


def _durable(path,data):
    with path.open('xb') as file:
        file.write(data);file.flush();os.fsync(file.fileno())


def edit_recovery_details(store,task_id,operation_id):
    """Bounded inspection of the durable before/requested/current versions."""
    from .diff import review_context,working_file
    from .snapshot import _is_link_path
    action=store.action(operation_id)
    if action['task_id']!=task_id or not action['invocation_key'].startswith('manual-edit:'):
        raise ApiError('not_found','Manual edit not found.',status_code=404)
    _,directory,_,_,_=review_context(store,task_id)
    folder=directory/'manual-edits'/operation_id
    if _is_link_path(folder.parent) or _is_link_path(folder):
        raise ApiError('recovery_required','The edit journal is unavailable.',status_code=409)
    try:
        metadata=json.loads((folder/'prepare.json').read_text(encoding='utf8'))
        relative=validate_relative(metadata['path'])
        if excluded(relative):raise ValueError('excluded')
        versions={}
        for name,hash_key in [('before','before_hash'),('after','after_hash')]:
            file=folder/(name+'.bin')
            if _is_link_path(file):raise ValueError('linked journal')
            with file.open('rb') as stream:data=stream.read(MAX_REVIEW_BYTES+1)
            if len(data)>MAX_REVIEW_BYTES or _digest(data)!=metadata[hash_key]:raise ValueError('invalid journal hash')
            versions[name]=data.decode('utf-8-sig')
    except (OSError,ValueError,KeyError,TypeError):
        raise ApiError('recovery_required','The edit journal is incomplete or changed.',status_code=409) from None
    return {'operation_id':operation_id,'state':action['state'],'path':str(relative),'before':versions['before'],'requested':versions['after'],'current':working_file(store,task_id,str(relative))}


def save_working_file(store,task_id,*,path,content,expected_revision,expected_manifest_hash,expected_file_hash,key):
    relative=validate_relative(path)
    if excluded(relative):raise ApiError('invalid_request','Excluded file cannot be edited.',status_code=422)
    material={'path':str(relative),'content':content,'revision':expected_revision,'manifest':expected_manifest_hash,'hash':expected_file_hash}
    body_hash=_digest(json.dumps(material,ensure_ascii=False,sort_keys=True).encode())
    prior=store.action_by_invocation(task_id,'manual-edit:'+key)
    if prior:
        if prior['args_hash']!=body_hash:raise ApiError('idempotency_conflict','This edit key was used for different content.',status_code=409)
        if prior['state']=='succeeded':return json.loads(prior['result_ref'])
        if prior['state']!='pending':raise ApiError('recovery_required','The previous edit needs reconciliation; it will not be repeated.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_manifest_hash) as held:
        operation=store.ensure_action(task_id,'manual-edit:'+key,body_hash)
        if operation['state']=='succeeded':return json.loads(operation['result_ref'])
        if operation['state']!='pending':raise ApiError('recovery_required','This edit cannot be dispatched again.',status_code=409)
        with locked_regular_file(held['working'],str(relative)) as file:
            before=file.read(MAX_REVIEW_BYTES+1)
            if len(before)>MAX_REVIEW_BYTES or b'\0' in before:
                raise ApiError('invalid_request','This file cannot be edited as text.',status_code=422)
            if _digest(before)!=expected_file_hash:raise ApiError('selection_stale','The opened file changed.',status_code=409)
            try:before.decode('utf-8-sig')
            except UnicodeError:raise ApiError('invalid_request','Only UTF-8 files can be edited.',status_code=422) from None
            normalized=content.replace('\r\n','\n').replace('\r','\n')
            if b'\r\n' in before:normalized=normalized.replace('\n','\r\n')
            after=normalized.encode('utf-8-sig' if before.startswith(b'\xef\xbb\xbf') else 'utf-8')
            if len(after)>MAX_REVIEW_BYTES or b'\0' in after:raise ApiError('invalid_request','Edited content is too large or binary.',status_code=422)
            folder=held['directory']/'manual-edits'/operation['operation_id']
            folder.mkdir(parents=True,exist_ok=True)
            # A previous pending prepare can only have these exact content hashes.
            for name,data in [('before.bin',before),('after.bin',after)]:
                target=folder/name
                if target.exists():
                    if target.read_bytes()!=data:raise ApiError('recovery_required','The saved edit journal differs.',status_code=409)
                else:_durable(target,data)
            metadata={'path':str(relative),'before_hash':_digest(before),'after_hash':_digest(after),'expected_working_revision':expected_revision}
            if not (folder/'prepare.json').exists():_durable(folder/'prepare.json',json.dumps(metadata,ensure_ascii=False).encode())
            held['lease'].check('save working file')
            # Recheck all inputs immediately before the write, while the file and
            # its directory chain cannot be replaced by another Windows editor.
            if manifest_hash(held['working'])!=expected_manifest_hash:
                raise ApiError('selection_stale','Working inputs changed before saving.',status_code=409)
            with store.db.write() as db:
                changed=db.execute("UPDATE actions SET state='dispatching' WHERE operation_id=? AND state='pending'",(operation['operation_id'],)).rowcount
                if changed!=1:raise ApiError('recovery_required','The edit was already dispatched.',status_code=409)
            try:
                file.seek(0);file.write(after);file.truncate();file.flush();os.fsync(file.fileno())
                held['lease'].check('finish working edit')
                version=observe(store,task_id,manifest_hash(held['working']))
                result={'path':str(relative),'hash':metadata['after_hash'],'working_revision':version['revision'],'working_manifest_hash':version['manifest_hash'],'operation_id':operation['operation_id']}
                store.set_action_state(operation['operation_id'],'succeeded',result_ref=json.dumps(result))
                store.record_event(task_id,'file_changed',{'file_id':'file_'+hashlib.sha256((task_id+'\0'+str(relative)).encode()).hexdigest()[:20],'change_kind':'modified','origin':'manual_edit',**result})
                return result
            except BaseException:
                store.set_action_state(operation['operation_id'],'unknown',error='Manual edit interrupted; inspect its before/after image before continuing.')
                store.set_task_status(task_id,'recovery_required',reason='manual_edit_unknown')
                raise


def accept_current_after_interruption(store,task_id,operation_id,*,expected_revision,expected_manifest_hash,expected_file_hash):
    """Explicitly keep inspected current bytes; never rewrite or replay a save."""
    from server.storage import journal
    import time
    action=store.action(operation_id)
    if action['task_id']!=task_id or not action['invocation_key'].startswith('manual-edit:'):
        raise ApiError('not_found','Manual edit not found.',status_code=404)
    if action['state'] not in {'unknown','dispatching','running'}:
        raise ApiError('selection_stale','This edit is not awaiting reconciliation.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_manifest_hash,kind='manual_reconcile',recovery_operation=operation_id) as held:
        try:metadata=json.loads((held['directory']/'manual-edits'/operation_id/'prepare.json').read_text(encoding='utf8'))
        except (OSError,ValueError):raise ApiError('recovery_required','The edit journal cannot be read.',status_code=409) from None
        if not isinstance(metadata,dict) or not all(isinstance(metadata.get(key),str) for key in ('path','before_hash','after_hash')):
            raise ApiError('recovery_required','The edit journal is incomplete.',status_code=409)
        with locked_regular_file(held['working'],metadata['path']) as file:
            data=file.read(MAX_REVIEW_BYTES+1)
            if len(data)>MAX_REVIEW_BYTES or _digest(data)!=expected_file_hash:
                raise ApiError('selection_stale','The inspected file changed; review it again.',status_code=409)
            if manifest_hash(held['working'])!=expected_manifest_hash:
                raise ApiError('selection_stale','Working inputs changed during reconciliation.',status_code=409)
            held['lease'].check('accept interrupted edit')
            result={'path':metadata['path'],'hash':expected_file_hash,'working_revision':held['version']['revision'],'working_manifest_hash':held['version']['manifest_hash'],'operation_id':operation_id,'resolution':'kept_current','matches_requested_edit':expected_file_hash==metadata['after_hash']}
            now=time.time()
            with store.db.write() as db:
                state='succeeded' if result['matches_requested_edit'] else 'failed'
                changed=db.execute("UPDATE actions SET state=?,result_ref=?,updated_at=? WHERE operation_id=? AND state IN ('dispatching','running','unknown')",(state,json.dumps(result),now,operation_id)).rowcount
                if changed!=1:raise ApiError('selection_stale','The edit was already reconciled.',status_code=409)
                db.execute("UPDATE tasks SET status='paused',revision=revision+1,updated_at=? WHERE id=?",(now,task_id))
                journal.append(db,task_id,'action_finished',{'operation_id':operation_id,'state':state,'resolution':'kept_current','result_ref':json.dumps(result)})
                journal.append(db,task_id,'task_state_changed',{'state':'paused','reason':'manual_edit_reconciled'})
            return result
