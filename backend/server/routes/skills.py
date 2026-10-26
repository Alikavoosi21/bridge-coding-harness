"""Source registry commands; enabling a skill never grants tools or networking."""
from typing import Literal
from pathlib import Path
import uuid

from fastapi import APIRouter,Request
from pydantic import BaseModel,Field

from harness.skills_registry import SkillRegistry
from server.storage import Store
from server.errors import ApiError
from harness.skill_repin import preview as repin_preview,repin

router=APIRouter(tags=['skill sources'])


class CreateSkill(BaseModel):
    name: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(min_length=1, max_length=65536)
    confirm: bool = False


@router.post('/skills/create')
def create_skill(body: CreateSkill):
    """User-authored instructions, managed outside projects; explicit trust once."""
    if not body.confirm:
        raise ApiError('consent_required','متن مهارت را بررسی و تأیید کن.',status_code=400)
    import yaml
    from server.settings import home
    store=Store();registry=SkillRegistry(store)
    if any(item.get('name')==body.name and item.get('enabled') for item in registry.list(None)):
        raise ApiError('conflict','مهارتی با این نام فعال است؛ نام دیگری انتخاب کن.',status_code=409)
    folder=home()/'authored-skills'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    header=yaml.safe_dump({'name':body.name,'description':body.description},allow_unicode=True,sort_keys=False)
    (folder/'SKILL.md').write_text('---\n'+header+'---\n\n'+body.instructions,encoding='utf-8')
    source=registry.register(str(folder),scope='personal')
    return registry.enable(source['id'],expected_hash=source['current_hash'],confirm=True)


class SkillSource(BaseModel):
    source:str=Field(min_length=1,max_length=2048)
    scope:Literal['personal','project']
    workspace_id:str|None=None


class ScanSkills(BaseModel):
    source: str=Field(min_length=1,max_length=2048)


@router.post('/skill-sources/scan')
def scan_skills(body:ScanSkills):
    from harness.skills_registry import scan_skill_sources
    return scan_skill_sources(body.source)


class SkillFile(BaseModel):
    content: str=Field(min_length=1,max_length=65536)


@router.post('/skills/parse')
def parse_skill_file(body:SkillFile):
    import yaml
    from harness.skills_registry import parse_skill_text
    try:return parse_skill_text(body.content)
    except (ValueError,yaml.YAMLError) as error:
        raise ApiError('invalid_request','فایل SKILL.md معتبر نیست: '+str(error),status_code=422) from None


class EnableSkill(BaseModel):
    expected_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    confirm:bool


class SkillDiscovery(BaseModel):
    workspace_id:str=Field(min_length=1,max_length=80)


@router.post('/skill-sources/discovery')
def discover_sources(body:SkillDiscovery):
    registry=SkillRegistry(Store())
    errors=registry.bootstrap(body.workspace_id)
    return {'items':registry.list(body.workspace_id),'errors':errors}


@router.get('/tasks/{task_id}/skill-pins')
def task_skills(task_id:str):
    return {'items':SkillRegistry(Store()).task_pins(task_id)}


class RepinRequest(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=200)
    confirm:bool
    expected_revision:int=Field(ge=1)
    expected_working_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_pins_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.get('/tasks/{task_id}/skill-repin-preview')
def preview_task_repin(task_id:str):
    return repin_preview(Store(),task_id)


@router.post('/tasks/{task_id}/skill-repins')
def repin_task(task_id:str,body:RepinRequest,request:Request):
    store=Store();task=store.task(task_id)
    if request.app.state.harness.is_running(task['thread_id']):
        raise ApiError('workspace_busy','Stop the task before re-pinning skills.',status_code=409)
    return repin(store,task_id,key=body.idempotency_key,confirm=body.confirm,expected_revision=body.expected_revision,expected_working_revision=body.expected_working_revision,expected_working_hash=body.expected_working_hash,expected_pins_hash=body.expected_pins_hash)


@router.get('/skill-sources')
def sources(workspace_id:str|None=None):
    return {'items':SkillRegistry(Store()).list(workspace_id)}


@router.post('/skill-sources')
def register_source(body:SkillSource):
    return SkillRegistry(Store()).register(body.source,scope=body.scope,workspace_id=body.workspace_id)


@router.get('/skill-sources/{skill_id}')
def preview_source(skill_id:str):
    return SkillRegistry(Store()).detail(skill_id,body=True)


@router.post('/skill-sources/{skill_id}/enable')
def enable_source(skill_id:str,body:EnableSkill):
    return SkillRegistry(Store()).enable(skill_id,expected_hash=body.expected_hash,confirm=body.confirm)


@router.post('/skill-sources/{skill_id}/disable')
def disable_source(skill_id:str):
    return SkillRegistry(Store()).disable(skill_id)


@router.delete('/skill-sources/{skill_id}')
def forget_source(skill_id:str):
    return SkillRegistry(Store()).forget(skill_id)
