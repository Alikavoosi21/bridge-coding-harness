"""Human review reads only; apply is deliberately a separate explicit action."""
from fastapi import APIRouter,Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field

from harness.worktrees.diff import changes,file_diff,working_file
from harness.worktrees.selection import prepare_selection,validate_selection
from harness.worktrees.edit import save_working_file,accept_current_after_interruption,edit_recovery_details
from harness.worktrees.candidate_checks import run_candidate_checks,required_commands
from harness.worktrees.apply import apply_selection,operation_result
from harness.worktrees.restore import restore_preview,restore_operation
from harness.worktrees.reconcile import inspect_apply,keep_current_apply
from harness.worktrees.snapshot import UnsafePath
from server.errors import ApiError
from server.storage import Store

router=APIRouter(tags=['changes'])


@router.get('/tasks/{task_id}/restores/{operation_id}/recovery')
def inspect_restore(task_id:str,operation_id:str):
    from harness.worktrees.restore import inspect_interrupted_restore
    return review(lambda:inspect_interrupted_restore(Store(),task_id,operation_id))


class RestoreRecovery(BaseModel):
    confirm:bool
    expected_original_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_working_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/restores/{operation_id}/recovery')
def reconcile_restore(task_id:str,operation_id:str,body:RestoreRecovery):
    from harness.worktrees.restore import accept_interrupted_restore
    return review(lambda:accept_interrupted_restore(Store(),task_id,operation_id,**body.model_dump()))


class ApplyRequest(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=200)
    confirm:bool
    quality_ack:bool=False


@router.post('/tasks/{task_id}/apply-previews/{selection_id}/apply')
def apply_files(task_id:str,selection_id:str,body:ApplyRequest):
    return review(lambda:apply_selection(Store(),task_id,selection_id,key=body.idempotency_key,confirm=body.confirm,quality_ack=body.quality_ack))


@router.get('/tasks/{task_id}/apply-operations/{operation_id}')
def applied_files(task_id:str,operation_id:str):
    return review(lambda:inspect_apply(Store(),task_id,operation_id))


@router.get('/tasks/{task_id}/apply-operations/{operation_id}/restore-preview')
def restore_files_preview(task_id:str,operation_id:str):
    return review(lambda:restore_preview(Store(),task_id,operation_id))


class RestoreRequest(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=200)
    confirm:bool
    paths:list[str]=Field(min_length=1,max_length=1000)
    expected_original_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_working_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/apply-operations/{operation_id}/restores')
def restore_files(task_id:str,operation_id:str,body:RestoreRequest):
    return review(lambda:restore_operation(Store(),task_id,operation_id,key=body.idempotency_key,paths=body.paths,expected_original_hash=body.expected_original_hash,expected_working_revision=body.expected_working_revision,expected_working_hash=body.expected_working_hash,confirm=body.confirm))


class ApplyReconciliation(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=200)
    accept_current:bool
    expected_original_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_working_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/apply-operations/{operation_id}/reconciliations')
def reconcile_apply(task_id:str,operation_id:str,body:ApplyReconciliation):
    store=Store()
    def accept():return 200,review(lambda:keep_current_apply(store,task_id,operation_id,expected_original_hash=body.expected_original_hash,expected_revision=body.expected_working_revision,expected_working_hash=body.expected_working_hash,accept_current=body.accept_current))
    status,result,replayed=store.run_idempotent('apply-reconcile:'+task_id+':'+body.idempotency_key,{'operation_id':operation_id,**body.model_dump()},accept)
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)


def review(operation):
    try:return operation()
    except UnsafePath as error:
        raise ApiError('invalid_request',str(error),status_code=422) from error


@router.get('/tasks/{task_id}/changes')
def list_changes(task_id:str):
    return review(lambda:changes(Store(),task_id))


@router.get('/tasks/{task_id}/changes/file')
def changed_file(task_id:str,path:str=Query(min_length=1,max_length=1024)):
    return review(lambda:file_diff(Store(),task_id,path))


@router.get('/tasks/{task_id}/working-file')
def read_working_file(task_id:str,path:str=Query(min_length=1,max_length=1024)):
    return review(lambda:working_file(Store(),task_id,path))


