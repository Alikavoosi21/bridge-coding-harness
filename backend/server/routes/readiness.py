"""Readiness (P14): what works on this machine, before a task starts.

The setup screen must tell four failures apart, because the user fixes them
differently: a broken engine, an outdated schema, a missing Docker runtime or
image, and a provider/model that cannot run. It also reports whether a
workspace is open and whether the legacy runner is still read-only.

Nothing here starts a task, builds an image, or returns a key. The only action
is `POST /runtime/prepare`, which builds the fixed sandbox image and requires
an explicit `consent: true` from the user.
"""

from __future__ import annotations

import platform
from typing import Any

from fastapi import APIRouter, Request

from harness.runtime.docker import DEFAULT_BASE_IMAGE, DOCKERFILE, DockerRuntime, RuntimeUnavailable

from .. import keychain, settings
from ..errors import ApiError
from ..schemas import PrepareRuntime
from ..state import AppState
from ..storage import Store
from ..storage.migrations import SCHEMA_VERSION, migrate

router = APIRouter(tags=["readiness"])

_DEMO_SCHEME = "demo://"


def _state(request: Request) -> AppState:
    return request.app.state.harness


def _engine() -> dict[str, Any]:
    return {"ok": True, "python": platform.python_version(), "platform": platform.system()}


def _schema() -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = migrate()
    except (RuntimeError, OSError) as error:
        issue = {"component": "schema", "code": "schema_invalid", "message": str(error), "retryable": False}
        return {"ok": False, "version": None, "expected": SCHEMA_VERSION}, issue
    current = int(result.get("current", 0))
    ok = current == SCHEMA_VERSION
    issue = None
    if not ok:
        issue = {"component": "schema", "code": "schema_outdated", "message": f"The database is at version {current}; version {SCHEMA_VERSION} is required.", "retryable": True}
    return {"ok": ok, "version": current, "expected": SCHEMA_VERSION}, issue


def _runtime() -> tuple[dict[str, Any], dict[str, Any] | None]:
    capability = DockerRuntime().capability()
    payload = capability.as_dict()
    payload["dockerfile"] = str(DOCKERFILE)
    if capability.available:
        return payload, None
    if capability.server_version is None:
        code = "docker_missing" if "not installed" in capability.reason else "docker_unavailable"
    else:
        code = "image_missing"
    issue = {"component": "runtime", "code": code, "message": capability.reason, "retryable": code != "docker_missing"}
    return payload, issue


def _worker() -> dict[str, Any]:
    try:
        lease = Store().worker_lease()
    except (RuntimeError, OSError) as error:
        return {"state": "unknown", "fencing_token": None, "reason": str(error)}
    if lease is None:
        return {"state": "idle", "fencing_token": None}
    return {"state": "busy", "fencing_token": lease.get("fencing_token")}


def _model() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = settings.load()
    default_id = data.get("default_model")
    entry = next((item for item in data.get("models", []) if item.get("id") == default_id), None)
    if entry is None:
        payload = {"configured": False, "id": None, "name": None, "demo": False, "has_key": False, "tools": None}
        return payload, [{"component": "model", "code": "model_missing", "message": "No model is configured. Add one in Settings.", "retryable": False}]
    demo = str(entry.get("base_url", "")).startswith(_DEMO_SCHEME)
    has_key = demo or keychain.has_key(entry["id"])
    capabilities = entry.get("capabilities") if isinstance(entry.get("capabilities"), dict) else {}
    # Tool use is never guessed: it is `True` only after a probe against this
    # exact address/model/key, or for the demo model we control. Before a probe
    # the answer is `None`, and writes stay disabled.
    tools = True if demo else capabilities.get("tools")
    payload = {
        "configured": True,
        "id": entry["id"],
        "name": entry.get("name") or entry.get("model"),
        "demo": demo,
        "has_key": has_key,
        "tools": tools,
        "capability_checked_at": capabilities.get("checked_at"),
        "capability_error": capabilities.get("error_code"),
    }
    issues: list[dict[str, Any]] = []
    if not has_key:
        issues.append({"component": "model", "code": "provider_key_missing", "message": "This model has no API key stored.", "retryable": False})
    elif not demo and tools is None:
        issues.append({"component": "model", "code": "model_tools_unproven", "message": "Probe this model before allowing tasks that change files.", "retryable": True})
    elif tools is False:
        issues.append({"component": "model", "code": "model_tools_unavailable", "message": "This model did not confirm tool calls, so tasks that change files stay disabled.", "retryable": False})
    return payload, issues


def _workspace(request: Request) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        workspace = _state(request).workspace
    except Exception:  # noqa: BLE001 - no workspace is a normal state, not a crash
        return {"open": False, "name": None}, {"component": "workspace", "code": "workspace_closed", "message": "No workspace is open. Choose a project folder first.", "retryable": True}
    data = settings.load()
    return {"open": True, "name": settings.workspace_name(data, str(workspace.root))}, None


@router.get("/readiness")
def readiness(request: Request) -> dict[str, Any]:
    engine = _engine()
    schema, schema_issue = _schema()
    runtime, runtime_issue = _runtime()
    worker = _worker()
    model, model_issues = _model()
    workspace, workspace_issue = _workspace(request)
    issues = [issue for issue in (schema_issue, runtime_issue, workspace_issue, *model_issues) if issue is not None]
    base_ready = bool(engine.get("ok")) and bool(schema.get("ok")) and bool(workspace.get("open")) and bool(model.get("configured")) and bool(model.get("has_key"))
    can_chat = base_ready
    # A write needs all of: a real sandbox, a workspace, and a model that
    # actually confirmed tool calls. The legacy runner remains read-only.
    can_write = base_ready and bool(runtime.get("available")) and model.get("tools") is True
    if can_write:
        reason = "The sandbox is ready."
    elif not workspace.get("open"):
        reason = "No workspace is open. Choose a project folder first."
    elif not model.get("configured") or not model.get("has_key"):
        reason = "Connect a model first. Without one, no task can start."
    elif model.get("tools") is not True:
        reason = "This model did not confirm tool calls. Tasks can read and explain, but cannot change the project."
    elif not runtime.get("available"):
        reason = str(runtime.get("reason") or "The Docker sandbox is not available.")
    else:
        reason = "The sandbox is not ready yet."
    return {
        "engine": engine,
        "schema": schema,
        "runtime": runtime,
        "worker": worker,
        "model": model,
        "workspace": workspace,
        "task": {
            "can_chat": can_chat,
            "can_execute": can_write,
            "can_write": can_write,
            "mode": "sandbox" if can_write else "read_only",
            "reason": reason,
        },
        # The legacy runner is deliberately honest: even a ready runtime does
        # not turn it into a writer until the task controller (T006) is wired.
        "legacy_runs": {"mode": "read_only", "reason": "The legacy runner never writes; the task controller owns execution."},
        "issues": issues,
    }


@router.post("/runtime/prepare")
def prepare_runtime(body: PrepareRuntime) -> dict[str, Any]:
    """Build the sandbox image after explicit consent. The command is fixed."""
    if not body.consent:
        raise ApiError("consent_required", "Building the sandbox image needs your explicit consent.", status_code=400)
    runtime = DockerRuntime()
    try:
        result = runtime.build_image(DEFAULT_BASE_IMAGE)
    except RuntimeUnavailable as error:
        raise ApiError("runtime_unavailable", str(error), status_code=503, retryable=True) from error
    return {"runtime": runtime.capability().as_dict(), "build": result}
