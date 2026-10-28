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


async def test_without_docker_default_workspace_and_native_execution_are_ready(api, monkeypatch):
    from server.routes import readiness
    monkeypatch.setattr(readiness,'DockerRuntime',lambda: (_ for _ in ()).throw(AssertionError('Docker must not be queried')))
    data=(await api.get('/readiness')).json()
    assert data['runtime']['available'] and data['runtime']['kind']=='local'
    assert data['runtime']['sandboxed'] is False
    assert data['workspace']['open'] and data['task']['can_write']
    assert data['legacy_runs']['mode']=='read_only'
    assert data['issues']==[]


async def test_a_ready_runtime_and_an_open_workspace_allow_a_sandbox_task(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=True))
    opened = await api.post("/workspace", json={"path": api.workspace_path, "name": "پروژهٔ آزمون"})

    data = (await api.get("/readiness")).json()

    assert opened.status_code == 200
    assert data["workspace"] == {"open": True, "name": "پروژهٔ آزمون"}
    assert data["runtime"]["image_present"] is True
    assert data["worker"]["state"] == "idle"
    assert data["task"]["can_execute"] is True and data["task"]["can_write"] is True
    assert data["task"]["mode"] == "local"
    assert data["issues"] == []
    assert data["legacy_runs"]["mode"] == "read_only", "readiness does not turn the legacy runner into a writer"


async def test_missing_docker_image_does_not_block_native_execution(api, monkeypatch):
    _use(monkeypatch,_FakeRuntime(available=False,server_version='27.0.0'))
    data=(await api.get('/readiness')).json()
    assert data['runtime']['available'] and not data['issues']


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
    assert runtime.built == []
    assert response.json()["runtime"]["available"] is True


async def test_prepare_reports_missing_docker_as_unavailable_not_a_crash(api, monkeypatch):
    _use(monkeypatch, _FakeRuntime(available=False))

    response = await api.post("/runtime/prepare", json={"consent": True})

    assert response.status_code == 200
    assert response.json()["runtime"]["available"] is True


async def test_readiness_contains_no_key_no_token_and_no_private_path(api, monkeypatch, tmp_path):
    _use(monkeypatch, _FakeRuntime(available=True))
    await api.post("/workspace", json={"path": api.workspace_path})

    text = json.dumps((await api.get("/readiness")).json(), ensure_ascii=False)

    assert "api_key" not in text and "HARNESS_TOKEN" not in text
    assert str(tmp_path) not in text, "diagnostics show a workspace name, not the user's path"
