"""Real framework interrupts and fixture effects; no Docker/host-shell proof."""
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from harness.demo_model import ScriptedChatModel, call
from harness.gateway import ToolGateway
from harness.hooks.permission import PermissionHook
from harness.permissions import build_policy
from server.storage import Store, Database, migrate


@pytest.fixture
def setup(tmp_path):
    db=Database(tmp_path/'product.db');migrate(db);store=Store(db)
    workspace=store.upsert_workspace(str(tmp_path/'workspace'))
    task=store.create_task(workspace_id=workspace['id'],prompt='fixture')
    plan=store.save_plan(task['id'],steps=[{'title':'write'}])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    rules=tmp_path/'rules.yaml';rules.write_text('files: []\ntools: {}',encoding='utf8')
    gateway=ToolGateway(store,task['id'],rules,runtime_available=True,runtime_id='fake:fixture-only')
    return store,task,gateway,tmp_path


@pytest.mark.parametrize('decision',['approve','reject','edit'])
async def test_framework_pause_restart_and_human_decision_gate_real_fixture_effect(setup,decision):
    store,task,gateway,root=setup
    target=root/'effect.txt'

    @tool('write_file')
    def write_file(file_path: str, content: str) -> str:
        """Write a string to the test fixture only."""
        target.write_text(content,encoding='utf8')
        return 'written'

    model=ScriptedChatModel(script=[AIMessage(content='',tool_calls=[call('write_file',file_path='/effect.txt',content='accepted')]),AIMessage(content='done')])
    def agent(saver):
        return create_agent(model,tools=[write_file],checkpointer=saver,middleware=[PermissionHook(build_policy({'files':[],'tools':{}},'ask'),gateway),HumanInTheLoopMiddleware(interrupt_on=gateway.interrupt_on(['write_file']))])
    config={'configurable':{'thread_id':task['thread_id']}}
    async with AsyncSqliteSaver.from_conn_string(str(root/'checkpoint.db')) as saver:
        result=await agent(saver).ainvoke({'messages':[HumanMessage(content='write fixture')]},config,durability='sync')
        assert result.get('__interrupt__')
    assert not target.exists()
    review=gateway.approvals.list(task['id'])[0]
    if decision=='edit':
        from server.errors import ApiError
        context,_=gateway.evaluate({'name':'write_file','args':{'file_path':'/effect.txt','content':'edited by human'}})
        original=review
        review=gateway.approvals.edit(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],context=context)
        assert review['id']!=original['id'] and review['state']=='pending'
        with pytest.raises(ApiError):gateway.approvals.decide(task['id'],original['id'],fingerprint=original['action_hash'],revision=original['revision'],decision='approve')
        async with AsyncSqliteSaver.from_conn_string(str(root/'checkpoint.db')) as saver:
            with pytest.raises(ValueError,match='Number of human decisions'):
                await agent(saver).ainvoke(Command(resume={'decisions':[]}),config,durability='sync')
        assert not target.exists()
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=review['revision'],decision='approve' if decision=='edit' else decision)
    # Rebuild the graph and open the checkpoint again, like a process restart.
    async with AsyncSqliteSaver.from_conn_string(str(root/'checkpoint.db')) as saver:
        result=await agent(saver).ainvoke(Command(resume={'decisions':[]}),config,durability='sync')
        assert not result.get('__interrupt__')
    assert target.exists() == (decision!='reject')
    if target.exists():assert target.read_text(encoding='utf8')==('edited by human' if decision=='edit' else 'accepted')


async def test_one_effect_under_double_dispatch_and_unknown_is_not_replayed(setup):
    _,task,gateway,root=setup
    request=SimpleNamespace(tool_call={'id':'stable','name':'write_file','args':{'file_path':'/effect.txt','content':'one'}})
    assert gateway.requires_review(request)
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    effects=[]
    async def effect(request):
        effects.append(1)
        (root/'effect.txt').write_text('one',encoding='utf8')
        return ToolMessage(content='done',tool_call_id=request.tool_call['id'])
    first=await gateway.dispatch(request,effect)
    second=await gateway.dispatch(request,effect)
    assert effects==[1] and first.content==second.content=='done'
    request=SimpleNamespace(tool_call={**request.tool_call,'id':'unknown'})
    gateway.requires_review(request)
    review=gateway.approvals.list(task['id'])[-1]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    async def crash(_):
        effects.append(2)
        raise RuntimeError('effect occurred but result lost')
    with pytest.raises(RuntimeError):await gateway.dispatch(request,crash)
    refused=await gateway.dispatch(request,crash)
    assert refused.status=='error' and effects==[1,2]


async def test_rules_are_revalidated_after_approval_before_effect(setup):
    _,task,gateway,_=setup
    request=SimpleNamespace(tool_call={'id':'stable','name':'write_file','args':{'file_path':'/effect.txt','content':'one'}})
    gateway.requires_review(request)
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve')
    gateway.rules_file.write_text("files:\n - paths: ['/**']\n   operations: [write]\n   access: deny\ntools: {}",encoding='utf8')
    async def forbidden(_):raise AssertionError('must not dispatch')
    assert (await gateway.dispatch(request,forbidden)).status=='error'


