"""Isolated T010 fixture, never imported by the application."""
import json,os
from pathlib import Path
from server import settings
from server.storage import Store,migrate

root=Path(os.environ['HARNESS_HOME']).parent/'project';root.mkdir(parents=True)
(root/'notes.md').write_text('fixture',encoding='utf8')
data=settings.load();data.update(current_workspace=str(root),workspaces=[str(root)],setup={'step':4,'completed':True,'acknowledgements':{key:True for key in ('model_api','sandbox_network','demo_state','read_only')}});settings.save(data)
store=Store();migrate(store.db);ws=store.upsert_workspace(str(root))
result={}
for name in ('approve','edit','reject','mode','long-stop','quality-end','quality-again','quality-edit'):
    task=store.create_task(workspace_id=ws['id'],prompt=name,mode='auto' if name=='long-stop' or name.startswith('quality-') else 'grant',read_only=False)
    plan=store.save_plan(task['id'],steps=[{'title':'Fixture command'}],scope=['notes.md'],checks=[])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    result[name]=task['id']
print(json.dumps(result))
