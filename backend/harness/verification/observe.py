"""Observe profile check commands already authorized by the tool gateway.

This never starts a command or grants consent. The existing operation receipt
and the bytes read before execution are the evidence, not the model's verdict.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .results import CheckResults,CheckTarget
from ..command_context import saved_profile
from ..worktrees.snapshot import build,load_manifest,manifest_path


def manifest_hash(root: Path) -> str:
    snapshot=build(root)
    return snapshot_hash(snapshot)


def snapshot_hash(snapshot) -> str:
    # Exclude machine paths, timestamps and traversal order from content identity.
    files=sorted((entry.path,entry.sha256,entry.size) for entry in snapshot.files)
    return hashlib.sha256(json.dumps(files,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def prepare_check(store,task_id,call,root,runtime):
    if call['name']!='execute' or root is None:return None
    task=store.task(task_id);profile=saved_profile(store,task)
    command=(call.get('args') or {}).get('command')
    configured=next((row for row in profile.get('commands',[]) if row.get('command')==command),None)
    if not configured or not profile.get('profile_hash'):return None
    target=CheckTarget('working_copy',manifest_hash(Path(root)),profile['profile_hash'],runtime)
    original=load_manifest(manifest_path(Path(root)))
    baseline_eligible=original is None or snapshot_hash(original)==target.manifest_hash
    return target,str(configured.get('id') or configured.get('name') or command),command,baseline_eligible


def missing_baseline(store,task_id,runtime):
    profile=saved_profile(store,store.task(task_id))
    required=[row for row in profile.get('commands',[]) if row.get('required')]
    recorded=CheckResults(store).list(task_id)
    return [row['command'] for row in required if not any(
        item['profile_hash']==profile.get('profile_hash') and item['runtime_fingerprint']==runtime
        and item['target_kind']=='working_copy' and item['details'].get('phase')=='baseline'
        and item['details'].get('check_id')==str(row.get('id') or row.get('name') or row['command'])
        and item['outcome'] in {'passed','failed'} for item in recorded)]


def current_quality(store,task_id,root,runtime,*,input_hash=None):
    task=store.task(task_id)
    profile=saved_profile(store,task)
    commands=[row for row in profile.get('commands',[]) if row.get('required')]
    plan=task.get('plan')
    if plan and plan.get('profile_hash')!=profile.get('profile_hash'):
        return {'quality_status':'not_verified','check_refs':[],'profile_changed':True,'commands':[row['command'] for row in commands]}
    if not commands:return None
    if root is None or not profile.get('profile_hash'):
        return {'quality_status':'not_verified','check_refs':[],'commands':[row['command'] for row in commands]}
    target=CheckTarget('working_copy',input_hash or manifest_hash(Path(root)),profile['profile_hash'],runtime)
    required=[str(row.get('id') or row.get('name') or row['command']) for row in commands]
    quality=CheckResults(store).quality(task_id,target=target,required=required)
    from .inputs import changed_inputs_reviewed
    if not changed_inputs_reviewed(store,task_id,Path(root),profile,runtime):
        quality={'quality_status':'not_verified','check_refs':quality['check_refs'],'check_inputs_changed':True}
    if missing_baseline(store,task_id,runtime):
        quality={**quality,'quality_status':'not_verified','baseline_missing':True}
    return {**quality,'commands':[row['command'] for row in commands]}


def finish_check(store,task_id,prepared,receipt):
    if prepared is None:return None
    target,check_id,command,baseline_eligible=prepared
    outcome='stopped' if receipt.stopped else 'timed_out' if receipt.timed_out else 'passed' if receipt.exit_code==0 else 'failed'
    # A generic shell exit cannot distinguish assertion failure from missing
    # dependencies. Keep that classification unknown until a trusted adapter can.
    results=CheckResults(store)
    failure_kind='runtime' if receipt.exit_code in {126,127} else None
    if baseline_eligible and command in missing_baseline(store,task_id,target.runtime_fingerprint) and outcome in {'passed','failed'} and failure_kind is None:
        results.record(task_id,target=target,check_id=check_id,outcome=outcome,command=command,output=receipt.output,output_truncated=receipt.truncated,phase='baseline')
    result=results.record(task_id,target=target,check_id=check_id,outcome=outcome,command=command,output=receipt.output,output_truncated=receipt.truncated,failure_kind=failure_kind)
    store.record_event(task_id,'verification_finished',{'target_kind':'working_copy','selection_id':None,'outcome':outcome,'candidate_manifest_hash':target.manifest_hash,'check_refs':[result['id']]})
    return result
