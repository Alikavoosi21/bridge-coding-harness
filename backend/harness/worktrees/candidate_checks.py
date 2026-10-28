"""Explicit human-requested checks of a frozen apply selection, in Docker only.

Uses the product action receipt, shared leases, budgets and runtime. This is
not an agent loop. Optional dependency installation needs consent to the exact
saved command plus an expiring network grant; checks themselves stay offline.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import time
import shutil
from threading import Event,Lock

_live_lock=Lock()
_live={}


def stop_candidate(store,task_id):
    """Stop the live runtime handle; durable state remains in the product store."""
    with _live_lock:
        current=_live.get(task_id)
        if current is None:return False
        current['stop'].set();runtime=current['runtime'];exec_id=current['exec_id']
    store.set_task_status(task_id,'stopping',reason='candidate_check_stop_requested')
    if exec_id:runtime.cancel(exec_id)
    return True

from server.errors import ApiError
from ..command_context import saved_profile,command_details
from ..runtime.docker import ContainerConfig,DockerRuntime,RuntimeUnavailable
from ..task_runtime import runtime_descriptor,task_directory
from ..verification.observe import manifest_hash
from ..verification.results import CheckResults,CheckTarget
from .guard import locked_copy
from .selection import validate_selection
from .snapshot import build,sync


def required_commands(store,task_id):
    profile=saved_profile(store,store.task(task_id))
    return [{'id':str(row.get('id') or row.get('name') or row['command']),'command':row['command']} for row in profile.get('commands',[]) if row.get('required')]


def run_candidate_checks(store,task_id,selection_id,*,key,approved_commands,approved_install=None,network_grant=None,runtime_factory=None):
    # Exactly the displayed required command list is consented, in its order.
    commands=required_commands(store,task_id)
    if not commands or approved_commands!=[row['command'] for row in commands]:
        raise ApiError('action_not_approved','Approve the exact current required command list.',status_code=409)
    request={'selection':selection_id,'commands':commands}
    if approved_install is not None or network_grant is not None:request.update(install=approved_install,network_grant=network_grant)
    request_hash=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
    invocation='candidate-check:'+key
    previous=store.action_by_invocation(task_id,invocation)
    if previous:
        if previous['args_hash']!=request_hash:raise ApiError('idempotency_conflict','Check key was used for a different selection.',status_code=409)
        if previous['state']=='succeeded':return json.loads(previous['result_ref'])
        if previous['state']!='pending':raise ApiError('recovery_required','Candidate check was dispatched; it cannot be replayed.',status_code=409)
    selection=validate_selection(store,task_id,selection_id)
    # The captured working hash is represented by its durable observed revision.
    from .diff import changes
    report=changes(store,task_id)
    with locked_copy(store,task_id,expected_revision=selection['working_revision'],expected_manifest_hash=report['working_manifest_hash'],kind='candidate_check') as held:
        selection=validate_selection(store,task_id,selection_id)
        profile=saved_profile(store,store.task(task_id))
        install=(profile.get('install') or {}).get('command')
        if approved_install is not None and (not install or approved_install!=install):
            raise ApiError('action_not_approved','Approve only the exact saved installation command.',status_code=409)
        if network_grant is not None and approved_install is None:
            raise ApiError('action_not_approved','Network consent applies only to the separately approved installation.',status_code=409)
        from ..network_access import current as current_network
        permission=current_network(store,task_id) if approved_install else None
        if approved_install and (not permission or permission['id']!=network_grant):
            raise ApiError('action_not_approved','Enable temporary task networking and explicitly approve the installation.',status_code=409)
        capture=task_directory(store,task_id)/'selections'/selection_id
        for command in commands:
            install,_verifier,_source=command_details({'name':'execute','args':{'command':command['command']}},profile,capture)
            if install:raise ApiError('action_not_approved','Package installation needs a separate explicit approval.',status_code=409)
        descriptor=runtime_descriptor(store,task_id)
        from ..runtime.local import runtime_for
        runtime=runtime_factory(ContainerConfig(image=descriptor['image'])) if runtime_factory else runtime_for(descriptor)
        runtime.set_lease(held['lease'])
        try:image=runtime.pin_image()
        except RuntimeUnavailable as error:raise ApiError('runtime_unavailable',str(error),status_code=409) from error
        fingerprint=hashlib.sha256(json.dumps(asdict(runtime.config),sort_keys=True).encode()).hexdigest()
        if image!=descriptor['image'] or fingerprint!=selection['runtime_fingerprint']:
            raise ApiError('selection_stale','The candidate runtime differs from its approved preview.',status_code=409)
        action=store.ensure_action(task_id,invocation,request_hash)
        if action['state']=='succeeded':return json.loads(action['result_ref'])
        if action['state']!='pending':raise ApiError('recovery_required','Candidate checks cannot be replayed.',status_code=409)
        store.consume(task_id,tool_calls=len(commands)+bool(approved_install))
        target=CheckTarget('apply_candidate',selection['candidate_manifest_hash'],selection['profile_hash'],selection['runtime_fingerprint'],selection_id)
        results=CheckResults(store);started=time.monotonic();dispatched=False
        candidate=task_directory(store,task_id)/'selections'/selection_id
        # Commands may generate caches/output. They never mount the immutable
        # capture, working copy or original, only this disposable execution copy.
        temporary=tempfile.mkdtemp(prefix='candidate-check-'+action['operation_id']+'-',dir=held['directory'])
        safe_cleanup=True
        handle={'runtime':runtime,'exec_id':None,'stop':Event()}
        try:
            copy=Path(temporary)/'working'
            sync(build(candidate),copy,write_manifest_file=False)
            try:
                with store.db.write() as db:
                    claimed=db.execute("UPDATE actions SET state='dispatching' WHERE operation_id=? AND state='pending'",(action['operation_id'],)).rowcount
                    if claimed!=1:raise ApiError('recovery_required','Candidate check already dispatched.',status_code=409)
                dispatched=True
                store.set_task_status(task_id,'verifying',reason='candidate_check_started')
                with _live_lock:_live[task_id]=handle
                refs=[]
                if approved_install:
                    if handle['stop'].is_set():raise ApiError('conflict','Candidate installation was stopped before dispatch.',status_code=409)
                    permission=current_network(store,task_id)
                    if not permission or permission['id']!=network_grant:
                        raise ApiError('action_not_approved','Network permission changed before candidate installation.',status_code=409)
                    safe_cleanup=False
                    exec_id=action['operation_id']+'-install'
                    with _live_lock:handle['exec_id']=exec_id
                    store.set_action_state(action['operation_id'],'running',runtime_exec_id=exec_id)
                    receipt=runtime.execute(approved_install,snapshot=copy,exec_id=exec_id,timeout=300,max_output=65536,network_until=permission['expiry'])
                    if receipt.unknown or receipt.exec_id!=exec_id:raise RuntimeError('Candidate installation termination is unconfirmed.')
                    safe_cleanup=True
                    if receipt.exit_code!=0 or receipt.stopped or receipt.timed_out:
                        raise ApiError('dependency_install_failed','Candidate dependency installation did not complete successfully; quality is unverified.',status_code=409)
                    if manifest_hash(copy)!=target.manifest_hash:
                        raise ApiError('selection_stale','Installation changed candidate source or lockfiles; review again.',status_code=409)
                    # Installation time is accounted for in active_ms, but the
                    # ordinary checks retain their own bounded offline window.
                    started_checks=time.monotonic()
                else:started_checks=started
                for index,command in enumerate(commands):
                    if handle['stop'].is_set():break
                    validate_selection(store,task_id,selection_id)
                    if manifest_hash(copy)!=target.manifest_hash:
                        raise ApiError('selection_stale','A check changed candidate inputs; no quality claim can be made.',status_code=409)
                    safe_cleanup=False
                    exec_id=action['operation_id']+'-'+str(index)
                    with _live_lock:handle['exec_id']=exec_id
                    if handle['stop'].is_set():safe_cleanup=True;break
                    store.set_action_state(action['operation_id'],'running',runtime_exec_id=exec_id)
                    receipt=runtime.execute(command['command'],snapshot=copy,exec_id=exec_id,timeout=max(1,int(90-(time.monotonic()-started_checks))),max_output=65536)
                    if receipt.unknown or receipt.exec_id!=exec_id:raise RuntimeError('The runtime could not confirm this candidate command termination.')
                    safe_cleanup=True
                    outcome='stopped' if receipt.stopped else 'timed_out' if receipt.timed_out else 'passed' if receipt.exit_code==0 else 'failed'
                    if manifest_hash(copy)!=target.manifest_hash:
                        raise ApiError('selection_stale','A check changed candidate inputs; capture and review again.',status_code=409)
                    record=results.record(task_id,target=target,check_id=command['id'],outcome=outcome,command=command['command'],output=receipt.output,output_truncated=receipt.truncated,failure_kind='runtime' if receipt.exit_code in {126,127} else None)
                    refs.append(record['id'])
                    store.record_event(task_id,'verification_finished',{'target_kind':'apply_candidate','selection_id':selection_id,'outcome':outcome,'candidate_manifest_hash':target.manifest_hash,'check_refs':[record['id']]})
                    if receipt.stopped or receipt.timed_out or time.monotonic()-started_checks>=90:break
                validate_selection(store,task_id,selection_id)
                quality=results.quality(task_id,target=target,required=[row['id'] for row in commands])
                if handle['stop'].is_set():quality={**quality,'quality_status':'not_verified'}
                result={'selection_id':selection_id,**quality}
                with store.db.write() as db:db.execute('UPDATE apply_selections SET quality_status=?,check_refs=? WHERE id=?',(quality['quality_status'],json.dumps(quality['check_refs']),selection_id))
                store.set_action_state(action['operation_id'],'succeeded',result_ref=json.dumps(result))
                store.set_task_status(task_id,'paused',reason='candidate_check_finished')
                return result
            except BaseException as error:
                if dispatched:
                    state='failed' if isinstance(error,ApiError) and safe_cleanup else 'unknown'
                    store.set_action_state(action['operation_id'],state,error='Candidate verification did not finish with valid evidence.')
                    if state=='unknown':store.set_task_status(task_id,'recovery_required',reason='candidate_check_unknown')
                    else:store.set_task_status(task_id,'paused',reason='candidate_check_failed')
                raise
            finally:store.consume(task_id,active_ms=int((time.monotonic()-started)*1000))
        finally:
            with _live_lock:_live.pop(task_id,None)
            if safe_cleanup:shutil.rmtree(temporary)
