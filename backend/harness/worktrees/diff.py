"""Read-only review of captured baseline, working copy and current original."""
from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

from server.errors import ApiError
from ..task_runtime import task_directory
from ..verification.observe import snapshot_hash
from .snapshot import build,load_manifest,manifest_path,validate_relative,excluded,_is_link_path,within,UnsafePath
from .state import observe

MAX_REVIEW_BYTES=2_000_000
MAX_DIFF_BYTES=65_536


def review_context(store,task_id):
    task=store.task(task_id);directory=task_directory(store,task_id)
    working=directory/'working';original=Path(store.workspace(task['workspace_id'])['root'])
    if not working.is_dir() or _is_link_path(working) or _is_link_path(directory) or not original.is_dir() or _is_link_path(original):
        raise ApiError('recovery_required','The saved working copy is unavailable or is a link.',status_code=409)
    try:saved=load_manifest(manifest_path(working))
    except (OSError,ValueError,KeyError,TypeError) as error:
        raise ApiError('recovery_required','The saved baseline manifest cannot be read.',status_code=409) from error
    if saved is None or saved.root.resolve()!=original.resolve():
        raise ApiError('recovery_required','The baseline manifest needs recovery.',status_code=409)
    return task,directory,working,original,saved


def changes(store,task_id):
    _,directory,working,original,saved=review_context(store,task_id)
    working_snapshot=build(working);current=build(original)
    before=saved.by_path();after=working_snapshot.by_path();source=current.by_path()
    unsupported={row['path'] for row in working_snapshot.excluded if 'link' in row['reason'] or row['reason']=='not a regular file'}
    source_unsupported={row['path'] for row in current.excluded if 'link' in row['reason'] or row['reason']=='not a regular file'}
    items=[]
    for path in sorted(before.keys()|after.keys()|unsupported):
        old,new,now=before.get(path),after.get(path),source.get(path)
        old_hash=old.sha256 if old else None;new_hash=new.sha256 if new else None
        if old_hash==new_hash and path not in unsupported:continue
        kind='unsupported' if path in unsupported else 'binary' if any(entry and entry.binary for entry in (old,new)) else 'added' if old is None else 'deleted' if new is None else 'modified'
        current_hash=now.sha256 if now else None
        items.append({'file_id':'file_'+hashlib.sha256((task_id+'\0'+path).encode()).hexdigest()[:20],'path':path,'kind':kind,'baseline_hash':old_hash,'working_hash':new_hash,'current_hash':current_hash,'current_supported':path not in source_unsupported,'conflict':path in source_unsupported or current_hash!=old_hash,'size':new.size if new else 0})
    working_hash=snapshot_hash(working_snapshot)
    version=observe(store,task_id,working_hash)
    return {'items':items,'working_revision':version['revision'],'working_manifest_hash':working_hash,'original_manifest_hash':snapshot_hash(current),'baseline_manifest_hash':snapshot_hash(saved),'baseline_available':(directory/'baseline').is_dir()}


def _text(root:Path,path:str,expected:str|None):
    if expected is None:return ''
    relative=validate_relative(path)
    if excluded(relative):raise UnsafePath('Excluded file cannot be reviewed.')
    file=root.joinpath(*relative.parts)
    cursor=root
    if _is_link_path(cursor):raise UnsafePath('Review root is a link.')
    for part in relative.parts:
        cursor=cursor/part
        if _is_link_path(cursor):raise UnsafePath('Review path is a link or unavailable.')
    if not within(root,file) or not file.is_file() or file.stat().st_size>MAX_REVIEW_BYTES:
        raise ApiError('invalid_request','This file cannot be shown in the text reviewer.',status_code=422)
    with file.open('rb') as handle:data=handle.read(MAX_REVIEW_BYTES+1)
    if len(data)>MAX_REVIEW_BYTES or hashlib.sha256(data).hexdigest()!=expected:
        raise ApiError('selection_stale','File changed while preparing the review.',status_code=409)
    if b'\0' in data:raise UnicodeError('Binary file')
    return data.decode('utf-8-sig')


def file_diff(store,task_id,path):
    relative=str(validate_relative(path))
    if excluded(validate_relative(relative)):raise UnsafePath('Excluded file cannot be reviewed.')
    report=changes(store,task_id)
    item=next((row for row in report['items'] if row['path']==relative),None)
    if item is None:raise ApiError('not_found','No working-copy change for this path.',status_code=404)
    if item['kind'] in {'binary','unsupported'}:
        return {**item,'supported':False,'reason':item['kind'],'diff':None}
    _,directory,working,original,_=review_context(store,task_id)
    baseline=directory/'baseline'
    try:
        before=_text(baseline if baseline.is_dir() else original,relative,item['baseline_hash'])
    except (ApiError,UnsafePath):
        return {**item,'supported':False,'reason':'baseline_unavailable','diff':None}
    except UnicodeError:
        return {**item,'supported':False,'reason':'encoding','diff':None}
    try:
        # Old tasks may lack captured bytes. Only the exact original hash can
        # serve as a read-only fallback; changed originals are never invented.
        after=_text(working,relative,item['working_hash'])
    except UnicodeError:
        return {**item,'supported':False,'reason':'encoding','diff':None}
    lines=difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='baseline/'+relative,tofile='working/'+relative)
    patch=''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n' for line in lines)
    encoded=patch.encode('utf-8')
    current=None;current_supported=item['current_supported']
    if current_supported:
        try:current=_text(original,relative,item['current_hash'])
        except (ApiError,UnsafePath,UnicodeError):current_supported=False
    return {**item,'supported':True,'before':before,'after':after,'current':current,'current_supported':current_supported,'diff':encoded[:MAX_DIFF_BYTES].decode('utf-8',errors='ignore'),'truncated':len(encoded)>MAX_DIFF_BYTES,'working_manifest_hash':report['working_manifest_hash']}


def working_file(store,task_id,path):
    relative=validate_relative(path)
    if excluded(relative):raise UnsafePath('Excluded file cannot be edited.')
    _,_,working,_,_=review_context(store,task_id)
    snapshot=build(working);entry=snapshot.by_path().get(str(relative))
    if entry is None:raise ApiError('not_found','Working file not found.',status_code=404)
    digest=snapshot_hash(snapshot);version=observe(store,task_id,digest)
    metadata={'path':str(relative),'hash':entry.sha256,'working_revision':version['revision'],'working_manifest_hash':digest,'encoding':entry.encoding,'newline':entry.newline}
    if entry.binary or entry.size>MAX_REVIEW_BYTES:return {**metadata,'supported':False,'content':None}
    try:content=_text(working,str(relative),entry.sha256)
    except UnicodeError:return {**metadata,'supported':False,'content':None}
    return {**metadata,'supported':True,'content':content}
