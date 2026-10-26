"""Allowlisted technical facts only; no raw logs, settings, project files or upload."""
import hashlib
from importlib.metadata import version,PackageNotFoundError
import io
import json
from pathlib import Path
import platform
import re
import uuid
import zipfile

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field

from ..errors import ApiError
from ..storage import Store
from ..storage import retention
from ..storage.contract import SCHEMA_VERSION,TASK_STATES

router=APIRouter(tags=['local-data'])
REPORT_FILES=['report.json','README.txt']


def report(store):
    from .readiness import _runtime
    runtime,issue=_runtime()
    versions={}
    for name in ('deepagents','langchain','langgraph','fastapi','langgraph-checkpoint-sqlite'):
        try:value=version(name)
        except PackageNotFoundError:value='unavailable'
        versions[name]=value if re.fullmatch(r'[0-9A-Za-z.+_-]{1,64}',value) else 'unavailable'
    with store.db.read() as db:
        counts={row['status']:row['count'] for row in db.execute('SELECT status,COUNT(*) AS count FROM tasks GROUP BY status') if row['status'] in TASK_STATES}
        profiles=db.execute('SELECT profile FROM workspaces WHERE profile IS NOT NULL').fetchall()
        pending=db.execute("SELECT COUNT(*) FROM actions WHERE state='unknown'").fetchone()[0]
    checks=0;installs=0
    for row in profiles:
        try:
            profile=json.loads(row['profile']);checks+=len(profile.get('commands',[]));installs+=bool(profile.get('install'))
        except (ValueError,TypeError,AttributeError):continue
    runtime_code=issue['code'] if issue and issue['code'] in {'docker_missing','docker_unavailable','image_missing'} else None
    return {'format_version':1,'app_version':'0.2.0','python':platform.python_version(),'os':platform.system(),'schema_version':SCHEMA_VERSION,'packages':versions,'runtime':{'available':bool(runtime.get('available')),'issue':runtime_code},'task_counts':counts,'unknown_operations':pending,'preflight_summary':{'projects_with_profile':len(profiles),'configured_checks':checks,'configured_installs':installs},'privacy':{'raw_logs':False,'project_code':False,'prompts':False,'diffs':False,'keys':False,'usernames':False,'private_paths':False,'provider_urls':False,'upload':False}}


def preview_report(store):
    data=report(store)
    return {'files':REPORT_FILES,'report':data,'preview_hash':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()}


@router.get('/diagnostics/preview')
def diagnostics_preview():return preview_report(Store())


class Export(BaseModel):
    confirm:bool
    preview_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/diagnostics/exports')
def diagnostics_export(body:Export):
    if not body.confirm:raise ApiError('action_not_approved','Review the local diagnostics contents first.',status_code=409)
    store=Store();preview=preview_report(store)
    if preview['preview_hash']!=body.preview_hash:raise ApiError('selection_stale','Technical facts changed; preview the report again.',status_code=409)
    folder=store.db.path.parent/'diagnostics'
    from harness.worktrees.snapshot import _is_link_path
    if folder.exists() and _is_link_path(folder):raise ApiError('invalid_request','Diagnostics folder must not be a link.',status_code=422)
    folder.mkdir(exist_ok=True)
    identifier='diagnostic_'+uuid.uuid4().hex
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.json',json.dumps(preview['report'],ensure_ascii=False,indent=2))
        archive.writestr('README.txt','Local technical report. Contains allowlisted versions and aggregate counts only. No source, prompt, diff, provider address, key, raw log or private path. Nothing is uploaded.\n')
    from harness.worktrees.edit import _durable
    file=folder/(identifier+'.zip');_durable(file,buffer.getvalue())
    return {'id':identifier,'path':str(file),'bytes':file.stat().st_size,'uploaded':False}


@router.get('/diagnostics/exports/{identifier}/download')
def diagnostics_download(identifier:str):
    if not re.fullmatch(r'diagnostic_[0-9a-f]{32}',identifier):raise ApiError('not_found','Report not found.',status_code=404)
    file=Store().db.path.parent/'diagnostics'/(identifier+'.zip')
    from harness.worktrees.snapshot import _is_link_path
    if not file.is_file() or _is_link_path(file) or _is_link_path(file.parent):raise ApiError('not_found','Report is unavailable.',status_code=404)
    return FileResponse(file,media_type='application/zip',filename=identifier+'.zip')


@router.get('/storage/preview')
def storage_preview():return retention.preview(Store())


class Policy(BaseModel):
    retention_days:int=Field(ge=1,le=3650)
    cache_limit_gb:int=Field(ge=1,le=50)


@router.put('/storage/policy')
def storage_policy(body:Policy):return retention.save_policy(Store(),body.model_dump())


class Cleanup(BaseModel):
    confirm:bool
    preview_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    item_ids:list[str]=Field(min_length=1,max_length=500)


@router.post('/storage/cleanup')
def storage_cleanup(body:Cleanup):return retention.cleanup(Store(),**body.model_dump())