class SelectionRequest(BaseModel):
    file_ids:list[str]=Field(min_length=1,max_length=1000)
    expected_working_revision:int=Field(ge=1)
    expected_manifest_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    idempotency_key:str=Field(min_length=1,max_length=200)


@router.post('/tasks/{task_id}/apply-previews')
def preview(task_id:str,body:SelectionRequest):
    store=Store()
    def capture():
        result=review(lambda:prepare_selection(store,task_id,file_ids=body.file_ids,expected_revision=body.expected_working_revision,expected_manifest_hash=body.expected_manifest_hash))
        return 201,result
    status,result,replayed=store.run_idempotent('preview:'+task_id+':'+body.idempotency_key,body.model_dump(),capture)
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)


@router.get('/tasks/{task_id}/apply-previews/{selection_id}')
def selection(task_id:str,selection_id:str):
    store=Store()
    def detail():
        from harness.verification.results import CheckResults,CheckTarget
        selected=validate_selection(store,task_id,selection_id)
        commands=required_commands(store,task_id)
        target=CheckTarget('apply_candidate',selected['candidate_manifest_hash'],selected['profile_hash'],selected['runtime_fingerprint'],selection_id)
        quality=CheckResults(store).quality(task_id,target=target,required=[row['id'] for row in commands])
        task=store.task(task_id);workspace=store.workspace(task['workspace_id'])
        from harness.command_context import saved_profile
        from harness.network_access import current
        return {**selected,**quality,'required_commands':commands,'install':saved_profile(store,task).get('install'),'network_permission':current(store,task_id),'destination':{'name':workspace['name'],'root':workspace['root']},'files':[row for row in changes(store,task_id)['items'] if row['file_id'] in selected['file_ids']]}
    return review(detail)


class CandidateCheckRequest(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=200)
    approved_commands:list[str]=Field(min_length=1,max_length=30)
    confirm:bool
    approved_install:str|None=Field(default=None,max_length=2000)
    network_grant:str|None=Field(default=None,max_length=200)


@router.post('/tasks/{task_id}/apply-previews/{selection_id}/checks')
def candidate_checks(task_id:str,selection_id:str,body:CandidateCheckRequest):
    if not body.confirm:raise ApiError('action_not_approved','Explicit consent to the displayed candidate commands is required.',status_code=409)
    return review(lambda:run_candidate_checks(Store(),task_id,selection_id,key=body.idempotency_key,approved_commands=body.approved_commands,approved_install=body.approved_install,network_grant=body.network_grant))


class WorkingEdit(BaseModel):
    path:str=Field(min_length=1,max_length=1024)
    content:str=Field(max_length=2_000_000)
    expected_working_revision:int=Field(ge=1)
    expected_manifest_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_file_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    idempotency_key:str=Field(min_length=1,max_length=200)


@router.put('/tasks/{task_id}/working-file')
def edit_working_file(task_id:str,body:WorkingEdit):
    return review(lambda:save_working_file(Store(),task_id,path=body.path,content=body.content,expected_revision=body.expected_working_revision,expected_manifest_hash=body.expected_manifest_hash,expected_file_hash=body.expected_file_hash,key=body.idempotency_key))


class EditReconciliation(BaseModel):
    expected_working_revision:int=Field(ge=1)
    expected_manifest_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_file_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    accept_current:bool
    idempotency_key:str=Field(min_length=1,max_length=200)


@router.get('/tasks/{task_id}/manual-edits/{operation_id}')
def inspect_edit(task_id:str,operation_id:str):
    return review(lambda:edit_recovery_details(Store(),task_id,operation_id))


@router.post('/tasks/{task_id}/manual-edits/{operation_id}/reconciliations')
def reconcile_edit(task_id:str,operation_id:str,body:EditReconciliation):
    if not body.accept_current:raise ApiError('invalid_request','Explicit acceptance of the inspected bytes is required.',status_code=422)
    store=Store()
    def accept():
        return 200,review(lambda:accept_current_after_interruption(store,task_id,operation_id,expected_revision=body.expected_working_revision,expected_manifest_hash=body.expected_manifest_hash,expected_file_hash=body.expected_file_hash))
    status,result,replayed=store.run_idempotent('manual-reconcile:'+task_id+':'+body.idempotency_key,{'operation_id':operation_id,**body.model_dump()},accept)
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)
