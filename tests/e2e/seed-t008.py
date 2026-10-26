"""Isolated local fixture only. Invoked by t008-smoke.cjs with HARNESS_HOME."""
import json
import os
from pathlib import Path
from server import settings
from server.storage import Store, migrate

root = Path(os.environ['HARNESS_HOME']).parent
first, second = root / 'پروژه نمونه', root / 'پروژه دوم'
for folder in (first, second):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'notes.md').write_text('Local fixture. No secrets.', encoding='utf-8')
    if os.environ.get('HARNESS_PARTIAL_FIXTURE')=='1':(folder/'second.md').write_text('Second original.',encoding='utf8')
data = settings.load()
data.update(current_workspace=str(first), workspaces=[str(first), str(second)], setup={'step': 4, 'completed': True, 'acknowledgements': {k: True for k in ('model_api','sandbox_network','demo_state','read_only')}})
settings.save(data)
store = Store()
migrate(store.db)
ws = store.upsert_workspace(str(first), 'پروژه نمونه')
store.upsert_workspace(str(second), 'پروژه دوم')
task = store.create_task(workspace_id=ws['id'], prompt='بررسی ساختار پروژه بدون تغییر فایل', read_only=True)
store.save_plan(task['id'], steps=[{'title': 'خواندن فایل راهنما', 'status': 'pending'}, {'title': 'گزارش ساختار پروژه', 'status': 'pending'}], scope=['notes.md'], checks=[])
store.set_task_status(task['id'], 'awaiting_plan', reason='fixture')
if os.environ.get('HARNESS_CHANGES_FIXTURE')=='1':
    from harness.workspace import Workspace
    from harness.task_runtime import open_task_runtime,task_directory
    assembly=open_task_runtime(Workspace.at(first),store,task['id'],read_only=True,max_seconds=60)
    assembly.close()
    (task_directory(store,task['id'])/'working'/'notes.md').write_text('Changed working fixture.',encoding='utf8')
    if os.environ.get('HARNESS_PARTIAL_FIXTURE')=='1':(task_directory(store,task['id'])/'working'/'second.md').write_text('Second agent version.',encoding='utf8')
    with store.db.write() as db:db.execute('UPDATE tasks SET read_only=0 WHERE id=?',(task['id'],))
    if os.environ.get('HARNESS_APPLY_FIXTURE')=='1':
        # Test-only identity: no container/model command is launched by this flow.
        (task_directory(store,task['id'])/'runtime.json').write_text(json.dumps({'image':'sha256:'+'a'*64,'runtime_id':'fixture-runtime'}),encoding='utf8')
        store.upsert_workspace(str(first),'پروژه نمونه',profile=json.dumps({'profile_hash':'fixture-profile','commands':[]}))
store.record_event(task['id'], 'message_started', {'message_id':'fixture-assistant','part_id':'fixture-assistant:text'})
store.record_event(task['id'], 'text_delta', {'message_id':'fixture-assistant','part_id':'fixture-assistant:text','offset':0,'delta':'برنامه آمادهٔ بازبینی است. فقط فایل‌های پروژه خوانده می‌شوند.'})
store.record_event(task['id'], 'message_finished', {'message_id':'fixture-assistant','part_id':'fixture-assistant:text','finish_reason':'stop'})
live = store.create_task(workspace_id=ws['id'], prompt='اجرای آزمایشی برای آزمون رابط', read_only=True)
store.set_task_status(live['id'], 'executing', reason='fixture: no runtime is running')
store.record_event(live['id'], 'message_started', {'message_id':'live-assistant','part_id':'live-assistant:text'})
body = '\n\n'.join(f'گام {index}: خواندن notes.md و بررسی ساختار؛ این متن دادهٔ آزمایشی است.' for index in range(40))
store.record_event(live['id'], 'text_delta', {'message_id':'live-assistant','part_id':'live-assistant:text','offset':0,'delta':body})
extra={}
if os.environ.get('HARNESS_SKILLS_FIXTURE')=='1':
    skill=root/'personal-skill';skill.mkdir()
    (skill/'SKILL.md').write_text('---\nname: check-code\ndescription: Review requested code only.\n---\n\nPRIVATE SKILL INSTRUCTIONS FOR PREVIEW\n',encoding='utf8')
    (skill/'helper.py').write_text("raise RuntimeError('Never execute on enable')",encoding='utf8')
    extra['skill_source']=str(skill)
    if os.environ.get('HARNESS_REPIN_FIXTURE')=='1':
        from harness.skills_registry import SkillRegistry
        from harness.workspace import Workspace
        from harness.task_runtime import open_task_runtime
        registry=SkillRegistry(store);registered=registry.register(skill,scope='personal')
        registry.enable(registered['id'],expected_hash=registered['current_hash'],confirm=True)
        assembly=open_task_runtime(Workspace.at(first),store,task['id'],read_only=True,max_seconds=60);assembly.close()
        store.decide_plan(task['id'],expected_revision=store.plan(task['id'])['revision'],approve=True)
        extra['skill_id']=registered['id']
