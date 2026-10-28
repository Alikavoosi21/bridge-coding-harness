"""The task command surface over HTTP: create, read, stream the journal, delete."""

from __future__ import annotations

import httpx
import pytest

from server import keychain
from server.app import create_app


@pytest.fixture
async def api(tmp_path, monkeypatch):
    """A client on a fresh app with its own home folder and no token."""
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HARNESS_TOKEN", raising=False)
    vault: dict[str, str] = {}
    monkeypatch.setattr(keychain, "get_key", lambda model_id: vault.get(model_id, ""))
    monkeypatch.setattr(keychain, "set_key", vault.__setitem__)
    monkeypatch.setattr(keychain, "delete_key", lambda model_id: vault.pop(model_id, None))

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        client.app = app  # type: ignore[attr-defined]
        client.workspace_path = str(tmp_path / "ws")  # type: ignore[attr-defined]
        yield client


async def _open(api) -> None:
    response = await api.post("/workspace", json={"path": api.workspace_path})
    assert response.status_code == 200, response.text


async def test_artifact_history_does_not_recreate_missing_files_or_replay_unknown(api):
    from harness.task_runtime import task_directory
    from server.storage import Store
    await _open(api)
    task=(await api.post('/tasks',json={'prompt':'artifact history'})).json()['task']
    store=Store();directory=task_directory(store,task['id'])
    (directory/'working').mkdir(parents=True,exist_ok=True)
    (directory/'baseline').mkdir(exist_ok=True)
    action=store.ensure_action(task['id'],'history-unknown','fixture-hash')
    store.set_action_state(action['operation_id'],'unknown')
    before=store.task(task['id'])
    base=f"/tasks/{task['id']}/artifacts"
    response=await api.get(base)
    assert response.status_code==200,response.text
    assert response.json()['working_available'] and response.json()['baseline_available']
    assert response.json()['unresolved_operations'][0]['operation_id']==action['operation_id']
    (directory/'working').rmdir()
    assert not (await api.get(base)).json()['working_available']
    assert not (directory/'working').exists()
    assert store.task(task['id'])['runs']==before['runs']
    assert store.action(action['operation_id'])['state']=='unknown'


async def test_a_task_is_created_read_listed_and_streamed(api):
    await _open(api)

    response = await api.post("/tasks", json={"prompt": "گزارش فروش را بنویس", "mode": "ask"})
    assert response.status_code == 202
    body = response.json()
    task = body["task"]

    assert task["status"] == "queued" and task["mode"] == "ask"
    assert task["read_only"] is True, "a task that cannot be sandboxed may only read"
    assert task["runs"][0]["segment"] == 1
    assert body["run"]["id"] == task["runs"][0]["id"]
    assert body["last_event_seq"] == task["last_event_seq"] == 2

    read = (await api.get(f"/tasks/{task['id']}")).json()
    assert read["id"] == task["id"] and read["budget"]["active_ms"] == 0
    assert read["worker_lease"] is None

    listed = (await api.get("/tasks")).json()
    assert [item["id"] for item in listed["items"]] == [task["id"]]

    events = (await api.get(f"/tasks/{task['id']}/events", params={"after_seq": 0})).json()
    assert [event["sequence"] for event in events["items"]] == [1, 2]
    assert {event["task_id"] for event in events["items"]} == {task["id"]}
    assert (await api.get(f"/tasks/{task['id']}/events", params={"after_seq": 2})).json()["items"] == []


async def test_creating_with_an_idempotency_key_replays_and_conflicts(api):
    await _open(api)
    body = {"prompt": "یک گزارش بساز", "mode": "ask", "idempotency_key": "create-1"}

    first = await api.post("/tasks", json=body)
    second = await api.post("/tasks", json=body)

    assert first.status_code == second.status_code == 202
    assert first.json()["task"]["id"] == second.json()["task"]["id"]
    assert "idempotent-replayed" not in first.headers
    assert second.headers["idempotent-replayed"] == "true"
    assert len((await api.get("/tasks")).json()["items"]) == 1

    conflict = await api.post("/tasks", json={**body, "prompt": "یک گزارش دیگر بساز"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


async def test_a_task_cannot_be_deleted_while_it_holds_recovery_evidence(api):
    await _open(api)
    task = (await api.post("/tasks", json={"prompt": "x"})).json()["task"]

    assert (await api.delete(f"/tasks/{task['id']}")).status_code == 403
    refused = await api.delete(f"/tasks/{task['id']}", params={"consent": "true"})
    assert refused.status_code == 409

    from server.storage import Store

    Store().set_task_status(task["id"], "closed", outcome="completed")
    assert (await api.delete(f"/tasks/{task['id']}", params={"consent": "true"})).json() == {"deleted": True}
    assert (await api.get(f"/tasks/{task['id']}")).status_code == 404


async def test_creating_a_task_without_a_workspace_is_refused(api):
    response = await api.post("/tasks", json={"prompt": "x"})

    assert response.status_code == 202
    assert response.json()["task"]["workspace_id"]


async def test_validation_errors_use_the_same_shape(api):
    response = await api.post("/tasks", json={"prompt": ""})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"]["errors"]


async def test_a_foreign_origin_and_a_missing_token_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HARNESS_TOKEN", "secret-token")
    app = create_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        assert (await client.get("/health")).status_code == 401
        allowed = await client.get("/health", headers={"Authorization": "Bearer secret-token"})
        assert allowed.status_code == 200
        foreign = await client.get("/health", headers={"Authorization": "Bearer secret-token", "Origin": "http://evil.example"})
        assert foreign.status_code == 403
