from harness.hooks.plan import PlanGate
from server.storage import Store,Database,migrate


def test_progress_typography_preserves_approval_but_a_changed_step_does_not(tmp_path):
    db=Database(tmp_path/'state.db');migrate(db);store=Store(db)
    ws=store.upsert_workspace(str(tmp_path/'project'))
    task=store.create_task(workspace_id=ws['id'],prompt='fixture')
    plan=store.save_plan(task['id'],steps=[{'title':'گزارش بررسیها','status':'pending'}])
    store.decide_plan(task['id'],expected_revision=plan['revision'],approve=True)
    gate=PlanGate(store,task['id'])
    gate.record_todos([{'content':'گزارش بررسی\u200cها','status':'completed'}])
    updated=store.plan(task['id'])
    assert updated['approved_revision']==updated['revision']==plan['revision']
    assert updated['steps'][0]['title']=='گزارش بررسیها' and updated['steps'][0]['status']=='completed'
    gate.record_todos([{'content':'پاک کردن پروژه','status':'pending'}])
    assert store.plan(task['id'])['approved_revision'] is None