if os.environ.get('HARNESS_RECOVERY_FIXTURE')=='1':
    from contextlib import contextmanager
    from harness.worktrees.diff import changes
    from harness.worktrees.selection import prepare_selection
    import harness.worktrees.apply as applying
    from harness.worktrees.file_lock import locked_regular_file
    # Use the already-captured task, and inject a real short write on its original.
    report=changes(store,task['id'])
    selected=prepare_selection(store,task['id'],file_ids=[row['file_id'] for row in report['items']],expected_revision=report['working_revision'],expected_manifest_hash=report['working_manifest_hash'])
    class Interrupted:
        def __init__(self,file):self.file=file
        def __getattr__(self,name):return getattr(self.file,name)
        def write(self,data):
            self.file.write(data[:3]);self.file.flush();raise OSError('fixture injected partial write')
    calls=0
    @contextmanager
    def interrupted(root,path,**kwargs):
        global calls
        calls+=1
        partial=os.environ.get('HARNESS_PARTIAL_FIXTURE')=='1'
        if partial and calls==2:(root/path).write_text('User kept after interruption.',encoding='utf8')
        with locked_regular_file(root,path,**kwargs) as file:yield file if partial else Interrupted(file)
    applying.locked_regular_file=interrupted
    try:operation=applying.apply_selection(store,task['id'],selected['id'],key='seed-interruption',confirm=True,quality_ack=True)
    finally:applying.locked_regular_file=locked_regular_file
    expected='partial' if os.environ.get('HARNESS_PARTIAL_FIXTURE')=='1' else 'unknown'
    assert operation['state']==expected
    changed=next(row['path'] for row in operation['files'] if row['state'] in {'conflict','unknown'})
    (first/changed).write_text('User kept after interruption.',encoding='utf8')
    extra={'recovery_operation':operation['id'],'recovery_state':expected,'recovery_path':changed}
if os.environ.get('HARNESS_DATA_FIXTURE')=='1':
    import time
    closed=store.create_task(workspace_id=ws['id'],prompt='PRIVATE DIAGNOSTIC FIXTURE',read_only=True)
    store.close_task(closed['id'])
    cache=store.db.path.parent/'tasks'/closed['id']/'working'/'.pytest_cache'
    cache.mkdir(parents=True)
    (cache/'cached.txt').write_text('Disposable cache fixture.',encoding='utf8')
    (cache.parent/'kept.py').write_text('PRIVATE SOURCE KEPT',encoding='utf8')
    past=time.time()-40*86400
    for file in [cache/'cached.txt',cache]:os.utime(file,(past,past))
    with store.db.write() as db:db.execute('UPDATE tasks SET updated_at=? WHERE id=?',(past,closed['id']))
    extra['cache_task']=closed['id']
print(json.dumps({'task':task['id'],'live':live['id'],'live_length':len(body),'workspace':str(first),'second':str(second),**extra},ensure_ascii=False))
