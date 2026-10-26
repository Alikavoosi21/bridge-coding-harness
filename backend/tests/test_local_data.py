import io
import json
import os
from pathlib import Path
import time
import zipfile
from types import SimpleNamespace

import httpx
import pytest

from server.app import create_app
from server.storage import Store
from server.storage import retention
from server.errors import ApiError


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    app=create_app();store=Store();project=tmp_path/'private-project';project.mkdir()
    (project/'source.py').write_text('PRIVATE SOURCE CONTENT',encoding='utf8')
    ws=store.upsert_workspace(str(project),profile=json.dumps({'commands':[{'command':'PRIVATE COMMAND','required':True}],'install':None}))
    return app,store,ws,project


def old_cache(store,ws,*,status='closed'):
    task=store.create_task(workspace_id=ws['id'],prompt='PRIVATE PROMPT',read_only=True)
    store.set_task_status(task['id'],status)
    folder=store.db.path.parent/'tasks'/task['id'];cache=folder/'working'/'.pytest_cache';cache.mkdir(parents=True)
    (cache/'cache.bin').write_bytes(b'rebuildable cache')
    for name in ('baseline','knowledge/skills','selections','apply-journals'):
        path=folder/name;path.mkdir(parents=True,exist_ok=True);(path/'keep.txt').write_text('protected bytes',encoding='utf8')
    (folder/'working'/'source.py').write_text('saved working code',encoding='utf8')
    past=time.time()-40*86400
    for path in [*cache.rglob('*'),cache]:os.utime(path,(past,past))
    with store.db.write() as db:db.execute('UPDATE tasks SET updated_at=? WHERE id=?',(past,task['id']))
    return task,folder,cache


def test_cleanup_protects_active_unknown_baseline_pins_and_original_and_checks_staleness(fixture):
    _,store,ws,project=fixture
    task,folder,cache=old_cache(store,ws)
    active,_,active_cache=old_cache(store,ws,status='executing')
    recovery,_,recovery_cache=old_cache(store,ws,status='recovery_required')
    closed_unknown,_,unknown_cache=old_cache(store,ws)
    operation=store.ensure_action(closed_unknown['id'],'fixture unknown','hash');store.set_action_state(operation['operation_id'],'unknown')
    preview=retention.preview(store)
    assert len(preview['items'])==1 and preview['protected_tasks']==3
    selected=[preview['items'][0]['id']]
    with pytest.raises(ApiError):retention.cleanup(store,preview_hash=preview['preview_hash'],item_ids=selected)
    (cache/'cache.bin').write_bytes(b'changed after preview')
    with pytest.raises(ApiError) as stale:retention.cleanup(store,preview_hash=preview['preview_hash'],item_ids=selected,confirm=True)
    assert stale.value.code=='selection_stale' and cache.exists()
    fresh=retention.preview(store)
    result=retention.cleanup(store,preview_hash=fresh['preview_hash'],item_ids=[row['id'] for row in fresh['items']],confirm=True) if fresh['items'] else None
    # The just-edited cache becomes too recent; refreshing never silently selects it.
    assert result is None and cache.exists()
    past=time.time()-40*86400
    for path in [cache/'cache.bin',cache]:os.utime(path,(past,past))
    fresh=retention.preview(store)
    result=retention.cleanup(store,preview_hash=fresh['preview_hash'],item_ids=[fresh['items'][0]['id']],confirm=True)
    assert result['deleted'] and not cache.exists() and active_cache.exists() and recovery_cache.exists() and unknown_cache.exists()
    assert (folder/'working'/'source.py').exists() and (folder/'baseline'/'keep.txt').exists()
    assert (folder/'knowledge'/'skills'/'keep.txt').exists() and (folder/'apply-journals'/'keep.txt').exists()
    assert (project/'source.py').read_text()=='PRIVATE SOURCE CONTENT'
    assert store.task(task['id'])['status']=='closed'


def test_cleanup_refuses_cache_hardlinks_and_cannot_name_arbitrary_paths(fixture):
    _,store,ws,project=fixture
    _,_,cache=old_cache(store,ws)
    os.link(project/'source.py',cache/'linked.py')
    result=retention.preview(store)
    assert not result['items'] and result['skipped_entries']==1
    with pytest.raises(ApiError):retention.cleanup(store,preview_hash=result['preview_hash'],item_ids=['../../private-project'],confirm=True)
    assert (project/'source.py').exists()


async def test_diagnostics_zip_contains_only_previewed_technical_facts_not_secret_strings(fixture,monkeypatch):
    app,store,ws,project=fixture
    old_cache(store,ws)
    secret='private-user-SECRET-KEY-123'
    (store.db.path.parent/'engine.log').write_text(secret+' '+str(project),encoding='utf8')
    monkeypatch.setattr('server.routes.readiness._runtime',lambda:({'available':False,'dockerfile':str(project)}, {'code':'docker_missing','message':secret}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        preview=(await api.get('/diagnostics/preview')).json()
        body={'confirm':False,'preview_hash':preview['preview_hash']}
        assert (await api.post('/diagnostics/exports',json=body)).status_code==409
        body['confirm']=True;response=await api.post('/diagnostics/exports',json=body)
        assert response.status_code==200,response.text
        created=response.json();assert created['uploaded'] is False
        data=(await api.get('/diagnostics/exports/'+created['id']+'/download')).content
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert archive.namelist()==preview['files']
            text='\n'.join(archive.read(name).decode() for name in archive.namelist())
            assert json.loads(archive.read('report.json'))==preview['report']
        assert all(value not in text for value in [secret,str(project),'PRIVATE SOURCE','PRIVATE PROMPT','PRIVATE COMMAND'])
        assert (await api.get('/diagnostics/exports/not-a-report/download')).status_code==404
        assert (await api.put('/storage/policy',json={'retention_days':0,'cache_limit_gb':5})).status_code==422
        assert (await api.put('/storage/policy',json={'retention_days':15,'cache_limit_gb':2})).json()['retention_days']==15


async def test_low_disk_refuses_new_task_without_deleting_any_data(fixture,monkeypatch):
    app,store,ws,project=fixture
    monkeypatch.setattr(retention.shutil,'disk_usage',lambda _:SimpleNamespace(free=1,total=2,used=1))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        response=await api.post('/tasks',json={'workspace_id':ws['id'],'prompt':'must not create'})
        assert response.status_code==409 and response.json()['details']['reason']=='storage_low'
    with store.db.read() as db:assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
    assert (project/'source.py').exists()