async def test_task_grant_allows_a_new_invocation_but_not_changed_settings_or_after_revoke(setup):
    store,task,gateway,_=setup
    with store.db.write() as db:db.execute("UPDATE tasks SET mode='grant' WHERE id=?",(task['id'],))
    original={'id':'one','name':'write_file','args':{'file_path':'/effect.txt','content':'one'}}
    assert gateway.requires_review(SimpleNamespace(tool_call=original))
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve',grant=True)
    effects=[]
    async def effect(request):
        effects.append(request.tool_call['id'])
        return ToolMessage(content='done',tool_call_id=request.tool_call['id'])
    await gateway.dispatch(SimpleNamespace(tool_call=original),effect)
    second={**original,'id':'two'}
    assert not gateway.requires_review(SimpleNamespace(tool_call=second))
    await gateway.dispatch(SimpleNamespace(tool_call=second),effect)
    assert effects==['one','two']
    assert store.action_by_invocation(task['id'],'tool:one')['operation_id']!=store.action_by_invocation(task['id'],'tool:two')['operation_id']
    changed={**original,'id':'three','args':{**original['args'],'content':'changed'}}
    assert gateway.requires_review(SimpleNamespace(tool_call=changed))
    gateway.approvals.revoke(task['id'])
    assert gateway.requires_review(SimpleNamespace(tool_call={**original,'id':'four'}))


def test_event_bridge_uses_the_gateway_identity_and_does_not_invent_another_approval(setup):
    from harness.task_events import TaskEventRecorder
    from harness.events import Event
    store,task,gateway,_=setup
    request=SimpleNamespace(tool_call={'id':'stable','name':'write_file','args':{'file_path':'/a','content':'one'}})
    gateway.requires_review(request)
    review=gateway.approvals.list(task['id'])[0]
    recorder=TaskEventRecorder(store,task['id'],task['runs'][0]['id'])
    recorder.record(Event('approval_required',task['thread_id'],{'actions':[{'tool':'write_file','args':request.tool_call['args']}]}))
    recorder.record(Event('tool_started',task['thread_id'],{'tool':'write_file','call_id':'stable','args':request.tool_call['args']}))
    events=store.events(task['id'])['items']
    assert len([event for event in events if event['type']=='approval_required'])==1
    assert [event for event in events if event['type']=='action_started'][-1]['payload']['operation_id']==review['action_id']


async def test_mode_downgrade_revokes_and_cancels_waiting_actions_without_stopping_running_action(setup):
    store,task,gateway,_=setup
    with store.db.write() as db:db.execute("UPDATE tasks SET mode='grant' WHERE id=?",(task['id'],))
    original={'id':'one','name':'write_file','args':{'file_path':'/a','content':'one'}}
    gateway.requires_review(SimpleNamespace(tool_call=original))
    review=gateway.approvals.list(task['id'])[0]
    gateway.approvals.decide(task['id'],review['id'],fingerprint=review['action_hash'],revision=1,decision='approve',grant=True)
    running=store.ensure_action(task['id'],'running','hash')
    store.set_action_state(running['operation_id'],'running')
    current=store.task(task['id'])
    result=gateway.approvals.change_access(task['id'],expected_revision=current['revision'],mode='ask')
    assert result['mode']=='ask'
    assert store.action(running['operation_id'])['state']=='running'
    assert not gateway.approvals.matching_grant(task['id'],review['action_hash'])
    async def forbidden(_):raise AssertionError('cancelled approval must not execute')
    assert (await gateway.dispatch(SimpleNamespace(tool_call=original),forbidden)).status=='error'


@pytest.mark.parametrize('wrong_operation',[False,True,'missing'])
async def test_terminal_receipt_is_durable_bounded_and_bound_to_operation(setup,wrong_operation):
    from harness.runtime.docker import ExecResult
    store,task,gateway,_=setup
    with store.db.write() as db:
        db.execute("UPDATE tasks SET mode='auto' WHERE id=?",(task['id'],))
    gateway.backend=SimpleNamespace(last_receipt=None)
    call={'id':'terminal','name':'execute','args':{'command':'printf fixture'}}
    async def effect(request):
        operation=store.action_by_invocation(task['id'],'tool:terminal')['operation_id']
        gateway.backend.last_receipt=ExecResult('exec-fixture',0,'س'*40000,operation_id='other' if wrong_operation else operation)
        if wrong_operation=='missing':gateway.backend.last_receipt=None
        return ToolMessage(content='fixture result',tool_call_id=request.tool_call['id'])
    await gateway.dispatch(SimpleNamespace(tool_call=call),effect)
    event=[e for e in store.events(task['id'])['items'] if e['type']=='action_finished'][-1]
    if wrong_operation:
        assert event['payload']['state']=='unknown' and 'receipt' not in event['payload']
    else:
        receipt=event['payload']['receipt']
        assert receipt['operation_id']==event['payload']['operation_id']
        assert receipt['exit_code']==0 and receipt['cwd']=='/workspace'
        assert receipt['truncated'] and len(receipt['output'].encode('utf-8'))==65536
