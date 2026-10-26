"""Explicit idle re-pin, with archived old copies and checkpoint reload marker.

No model call or tool grant is performed here. A fresh read-only plan and new
approval are required before execution with the replacement skill snapshot.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid

from server.errors import ApiError
from .skills_registry import SkillRegistry,inspect_source
from .task_runtime import task_directory
from .worktrees.diff import changes
from .worktrees.guard import locked_copy
from .worktrees.snapshot import build,sync,_is_link_path
from .verification.observe import snapshot_hash


def _write(path,value):
    from .worktrees.edit import _durable
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    _durable(temporary,json.dumps(value,ensure_ascii=False,sort_keys=True).encode())
    temporary.replace(path)


def marker(store,task_id):
    path=task_directory(store,task_id)/'skill-repin.json'
    if not path.exists():return None
    try:
        if _is_link_path(path):raise ValueError('linked marker')
        value=json.loads(path.read_text(encoding='utf8'))
        if not isinstance(value,dict):raise ValueError('invalid marker')
        return value
    except (OSError,ValueError):raise ApiError('recovery_required','The skill re-pin journal needs recovery.',status_code=409) from None


def desired_pins(store,task_id):
    task=store.task(task_id);pins=[];names=set()
    with store.db.read() as db:
        rows=db.execute("SELECT id,hash,scope FROM skill_sources WHERE enabled=1 AND trust='reviewed' AND (scope IN ('personal','bundled') OR scope=?) ORDER BY id",('project:'+task['workspace_id'],)).fetchall()
    for row in rows:
        metadata=inspect_source(store.db.path.parent/'skill-copies'/row['hash'])
        if not metadata['valid'] or metadata['current_hash']!=row['hash']:
            raise ApiError('recovery_required','Reviewed skill copy unavailable.',status_code=409)
        if metadata['name'] in names:raise ApiError('conflict','Enabled skill names overlap.',status_code=409)
        names.add(metadata['name'])
        pins.append({'skill_id':row['id'],'hash':row['hash'],'scope':row['scope'],'name':metadata['name'],'description':metadata['description']})
    return pins


def preview(store,task_id):
    task=store.task(task_id);pins=desired_pins(store,task_id);report=changes(store,task_id)
    current=SkillRegistry(store).task_pins(task_id)
    root=task_directory(store,task_id)/'knowledge'/'skills'
    if _is_link_path(root) or _is_link_path(root.parent):raise ApiError('recovery_required','Skill migration source is linked.',status_code=409)
    tree_hash=snapshot_hash(build(root)) if root.exists() else None
    tracked={pin['name'] for pin in current}
    legacy=sorted(path.name for path in root.iterdir() if path.name not in tracked) if root.exists() else []
    # Consent covers both the destination and the old tree that is archived.
    # Legacy content is never silently trusted or executed during migration.
    digest=hashlib.sha256(json.dumps({'desired':pins,'previous_tree_hash':tree_hash},sort_keys=True).encode()).hexdigest()
    return {'current':current,'legacy_entries':legacy,'previous_tree_hash':tree_hash,'desired':pins,'pins_hash':digest,'task_revision':task['revision'],'working_revision':report['working_revision'],'working_manifest_hash':report['working_manifest_hash']}


def require_fresh_plan(store,task_id):
    if not hasattr(store,'db'):return
    state=marker(store,task_id)
    if state and (state.get('status')!='applied' or state.get('needs_replan')):
        raise ApiError('action_not_approved','Skills changed; run a fresh read-only plan before approving execution.',status_code=409)


def finish_replan(store,task_id):
    state=marker(store,task_id)
    if not state or not state.get('needs_replan'):return
    plan=store.plan(task_id)
    if plan and plan['updated_at']>state.get('plan_updated_at_before',0) and not state.get('cache_reset_pending'):
        state['needs_replan']=False
        _write(task_directory(store,task_id)/'skill-repin.json',state)


async def reset_checkpoint_cache(agent,config,store,task_id):
    """Await durable LangGraph state update before acknowledging the reset."""
    from langgraph.types import Overwrite
    from langchain_core.messages import HumanMessage
    state=marker(store,task_id)
    if not state or not state.get('cache_reset_pending'):return False
    if state.get('status')!='applied':raise ApiError('recovery_required','Skill re-pin did not finish.',status_code=409)
    notice=HumanMessage(id='skill-repin:'+state['operation_id'],content='The user explicitly re-pinned this task to reviewed skill snapshots. Previous skill bodies are historical. Re-read relevant skills from the current paths and propose a fresh plan; do not execute until new approval.')
    await agent.aupdate_state(config,{'skills_metadata':None,'skills_load_errors':[],'pinned_skills':Overwrite([]),'messages':[notice]})
    state['cache_reset_pending']=False
    _write(task_directory(store,task_id)/'skill-repin.json',state)
    return True


def repin(store,task_id,*,key,expected_revision,expected_working_revision,expected_working_hash,expected_pins_hash,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Explicit re-pin confirmation is required.',status_code=409)
    body={'revision':expected_revision,'working_revision':expected_working_revision,'working_hash':expected_working_hash,'pins_hash':expected_pins_hash}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    invocation='skill-repin:'+key;prior=store.action_by_invocation(task_id,invocation)
    if prior:
        if prior['args_hash']!=digest:raise ApiError('idempotency_conflict','Re-pin key belongs to a different request.',status_code=409)
        if prior['state']=='succeeded':return json.loads(prior['result_ref'])
        if prior['state']!='pending':raise ApiError('recovery_required','Interrupted re-pin is not replayed.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_working_revision,expected_manifest_hash=expected_working_hash,kind='skill_repin') as held:
        if held['task']['status'] in {'closed','failed','cancelled'}:raise ApiError('conflict','Finished tasks keep their historical skill pins.',status_code=409)
        fresh=preview(store,task_id)
        if fresh['task_revision']!=expected_revision or fresh['pins_hash']!=expected_pins_hash:
            raise ApiError('selection_stale','Reviewed skill selection changed; preview again.',status_code=409)
        action=store.ensure_action(task_id,invocation,digest)
        archive=held['directory']/'skill-repins'/action['operation_id'];archive.mkdir(parents=True,exist_ok=True)
        staged=archive/'new-skills'
        if staged.exists():raise ApiError('recovery_required','A staged re-pin already exists.',status_code=409)
        staged.mkdir()
        for pin in fresh['desired']:
            source=store.db.path.parent/'skill-copies'/pin['hash']
            sync(build(source),staged/pin['name'],write_manifest_file=False)
            if snapshot_hash(build(staged/pin['name']))!=pin['hash']:
                raise ApiError('recovery_required','Skill changed during staging.',status_code=409)
        plan=store.clear_plan_approval(task_id,reason='skills_repin_requested')
        state={'operation_id':action['operation_id'],'status':'prepared','cache_reset_pending':True,'needs_replan':True,'plan_updated_at_before':plan['updated_at'] if plan else 0,'desired':fresh['desired'],'previous_tree_hash':fresh['previous_tree_hash']}
        _write(archive/'prepare.json',{**state,'previous':fresh['current']})
        _write(held['directory']/'skill-repin.json',state)
        store.set_action_state(action['operation_id'],'dispatching')
        try:
            root=held['directory']/'knowledge'/'skills';old_marker=held['directory']/'skill-pins.json'
            held['lease'].check('re-pin skills')
            if _is_link_path(root) or _is_link_path(root.parent):raise ApiError('recovery_required','Skill pin root is unavailable.',status_code=409)
            if root.exists():root.rename(archive/'previous-skills')
            staged.rename(root)
            if old_marker.exists():old_marker.rename(archive/'previous-pins.json')
            now=time.time()
            with store.db.write() as db:
                db.execute('DELETE FROM skill_pins WHERE task_id=?',(task_id,))
                for pin in fresh['desired']:db.execute('INSERT INTO skill_pins(task_id,skill_id,hash,pinned_at) VALUES(?,?,?,?)',(task_id,pin['skill_id'],pin['hash'],now))
                db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL',(now,task_id))
                db.execute("UPDATE approvals SET state='cancelled' WHERE task_id=? AND state='pending'",(task_id,))
                db.execute("UPDATE actions SET state='denied' WHERE task_id=? AND operation_id!=? AND state IN ('pending','awaiting_approval')",(task_id,action['operation_id']))
            _write(old_marker,fresh['desired'])
            state['status']='applied';_write(held['directory']/'skill-repin.json',state)
            store.set_task_status(task_id,'awaiting_plan',reason='skills_repin_requires_plan')
            result={'operation_id':action['operation_id'],'pins':fresh['desired'],'needs_replan':True}
            store.set_action_state(action['operation_id'],'succeeded',result_ref=json.dumps(result))
            return result
        except BaseException:
            store.set_action_state(action['operation_id'],'unknown',error='Skill re-pin interrupted; no automatic replay.')
            store.set_task_status(task_id,'recovery_required',reason='skills_repin_unknown')
            raise


def rollback_repin(store,task_id,operation_id,*,expected_working_revision,expected_working_hash,expected_skill_hash,confirm=False):
    if not confirm:raise ApiError('action_not_approved','Explicit skill rollback consent is required.',status_code=409)
    action=store.action(operation_id)
    if action['task_id']!=task_id or not action['invocation_key'].startswith('skill-repin:') or action['state']!='unknown':raise ApiError('conflict','This skill re-pin is not awaiting recovery.',status_code=409)
    with locked_copy(store,task_id,expected_revision=expected_working_revision,expected_manifest_hash=expected_working_hash,kind='skill_repin_recovery',recovery_operation=operation_id) as held:
        root=held['directory']/'knowledge'/'skills';archive=held['directory']/'skill-repins'/operation_id
        if _is_link_path(archive) or _is_link_path(archive.parent) or _is_link_path(archive/'prepare.json') or _is_link_path(root):raise ApiError('recovery_required','Re-pin recovery storage is linked.',status_code=409)
        current_hash=snapshot_hash(build(root)) if root.exists() else None
        if current_hash!=expected_skill_hash:raise ApiError('selection_stale','Current skill bytes changed after inspection.',status_code=409)
        saved=json.loads((archive/'prepare.json').read_text(encoding='utf8'))
        previous=archive/'previous-skills';old_hash=saved.get('previous_tree_hash')
        if not old_hash:raise ApiError('recovery_required','Legacy re-pin archive has no verifiable previous tree identity.',status_code=409)
        if previous.exists():
            if _is_link_path(previous) or snapshot_hash(build(previous))!=old_hash:raise ApiError('recovery_required','Previous skill archive changed.',status_code=409)
            abandoned=archive/'abandoned-skills'
            if root.exists():
                if abandoned.exists():raise ApiError('recovery_required','Interrupted rollback needs review.',status_code=409)
                root.rename(abandoned)
            previous.rename(root)
        elif current_hash!=old_hash:raise ApiError('recovery_required','The previous skill tree is unavailable.',status_code=409)
        pins=saved['previous'];now=time.time()
        with store.db.write() as db:
            db.execute('DELETE FROM skill_pins WHERE task_id=?',(task_id,))
            for pin in pins:db.execute('INSERT INTO skill_pins(task_id,skill_id,hash,pinned_at) VALUES(?,?,?,?)',(task_id,pin['skill_id'],pin['hash'],now))
        manifest=[{key:pin[key] for key in ('skill_id','hash','scope','name','description')} for pin in pins]
        _write(held['directory']/'skill-pins.json',manifest)
        plan=store.clear_plan_approval(task_id,reason='skill_repin_rolled_back')
        _write(held['directory']/'skill-repin.json',{'operation_id':operation_id,'status':'applied','cache_reset_pending':True,'needs_replan':True,'plan_updated_at_before':plan['updated_at'] if plan else 0,'desired':manifest,'resolution':'rolled_back'})
        store.set_action_state(operation_id,'failed',result_ref=json.dumps({'resolution':'rolled_back','operation_id':operation_id}))
        store.set_task_status(task_id,'awaiting_plan',reason='skill_repin_rolled_back_requires_fresh_plan')
        return {'operation_id':operation_id,'resolution':'rolled_back'}
