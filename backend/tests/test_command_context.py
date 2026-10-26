"""Saved profile consent and actual script inputs, with no shell execution."""
import json
from types import SimpleNamespace

import pytest

from harness.command_context import command_details
from harness.gateway import ToolGateway
from server.storage import Store,Database,migrate


@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'working';root.mkdir()
    (root/'check.py').write_bytes(b'print("fixture")\r\n')
    profile={'profile_hash':'profile-v1','commands':[{'command':'python check.py','source':'check.py','required':True}], 'install':{'command':'uv sync --frozen'}}
    db=Database(tmp_path/'product.db');migrate(db);store=Store(db)
    ws=store.upsert_workspace(str(root),profile=json.dumps(profile))
    task=store.create_task(workspace_id=ws['id'],prompt='fixture',mode='auto')
    plan=store.save_plan(task['id'],steps=[{'title':'verify'}]);store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    rules=tmp_path/'rules.yaml';rules.write_text('files: []\ntools: {}',encoding='utf8')
    gateway=ToolGateway(store,task['id'],rules,runtime_available=True,runtime_id='fixture',script_root=root)
    return gateway,task,root,profile


def test_install_consent_changes_with_actual_dependency_lock(setup):
    gateway,task,root,profile=setup
    call={'id':'install-lock','name':'execute','args':{'command':'uv sync --frozen'}}
    (root/'uv.lock').write_text('reviewed lock',encoding='utf8')
    before,access=gateway.evaluate(call)
    assert access=='ask'
    (root/'uv.lock').write_text('changed lock',encoding='utf8')
    after,access=gateway.evaluate(call)
    assert access=='ask' and before.fingerprint()!=after.fingerprint()


def test_first_saved_verifier_requires_consent_and_script_change_invalidates_it(setup):
    gateway,task,root,profile=setup
    call={'id':'verify-one','name':'execute','args':{'command':'python check.py','first_verifier':False}}
    assert gateway.requires_review(SimpleNamespace(tool_call=call))
    review=gateway.approvals.list(task['id'])[0]
    assert review['request']['environment_profile']=='offline:profile-v1'
    assert review['request']['review']=={'reason':'first_verifier','effect':'command','path':None,'sandbox_network':False}
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    assert not gateway.requires_review(SimpleNamespace(tool_call={**call,'id':'verify-two'}))
    before=gateway.evaluate(call)[0].fingerprint()
    (root/'check.py').write_bytes(b'print("changed script")\n')
    after,access=gateway.evaluate(call)
    assert before!=after.fingerprint() and access=='ask'
    assert gateway.requires_review(SimpleNamespace(tool_call={**call,'id':'verify-changed'}))


async def test_authorized_profile_check_records_receipt_for_preexecution_manifest_once(setup):
    from langchain_core.messages import ToolMessage
    from harness.runtime.docker import ExecResult
    from harness.verification.observe import manifest_hash
    from harness.verification.results import CheckResults,CheckTarget
    gateway,task,root,profile=setup
    call={'id':'check-one','name':'execute','args':{'command':'python check.py'}}
    request=SimpleNamespace(tool_call=call)
    before=manifest_hash(root)
    assert gateway.requires_review(request)
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    gateway.backend=SimpleNamespace(last_receipt=None)
    hits=[]
    async def command(_):
        hits.append(1)
        operation=gateway.store.action_by_invocation(task['id'],'tool:check-one')['operation_id']
        gateway.backend.last_receipt=ExecResult('fixture',0,'fixture pass',operation_id=operation)
        (root/'check.py').write_text('formatter changed the input',encoding='utf-8')
        return ToolMessage(content='fixture pass',tool_call_id='check-one')
    await gateway.dispatch(request,command)
    changed_after_command=CheckTarget('working_copy',manifest_hash(root),'profile-v1','fixture')
    assert CheckResults(gateway.store).quality(task['id'],target=changed_after_command,required=['python check.py'])['quality_status']=='stale'
    # The same invocation replays its durable ToolMessage rather than another check.
    # Restore reviewed bytes so policy fingerprint is still the reviewed one.
    (root/'check.py').write_bytes(b'print("fixture")\r\n')
    await gateway.dispatch(request,command)
    assert hits==[1]
    results=CheckResults(gateway.store)
    target=CheckTarget('working_copy',before,'profile-v1','fixture')
    assert results.quality(task['id'],target=target,required=['python check.py'])['quality_status']=='verified_snapshot'
    (root/'check.py').write_text('new bytes',encoding='utf-8')
    changed=CheckTarget('working_copy',manifest_hash(root),'profile-v1','fixture')
    assert results.quality(task['id'],target=changed,required=['python check.py'])['quality_status']=='stale'
    events=[event for event in gateway.store.events(task['id'])['items'] if event['type']=='verification_finished']
    assert len(events)==1 and events[0]['payload']['candidate_manifest_hash']==before


