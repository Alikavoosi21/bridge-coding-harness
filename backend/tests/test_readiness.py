"""Readiness (P14): distinct failures, no secrets, and consent before a build."""

from __future__ import annotations

import json

import httpx
import pytest

from harness.runtime.docker import Capability, RuntimeUnavailable
from server import keychain
from server.app import create_app


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
        client.app = app  # type: ignore[attr-defined]
        client.workspace_path = str(tmp_path / "پروژه من")  # type: ignore[attr-defined]
        yield client


class _FakeRuntime:
    def __init__(self, *, available: bool, server_version: str | None = None) -> None:
        self._available = available
        self._server_version = server_version
        self.built: list[str] = []

    def capability(self) -> Capability:
        if self._available:
            return Capability(True, "ready", server_version=self._server_version or "27.0.0", image_present=True)
        return Capability(False, "Docker is not installed. The task stays read-only." if self._server_version is None else "The sandbox image is missing.", server_version=self._server_version)

    def build_image(self, base_image: str) -> dict:
        if not self._available:
            raise RuntimeUnavailable("Docker is not installed. The task stays read-only.")
        self.built.append(base_image)
        return {"image": "bridge-coding-sandbox:0.2", "built": True, "output": ""}


def _use(monkeypatch, runtime: _FakeRuntime) -> _FakeRuntime:
    from server.routes import readiness

    monkeypatch.setattr(readiness, "DockerRuntime", lambda: runtime)
    return runtime


async def test_without_docker_the_readiness_says_read_only_and_names_the_reason(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=False))

    response = await api.get("/readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["engine"]["ok"] is True
    assert data["schema"]["ok"] is True and data["schema"]["version"] == data["schema"]["expected"]
    assert data["runtime"]["available"] is False
    assert data["workspace"]["open"] is False
    assert data["model"]["demo"] is True and data["model"]["tools"] is True
    assert data["task"]["can_write"] is False and data["task"]["mode"] == "read_only"
    assert data["legacy_runs"]["mode"] == "read_only"
    assert {issue["component"] for issue in data["issues"]} == {"runtime", "workspace"}
    assert {issue["code"] for issue in data["issues"]} == {"docker_missing", "workspace_closed"}


async def test_a_ready_runtime_and_an_open_workspace_allow_a_sandbox_task(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=True))
    opened = await api.post("/workspace", json={"path": api.workspace_path, "name": "پروژهٔ آزمون"})

    data = (await api.get("/readiness")).json()

    assert opened.status_code == 200
    assert data["workspace"] == {"open": True, "name": "پروژهٔ آزمون"}
    assert data["runtime"]["image_present"] is True
    assert data["worker"]["state"] == "idle"
    assert data["task"]["can_execute"] is True and data["task"]["can_write"] is True
    assert data["task"]["mode"] == "sandbox"
    assert data["issues"] == []
    assert data["legacy_runs"]["mode"] == "read_only", "readiness does not turn the legacy runner into a writer"


async def test_a_missing_image_is_a_different_failure_from_missing_docker(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=False, server_version="27.0.0"))

    codes = {issue["code"] for issue in (await api.get("/readiness")).json()["issues"]}

    assert "image_missing" in codes
    assert "docker_missing" not in codes


async def test_prepare_needs_consent_and_never_runs_without_it(api, monkeypatch):
    runtime = _use(monkeypatch, _FakeRuntime(available=True))

    response = await api.post("/runtime/prepare", json={"consent": False})

    assert response.status_code == 400
    assert response.json()["code"] == "consent_required"
    assert runtime.built == []


async def test_prepare_builds_the_fixed_image_once_consent_is_given(api, monkeypatch):
    runtime = _use(monkeypatch, _FakeRuntime(available=True))

    response = await api.post("/runtime/prepare", json={"consent": True})

    assert response.status_code == 200
    assert runtime.built == ["python:3.12-slim-bookworm"]
    assert response.json()["build"]["built"] is True


async def test_prepare_reports_missing_docker_as_unavailable_not_a_crash(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=False))

    response = await api.post("/runtime/prepare", json={"consent": True})

    assert response.status_code == 503
    assert response.json()["code"] == "runtime_unavailable"
    assert response.json()["retryable"] is True


async def test_readiness_contains_no_key_no_token_and_no_private_path(api, monkeypatch, tmp_path):
    _use(monkeypatch, _FakeRuntime(available=True))
    await api.post("/workspace", json={"path": api.workspace_path})

    text = json.dumps((await api.get("/readiness")).json(), ensure_ascii=False)

    assert "api_key" not in text and "HARNESS_TOKEN" not in text
    assert str(tmp_path) not in text, "diagnostics show a workspace name, not the user's path"
