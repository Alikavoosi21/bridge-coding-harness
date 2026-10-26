import base64
import httpx
import pytest
from pathlib import Path

from server.app import create_app
from server.storage import Store
from harness.skills_registry import SkillRegistry


@pytest.fixture
async def client(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),base_url='http://localhost') as api:
        await api.post('/workspace',json={'path':str(tmp_path/'project')})
        yield api


async def test_easy_skill_create_enable_and_pin(client):
    payload={'name':'brief-review','description':'Review code when explicitly requested.','instructions':'Read the requested file. Report up to three concrete defects.','confirm':False}
    assert (await client.post('/skills/create',json=payload)).status_code==400
    payload['confirm']=True
    result=await client.post('/skills/create',json=payload)
    assert result.status_code==200,result.text
    skill=result.json();assert skill['enabled'] and skill['valid'] and skill['name']=='brief-review'
    task=(await client.post('/tasks',json={'prompt':'/brief-review inspect main.py'})).json()['task']
    registry=SkillRegistry(Store());registry.pin_task(task['id'])
    assert any(pin['name']=='brief-review' and pin['valid'] for pin in registry.task_pins(task['id']))
    assert (await client.post('/skills/create',json=payload)).status_code==409


async def test_only_explicit_attachment_is_saved(client):
    response=await client.post('/attachments',json={'name':'notes.txt','data':base64.b64encode(b'User provided this.').decode()})
    assert response.status_code==200,response.text
    saved=response.json()['path'];assert saved.startswith('.bridge-attachments/')
    files=(await client.get('/files')).json()
    assert any(item['path'].lstrip('/')==saved for item in files)
    assert (await client.post('/attachments',json={'name':'.env','data':'YWJj'})).status_code==422
    assert (await client.post('/attachments',json={'name':'bad.txt','data':'not base64'})).status_code==422


async def test_closed_answer_accepts_followup_on_same_thread_and_revokes_old_approval(client,monkeypatch):
    from server.state import AppState
    task=(await client.post('/tasks',json={'prompt':'Explain what a unit test is.'})).json()['task']
    store=Store();plan=store.save_plan(task['id'],steps=[{'title':'Previous work','status':'completed'}],scope=['main.py'])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    store.set_task_status(task['id'],'closed',outcome='completed')
    calls=[]
    monkeypatch.setattr(AppState,'submit',lambda self,phase,task_id,instruction=None:calls.append((phase,task_id,instruction)) or store.task(task_id))
    key='followup-same-thread'
    for _ in range(2):
        response=await client.post('/tasks/'+task['id']+'/plan-proposals',json={'instruction':'Explain it more simply.','idempotency_key':key})
        assert response.status_code==202,response.text
    current=store.task(task['id'])
    assert current['thread_id']==task['thread_id']
    assert store.plan(task['id'])['approved_revision'] is None
    assert len(calls)==1
    assert sum(any(p.get('text')=='Explain it more simply.' for p in m['parts']) for m in store.messages(task['id']))==1
