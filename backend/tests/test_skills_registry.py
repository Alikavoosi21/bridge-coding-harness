"""Reviewed skill copies are data, never execution or permission grants."""
from pathlib import Path

import pytest

from harness.skills_registry import SkillRegistry,inspect_source
from harness.task_runtime import task_directory
from server.errors import ApiError
from server.storage import Store,Database,migrate


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    store=Store(Database());migrate(store.db)
    project=tmp_path/'project';project.mkdir()
    workspace=store.upsert_workspace(str(project))
    source=project/'my-skill';source.mkdir()
    (source/'SKILL.md').write_text('---\nname: check-code\ndescription: Inspect code when requested.\n---\n\nRead only the relevant file.\n',encoding='utf8')
    (source/'helper.py').write_text("raise RuntimeError('must never be executed by enabling a skill')",encoding='utf8')
    return store,SkillRegistry(store),workspace,source


def test_registration_is_disabled_metadata_only_and_requires_reviewed_hash(fixture):
    store,registry,workspace,source=fixture
    registered=registry.register(source,scope='project',workspace_id=workspace['id'])
    assert registered['valid'] and not registered['enabled'] and registered['trust']=='unreviewed'
    assert 'body' not in registered and 'body' not in registry.list(workspace['id'])[0]
    assert 'Read only' in registry.detail(registered['id'],body=True)['body']
    with pytest.raises(ApiError) as consent:registry.enable(registered['id'],expected_hash=registered['current_hash'])
    assert consent.value.code=='action_not_approved'
    (source/'helper.py').write_text('changed script',encoding='utf8')
    with pytest.raises(ApiError) as stale:registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
    assert stale.value.code=='selection_stale'
    latest=registry.detail(registered['id']);enabled=registry.enable(registered['id'],expected_hash=latest['current_hash'],confirm=True)
    assert enabled['enabled'] and enabled['trust']=='reviewed'
    with store.db.read() as db:
        assert db.execute('SELECT COUNT(*) FROM grants').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM actions').fetchone()[0]==0


def test_running_task_keeps_immutable_pin_after_source_changes_disable_and_new_enable(fixture):
    store,registry,workspace,source=fixture
    registered=registry.register(source,scope='personal')
    first_hash=registered['current_hash'];registry.enable(registered['id'],expected_hash=first_hash,confirm=True)
    task=store.create_task(workspace_id=workspace['id'],prompt='pin old skill')
    pins=registry.pin_task(task['id'])
    assert pins[0]['hash']==first_hash and 'body' not in pins[0]
    captured=task_directory(store,task['id'])/'knowledge'/'skills'/'check-code'/'helper.py'
    original=captured.read_bytes()
    (source/'helper.py').write_text('new source implementation',encoding='utf8')
    assert registry.detail(registered['id'])['changed']
    registry.disable(registered['id'])
    assert registry.pin_task(task['id'])==pins and captured.read_bytes()==original
    latest=registry.detail(registered['id']);registry.enable(registered['id'],expected_hash=latest['current_hash'],confirm=True)
    newer=store.create_task(workspace_id=workspace['id'],prompt='pin new skill')
    assert registry.pin_task(newer['id'])[0]['hash']!=first_hash
    assert registry.pin_task(task['id'])==pins and captured.read_bytes()==original
    registry.forget(registered['id'])
    assert source.is_dir() and (source/'SKILL.md').is_file()
    assert registry.list(workspace['id'])==[]
    assert registry.pin_task(task['id'])==pins
    again=registry.register(source,scope='personal')
    assert again['id']==registered['id'] and again['trust']=='unreviewed' and not again['enabled']


def test_empty_pin_stays_empty_and_tampering_is_not_silently_repaired(fixture):
    store,registry,workspace,source=fixture
    task=store.create_task(workspace_id=workspace['id'],prompt='empty pin')
    assert registry.pin_task(task['id'])==[]
    registered=registry.register(source,scope='personal');registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
    assert registry.pin_task(task['id'])==[]
    newer=store.create_task(workspace_id=workspace['id'],prompt='reviewed pin')
    registry.pin_task(newer['id'])
    captured=task_directory(store,newer['id'])/'knowledge'/'skills'/'check-code'/'helper.py'
    captured.write_text('tampering',encoding='utf8')
    assert not registry.task_pins(newer['id'])[0]['valid']
    with pytest.raises(ApiError) as invalid:registry.pin_task(newer['id'])
    assert invalid.value.code=='recovery_required' and captured.read_text(encoding='utf8')=='tampering'


def test_invalid_sources_explain_errors_and_cannot_gain_enable(fixture,tmp_path):
    _,registry,workspace,source=fixture
    (source/'SKILL.md').write_text('no frontmatter',encoding='utf8')
    invalid=registry.register(source,scope='project',workspace_id=workspace['id'])
    assert not invalid['valid'] and 'frontmatter' in invalid['error']
    with pytest.raises(ApiError):registry.enable(invalid['id'],expected_hash='',confirm=True)
    with pytest.raises(ApiError) as outside:registry.register(tmp_path,scope='project',workspace_id=workspace['id'])
    assert outside.value.code=='invalid_request'
    (source/'.env').write_text('fixture secret',encoding='utf8')
    assert not inspect_source(source)['valid']


async def test_registry_http_requires_explicit_trust_and_forget_preserves_source(fixture):
    import httpx
    from server.app import create_app
    _,_,workspace,source=fixture
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://127.0.0.1:8765') as api:
        response=await api.post('/skill-sources',json={'source':str(source),'scope':'project','workspace_id':workspace['id']})
        assert response.status_code==200 and not response.json()['enabled']
        identifier=response.json()['id'];digest=response.json()['current_hash']
        listed=(await api.get('/skill-sources',params={'workspace_id':workspace['id']})).json()['items']
        assert len(listed)==1 and 'body' not in listed[0]
        assert 'body' in (await api.get('/skill-sources/'+identifier)).json()
        assert (await api.post('/skill-sources/'+identifier+'/enable',json={'expected_hash':digest,'confirm':False})).status_code==409
        assert (await api.post('/skill-sources/'+identifier+'/enable',json={'expected_hash':digest,'confirm':True})).json()['enabled']
        assert not (await api.post('/skill-sources/'+identifier+'/disable')).json()['enabled']
        assert (await api.delete('/skill-sources/'+identifier)).json()['source_deleted'] is False
    assert (source/'SKILL.md').exists()
