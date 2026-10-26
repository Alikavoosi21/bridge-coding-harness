"""Human decisions are durable receipts; resuming is a separate explicit action."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from harness.gateway import ToolGateway
from harness.task_controller import TaskControllerError
from ..errors import ApiError
from ..storage import Store
from ..storage.approvals import ApprovalStore

router=APIRouter(tags=['task-approvals'])


class NetworkPermission(BaseModel):
    confirm:bool
    expected_revision:int=Field(ge=1)
    duration_seconds:int=Field(default=300,ge=30,le=600)
    idempotency_key:str=Field(min_length=1,max_length=200)


@router.get('/tasks/{task_id}/network-permission')
def network_status(task_id:str):
    from harness.network_access import current
    return {'permission':current(Store(),task_id)}


@router.post('/tasks/{task_id}/network-permission')
def permit_network(task_id:str,body:NetworkPermission,request:Request):
    from harness.network_access import allow
    store=Store();task=store.task(task_id)
    if request.app.state.harness.is_running(task['thread_id']):raise ApiError('workspace_busy','Stop the task before changing sandbox networking.',status_code=409)
    def handler():return 200,{'permission':allow(store,task_id,expected_revision=body.expected_revision,duration_seconds=body.duration_seconds,confirm=body.confirm)}
    status,result,replayed=store.run_idempotent('network:'+task_id+':'+body.idempotency_key,body.model_dump(),handler)
    return result


@router.post('/tasks/{task_id}/network-permission/revoke')
def revoke_network(task_id:str,request:Request):
    from harness.network_access import revoke
    store=Store();task=store.task(task_id)
    result=revoke(store,task_id)
    from harness.worktrees.candidate_checks import stop_candidate
    candidate_stopped=stop_candidate(store,task_id)
    if not candidate_stopped and request.app.state.harness.is_running(task['thread_id']):request.app.state.harness.controller_for(task_id).stop(task_id)
    return result


class Decision(BaseModel):
    decision: Literal['approve','reject']
    fingerprint: str = Field(min_length=1,max_length=128)
    revision: int = Field(ge=1)
    grant: bool = False
    expires_at: float | None = Field(default=None,allow_inf_nan=False)
    reason: str = Field(default='',max_length=1000)


def _gateway(store: Store, task_id: str):
    task=store.task(task_id)
    workspace=store.workspace(task['workspace_id'])
    from harness.task_runtime import runtime_descriptor,task_directory
    from harness.runtime.docker import ContainerConfig,DockerRuntime
    descriptor=runtime_descriptor(store,task_id)
    available=False
    if descriptor:
        available=DockerRuntime(ContainerConfig(image=descriptor['image'])).capability().available
    working=task_directory(store,task_id)/'working'
    skills=task_directory(store,task_id)/'knowledge'/'skills'
    return ToolGateway(store,task_id,Path(workspace['root'])/'.harness'/'rules.yaml',runtime_available=available,runtime_id=descriptor['runtime_id'] if descriptor else 'read-only',script_root=working if working.is_dir() else None,skills_root=skills if skills.is_dir() else None)


@router.get('/tasks/{task_id}/approvals')
def list_approvals(task_id: str):
    return {'items':ApprovalStore(Store()).list(task_id)}


@router.post('/tasks/{task_id}/approvals/{approval_id}/decisions')
def decide(task_id: str, approval_id: str, body: Decision):
    store=Store();service=ApprovalStore(store)
    review=next((row for row in service.list(task_id) if row['id']==approval_id),None)
    if not review:
        raise ApiError('not_found','Approval not found.',status_code=404)
    if body.decision=='approve':
        if not review['request']:
            raise ApiError('selection_stale','This old request needs a fresh review.',status_code=409)
        context,access=_gateway(store,task_id).evaluate({'name':review['request']['tool'],'args':review['request']['args']})
        if access=='deny' or context.fingerprint()!=review['action_hash']:
            raise ApiError('action_not_approved','The current task, rules or runtime refuse this operation.',status_code=409)
    receipt=service.decide(task_id,approval_id,fingerprint=body.fingerprint,revision=body.revision,decision=body.decision,grant=body.grant,expires_at=body.expires_at,reason=body.reason)
    return {'approval':receipt,'task':store.task(task_id)}


@router.post('/tasks/{task_id}/grants/revoke')
def revoke(task_id: str):
    ApprovalStore(Store()).revoke(task_id)
    return {'revoked':True,'task_id':task_id}


@router.get('/tasks/{task_id}/grants')
def list_grants(task_id: str):
    return {'items':ApprovalStore(Store()).grants(task_id)}


class Resume(BaseModel):
    idempotency_key: str = Field(min_length=1,max_length=200)


class Edit(BaseModel):
    fingerprint: str = Field(min_length=1,max_length=128)
    revision: int = Field(ge=1)
    args: dict[str,Any]


@router.post('/tasks/{task_id}/approvals/{approval_id}/edits')
def edit(task_id: str, approval_id: str, body: Edit):
    store=Store();service=ApprovalStore(store)
    review=next((row for row in service.list(task_id) if row['id']==approval_id),None)
    if not review or not review['request']:
        raise ApiError('not_found','Approval request not found.',status_code=404)
    gateway=_gateway(store,task_id)
    context,access=gateway.evaluate({'name':review['request']['tool'],'args':body.args})
    if access=='deny':
        raise ApiError('action_not_approved','The edited operation is refused by current policy.',status_code=409)
    replacement=service.edit(task_id,approval_id,fingerprint=body.fingerprint,revision=body.revision,context=context,review_details=gateway.review_details(context))
    return {'approval':replacement,'task':store.task(task_id)}


class Access(BaseModel):
    mode: Literal['ask','grant','auto']
    expected_revision: int = Field(ge=1)
    read_only: bool | None = None


@router.patch('/tasks/{task_id}/access')
def access(task_id: str, body: Access, request: Request):
    store=Store();task=store.task(task_id)
    if body.read_only is not None and bool(task['read_only'])!=body.read_only:
        if request.app.state.harness.is_running(task['thread_id']):
            raise ApiError('workspace_busy','ابتدا اجرای جاری را متوقف کن.',status_code=409)
        if not body.read_only:
            from .tasks import StartTask,_require_write_capability
            _require_write_capability(StartTask(prompt=task['prompt'],read_only=False))
    return {'task':ApprovalStore(store).change_access(task_id,expected_revision=body.expected_revision,mode=body.mode,read_only=body.read_only)}


@router.post('/tasks/{task_id}/approval-resumptions')
async def resume(task_id: str, body: Resume, request: Request):
    store=Store()
    def handler():
        task=store.task(task_id)
        if task['status']!='awaiting_action':
            raise ApiError('conflict','This task is not waiting for an action decision.',status_code=409)
        rows=ApprovalStore(store).list(task_id)
        if not rows or any(row['state']=='pending' for row in rows):
            raise ApiError('action_not_approved','Decide all pending actions before resuming.',status_code=409)
        workspace=store.workspace(task['workspace_id'])
        if Path(workspace['root']).resolve()!=request.app.state.harness.workspace.root.resolve():
            raise ApiError('conflict','Open this task workspace before resuming.',status_code=409)
        # Predicates re-read canonical decisions on node replay. Dispatch also
        # checks each receipt; renderer-provided framework decisions are refused.
        try:
            task=request.app.state.harness.submit('resume',task_id)
        except TaskControllerError as error:
            raise ApiError(error.code,error.message,status_code=error.status_code,details=error.details,current_revision=error.current_revision) from error
        return 202,{'task':task}
    status,result,replayed=store.run_idempotent(body.idempotency_key,{'endpoint':'approval-resumptions','task_id':task_id},handler)
    from fastapi.responses import JSONResponse
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)
