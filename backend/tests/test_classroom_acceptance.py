"""Three real API/Deep Agents/checkpoint walkthroughs with a disclosed demo model.

No provider, shell, dependency install or Docker execution is simulated as real.
"""
import json

import httpx
import pytest

from server.app import create_app
from server.storage import Store
from harness.task_runtime import task_directory


@pytest.mark.parametrize('language',['javascript','typescript','python'])
async def test_local_classroom_readonly_plan_approve_continue_reload(language,tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    root=tmp_path/language;root.mkdir()
    if language=='python':
        source='prices.py';text='def total(values):\n    return sum(values)\n'
        files={'pyproject.toml':'[project]\nname="classroom-sample"\ndependencies=["pytest"]\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n','uv.lock':'','prices.py':text}
        expected='uv run pytest'
    else:
        source='prices.ts' if language=='typescript' else 'prices.js'
        text='export const total = (values'+(': number[]' if language=='typescript' else '')+') => values.reduce((a,b) => a+b, 0);\n'
        scripts={'test':'node --test'}
        if language=='typescript':scripts['typecheck']='tsc --noEmit'
        files={'package.json':json.dumps({'name':'classroom-sample','scripts':scripts}),'package-lock.json':'{}',source:text}
        if language=='typescript':files['tsconfig.json']='{"compilerOptions":{"strict":true}}'
        expected='npm test'
    for name,content in files.items():(root/name).write_text(content,encoding='utf8')
    (root/'.env').write_text('PRIVATE=not-for-agent',encoding='utf8')
    original={path.name:path.read_bytes() for path in root.iterdir() if path.is_file()}
    app=create_app();store=Store()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as api:
        assert (await api.post('/workspace',json={'path':str(root)})).status_code==200
        ws=(await api.get('/workspaces')).json()['items'][0]
        preflight=(await api.post(f"/workspaces/{ws['id']}/preflight")).json()
        commands=preflight['profile']['commands']
        assert expected in [row['command'] for row in commands]
        if language=='typescript':assert 'npm run typecheck' in [row['command'] for row in commands]
        profile=await api.patch(f"/workspaces/{ws['id']}",json={'profile':{'commands':commands,'install':None}})
        assert profile.status_code==200,profile.text
        payload={'prompt':'ساختار این پروژه و بررسی‌های لازم را توضیح بده؛ هیچ فایل یا فرمانی را تغییر یا اجرا نکن.','references':[source],'read_only':True,'idempotency_key':language+':create'}
        first=await api.post('/tasks',json=payload);assert first.status_code==202,first.text
        task=first.json()['task'];base='/tasks/'+task['id']
        assert (await api.post('/tasks',json=payload)).json()['task']['id']==task['id']
        proposed=await api.post(base+'/plan-proposals',json={'expected_revision':task['revision'],'idempotency_key':language+':plan'})
        assert proposed.status_code==202,proposed.text
        await app.state.harness.manager.wait(task['thread_id'])
        planned=(await api.get(base)).json()
        assert planned['status']=='awaiting_plan' and not planned['plan']['approved_revision']
        assert planned['budget']['model_calls']==3 # no repair loop for a pending proposed plan
        assert all(step['status']=='pending' for step in planned['plan']['steps'])
        approval=await api.post(base+'/plan-decisions',json={'expected_revision':planned['plan']['revision'],'decision':'approve','idempotency_key':language+':approve'})
        assert approval.status_code==200,approval.text
        body={'expected_plan_revision':planned['plan']['revision'],'idempotency_key':language+':continue'}
        continued=await api.post(base+'/continuations',json=body);assert continued.status_code==202,continued.text
        await app.state.harness.manager.wait(task['thread_id'])
        final=(await api.get(base)).json()
        assert final['status']=='closed' and final['read_only'] and final['thread_id']==task['thread_id']
        assert len(final['runs'])==2 and final['budget']['model_calls']==6
        replay=await api.post(base+'/continuations',json=body)
        assert replay.status_code==202 and len((await api.get(base)).json()['runs'])==2
        events=(await api.get(base+'/events')).json()['items']
        tools=[row['payload'].get('tool') for row in events if row['type']=='action_started']
        assert 'ls' in tools and not any(tool in tools for tool in ['execute','write_file','edit_file'])
        messages=''.join(row['payload'].get('delta','') for row in events if row['type']=='text_delta')
        assert 'نمایشی' in messages and 'هیچ اصلاح کد' in messages
        assert not (task_directory(store,task['id'])/'working'/'.env').exists()
        assert all((root/name).read_bytes()==content for name,content in original.items())
        assert not (root/'node_modules').exists() and not (root/'.venv').exists()
