"""Real SQLite approval receipts; no runtime/model or host execution."""
from dataclasses import replace
import time

import pytest

from harness.policy import ActionContext
from server.errors import ApiError
from server.storage import Store, Database, migrate
from server.storage.approvals import ApprovalStore


@pytest.fixture
def setup(tmp_path):
    db=Database(tmp_path/'product.db');migrate(db);store=Store(db)
    ws=store.upsert_workspace(str(tmp_path/'project'))
    task=store.create_task(workspace_id=ws['id'],prompt='fixture',mode='grant')
    plan=store.save_plan(task['id'],steps=[{'title':'run'}],scope=[],checks=[])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    context=ActionContext('execute',{'command':'python -m pytest'},'/workspace','/bin/sh','image:one','offline',plan['revision'])
    return store,task,context


def decide(service,task,row,**changes):
    data=dict(fingerprint=row['action_hash'],revision=row['revision'],decision='approve')
    data.update(changes)
    return service.decide(task['id'],row['id'],**data)


def test_approval_survives_restart_and_double_click_has_one_receipt(setup):
    store,task,context=setup
    service=ApprovalStore(store)
    row=service.request(task['id'],'call:one',context)
    assert service.request(task['id'],'call:one',context)['id']==row['id']
    reopened=ApprovalStore(Store(Database(store.db.path)))
    receipt=decide(reopened,task,row,grant=True)
    assert receipt['decision']=='approve'
    assert decide(reopened,task,row)['id']==receipt['id']
    assert reopened.has_grant(task['id'],row['action_id'],context.fingerprint())
    with store.db.read() as db:
        assert db.execute('SELECT COUNT(*) FROM grants').fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM events WHERE type='approval_decided'").fetchone()[0]==1
    with pytest.raises(ApiError):decide(reopened,task,row,decision='reject')
    reopened.revoke(task['id'])
    assert not reopened.has_grant(task['id'],row['action_id'],context.fingerprint())


@pytest.mark.parametrize('change', ['hash','revision','plan','unknown','other_task'])
def test_stale_or_foreign_decisions_cannot_authorize(setup,change):
    store,task,context=setup;service=ApprovalStore(store)
    row=service.request(task['id'],'call:one',context)
    options={}
    if change=='hash':options['fingerprint']='forged'
    elif change=='revision':options['revision']=100
    elif change=='plan':store.save_plan(task['id'],steps=[{'title':'changed'}])
    elif change=='unknown':store.set_action_state(row['action_id'],'unknown')
    else:task=store.create_task(workspace_id=task['workspace_id'],prompt='other')
    with pytest.raises(ApiError):decide(service,task,row,**options)
    assert not service.has_grant(task['id'],row['action_id'],context.fingerprint())


def test_grant_expires_and_never_transfers_to_another_task(setup):
    store,task,context=setup;service=ApprovalStore(store)
    row=service.request(task['id'],'call:one',context)
    decide(service,task,row,grant=True,expires_at=time.time()+100)
    other=store.create_task(workspace_id=task['workspace_id'],prompt='other',mode='grant')
    assert not service.has_grant(other['id'],row['action_id'],context.fingerprint())
    with store.db.write() as db:db.execute('UPDATE grants SET expiry=0')
    assert not service.has_grant(task['id'],row['action_id'],context.fingerprint())


def test_changed_arguments_require_a_new_invocation_and_new_review(setup):
    store,task,context=setup;service=ApprovalStore(store)
    original=service.request(task['id'],'call:one',context)
    changed=replace(context,args={'command':'python -m pytest -x'})
    with pytest.raises(ApiError):service.request(task['id'],'call:one',changed)
    replacement=service.request(task['id'],'call:edited',changed)
    assert replacement['id']!=original['id']
    assert replacement['state']=='pending'
    assert replacement['action_id']!=original['action_id']


def test_same_operation_links_new_segment_without_replaying_unknown(setup):
    store,task,context=setup;service=ApprovalStore(store)
    row=service.request(task['id'],'call:one',context,origin_run_id=task['runs'][0]['id'])
    store.set_action_state(row['action_id'],'unknown')
    run=store.start_segment(task['id'])
    replay=store.ensure_action(task['id'],'call:one',context.fingerprint(),origin_run_id=run['id'])
    assert replay['operation_id']==row['action_id'] and replay['state']=='unknown'
    with store.db.read() as db:
        assert db.execute('SELECT COUNT(*) FROM action_run_links WHERE operation_id=?',(row['action_id'],)).fetchone()[0]==2
    with pytest.raises(ApiError):service.request(task['id'],'call:one',context)
