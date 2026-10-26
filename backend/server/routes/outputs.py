from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,Field
from harness.outputs import output_info
from harness.runtime.docker import RuntimeUnavailable
from harness.worktrees.snapshot import UnsafePath
from server.errors import ApiError
from server.storage import Store

router=APIRouter(tags=['output preview and execution'])


class StartOutput(BaseModel):
    kind:Literal['html','command','server']
    path:str=Field(default='',max_length=2048)
    command:str=Field(default='',max_length=4000)
    port:int=Field(default=3000,ge=1024,le=65535)
    confirm:bool=False
    install_command:str=Field(default='',max_length=2000)
    install_consent:bool=False
    network_consent:bool=False
    expected_revision:int=Field(ge=1)
    expected_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    key:str=Field(min_length=1,max_length=150)


@router.get('/tasks/{task_id}/outputs')
def info(task_id:str,request:Request):
    return {**output_info(Store(),task_id),'sessions':request.app.state.harness.outputs.list(task_id)}


@router.post('/tasks/{task_id}/outputs',status_code=202)
def start(task_id:str,body:StartOutput,request:Request):
    if '\x00' in body.command or '\x00' in body.install_command or (body.kind!='html' and not body.command.strip()):raise ApiError('invalid_request','فرمان اجرا را مشخص کن.',status_code=422)
    try:return request.app.state.harness.outputs.start(Store(),task_id,**body.model_dump())
    except UnsafePath as error:raise ApiError('invalid_request',str(error),status_code=422) from error
    except RuntimeUnavailable as error:raise ApiError('runtime_unavailable',str(error),status_code=409) from error


@router.get('/tasks/{task_id}/outputs/{output_id}')
def get(task_id:str,output_id:str,request:Request):return request.app.state.harness.outputs.get(task_id,output_id)


@router.post('/tasks/{task_id}/outputs/{output_id}/stop')
def stop(task_id:str,output_id:str,request:Request):return request.app.state.harness.outputs.stop(task_id,output_id)
