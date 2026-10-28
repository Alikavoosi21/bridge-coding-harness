import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from harness.outputs import OutputSessions,output_info
from harness.runtime.docker import DockerRuntime
from harness.task_runtime import open_task_runtime,task_directory
from harness.workspace import Workspace
from server.app import create_app
from server.storage import Store,Database,migrate


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('HARNESS_HOME',str(tmp_path/'home'));monkeypatch.delenv('HARNESS_TOKEN',raising=False)
    workspace=Workspace.at(tmp_path/'project').scaffold()
    (workspace.root/'index.html').write_text('<!doctype html><link rel="stylesheet" href="style.css"><h1>OUTPUT_PREVIEW</h1><button onclick="document.querySelector(\'h1\').textContent=\'JS_WORKS\'">Click</button><script src="app.js"></script>',encoding='utf8')
    (workspace.root/'style.css').write_text('body{background:rgb(12,60,120)}',encoding='utf8')
    (workspace.root/'app.js').write_text('document.title="Script loaded";',encoding='utf8')
    (workspace.root/'main.py').write_text('from pathlib import Path\nPath("execution.txt").write_text("copy only")\nprint("EXECUTION_OK")',encoding='utf8')
    (workspace.root/'server.js').write_text('const http=require("http"),fs=require("fs");http.createServer((q,r)=>{r.setHeader("Content-Type","text/html");r.end("<h1>LIVE_APP_OK</h1>")}).listen(process.env.PORT||3000,"0.0.0.0");console.log("SERVER_STARTED");',encoding='utf8')
    (workspace.root/'.env').write_text('SECRET_VALUE=must_not_be_served',encoding='utf8')
    store=Store(Database());migrate(store.db);ws=store.upsert_workspace(str(workspace.root))
    task=store.create_task(workspace_id=ws['id'],prompt='fixture',read_only=True)
    runtime=open_task_runtime(workspace,store,task['id'],read_only=True,max_seconds=30);runtime.close()
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    store.set_task_status(task['id'],'closed',outcome='completed')
    return store,task,workspace,task_directory(store,task['id'])


def payload(store,task,kind='html',**extra):
    info=output_info(store,task['id'])
    return {'kind':kind,'path':'index.html' if kind=='html' else '','command':'','port':3000,'confirm':True,'install_command':'','install_consent':False,'expected_revision':info['working_revision'],'expected_hash':info['working_manifest_hash'],'key':'fixture-'+kind,**extra}


def test_static_html_and_assets_serve_only_the_captured_copy(fixture):
    store,task,workspace,directory=fixture;manager=OutputSessions()
    try:
        request=payload(store,task);result=manager.start(store,task['id'],**request)
        assert result['state']=='ready' and result['url'].startswith('http://127.0.0.1:')
        assert manager.start(store,task['id'],**request)['id']==result['id']
        response=httpx.get(result['url']);assert 'OUTPUT_PREVIEW' in response.text
        assert 'connect-src \'none\'' in response.headers['content-security-policy']
        assert httpx.get(result['url'].replace('index.html','style.css')).status_code==200
        assert httpx.get(result['url'].replace('index.html','app.js')).status_code==200
        for name in ('.env','main.py','%2e%2e%2f.env'):
            assert httpx.get(result['url'].replace('index.html',name)).status_code==404
        assert httpx.get(result['url'].replace('index.html',''),headers={'Host':'attacker.test'}).status_code==404
        (directory/'working'/'index.html').write_text('NEW_WORKING_CONTENT',encoding='utf8')
        assert 'OUTPUT_PREVIEW' in httpx.get(result['url']).text
        assert manager.stop(task['id'],result['id'])['state']=='stopped'
    finally:manager.close_all()


async def test_api_requires_explicit_command_and_install_consent(fixture):
    store,task,_,_=fixture;app=create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as api:
        base='/tasks/'+task['id']+'/outputs'
        denied=await api.post(base,json=payload(store,task,'command',command='python main.py',confirm=False));assert denied.status_code==409
        denied=await api.post(base,json=payload(store,task,'command',command='python main.py',install_command='pip install x',install_consent=False));assert denied.status_code==409
        denied=await api.post(base,json=payload(store,task,'server',command='node server.js',network_consent=False));assert denied.status_code==409
        denied=await api.post(base,json=payload(store,task,path='../index.html'));assert denied.status_code==422
        assert not app.state.harness.outputs.sessions


@pytest.mark.parametrize('kind,command',[('command','python main.py'),('server','node server.js')])
async def test_real_docker_executes_output_and_publishes_only_loopback(fixture,kind,command):
    capability=DockerRuntime().capability()
    if not capability.available:pytest.skip(capability.reason)
    store,task,workspace,directory=fixture;manager=OutputSessions(runtime_factory=DockerRuntime)
    try:
        result=manager.start(store,task['id'],**payload(store,task,kind,command=command,network_consent=kind=='server'))
        for _ in range(150):
            await asyncio.sleep(0.3);result=manager.get(task['id'],result['id'])
            if result['state'] in {'ready','finished','failed','unknown'}:break
        assert result['state']==('ready' if kind=='server' else 'finished'),result
        if kind=='command':
            assert result['exit_code']==0 and 'EXECUTION_OK' in result['output']
            assert not (workspace.root/'execution.txt').exists() and not (directory/'working'/'execution.txt').exists()
        else:
            assert result['url'].startswith('http://127.0.0.1:')
            assert 'LIVE_APP_OK' in httpx.get(result['url']).text
            internal=manager.sessions[result['id']]
            inspect=json.loads(manager._docker(internal,['inspect',internal['container']]))[0]
            assert inspect['HostConfig']['NetworkMode']=='bridge'
            assert all(row['HostIp']=='127.0.0.1' for rows in inspect['NetworkSettings']['Ports'].values() for row in rows)
            assert str(workspace.root) not in str(inspect['Mounts'])
        stopped=manager.stop(task['id'],result['id'])
        for _ in range(20):
            if stopped['state']!='stopping':break
            await asyncio.sleep(0.2);stopped=manager.get(task['id'],result['id'])
        assert stopped['state']=='stopped',stopped
    finally:manager.close_all()
