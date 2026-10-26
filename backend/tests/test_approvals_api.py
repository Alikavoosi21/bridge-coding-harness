"""Product HTTP receipts and guards; no provider key or runtime required."""
from pathlib import Path

import httpx
import pytest

from harness.gateway import ToolGateway
from harness.policy import ActionContext
from server.app import create_app
from server.storage import Store
from server.storage.approvals import ApprovalStore


@pytest.fixture
async def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'))
    monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        await api.post('/workspace',json={'path':str(tmp_path/'project')})
        task=(await api.post('/tasks',json={'prompt':'fixture'})).json()['task']
        store=Store()
        # Fixture-only task; exercise policy decisions without enabling writes
        # through the real start endpoint, which still requires actual Docker.
        with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
        plan=store.save_plan(task['id'],steps=[{'title':'read'}])
        store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
        rules=Path(tmp_path/'project'/'.harness'/'rules.yaml')
        rules.write_text('files: []\ntools:\n  read_file: ask',encoding='utf8')
        context=ActionContext('read_file',{'file_path':'/notes.md'},'/workspace','/bin/sh','read-only','offline',plan['revision'])
        review=ApprovalStore(store).request(task['id'],'fixture:read',context)
        yield api,store,task,review


async def test_receipt_list_double_click_and_legacy_bypass_are_guarded(fixture):
    api,store,task,review=fixture
    base=f"/tasks/{task['id']}"
    rows=(await api.get(base+'/approvals')).json()['items']
    assert rows[0]['action_id']==review['action_id']
    data={'decision':'approve','fingerprint':review['action_hash'],'revision':1}
    for _ in range(2):
        response=await api.post(base+f"/approvals/{review['id']}/decisions",json=data)
        assert response.status_code==200,response.text
        assert response.json()['approval']['decision']=='approve'
    with store.db.read() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND type='approval_decided'",(task['id'],)).fetchone()[0]==1
    assert (await api.post(f"/runs/{task['thread_id']}/decisions",json={'decisions':[{'type':'approve'}]})).status_code==409
    assert (await api.post('/runs',json={'prompt':'bypass','thread_id':task['thread_id']})).status_code==409
    assert (await api.post(base+'/grants/revoke')).status_code==200


async def test_changed_rules_block_receipt_and_pending_review_blocks_resume(fixture):
    api,store,task,review=fixture
    store.set_task_status(task['id'],'awaiting_action')
    workspace=store.workspace(task['workspace_id'])
    (Path(workspace['root'])/'.harness'/'rules.yaml').write_text('files: []\ntools:\n  read_file: deny',encoding='utf8')
    base=f"/tasks/{task['id']}"
    response=await api.post(base+f"/approvals/{review['id']}/decisions",json={'decision':'approve','fingerprint':review['action_hash'],'revision':1})
    assert response.status_code==409
    assert (await api.post(base+'/approval-resumptions',json={'idempotency_key':'resume:one'})).status_code==409
    assert store.action(review['action_id'])['state']=='awaiting_approval'


async def test_network_http_consent_is_idempotent_task_scoped_and_revocable(fixture):
    api,store,task,_=fixture
    base=f"/tasks/{task['id']}/network-permission"
    store.set_task_status(task['id'],'paused',reason='network consent fixture')
    body={'confirm':True,'expected_revision':store.task(task['id'])['revision'],'duration_seconds':300,'idempotency_key':'network-http'}
    assert (await api.get(base)).json()['permission'] is None
    first=await api.post(base,json=body)
    assert first.status_code==200,first.text
    second=await api.post(base,json=body)
    assert second.status_code==200 and first.json()==second.json()
    assert (await api.get(base)).json()==first.json()
    grants=(await api.get(f"/tasks/{task['id']}/grants")).json()['items']
    assert any(row['capability']=='sandbox_network' and row['active'] for row in grants)
    assert (await api.post(base+'/revoke')).status_code==200
    assert (await api.get(base)).json()['permission'] is None
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=1 WHERE id=?',(task['id'],))
    body['idempotency_key']='readonly-network'
    assert (await api.post(base,json=body)).status_code==409


async def test_grant_list_reports_effective_state_and_revoke_without_reexecution(fixture):
    api,store,task,review=fixture
    base=f"/tasks/{task['id']}"
    with store.db.write() as db:
        db.execute("UPDATE tasks SET mode='grant' WHERE id=?",(task['id'],))
    response=await api.post(base+f"/approvals/{review['id']}/decisions",json={'decision':'approve','fingerprint':review['action_hash'],'revision':1,'grant':True})
    assert response.status_code==200,response.text
    items=(await api.get(base+'/grants')).json()['items']
    assert len(items)==1 and items[0]['active'] and items[0]['expiry'] is None
    assert (await api.post(base+'/grants/revoke')).status_code==200
    items=(await api.get(base+'/grants')).json()['items']
    assert not items[0]['active'] and items[0]['revoked_at'] is not None
    assert store.action(review['action_id'])['state']=='pending'


async def test_edit_requires_a_new_receipt_and_access_change_returns_canonical_mode(fixture):
    api,store,task,review=fixture
    base=f"/tasks/{task['id']}"
    result=await api.post(base+f"/approvals/{review['id']}/edits",json={'fingerprint':review['action_hash'],'revision':1,'args':{'file_path':'/other.md'}})
    assert result.status_code==200,result.text
    replacement=result.json()['approval']
    assert replacement['revision']==2 and replacement['state']=='pending'
    assert replacement['action_id']==review['action_id']
    assert replacement['action_hash']!=review['action_hash']
    stale=await api.post(base+f"/approvals/{review['id']}/decisions",json={'decision':'approve','fingerprint':review['action_hash'],'revision':1})
    assert stale.status_code==409
    current=store.task(task['id'])
    changed=await api.patch(base+'/access',json={'mode':'grant','expected_revision':current['revision']})
    assert changed.status_code==200 and changed.json()['task']['mode']=='grant'
    assert store.action(review['action_id'])['state']=='denied'
    stale=await api.patch(base+'/access',json={'mode':'auto','expected_revision':current['revision']})
    assert stale.status_code==409


async def test_stop_receipt_is_idempotent_and_never_claims_stopped_before_runtime_settles(fixture,monkeypatch):
    api,store,task,review=fixture
    store.set_task_status(task['id'],'executing')
    calls=[]
    runner=api._transport.app.state.harness.manager.runner
    def stop(thread_id):calls.append(thread_id);return True
    monkeypatch.setattr(runner,'stop',stop)
    base=f"/tasks/{task['id']}"
    for _ in range(2):
        response=await api.post(base+'/stop',json={'idempotency_key':'stop:one'})
        assert response.status_code==202,response.text
        assert response.json()['accepted'] is True
        assert response.json()['task']['status']=='stopping'
    assert calls==[task['thread_id']]
    assert store.action(review['action_id'])['state']=='denied'


@pytest.mark.parametrize('state,expected',[('awaiting_action','paused'),('executing','recovery_required')])
async def test_stop_without_a_live_runtime_is_honest_about_confirmation(fixture,state,expected):
    api,store,task,_=fixture
    store.set_task_status(task['id'],state)
    response=await api.post(f"/tasks/{task['id']}/stop",json={'idempotency_key':'stop:missing'})
    assert response.status_code==202,response.text
    assert response.json()['task']['status']==expected