@pytest.mark.parametrize('exit_code,stopped,blocked',[(0,False,False),(1,False,False),(130,True,True),(126,False,True),(127,False,True)])
async def test_baseline_blocks_mutation_until_a_conclusive_check_and_survives_restart(setup,exit_code,stopped,blocked):
    from langchain_core.messages import ToolMessage
    from harness.runtime.docker import ExecResult
    from harness.verification.results import CheckResults
    gateway,task,root,_=setup
    writes=[]
    mutation=SimpleNamespace(tool_call={'id':'write-after-baseline','name':'write_file','args':{'file_path':'/output.txt','content':'fixture'}})
    async def write(_):
        writes.append(1)
        return ToolMessage(content='written',tool_call_id='write-after-baseline')
    refusal=await gateway.dispatch(mutation,write)
    assert refusal.status=='error' and 'baseline' in refusal.content and writes==[]
    assert 'not a rejected or pending approval' in refusal.content
    assert 'python check.py' in refusal.content and 'without cd' in refusal.content
    check=SimpleNamespace(tool_call={'id':'baseline','name':'execute','args':{'command':'python check.py'}})
    assert gateway.requires_review(check)
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    gateway.backend=SimpleNamespace(last_receipt=None)
    async def execute(_):
        operation=gateway.store.action_by_invocation(task['id'],'tool:baseline')['operation_id']
        gateway.backend.last_receipt=ExecResult('fixture',exit_code,'fixture check',stopped=stopped,operation_id=operation)
        return ToolMessage(content='fixture check',tool_call_id='baseline')
    await gateway.dispatch(check,execute)
    restarted=ToolGateway(gateway.store,task['id'],gateway.rules_file,runtime_available=True,runtime_id=gateway.runtime_id,script_root=root)
    await restarted.dispatch(mutation,write)
    assert len(writes)==(0 if blocked else 1)
    records=CheckResults(gateway.store).list(task['id'])
    baseline=[row for row in records if row['details']['phase']=='baseline']
    assert len(baseline)==(0 if blocked else 1)


def test_late_check_cannot_masquerade_as_prechange_baseline(setup):
    from harness.runtime.docker import ExecResult
    from harness.verification.observe import prepare_check,finish_check,missing_baseline,current_quality
    from harness.verification.results import CheckResults
    from harness.worktrees.snapshot import build,write_manifest
    gateway,task,root,_=setup
    write_manifest(build(root),destination=root)
    (root/'main.py').write_text('existing task already changed',encoding='utf8')
    prepared=prepare_check(gateway.store,task['id'],{'name':'execute','args':{'command':'python check.py'}},root,'fixture')
    finish_check(gateway.store,task['id'],prepared,ExecResult('fixture',0,'fixture success',operation_id='fixture'))
    records=CheckResults(gateway.store).list(task['id'])
    assert records and all(row['details']['phase']=='current' for row in records)
    assert missing_baseline(gateway.store,task['id'],'fixture')==['python check.py']
    quality=current_quality(gateway.store,task['id'],root,'fixture')
    assert quality['quality_status']=='not_verified' and quality['baseline_missing']


async def test_test_script_change_needs_explicit_plan_scope_and_fresh_check_consent(setup):
    from langchain_core.messages import ToolMessage
    from harness.runtime.docker import ExecResult
    from harness.verification.observe import current_quality,manifest_hash
    from harness.verification.results import CheckResults,CheckTarget
    from harness.worktrees.snapshot import build,write_manifest
    gateway,task,root,_=setup;store=gateway.store
    write_manifest(build(root),destination=root)
    gateway.backend=SimpleNamespace(last_receipt=None)
    async def check(request):
        operation=store.action_by_invocation(task['id'],'tool:'+request.tool_call['id'])['operation_id']
        gateway.backend.last_receipt=ExecResult('fixture',0,'fixture check passed',operation_id=operation)
        return ToolMessage(content='fixture check passed',tool_call_id=request.tool_call['id'])
    initial=SimpleNamespace(tool_call={'id':'baseline-protected','name':'execute','args':{'command':'python check.py'}})
    assert gateway.requires_review(initial)
    review=gateway.approvals.list(task['id'])[-1]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    await gateway.dispatch(initial,check)
    change=SimpleNamespace(tool_call={'id':'change-test','name':'write_file','args':{'file_path':'/check.py','content':'print("changed criterion")'}})
    assert gateway.evaluate(change.tool_call)[1]=='deny'
    plan=store.plan(task['id'])
    revised=store.save_plan(task['id'],steps=plan['steps'],scope=['check.py'],checks=plan['checks'],expected_revision=plan['revision'])
    store.decide_plan(task['id'],expected_revision=revised['revision'],approve=True)
    assert gateway.requires_review(change)  # auto never silently approves check edits
    review=gateway.approvals.list(task['id'])[-1]
    assert review['request']['review']['reason']=='check_change'
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    async def write(request):
        (root/'check.py').write_text(request.tool_call['args']['content'],encoding='utf8')
        return ToolMessage(content='written',tool_call_id=request.tool_call['id'])
    await gateway.dispatch(change,write)
    target=CheckTarget('working_copy',manifest_hash(root),'profile-v1','fixture')
    CheckResults(store).record(task['id'],target=target,check_id='python check.py',outcome='passed',command='python check.py')
    assert current_quality(store,task['id'],root,'fixture')['quality_status']=='not_verified'
    current=SimpleNamespace(tool_call={'id':'review-modified-test','name':'execute','args':{'command':'python check.py'}})
    assert gateway.requires_review(current)
    review=gateway.approvals.list(task['id'])[-1]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    await gateway.dispatch(current,check)
    assert current_quality(store,task['id'],root,'fixture')['quality_status']=='verified_snapshot'


