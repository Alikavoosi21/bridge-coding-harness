"""Capture a file selection without modifying the user's original project.

Candidate checks and apply must revalidate this immutable capture. This module
does not execute checks, accept a quality acknowledgement, or apply files.
"""
from dataclasses import replace
import json
import tempfile
import time
import uuid
from pathlib import Path

from server.errors import ApiError
from ..command_context import saved_profile,profile_identity
from ..task_runtime import runtime_descriptor
from ..verification.observe import manifest_hash,snapshot_hash
from .diff import changes
from .guard import locked_copy
from .snapshot import build,sync,_is_link_path


def prepare_selection(store,task_id,*,file_ids,expected_revision,expected_manifest_hash):
    if not file_ids or len(set(file_ids))!=len(file_ids):
        raise ApiError('invalid_request','Select at least one distinct changed file.',status_code=422)
    with locked_copy(store,task_id,expected_revision=expected_revision,expected_manifest_hash=expected_manifest_hash,kind='apply_preview') as held:
        report=changes(store,task_id)
        by_id={row['file_id']:row for row in report['items']}
        if any(identifier not in by_id for identifier in file_ids):
            raise ApiError('selection_stale','The selected changes are no longer available.',status_code=409)
        selected=[by_id[identifier] for identifier in sorted(file_ids)]
        if any(row['conflict'] or row['kind'] in {'unsupported','binary'} for row in selected):
            raise ApiError('selection_stale','Resolve conflicting or unsupported files before preview.',status_code=409)
        profile=saved_profile(store,held['task']);runtime=runtime_descriptor(store,task_id)
        identity=profile_identity(profile)
        if not identity or not runtime:
            raise ApiError('runtime_unavailable','A saved verification profile and runtime identity are required.',status_code=409)
        identifier='selection_'+uuid.uuid4().hex
        parent=held['directory']/'selections';parent.mkdir(exist_ok=True)
        if _is_link_path(parent):raise ApiError('recovery_required','Selection storage is a link.',status_code=409)
        original=build(held['original']);working=build(held['working'])
        paths={row['path'] for row in selected}
        # Start with CURRENT original, not baseline or the entire working copy.
        # A selected deletion is represented by its absence from both sets.
        base_entries=tuple(entry for entry in original.files if entry.path not in paths)
        selected_entries=tuple(entry for entry in working.files if entry.path in paths)
        with tempfile.TemporaryDirectory(prefix='capture-',dir=parent) as temporary:
            candidate=Path(temporary)/'candidate'
            sync(replace(original,files=base_entries),candidate,write_manifest_file=False)
            sync(replace(working,files=selected_entries),candidate,write_manifest_file=False)
            candidate_hash=manifest_hash(candidate)
            held['lease'].check('finish selection capture')
            if manifest_hash(held['original'])!=report['original_manifest_hash'] or manifest_hash(held['working'])!=expected_manifest_hash:
                raise ApiError('selection_stale','Inputs changed while capturing the selection.',status_code=409)
            # Both reads must still refer to the same versions used by the report.
            if snapshot_hash(original)!=report['original_manifest_hash'] or snapshot_hash(working)!=expected_manifest_hash:
                raise ApiError('selection_stale','Inputs changed before capturing the selection.',status_code=409)
            destination=parent/identifier
            candidate.rename(destination)
        result={'id':identifier,'task_id':task_id,'working_revision':expected_revision,'file_ids':sorted(file_ids),'original_manifest_hash':report['original_manifest_hash'],'candidate_manifest_hash':candidate_hash,'profile_hash':identity,'runtime_fingerprint':runtime['runtime_id'],'quality_status':'not_verified','check_refs':[]}
        with store.db.write() as db:
            revision=db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM apply_selections WHERE task_id=?',(task_id,)).fetchone()[0]
            db.execute('INSERT INTO apply_selections(id,task_id,revision,working_revision,file_ids,original_manifest_hash,candidate_manifest_hash,profile_hash,runtime_fingerprint,quality_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identifier,task_id,revision,expected_revision,json.dumps(sorted(file_ids)),result['original_manifest_hash'],candidate_hash,identity,runtime['runtime_id'],'not_verified',time.time()))
        return {**result,'revision':revision}


def validate_selection(store,task_id,selection_id):
    """Reject changes to selected OR unselected inputs; never silently recapture."""
    with store.db.read() as db:
        row=db.execute('SELECT * FROM apply_selections WHERE id=? AND task_id=?',(selection_id,task_id)).fetchone()
    if row is None:raise ApiError('not_found','Selection not found.',status_code=404)
    from .diff import review_context
    from .state import observe
    task,directory,working,original,_=review_context(store,task_id)
    current=observe(store,task_id,manifest_hash(working))
    profile=saved_profile(store,task);runtime=runtime_descriptor(store,task_id)
    candidate=directory/'selections'/selection_id
    if current['revision']!=row['working_revision'] or manifest_hash(original)!=row['original_manifest_hash'] or profile_identity(profile)!=row['profile_hash'] or not runtime or runtime['runtime_id']!=row['runtime_fingerprint'] or _is_link_path(candidate.parent) or _is_link_path(candidate) or not candidate.is_dir() or manifest_hash(candidate)!=row['candidate_manifest_hash']:
        raise ApiError('selection_stale','Selection inputs changed; create a new preview.',status_code=409)
    result=dict(row)
    result['file_ids']=json.loads(result['file_ids'])
    result['check_refs']=json.loads(result['check_refs'])
    return result
