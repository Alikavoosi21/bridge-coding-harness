"""T006: a plan is revisioned, approval is exact, and the gate reads storage.

The gate is deliberately tested through a real `Store`, not a stub: the
invariant under test is that plan state lives in product storage, so a restart
or a second tab sees the same approval. The controller tests use the real store
with a stub manager, which is enough to prove that an unapproved plan never
opens a segment.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from harness import Runner
from harness.demo_model import call
from harness.hooks.plan import PlanGate, PlanGateHook
from harness.task_controller import TaskController, TaskControllerError
from server.errors import ApiError
from server.storage import Database, Store, migrate

from .conftest import DEMO, collect, finished, request


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    database = Database()
    migrate(database)
    return Store(database)


def _task(store: Store) -> dict:
    workspace = store.upsert_workspace("C:/work/plans", "Plans")
    return store.create_task(workspace_id=workspace["id"], prompt="گزارش را بنویس")


def _steps(statuses: tuple[str, ...] = ("pending", "pending"), titles: tuple[str, ...] | None = None) -> list[dict]:
    labels = titles or tuple(f"گام {index}" for index in range(1, len(statuses) + 1))
    return [
        {"id": f"step-{index}", "title": title, "status": status}
        for index, (title, status) in enumerate(zip(labels, statuses), start=1)
    ]


def _plan(store: Store, task: dict, **overrides) -> dict:
    titles = overrides.pop("titles", None)
    return store.save_plan(
        task["id"],
        steps=overrides.pop("steps", _steps(titles=titles) if titles else _steps()),
        scope=overrides.pop("scope", ["report.md"]),
        checks=overrides.pop("checks", ["the report opens"]),
        **overrides,
    )


def _grant(store: Store, task: dict) -> str:
    grant_id = "grant-1"
    now = time.time()
    with store.db.write() as connection:
        connection.execute(
            "INSERT INTO grants (id, task_id, capability, fingerprint, expiry, revoked_at, created_at) VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (grant_id, task["id"], "write", "fingerprint", None, now),
        )
    return grant_id


# ── revisioning ──────────────────────────────────────────────────────────────


def test_a_plan_edit_at_an_old_revision_is_refused(store):
    task = _task(store)
    _plan(store, task)

    with pytest.raises(ApiError) as stale:
        store.save_plan(task["id"], steps=_steps(("completed", "pending")), expected_revision=0)
    assert stale.value.code == "selection_stale" and stale.value.current_revision == 1


def test_a_material_edit_clears_approval_and_revokes_grants(store):
    task = _task(store)
    plan = _plan(store, task)
    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)
    grant_id = _grant(store, task)

    changed = _plan(store, task, titles=("گام تازه", "گام ۲"))
    assert changed["revision"] == plan["revision"] + 1
    assert changed["approved_revision"] is None

    with store.db.read() as connection:
        revoked = connection.execute("SELECT revoked_at FROM grants WHERE id = ?", (grant_id,)).fetchone()["revoked_at"]
    assert revoked is not None, "a changed plan cannot keep a permission the user gave to the old one"


def test_a_progress_update_keeps_the_revision_and_the_approval(store):
    task = _task(store)
    plan = _plan(store, task, steps=_steps(("pending", "pending")))
    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)

    progress = _plan(store, task, steps=_steps(("completed", "pending")))
    assert progress["revision"] == plan["revision"]
    assert progress["approved_revision"] == plan["revision"]
    assert progress["checks"] == plan["checks"] and progress["scope"] == plan["scope"]


def test_approving_a_revision_that_is_no_longer_current_is_refused(store):
    task = _task(store)
    first = _plan(store, task)
    second = _plan(store, task, titles=("گام تازه", "گام ۲"))

    with pytest.raises(ApiError) as stale:
        store.decide_plan(task["id"], expected_revision=first["revision"], approve=True)
    assert stale.value.code == "selection_stale" and stale.value.current_revision == second["revision"]
    assert store.plan(task["id"])["approved_revision"] is None


def test_approval_does_not_start_execution(store):
    task = _task(store)
    plan = _plan(store, task)
    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)

    current = store.task(task["id"])
    assert current["status"] == "awaiting_plan"
    assert len(current["runs"]) == 1, "the decision is recorded, not acted on"


# ── the gate ─────────────────────────────────────────────────────────────────


def _request(name: str, **args) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": name, "args": args, "id": f"call_{name}"})


async def test_the_gate_denies_a_write_before_the_handler_runs(store):
    task = _task(store)
    called: list[str] = []

    async def handler(_request):
        called.append("ran")
        return "ran"

    hook = PlanGateHook(PlanGate(store, task["id"]))
    result = await hook.awrap_tool_call(_request("write_file", file_path="/x.md"), handler)

    assert isinstance(result, ToolMessage) and result.status == "error"
    assert called == [], "a denied write never reaches the tool"
    assert "no plan" in str(result.content).lower()


async def test_the_gate_allows_a_write_only_after_the_current_revision_is_approved(store):
    task = _task(store)
    called: list[str] = []

    async def handler(_request):
        called.append("ran")
        return "ran"

    hook = PlanGateHook(PlanGate(store, task["id"]))
    plan = _plan(store, task)
    denied = await hook.awrap_tool_call(_request("write_file", file_path="/x.md"), handler)
    assert isinstance(denied, ToolMessage) and called == []

    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)
    allowed = await hook.awrap_tool_call(_request("write_file", file_path="/x.md"), handler)
    assert allowed == "ran" and called == ["ran"]


async def test_the_gate_records_todos_without_losing_the_approved_scope(store):
    task = _task(store)
    plan = _plan(store, task, steps=_steps(("pending", "pending")))
    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)

    todos = _steps(("completed", "pending"))
    result = SimpleNamespace(update={"todos": todos})

    async def handler(_request):
        return result

    hook = PlanGateHook(PlanGate(store, task["id"]))
    await hook.awrap_tool_call(_request("write_todos", todos=todos), handler)

    stored = store.plan(task["id"])
    assert stored["revision"] == plan["revision"]
    assert stored["approved_revision"] == plan["revision"]
    assert stored["steps"][0]["status"] == "completed"
    assert stored["scope"] == plan["scope"] and stored["checks"] == plan["checks"]


# ── the controller ───────────────────────────────────────────────────────────


class _Manager:
    """Enough of RunManager to prove a refusal never launches anything."""

    def __init__(self) -> None:
        self.launched: list[dict] = []

    def is_running(self, _thread_id: str) -> bool:
        return False

    def launch(self, thread_id: str, stream) -> None:  # noqa: ANN001
        self.launched.append({"thread_id": thread_id, "stream": stream})


def test_execute_refuses_a_task_that_has_no_approved_plan(store):
    task = _task(store)
    manager = _Manager()
    controller = TaskController(manager, store, model_resolver=lambda: DEMO)

    with pytest.raises(TaskControllerError) as missing:
        controller.execute(task["id"])
    assert missing.value.code == "action_not_approved" and manager.launched == []

    plan = _plan(store, task)
    with pytest.raises(TaskControllerError) as unapproved:
        controller.execute(task["id"])
    assert unapproved.value.code == "action_not_approved" and manager.launched == []

    store.decide_plan(task["id"], expected_revision=plan["revision"], approve=True)
    _plan(store, task, titles=("گام تازه", "گام ۲"))
    with pytest.raises(TaskControllerError) as changed:
        controller.execute(task["id"])
    assert changed.value.code == "action_not_approved" and manager.launched == []


def test_resume_refuses_a_plan_that_is_no_longer_approved(store):
    task = _task(store)
    manager = _Manager()
    controller = TaskController(manager, store, model_resolver=lambda: DEMO)

    with pytest.raises(TaskControllerError) as missing:
        controller.resume(task["id"], [{"type": "approve"}])
    assert missing.value.code == "action_not_approved" and manager.launched == []


def test_each_segment_shares_one_budget_and_the_counters_accumulate(store):
    task = _task(store)
    first_run = task["runs"][0]
    store.consume(task["id"], active_ms=1_200, model_calls=2, tool_calls=1)

    second_run = store.start_segment(task["id"])
    store.consume(task["id"], active_ms=800, model_calls=1, tool_calls=2)

    budget = store.budget(task["id"])
    assert budget["id"] == task["budget"]["id"], "a new segment reuses the budget row"
    assert (budget["active_ms"], budget["model_calls"], budget["tool_calls"]) == (2_000, 3, 3)
    runs = store.task(task["id"])["runs"]
    assert [run["segment"] for run in runs] == [1, 2]
    assert {run["budget_id"] for run in runs} == {budget["id"]}
    assert runs[-1]["id"] == second_run["id"] and runs[0]["id"] == first_run["id"]
    assert store.task(task["id"])["status"] == "executing"


# ── resume keeps the thread and does not repeat work ─────────────────────────


# ── the HTTP surface ─────────────────────────────────────────────────────────


@pytest.fixture
async def api(tmp_path, monkeypatch):
    """A client on a fresh app with its own home folder and no token."""
    import httpx

    from server.app import create_app

    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "api-home"))
    monkeypatch.delenv("HARNESS_TOKEN", raising=False)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        client.workspace_path = str(tmp_path / "api-ws")  # type: ignore[attr-defined]
        yield client


async def _created_task(api) -> dict:
    opened = await api.post("/workspace", json={"path": api.workspace_path})
    assert opened.status_code == 200, opened.text
    created = await api.post("/tasks", json={"prompt": "گزارش را بنویس"})
    assert created.status_code == 202, created.text
    return created.json()["task"]


async def test_the_plan_route_writes_and_rejects_a_stale_revision(api):
    task = await _created_task(api)
    body = {
        "expected_revision": 0,
        "steps": [{"title": "خواندن داده", "status": "pending"}, {"title": "نوشتن گزارش", "status": "pending"}],
        "scope": ["report.md"],
        "checks": ["the report opens"],
    }
    written = await api.patch(f"/tasks/{task['id']}/plan", json=body)
    assert written.status_code == 200, written.text
    plan = written.json()["plan"]
    assert plan["revision"] == 1 and plan["steps"][0]["title"] == "خواندن داده"

    stale = await api.patch(f"/tasks/{task['id']}/plan", json={**body, "expected_revision": 0, "scope": ["other.md"]})
    assert stale.status_code == 409
    assert stale.json()["code"] == "selection_stale" and stale.json()["current_revision"] == 1


async def test_a_decision_is_idempotent_and_never_starts_execution(api):
    task = await _created_task(api)
    body = {"expected_revision": 0, "steps": [{"title": "گام", "status": "pending"}]}
    written = await api.patch(f"/tasks/{task['id']}/plan", json=body)
    assert written.status_code == 200, written.text

    decision = {"decision": "approve", "expected_revision": 1, "idempotency_key": "decide-once"}
    first = await api.post(f"/tasks/{task['id']}/plan-decisions", json=decision)
    assert first.status_code == 200, first.text
    assert first.json()["plan"]["approved_revision"] == 1
    assert first.json()["task"]["status"] == "awaiting_plan"
    assert len(first.json()["task"]["runs"]) == 1

    replay = await api.post(f"/tasks/{task['id']}/plan-decisions", json=decision)
    assert replay.status_code == 200 and replay.headers.get("Idempotent-Replayed") == "true"

    stale = await api.post(f"/tasks/{task['id']}/plan-decisions", json={**decision, "idempotency_key": "decide-twice", "expected_revision": 9})
    assert stale.status_code == 409 and stale.json()["code"] == "selection_stale"


async def test_resume_does_not_repeat_the_work_before_the_interrupt(workspace, script):
    hits: list[str] = []

    @tool
    def probe(text: str) -> str:
        """Record one probe and return it."""
        hits.append(text)
        return text

    script(
        AIMessage(content="", tool_calls=[call("probe", text="before")]),
        AIMessage(content="", tool_calls=[call("write_file", file_path="/x.md", content="x")]),
        AIMessage(content="تمام شد."),
    )
    req = request(mode="ask")
    first = await collect(Runner(workspace, extra_tools=[probe]).start(req))

    assert finished(first)["stop_reason"] == "awaiting_approval"
    assert hits == ["before"]

    # A fresh Runner after a restart: only the checkpoint and the case files carry over.
    second = await collect(Runner(workspace, extra_tools=[probe]).resume(req, [{"type": "approve"}]))

    assert finished(second)["stop_reason"] == "completed"
    assert hits == ["before"], "work finished before the interrupt is not executed again"
