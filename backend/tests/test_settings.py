"""T005: setup, probe capability, write gating, disclosures, and write-only keys."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from harness import ModelSpec
from harness.models import probe_model
from harness.runtime.docker import Capability
from server import keychain
from server.app import create_app
from server.routes import models as model_routes
from server.routes import readiness as readiness_routes
from server.routes import tasks as task_routes


@pytest.fixture
async def api(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("HARNESS_TOKEN", raising=False)
    vault: dict[str, str] = {}
    monkeypatch.setattr(keychain, "get_key", lambda model_id: vault.get(model_id, ""))
    monkeypatch.setattr(keychain, "set_key", vault.__setitem__)
    monkeypatch.setattr(keychain, "delete_key", lambda model_id: vault.pop(model_id, None))

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        client.vault = vault  # type: ignore[attr-defined]
        client.app = app  # type: ignore[attr-defined]
        client.workspace_path = str(tmp_path / "پروژه من")  # type: ignore[attr-defined]
        yield client


class _FakeRuntime:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def capability(self) -> Capability:
        if self.available:
            return Capability(True, "ready", server_version="27.0.0", image_present=True)
        return Capability(False, "Docker is not installed. The task stays read-only.")


def _use_runtime(monkeypatch, available: bool = True) -> None:
    runtime = _FakeRuntime(available=available)
    monkeypatch.setattr(readiness_routes, "DockerRuntime", lambda: runtime)
    monkeypatch.setattr(task_routes, "DockerRuntime", lambda: runtime)


async def _open(api) -> None:
    assert (await api.post("/workspace", json={"path": api.workspace_path, "name": "پروژهٔ آزمون"})).status_code == 200


async def _save_model(api, *, key: str | None = "sk-test-secret") -> str:
    response = await api.post(
        "/models",
        json={"name": "آزمایشی", "base_url": "https://example.invalid/v1", "model": "test-model", "api_key": key},
    )
    assert response.status_code == 200
    model_id = response.json()["id"]
    assert (await api.post(f"/models/{model_id}/default")).status_code == 200
    return model_id


def _probe(tools: bool | None, *, error: str | None = None) -> dict[str, Any]:
    return {
        "model": "test-model",
        "tools": tools,
        "provider_reachable": True,
        "demo": False,
        "streaming": True,
        "error_code": error,
        "error_message": None,
        "checked_at": 123.0,
    }


async def test_a_stored_key_is_never_returned_by_models_or_settings(api):
    model_id = await _save_model(api)

    listed = (await api.get("/models")).json()
    settings = (await api.get("/settings")).json()
    text = json.dumps({"models": listed, "settings": settings}, ensure_ascii=False)

    assert api.vault[model_id] == "sk-test-secret"
    assert "sk-test-secret" not in text
    assert "api_key" not in text
    saved = next(item for item in listed if item["id"] == model_id)
    assert saved["has_key"] is True
    settings_saved = next(item for item in settings["models"] if item["id"] == model_id)
    assert settings_saved["has_key"] is True


async def test_probe_records_capability_without_the_key(api, monkeypatch):
    model_id = await _save_model(api)
    seen: list[ModelSpec] = []

    async def fake_probe(spec: ModelSpec, **_kwargs) -> dict[str, Any]:
        seen.append(spec)
        return _probe(True)

    monkeypatch.setattr(model_routes, "probe_model", fake_probe)

    response = await api.post("/models/probe", json={"id": model_id})
    data = response.json()

    assert response.status_code == 200
    assert data["probe"]["tools"] is True
    assert seen and seen[0].api_key == "sk-test-secret"
    assert "sk-test-secret" not in json.dumps(data, ensure_ascii=False)
    stored = next(item for item in (await api.get("/models")).json() if item["id"] == model_id)
    assert stored["capabilities"]["tools"] is True


async def test_an_unprobed_model_cannot_start_a_write_task(api, monkeypatch):
    _use_runtime(monkeypatch, available=True)
    await _open(api)
    await _save_model(api)

    response = await api.post("/tasks", json={"prompt": "یک فایل بساز", "read_only": False})

    assert response.status_code == 409
    assert response.json()["code"] == "model_tools_unavailable"
    assert response.json()["details"]["reason"] == "model_tools_unproven"


async def test_a_model_without_tools_keeps_readiness_read_only_even_with_docker(api, monkeypatch):
    _use_runtime(monkeypatch, available=True)
    await _open(api)
    model_id = await _save_model(api)

    async def fake_probe(spec: ModelSpec, **_kwargs) -> dict[str, Any]:
        return _probe(False, error="tools_not_observed")

    monkeypatch.setattr(model_routes, "probe_model", fake_probe)
    await api.post("/models/probe", json={"id": model_id})

    readiness = (await api.get("/readiness")).json()

    assert readiness["runtime"]["available"] is True
    assert readiness["model"]["tools"] is False
    assert readiness["task"]["can_write"] is False
    assert readiness["task"]["mode"] == "read_only"
    assert {issue["code"] for issue in readiness["issues"]} >= {"model_tools_unavailable"}


async def test_a_proven_model_still_needs_a_real_sandbox_for_writes(api, monkeypatch):
    _use_runtime(monkeypatch, available=False)
    await _open(api)
    model_id = await _save_model(api)

    async def fake_probe(spec: ModelSpec, **_kwargs) -> dict[str, Any]:
        return _probe(True)

    monkeypatch.setattr(model_routes, "probe_model", fake_probe)
    await api.post("/models/probe", json={"id": model_id})

    response = await api.post("/tasks", json={"prompt": "یک فایل بساز", "read_only": False})

    assert response.status_code == 409
    assert response.json()["code"] == "runtime_unavailable"
    assert (await api.get("/readiness")).json()["task"]["can_write"] is False


async def test_a_proven_model_and_available_runtime_allow_a_write_task(api, monkeypatch):
    _use_runtime(monkeypatch, available=True)
    await _open(api)
    model_id = await _save_model(api)

    async def fake_probe(spec: ModelSpec, **_kwargs) -> dict[str, Any]:
        return _probe(True)

    monkeypatch.setattr(model_routes, "probe_model", fake_probe)
    await api.post("/models/probe", json={"id": model_id})

    response = await api.post("/tasks", json={"prompt": "یک فایل بساز", "read_only": False})

    assert response.status_code == 202
    assert response.json()["task"]["read_only"] is False


async def test_setup_needs_a_workspace_and_a_model_before_it_can_complete(api):
    response = await api.put("/settings", json={"setup": {"step": 4, "completed": True}})

    assert response.status_code == 409
    assert response.json()["code"] == "setup_incomplete"
    assert response.json()["details"]["missing"] == ["workspace"]


async def test_completion_is_explicit_and_saving_a_profile_does_not_confirm_a_first_run(api):
    await _open(api)
    workspace = api.workspace_path
    with open(f"{workspace}/package.json", "w", encoding="utf-8") as file:
        json.dump({"scripts": {"test": "vitest"}}, file)

    saved = (await api.put("/settings", json={"setup": {"step": 3, "completed": False}})).json()
    assert saved["setup"]["completed"] is False

    workspaces = (await api.get("/workspaces")).json()["items"]
    workspace_id = workspaces[0]["id"]
    preflight = (await api.post(f"/workspaces/{workspace_id}/preflight")).json()
    profile = preflight["profile"]
    patched = await api.patch(
        f"/workspaces/{workspace_id}",
        json={"profile": {"commands": profile["commands"]}},
    )
    assert patched.status_code == 200
    assert patched.json()["profile"]["commands"][0]["command"] == "npm test"

    still_open = (await api.get("/settings")).json()
    assert still_open["setup"]["completed"] is False, "saving a profile is not a first run"

    done = (await api.put("/settings", json={"setup": {"step": 4, "completed": True}})).json()
    assert done["setup"]["completed"] is True
    assert done["setup"]["completed_at"] is not None


async def test_disclosures_are_recorded_separately_and_are_not_grants(api):
    data = (await api.put("/settings", json={"disclosures": {"model_api": True, "sandbox_network": True}})).json()

    assert data["disclosures"]["model_api"] is True
    assert data["disclosures"]["sandbox_network"] is True
    assert data["setup"]["completed"] is False
    bad = await api.put("/settings", json={"disclosures": {"something_else": True}})
    assert bad.status_code == 422


async def test_probe_classifies_provider_failures_and_redacts_the_key(monkeypatch):
    class _Failing:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            raise RuntimeError("401 unauthorized: bad key sk-very-secret")

    monkeypatch.setattr("harness.models.build_chat_model", lambda spec: _Failing())

    auth = await probe_model(ModelSpec(id="x", name="x", base_url="https://example.invalid/v1", model="m", api_key="sk-very-secret"))
    assert auth["tools"] is None
    assert auth["provider_reachable"] is True
    assert auth["error_code"] == "provider_auth"
    assert "sk-very-secret" not in json.dumps(auth)

    class _Offline:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("harness.models.build_chat_model", lambda spec: _Offline())
    offline = await probe_model(ModelSpec(id="x", name="x", base_url="https://example.invalid/v1", model="m"))
    assert offline["tools"] is None
    assert offline["provider_reachable"] is False
    assert offline["error_code"] == "provider_unreachable"


async def test_probe_reads_tool_calls_as_real_capability(monkeypatch):
    class _WithTools:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            return AIMessage(content="", tool_calls=[{"name": "report_capability", "args": {"ok": True}, "id": "call_1", "type": "tool_call"}])

    monkeypatch.setattr("harness.models.build_chat_model", lambda spec: _WithTools())
    result = await probe_model(ModelSpec(id="x", name="x", base_url="https://example.invalid/v1", model="m"))
    assert result["tools"] is True and result["error_code"] is None

    class _WithoutTools:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            return AIMessage(content="I cannot call tools.")

    monkeypatch.setattr("harness.models.build_chat_model", lambda spec: _WithoutTools())
    result = await probe_model(ModelSpec(id="x", name="x", base_url="https://example.invalid/v1", model="m"))
    assert result["tools"] is False
    assert result["error_code"] == "tools_not_observed"
