"""Machine settings and the four-step setup record.

Secrets never live here: model keys are in the OS keychain and are write-only
through `/models`. This route returns public model fields, the setup step, and
which disclosures the user has actually seen. An acknowledgement is not a
permission or a grant.

Completing setup is explicit. Saving a suggested verification profile, adding a
model, or probing a provider never sets `completed` by itself.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from harness.preflight import analyze_workspace

from .. import keychain, settings
from ..errors import ApiError
from ..schemas import SettingsIn
from ..storage import Store

router = APIRouter(tags=["settings"])

DISCLOSURES = ("model_api", "sandbox_network", "demo_state", "read_only")


def _clean_flags(values: dict[str, bool] | None) -> dict[str, bool]:
    if values is None:
        return {}
    unknown = sorted(set(values) - set(DISCLOSURES))
    if unknown:
        raise ApiError("invalid_request", f"Unknown disclosure: {unknown[0]}", status_code=422)
    return {name: bool(value) for name, value in values.items()}


def _setup(data: dict[str, Any]) -> dict[str, Any]:
    stored = data.get("setup") if isinstance(data.get("setup"), dict) else {}
    step = stored.get("step")
    if not isinstance(step, int) or not 1 <= step <= 4:
        step = _inferred_step(data)
    return {
        "step": step,
        "completed": bool(stored.get("completed", False)),
        "deferred": bool(stored.get("deferred", False)),
        "completed_at": stored.get("completed_at"),
        "acknowledgements": {name: bool(stored.get("acknowledgements", {}).get(name, False)) for name in DISCLOSURES},
    }


def _inferred_step(data: dict[str, Any]) -> int:
    """Where an interrupted setup would continue when no step was recorded yet."""
    workspace = data.get("current_workspace")
    if not workspace or not Path(workspace).is_dir():
        return 1
    model = next((item for item in data.get("models", []) if item.get("id") == data.get("default_model")), None)
    if model is None:
        return 2
    if not str(model.get("base_url", "")).startswith("demo://") and not keychain.has_key(model["id"]):
        return 2
    return 3


def _workspace(data: dict[str, Any]) -> dict[str, Any]:
    root = data.get("current_workspace")
    if not root or not Path(root).is_dir():
        return {"open": False, "id": None, "name": None, "path": None, "profile": None}
    store = Store()
    entry = store.workspace_by_root(str(root))
    if entry is None:
        entry = store.upsert_workspace(str(root), settings.workspace_name(data, str(root)))
    return {
        "open": True,
        "id": entry["id"],
        "name": settings.workspace_name(data, str(root)),
        "path": str(root),
        "profile": _json_or_none(entry.get("profile")),
    }


def _json_or_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        import json

        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _public(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or settings.load()
    default_id = data.get("default_model")
    models = []
    for entry in data.get("models", []):
        public = {key: value for key, value in entry.items() if key != "api_key"}
        public["has_key"] = str(entry.get("base_url", "")).startswith("demo://") or keychain.has_key(entry["id"])
        public["is_default"] = entry["id"] == default_id
        models.append(public)
    setup = _setup(data)
    disclosures = {name: bool(data.get("disclosures", {}).get(name, False)) for name in DISCLOSURES} if isinstance(data.get("disclosures"), dict) else {name: False for name in DISCLOSURES}
    return {
        "models": models,
        "default_model": default_id,
        "workspace": _workspace(data),
        "setup": setup,
        "disclosures": disclosures,
    }


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return _public()


@router.put("/settings")
def put_settings(body: SettingsIn) -> dict[str, Any]:
    data = settings.load()

    if body.default_model is not None:
        if not any(entry.get("id") == body.default_model for entry in data.get("models", [])):
            raise ApiError("invalid_request", "No such model.", status_code=422)
        data["default_model"] = body.default_model

    if body.disclosures is not None:
        current = data.get("disclosures") if isinstance(data.get("disclosures"), dict) else {}
        data["disclosures"] = {**current, **_clean_flags(body.disclosures)}

    if body.setup is not None:
        current = _setup(data)
        flags = _clean_flags(body.setup.acknowledgements)
        acknowledgements = {**current["acknowledgements"], **flags}
        completed = bool(body.setup.completed)
        missing = _missing_for_completion(data) if completed else []
        if missing:
            raise ApiError(
                "setup_incomplete",
                "Setup cannot be completed yet: " + ", ".join(missing) + ".",
                status_code=409,
                details={"missing": missing},
            )
        data["setup"] = {
            "step": 4 if completed else max(1, min(body.setup.step, 4)),
            "completed": completed,
            "deferred": False if completed else current['deferred'],
            "completed_at": current["completed_at"] if completed and current["completed_at"] else (time.time() if completed else None),
            "acknowledgements": acknowledgements,
        }

    settings.save(data)
    return _public(data)


@router.post('/setup/defer')
def defer_setup() -> dict[str, Any]:
    """Leave setup without pretending prerequisites or consent are satisfied."""
    data = settings.load()
    data['setup'] = {**_setup(data), 'deferred': True}
    settings.save(data)
    return _public(data)


def _missing_for_completion(data: dict[str, Any]) -> list[str]:
    """The user-visible prerequisites for finishing setup (not for a first run)."""
    missing: list[str] = []
    root = data.get("current_workspace")
    if not root or not Path(root).is_dir():
        missing.append("workspace")
    entry = next((item for item in data.get("models", []) if item.get("id") == data.get("default_model")), None)
    if entry is None:
        missing.append("model")
    elif not str(entry.get("base_url", "")).startswith("demo://") and not keychain.has_key(entry["id"]):
        missing.append("provider_key")
    return missing


@router.post("/setup/preflight")
def setup_preflight() -> dict[str, Any]:
    """The setup screen's read-only check of the open workspace.

    Kept as a setup alias so the wizard does not need the product workspace id
    before it has opened one. The plural workspace route is the canonical form.
    """
    data = settings.load()
    root = data.get("current_workspace")
    if not root or not Path(root).is_dir():
        raise ApiError("workspace_closed", "No workspace is open. Choose a project folder first.", status_code=409)
    return analyze_workspace(Path(root))
