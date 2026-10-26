"""Explicit file-level apply. Journal each effect; never replay an unknown write.

Windows handles protect the final target against concurrent writers/path swaps.
There is no promise of a multi-file atomic transaction or automatic rollback.
"""
import hashlib
import json
import os
import time
import uuid

from server.errors import ApiError
from server.storage import journal
from ..verification.results import CheckResults,CheckTarget
from .candidate_checks import required_commands
from .diff import changes,MAX_REVIEW_BYTES
from .edit import _durable
from .file_lock import locked_regular_file,delete_locked_file
from .guard import locked_copy
from .selection import validate_selection
from .snapshot import build,_is_link_path


def operation_result(store,task_id,operation_id):
    with store.db.read() as db:
        row=db.execute('SELECT * FROM apply_operations WHERE id=? AND task_id=?',(operation_id,task_id)).fetchone()
        if row is None:raise ApiError('not_found','Apply operation not found.',status_code=404)
        files=[dict(item) for item in db.execute('SELECT path,before_hash,current_hash,after_hash,state FROM apply_files WHERE operation_id=? ORDER BY path',(operation_id,))]
    return {'id':row['id'],'selection_id':row['selection_id'],'state':row['state'],'files':files}


def apply_selection(store,task_id,selection_id,*,key,quality_ack=False,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Explicit confirmation to change the original is required.',status_code=409)
    namespaced=task_id+':'+key
    with store.db.read() as db:previous=db.execute('SELECT * FROM apply_operations WHERE idempotency_key=?',(namespaced,)).fetchone()
    if previous:
        if previous['selection_id']!=selection_id or bool(previous['quality_ack'])!=quality_ack:
            raise ApiError('idempotency_conflict','Apply key was used for a different request.',status_code=409)
        # Historical receipt only. A nonterminal operation is displayed for
        # reconciliation, never executed again, even when the request is retried.
        return operation_result(store,task_id,previous['id'])
    selection=validate_selection(store,task_id,selection_id)
    report=changes(store,task_id)
    with locked_copy(store,task_id,expected_revision=selection['working_revision'],expected_manifest_hash=report['working_manifest_hash'],kind='apply') as held:
        selection=validate_selection(store,task_id,selection_id)
        target=CheckTarget('apply_candidate',selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'],selection_id)
        quality=CheckResults(store).quality(task_id,target=target,required=[row['id'] for row in required_commands(store,task_id)])
        if quality['quality_status']!='verified_snapshot' and not quality_ack:
            raise ApiError('action_not_approved','This exact candidate has no successful checks; explicit quality acknowledgement is required.',status_code=409)
        selected=[row for row in report['items'] if row['file_id'] in selection['file_ids']]
        if len(selected)!=len(selection['file_ids']) or any(row['conflict'] for row in selected):
            raise ApiError('selection_stale','Selected files conflict with the current original.',status_code=409)
        identifier='apply_'+uuid.uuid4().hex
        folder=held['directory']/'apply-journals'/identifier
        folder.mkdir(parents=True)
        capture=held['directory']/'selections'/selection_id
        # Durable byte images are prepared before ANY original mutation.
        original=build(held['original']).by_path();candidate=build(capture).by_path()
        for index,row in enumerate(selected):
            for name,root,entries in [('before',held['original'],original),('after',capture,candidate)]:
                entry=entries.get(row['path'])
                if entry is None:continue
                file=root/row['path']
                if _is_link_path(file) or entry.size>MAX_REVIEW_BYTES:
                    raise ApiError('invalid_request','This apply input is unsupported.',status_code=422)
                with file.open('rb') as stream:data=stream.read(MAX_REVIEW_BYTES+1)
                if len(data)>MAX_REVIEW_BYTES or hashlib.sha256(data).hexdigest()!=entry.sha256:
                    raise ApiError('selection_stale','Apply input changed while journaling.',status_code=409)
                _durable(folder/f'{index}-{name}.bin',data)
        _durable(folder/'prepare.json',json.dumps({'selection_id':selection_id,'files':selected,'quality':quality},ensure_ascii=False).encode())
        validate_selection(store,task_id,selection_id)
        now=time.time()
        with store.db.write() as db:
            db.execute('INSERT INTO apply_operations(id,task_id,selection_id,expected_working_revision,lease_token,quality_ack,idempotency_key,state,journal_ref,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identifier,task_id,selection_id,selection['working_revision'],held['lease'].lease_id,'unverified accepted' if quality_ack else None,namespaced,'prepared',str(folder),now,now))
            for row in selected:db.execute('INSERT INTO apply_files(operation_id,path,before_hash,current_hash,after_hash,state) VALUES(?,?,?,?,?,?)',(identifier,row['path'],row['current_hash'],row['current_hash'],row['working_hash'],'pending'))
        for index,row in enumerate(selected):
            writing=False
            try:
                held['lease'].check('apply file')
                # Each destination is independently revalidated against its
                # before hash under its exclusive handle. Never force overwrite.
                with locked_regular_file(held['original'],row['path'],create_new=row['kind']=='added',delete_access=row['kind']=='deleted') as file:
                    before=file.read(MAX_REVIEW_BYTES+1)
                    if row['current_hash'] is not None and hashlib.sha256(before).hexdigest()!=row['current_hash']:
                        raise ApiError('selection_stale','The original changed before applying this file.',status_code=409)
                    with store.db.write() as db:
                        db.execute("UPDATE apply_files SET state='writing' WHERE operation_id=? AND path=?",(identifier,row['path']))
                        db.execute("UPDATE apply_operations SET state='applying',updated_at=? WHERE id=?",(time.time(),identifier))
                    writing=True
                    held['lease'].check('write original file')
                    if row['kind']=='deleted':delete_locked_file(file)
                    else:
                        after=(folder/f'{index}-after.bin').read_bytes()
                        if hashlib.sha256(after).hexdigest()!=row['working_hash']:
                            raise ApiError('recovery_required','The captured after-image changed.',status_code=409)
                        file.seek(0);file.write(after);file.truncate();file.flush();os.fsync(file.fileno())
                    held['lease'].check('confirm applied file')
                with store.db.write() as db:
                    db.execute("UPDATE apply_files SET state='applied',current_hash=after_hash WHERE operation_id=? AND path=?",(identifier,row['path']))
                    journal.append(db,task_id,'apply_file_finished',{'operation_id':identifier,'path':row['path'],'file_id':row['file_id'],'state':'applied'})
            except BaseException as error:
                with store.db.read() as db:
                    durable=db.execute('SELECT state FROM apply_files WHERE operation_id=? AND path=?',(identifier,row['path'])).fetchone()
                state='unknown' if writing or (durable and durable['state']=='writing') else 'conflict'
                # A newly created empty target is already an effect even when
                # prepare failed. Treat its unresolved state conservatively.
                if row['kind']=='added':state='unknown'
                with store.db.write() as db:
                    db.execute('UPDATE apply_files SET state=? WHERE operation_id=? AND path=?',(state,identifier,row['path']))
                    db.execute('UPDATE apply_operations SET state=?,updated_at=? WHERE id=?',('unknown' if state=='unknown' else 'partial',time.time(),identifier))
                    journal.append(db,task_id,'apply_file_finished',{'operation_id':identifier,'path':row['path'],'file_id':row['file_id'],'state':state})
                if state=='unknown':store.set_task_status(task_id,'recovery_required',reason='apply_unknown')
                if not isinstance(error,Exception):raise
                return operation_result(store,task_id,identifier)
        with store.db.write() as db:db.execute("UPDATE apply_operations SET state='applied',updated_at=? WHERE id=?",(time.time(),identifier))
        return operation_result(store,task_id,identifier)