def test_deleted_test_changes_verifier_fingerprint_and_cannot_be_certified_by_old_plan(setup):
    from harness.worktrees.snapshot import build,write_manifest
    from harness.verification.observe import current_quality
    gateway,task,root,_=setup
    tests=root/'tests';tests.mkdir();test=tests/'test_app.py';test.write_text('assert False',encoding='utf8')
    write_manifest(build(root),destination=root)
    call={'id':'before','name':'execute','args':{'command':'python check.py'}}
    before=gateway.evaluate(call)[0].fingerprint()
    test.unlink()
    context,access=gateway.evaluate(call)
    assert context.fingerprint()!=before and access=='deny'
    assert current_quality(gateway.store,task['id'],root,'fixture')['quality_status']!='verified_snapshot'


def test_removing_required_commands_invalidates_the_approved_profile_until_new_plan_review(setup):
    from server.errors import ApiError
    from harness.verification.observe import current_quality
    from harness.hooks.plan import PlanGate
    gateway,task,root,profile=setup;store=gateway.store
    plan=store.plan(task['id']);assert plan['profile_hash']=='profile-v1'
    changed={**profile,'profile_hash':'profile-v2','commands':[]}
    with store.db.write() as db:db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps(changed),task['workspace_id']))
    assert gateway.evaluate({'name':'execute','args':{'command':'echo fixture'}})[1]=='deny'
    quality=current_quality(store,task['id'],root,'fixture')
    assert quality['quality_status']=='not_verified' and quality['profile_changed']
    with pytest.raises(ApiError) as stale:store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    assert stale.value.code=='selection_stale'
    store.clear_plan_approval(task['id'])
    PlanGate(store,task['id']).record_todos([{'content':'review changed verification profile','status':'pending'}])
    revised=store.plan(task['id'])
    assert revised['profile_hash']=='profile-v2' and revised['approved_revision'] is None and revised['revision']>plan['revision']
    store.decide_plan(task['id'],expected_revision=revised['revision'],approve=True)
    assert gateway.evaluate({'name':'execute','args':{'command':'echo fixture'}})[1]=='allow'


@pytest.mark.parametrize('command',['uv sync --frozen','python -m pip install pytest','npm ci','pnpm add package','poetry install'])
def test_installer_is_not_auto_authorized_by_model_flags(setup,command):
    gateway,_,_,_=setup
    _,access=gateway.evaluate({'id':'install','name':'execute','args':{'command':command,'installation':False}})
    assert access=='ask'


def test_profile_hash_and_config_bytes_are_bound_to_command(setup):
    gateway,task,root,profile=setup
    call={'name':'execute','args':{'command':'echo fixture'}}
    first=gateway.evaluate(call)[0].fingerprint()
    (root/'package.json').write_text('{"scripts":{"test":"example"}}',encoding='utf8')
    assert gateway.evaluate(call)[0].fingerprint()!=first
    first=gateway.evaluate(call)[0].fingerprint()
    profile['profile_hash']='profile-v2'
    ws=gateway.store.task(task['id'])['workspace_id']
    with gateway.store.db.write() as db:db.execute('UPDATE workspaces SET profile=? WHERE id=?',(json.dumps(profile),ws))
    assert gateway.evaluate(call)[0].fingerprint()!=first


def test_excluded_or_external_script_source_cannot_be_fingerprinted(setup):
    _,_,root,profile=setup
    with pytest.raises(ValueError):command_details({'name':'execute','args':{'command':'python ../external.py'}},profile,root)
