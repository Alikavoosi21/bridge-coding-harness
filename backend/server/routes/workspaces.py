"""Workspaces in the product contract: list, inspect, preflight, save a profile.

The legacy `/workspace` route still opens and names the folder for the current
UI. These plural routes are the stable surface for setup: a workspace has an
id, a read-only preflight, and a verification profile that can be saved only
from commands the preflight actually suggested.

No route here executes a command or writes into the project. Saving a profile
records a suggestion; the first run is still a separate, explicit event.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from harness.preflight import analyze_workspace, canonical_profile

from .. import settings
from ..errors import ApiError
from ..schemas import WorkspacePatch
from ..storage import Store

router = APIRouter(tags=["workspaces"])

CURRENT = "current"


def _store() -> Store:
    return Store()


def _public(entry: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    profile = entry.get("profile")
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except ValueError:
            profile = None
    return {
        "id": entry["id"],
        "root": entry["root"],
        "name": settings.workspace_name(data, entry["root"]),
        "profile": profile,
        "exclusions": entry.get("exclusions") or [],
        "manifest_hash": entry.get("manifest_hash"),
        "current": entry["root"] == data.get("current_workspace"),
    }


def _current_root(data: dict[str, Any]) -> str:
    root = data.get("current_workspace")
    if not root:
        raise ApiError("workspace_closed", "No workspace is open. Choose a project folder first.", status_code=409)
    if not Path(root).is_dir():
        raise ApiError("workspace_missing", "The workspace folder is gone. Choose it again.", status_code=409)
    return str(root)


def _resolve(workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    store = _store()
    if workspace_id == CURRENT:
        root = _current_root(data)
        entry = store.workspace_by_root(root)
        if entry is None:
            entry = store.upsert_workspace(root, settings.workspace_name(data, root))
        return entry
    entry = store.workspace(workspace_id)
    if not Path(entry["root"]).is_dir():
        raise ApiError("workspace_missing", "The workspace folder is gone.", status_code=409)
    return entry


@router.get("/workspaces")
def list_workspaces() -> dict[str, Any]:
    data = settings.load()
    store = _store()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    roots = list(dict.fromkeys([*data.get("workspaces", []), data.get("current_workspace")]))
    for root in roots:
        if not root or root in seen or not Path(root).is_dir():
            continue
        seen.add(root)
        entry = store.workspace_by_root(str(root)) or store.upsert_workspace(str(root), settings.workspace_name(data, str(root)))
        items.append(_public(entry, data))
    return {"items": items}


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str) -> dict[str, Any]:
    data = settings.load()
    return _public(_resolve(workspace_id, data), data)


@router.post("/workspaces/{workspace_id}/preflight")
def preflight(workspace_id: str) -> dict[str, Any]:
    """Read-only project detection and command suggestions for one workspace."""
    data = settings.load()
    entry = _resolve(workspace_id, data)
    analysis = analyze_workspace(Path(entry["root"]))
    return {"workspace": _public(entry, data), **analysis}


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: str, body: WorkspacePatch) -> dict[str, Any]:
    """Rename a workspace or save the profile it suggested.

    The profile is canonicalized from the current preflight: a command the
    analysis did not suggest is refused. This route never runs it.
    """
    data = settings.load()
    entry = _resolve(workspace_id, data)
    root = entry["root"]

    if body.name is not None:
        if not body.name.strip():
            raise ApiError("invalid_request", "The name is empty.", status_code=422)
        data["workspace_names"][root] = body.name.strip()[:60]
        settings.save(data)

    profile_payload = None
    if body.profile is not None:
        analysis = analyze_workspace(Path(root))
        try:
            profile = canonical_profile([item.model_dump() for item in body.profile.commands], analysis, body.profile.install)
        except ValueError as error:
            raise ApiError("unexpected_command", str(error), status_code=422) from error
        profile_payload = json.dumps(profile, ensure_ascii=False)
        entry = _store().upsert_workspace(root, name=body.name, profile=profile_payload)
    elif body.name is not None:
        entry = _store().upsert_workspace(root, name=body.name)

    return _public(entry, settings.load())
