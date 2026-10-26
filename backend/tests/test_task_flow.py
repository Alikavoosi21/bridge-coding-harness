"""T008: the durable conversation, steering, proposals, continuation and SSE.

These tests stay on the product side of the line. They do not call a model:
the controller methods are replaced at the seam where a model would run, so a
test proves the route and the store did their work without pretending a model
answered. The event bridge is tested separately with real runtime events.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage

from harness.events import Event
from harness.hooks.steering import SteeringHook, acknowledge_steering
from harness.task_controller import TaskController
from harness.task_events import TaskEventRecorder
from server.app import create_app
from server.storage import Database, Store, migrate


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    database = Database()
    migrate(database)
    return Store(database)


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "api-home"))
    monkeypatch.delenv("HARNESS_TOKEN", raising=False)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        client.workspace_path = str(tmp_path / "ws")  # type: ignore[attr-defined]
        yield client


async def _open(api) -> None:
    response = await api.post("/workspace", json={"path": api.workspace_path})
    assert response.status_code == 200, response.text


async def _task(api, **body) -> dict:
    await _open(api)
    created = await api.post("/tasks", json={"prompt": "گزارش فروش را بنویس", **body})
    assert created.status_code == 202, created.text
    return created.json()["task"]


# ── conversation and steering ────────────────────────────────────────────────


def test_phase_requests_preserve_original_goal_and_reference_files(store):
    from harness.config import ModelSpec

    workspace = store.upsert_workspace("C:/work/request-context", "Context")
    task = store.create_task(workspace_id=workspace["id"], prompt="Fix the sales total", references=["src/sales.ts"])
    controller = TaskController(None, store, model_resolver=lambda: ModelSpec("demo", "Demo", "demo://", "demo"))
    for phase, instruction in [("plan", "Inspect and propose"), ("execute", "Execute approved steps")]:
        request = controller._request(task, instruction, mode="read_only", phase=phase)
        assert "Fix the sales total" in request.prompt
        assert "src/sales.ts" in request.prompt
        assert instruction in request.prompt
    assert store.messages(task["id"])[0]["references"] == ["src/sales.ts"]


def test_execution_context_supplies_exact_required_checks_only(store):
    import json
    from harness.config import ModelSpec

    profile={'commands':[{'command':'python check.py','required':True},{'command':'npm run lint','required':False}]}
    workspace=store.upsert_workspace('C:/work/check-context',profile=json.dumps(profile))
    task=store.create_task(workspace_id=workspace['id'],prompt='Fix the code')
    controller=TaskController(None,store,model_resolver=lambda:ModelSpec('demo','Demo','demo://','demo'))
    execution=controller._request(task,'Execute approved steps',mode='auto',phase='execute')
    assert 'cwd=/workspace' in execution.prompt and 'python check.py' in execution.prompt
    assert 'npm run lint' not in execution.prompt
    assert 'Required checks' not in controller._request(task,'Propose',mode='read_only',phase='plan').prompt


async def test_a_message_is_durable_and_waits_for_the_next_model_turn(api):
    task = await _task(api)

    sent = await api.post(f"/tasks/{task['id']}/messages", json={"text": "فقط جمع ستون فروش را بیاور"})
    assert sent.status_code == 200, sent.text
    message = sent.json()["message"]
    assert message["role"] == "user" and message["delivered_at"] is None

    snapshot = (await api.get(f"/tasks/{task['id']}")).json()
    assert [item["id"] for item in snapshot["messages"]][-1] == message["id"]
    assert snapshot["messages"][-1]["parts"][0]["text"] == "فقط جمع ستون فروش را بیاور"

    pending = Store().pending_messages(task["id"])
    assert [item["id"] for item in pending] == [message["id"]]


def test_the_steering_hook_delivers_once_and_records_the_receipt(store):
    workspace = store.upsert_workspace("C:/work/steering", "Steering")
    task = store.create_task(workspace_id=workspace["id"], prompt="first")
    store.append_message(task["id"], text="also include the total", references=["/report.md"])

    hook = SteeringHook(store, task["id"])
    result = hook.before_model(None, None)

    assert result is not None
    injected = result["messages"][0]
    assert isinstance(injected, HumanMessage)
    assert "also include the total" in str(injected.content)
    assert "/report.md" in str(injected.content)
    assert store.pending_messages(task["id"]), "an uncheckpointed update is still pending"
    replay = hook.before_model({}, None)
    assert replay["messages"][0].id == injected.id
    acknowledge_steering(store, task["id"], {"messages": [injected]})
    assert store.pending_messages(task["id"]) == []
    assert hook.before_model({"messages": [injected]}, None) is None


async def test_a_message_at_a_stale_task_revision_is_refused(api):
    task = await _task(api)
    stale = await api.post(
        f"/tasks/{task['id']}/messages",
        json={"text": "x", "expected_revision": task["revision"] + 99},
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "selection_stale"


# ── proposals ────────────────────────────────────────────────────────────────


async def test_a_correction_is_saved_before_the_read_only_proposal_starts(api, monkeypatch):
    seen: list[str | None] = []

    def fake_propose(self, task_id: str, instruction: str | None = None):
        seen.append(instruction)
        store = Store()
        store.set_task_status(task_id, "planning", reason="plan_proposal")
        store.save_plan(
            task_id,
            steps=[{"title": "بازبینی داده", "status": "pending"}],
            scope=["sales.csv"],
            checks=["the report opens"],
        )
        store.set_task_status(task_id, "awaiting_plan", reason="plan_proposed")
        return store.task(task_id)

    monkeypatch.setattr(TaskController, "propose", fake_propose)
    task = await _task(api)

    proposed = await api.post(
        f"/tasks/{task['id']}/plan-proposals",
        json={"instruction": "فقط ستون فروش را بررسی کن", "expected_revision":task['revision'],"idempotency_key":"correction-retry"},
    )
    assert proposed.status_code == 202, proposed.text
    assert seen == ["فقط ستون فروش را بررسی کن"]

    body = proposed.json()
    assert body["plan"]["revision"] == 1
    assert body["plan"]["steps"][0]["title"] == "بازبینی داده"
    assert body["message"]["parts"][0]["text"] == "فقط ستون فروش را بررسی کن"

    snapshot = (await api.get(f"/tasks/{task['id']}")).json()
    assert snapshot["status"] == "awaiting_plan"
    assert snapshot["messages"][-1]["parts"][0]["text"] == "فقط ستون فروش را بررسی کن"
    replay=await api.post(f"/tasks/{task['id']}/plan-proposals",json={"instruction":"فقط ستون فروش را بررسی کن","expected_revision":task['revision'],"idempotency_key":"correction-retry"})
    assert replay.status_code==202 and replay.headers['Idempotent-Replayed']=='true'
    assert seen==["فقط ستون فروش را بررسی کن"]
    assert len((await api.get(f"/tasks/{task['id']}")).json()['messages'])==2


async def test_a_proposal_for_a_cancelled_task_does_not_create_a_message(api):
    task = await _task(api)
    Store().set_task_status(task["id"], "cancelled", outcome="stopped_by_user")

    refused = await api.post(f"/tasks/{task['id']}/plan-proposals", json={"instruction": "again"})
    assert refused.status_code == 409
    assert Store().pending_messages(task["id"]) == []


# ── continuation ─────────────────────────────────────────────────────────────


async def test_continuation_is_a_separate_action_and_rechecks_the_plan_revision(api, monkeypatch):
    calls: list[str] = []

    def fake_execute(self, task_id: str):
        calls.append(task_id)
        return Store().task(task_id)

    monkeypatch.setattr(TaskController, "execute", fake_execute)
    task = await _task(api)
    plan = Store().save_plan(
        task["id"],
        steps=[{"title": "گام", "status": "pending"}],
        scope=["report.md"],
        checks=[],
    )
    Store().decide_plan(task["id"], expected_revision=plan["revision"], approve=True)

    stale = await api.post(f"/tasks/{task['id']}/continuations", json={"expected_plan_revision": plan["revision"] + 1})
    assert stale.status_code == 409 and stale.json()["code"] == "selection_stale"
    assert calls == []

    started = await api.post(f"/tasks/{task['id']}/continuations", json={"expected_plan_revision": plan["revision"]})
    assert started.status_code == 202, started.text
    assert calls == [task["id"]]
    assert started.json()["plan"]["approved_revision"] == plan["revision"]


# ── references stay inside the project ───────────────────────────────────────


@pytest.mark.parametrize('endpoint', ['plan-proposals', 'continuations'])
async def test_routes_launch_on_the_real_app_event_loop(api, monkeypatch, endpoint):
    """Keep the real controller/manager; only replace the runtime stream."""
    task = await _task(api)
    store = Store()
    plan = store.save_plan(task['id'], steps=[{'title': 'read'}], scope=[], checks=[])
    if endpoint == 'continuations':
        store.decide_plan(task['id'], expected_revision=plan['revision'], approve=True)
    manager = api._transport.app.state.harness.manager
    launched = []

    async def runtime(request, *, plan_gate):
        launched.append(request.thread_id)
        yield Event('run_finished', request.thread_id, {'stop_reason': 'completed'})

    monkeypatch.setattr(manager.runner, 'start', runtime)
    response = await api.post(f"/tasks/{task['id']}/{endpoint}", json={})
    assert response.status_code == 202, response.text
    await manager.wait(task['thread_id'])
    assert launched == [task['thread_id']]
    assert store.task(task['id'])['status'] != 'planning'


async def test_a_reference_inside_the_project_is_kept_and_an_outside_path_is_refused(api, tmp_path):
    await _open(api)
    project = Path(api.workspace_path)
    project.mkdir(parents=True, exist_ok=True)
    (project / "notes.md").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    created = await api.post("/tasks", json={"prompt": "از این فایل استفاده کن", "references": ["notes.md"]})
    assert created.status_code == 202, created.text
    task = created.json()["task"]
    assert Store().messages(task["id"])[0]["references"] == ["/notes.md"]

    refused = await api.post("/tasks", json={"prompt": "بیرون", "references": [str(outside)]})
    assert refused.status_code == 422
    assert refused.json()["details"]["reason"] == "outside_workspace"


# ── SSE and the runtime event bridge ─────────────────────────────────────────


async def test_sse_replays_the_journal_then_closes_for_a_stable_task(api):
    task = await _task(api)
    store = Store()
    store.record_event(
        task["id"],
        "message_started",
        {"message_id": "msg_test", "part_id": "msg_test:text", "message_index": 1},
        run_id=task["runs"][0]["id"],
    )
    store.record_event(
        task["id"],
        "text_delta",
        {"message_id": "msg_test", "part_id": "msg_test:text", "offset": 0, "delta": "سلام"},
        run_id=task["runs"][0]["id"],
    )
    store.record_event(
        task["id"],
        "message_finished",
        {"message_id": "msg_test", "part_id": "msg_test:text", "finish_reason": "stop"},
        run_id=task["runs"][0]["id"],
    )
    store.set_task_status(task["id"], "awaiting_plan", reason="plan_proposed")

    response = await api.get(
        f"/tasks/{task['id']}/events",
        params={"after_seq": 2},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: message_started" in text
    assert "event: text_delta" in text
    assert "event: message_finished" in text
    assert "event: done" in text and "data: [DONE]" in text
    assert text.index("message_started") < text.index("text_delta") < text.index("message_finished")

    json_page = (await api.get(f"/tasks/{task['id']}/events", params={"after_seq": 2})).json()
    assert [event["type"] for event in json_page["items"][:3]] == ["message_started", "text_delta", "message_finished"]


def test_the_event_bridge_uses_canonical_names_offsets_and_learning_ids(store):
    workspace = store.upsert_workspace("C:/work/bridge", "Bridge")
    task = store.create_task(workspace_id=workspace["id"], prompt="bridge")
    recorder = TaskEventRecorder(store, task["id"], task["runs"][0]["id"])

    recorder.record(Event("text", "thread", {"text": "ab"}))
    recorder.record(Event("text", "thread", {"text": "س"}))
    recorder.record(Event("tool_started", "thread", {"tool": "read_file", "call_id": "call_1", "args": {"file_path": "/a.md"}}))
    recorder.record(Event("tool_finished", "thread", {"tool": "read_file", "call_id": "call_1", "ok": True, "output": "ok"}))
    recorder.record(Event("file_changed", "thread", {"path": "/a.md", "tool": "write_file"}))
    recorder.record(Event("approval_required", "thread", {"actions": [{"tool": "write_file", "args": {"file_path": "/a.md"}}]}))
    recorder.record(Event("verification", "thread", {"round": 1, "problems": ["the test failed"]}))
    recorder.record(Event("run_finished", "thread", {"stop_reason": "completed"}))
    recorder.finish("completed")

    events = store.events(task["id"], after_seq=2)["items"]
    assert [event["type"] for event in events] == [
        "message_started",
        "text_delta",
        "text_delta",
        "action_started",
        "action_finished",
        "file_changed",
        "approval_required",
        "repair_started",
        "message_finished",
    ]
    assert events[1]["payload"]["offset"] == 0
    assert events[2]["payload"]["offset"] == 2, "offsets count code points, not UTF-8 bytes"
    assert events[3]["payload"]["operation_id"] == "op_call_1"
    assert events[3]["payload"]["operation_id"] == events[4]["payload"]["operation_id"]
    assert events[5]["payload"]["file_id"].startswith("file_")
    assert events[8]["payload"]["finish_reason"] == "stop"


def test_steering_survives_failure_before_checkpoint_and_ack_after_restart(store, tmp_path):
    from langgraph.graph import StateGraph, MessagesState, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver
    workspace = store.upsert_workspace(str(tmp_path / "steering-project"), "Steering")
    task = store.create_task(workspace_id=workspace["id"], prompt="first")
    message = store.append_message(task["id"], text="keep this instruction")
    hook = SteeringHook(store, task["id"])
    config = {"configurable": {"thread_id": task["thread_id"]}}
    fail = [True]
    def inject(state):
        update = hook.before_model(state, None)
        if fail[0]:
            fail[0] = False
            raise RuntimeError("crash before middleware update checkpoint")
        return update or {}
    builder = StateGraph(MessagesState)
    builder.add_node("steering", inject)
    builder.add_edge(START, "steering")
    builder.add_edge("steering", END)
    db = str(tmp_path / "checkpoints.db")
    with SqliteSaver.from_conn_string(db) as saver:
        graph = builder.compile(checkpointer=saver)
        with pytest.raises(RuntimeError, match="crash before"):
            graph.invoke({"messages": []}, config, durability="sync")
        assert store.pending_messages(task["id"])
        graph.invoke(None, config, durability="sync")
        assert store.pending_messages(task["id"]), "checkpoint commit alone does not lie about an earlier receipt"
    with SqliteSaver.from_conn_string(db) as saver:
        graph = builder.compile(checkpointer=saver)
        saved = graph.get_state(config)
        assert [m.id for m in saved.values["messages"]] == [message["id"]]
        assert hook.before_model(saved.values, None) is None
        assert not store.pending_messages(task["id"])
        assert len(graph.get_state(config).values["messages"]) == 1
