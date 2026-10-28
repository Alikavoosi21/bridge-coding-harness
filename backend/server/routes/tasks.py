"""Tasks: the durable command surface over the product store.

The legacy `/runs` routes stay in place until the execution controller replaces
them. These routes are the new contract: a task is created once, its journal is
read from a cursor, and a finished task can be deleted only with consent.

Nothing here starts an agent. Creation writes the task, its first run segment,
its budget and the opening journal events; execution arrives with T006.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path as FilePath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request, Response

from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from harness.runtime.docker import DockerRuntime
from harness.task_controller import TaskControllerError

from .. import settings
from ..errors import ApiError
from ..state import AppState
from ..storage import Store
from ..storage.contract import LIMITS, TASK_STATES

router = APIRouter(tags=["tasks"])

TaskId = Annotated[str, Path(min_length=1, max_length=80)]

# A journal can grow while one of these states is current. Anything else is a
# stable product state: replay what is stored, then close the stream cleanly. A
# browser reconnect is a new read, not a new run.
STREAMING_STATES = {"queued", "planning", "executing", "verifying", "repairing", "stopping"}
STREAM_POLL_SECONDS = 0.35


class TaskLimits(BaseModel):
    active_ms: int | None = Field(default=None, gt=0)
    model_calls: int | None = Field(default=None, gt=0)
    tool_calls: int | None = Field(default=None, gt=0)


class StartTask(BaseModel):
    prompt: str = Field(min_length=1)
    # Left out, the open workspace is used.
    workspace_id: str | None = None
    title: str | None = Field(default=None, max_length=200)
    model_id: str | None = None
    mode: Literal["ask", "grant", "auto"] = "ask"
    # The default is safe: a task that cannot run in a sandbox may only read.
    read_only: bool = True
    limits: TaskLimits | None = None
    # Project-relative paths the prompt points at. They are stored verbatim only
    # after containment is proven against the task's workspace root.
    references: list[str] = Field(default_factory=list, max_length=50)
    idempotency_key: str | None = Field(default=None, max_length=200)


class SendMessage(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    references: list[str] = Field(default_factory=list, max_length=50)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=200)


class PlanProposal(BaseModel):
    """Start (or redo) a read-only planning pass.

    An instruction is the user's correction. It is stored as a real user
    message before the pass starts, so a reload shows exactly what was asked.
    """

    instruction: str | None = Field(default=None, max_length=20_000)
    references: list[str] = Field(default_factory=list, max_length=50)
    expected_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=200)


class Continuation(BaseModel):
    """The explicit action after plan approval: open an execution segment."""

    expected_plan_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=200)


def _store() -> Store:
    return Store()


def _state(request: Request) -> AppState:
    return request.app.state.harness


def _workspace_id(request: Request, explicit: str | None) -> str:
    """Resolve the workspace row, creating it from the open folder if needed."""
    store = _store()
    if explicit:
        return store.workspace(explicit)["id"]
    state = _state(request)
    try:
        root = str(state.workspace.root)
        name = settings.workspace_name(settings.load(), root)
    except HTTPException:  # no workspace open: fall back to the last one in settings, if it still exists
        data = settings.load()
        root = data.get("current_workspace") or ""
        name = settings.workspace_name(data, root) if root else ""
    if not root:
        raise ApiError(
            "conflict",
            "No workspace is open. Create or open one first.",
            status_code=409,
            details={"reason": "no_workspace"},
        )
    workspace = store.upsert_workspace(root, name)
    return workspace["id"]


def _require_write_capability(body: StartTask) -> None:
    """A task that may change files needs a proven model and a real sandbox.

    `read_only` defaults to true. Turning it off is not a UI preference: it
    requires a stored probe result for this model and an available Docker
    runtime. Without either, the request is refused instead of running on the
    host or pretending the model can call tools.
    """
    if body.read_only:
        return
    data = settings.load()
    model_id = body.model_id or data.get("default_model")
    entry = next((item for item in data.get("models", []) if item.get("id") == model_id), None)
    capabilities = entry.get("capabilities") if entry and isinstance(entry.get("capabilities"), dict) else {}
    if capabilities.get("tools") is not True:
        reason = "model_tools_unproven" if capabilities.get("tools") is None else "model_tools_unsupported"
        raise ApiError(
            "model_tools_unavailable",
            "This model did not confirm tool calls. The task can only run read-only.",
            status_code=409,
            details={"reason": reason, "model_id": model_id},
        )
    from harness.runtime.local import LocalRuntime
    capability = LocalRuntime().capability()
    if not capability.available:
        raise ApiError(
            "runtime_unavailable",
            capability.reason,
            status_code=409,
            retryable=True,
            details={"reason": "docker_unavailable"},
        )


def _controller_error(error: TaskControllerError) -> ApiError:
    """The controller speaks product refusals; the HTTP layer uses one error shape."""
    return ApiError(
        error.code,
        error.message,
        status_code=error.status_code,
        details=error.details,
        current_revision=error.current_revision,
    )


def _controller_call(action):  # noqa: ANN001, ANN202 - one small call adapter
    try:
        return action()
    except TaskControllerError as error:
        raise _controller_error(error) from error


def _check_task_revision(store: Store, task_id: str, expected: int | None) -> None:
    if expected is None:
        return
    task = store.task(task_id)
    if task["revision"] != expected:
        raise ApiError(
            "selection_stale",
            "This task changed after you read it. Review the current state.",
            status_code=409,
            current_revision=task["revision"],
            details={"expected_revision": expected},
        )


def _reference_paths(store: Store, workspace_id: str, references: list[str]) -> list[str]:
    """Keep references inside the task's project.

    A reference is not a permission grant. It is a path the prompt points at,
    so it must already be inside the workspace; taking a path from outside and
    silently adding the whole folder to the sandbox is exactly what v1 forbids.
    """
    if not references:
        return []
    root = FilePath(store.workspace(workspace_id)["root"]).resolve()
    kept: list[str] = []

    def refuse(raw: str, reason: str) -> ApiError:
        return ApiError(
            "invalid_request",
            "Only files inside the project can be added as a reference.",
            status_code=422,
            details={"reference": raw, "reason": reason},
        )

    for raw in references:
        text = raw.strip()
        if not text:
            raise refuse(raw, "empty")
        candidate = FilePath(text).expanduser()
        if not candidate.is_absolute():
            candidate = root / text.lstrip("/\\")
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise refuse(raw, "outside_workspace") from error
        if not resolved.exists():
            raise refuse(raw, "not_found")
        if not resolved.is_file():
            raise refuse(raw, "not_a_file")
        virtual = "/" + relative.as_posix()
        if virtual not in kept:
            kept.append(virtual)
    return kept


@router.post("/tasks", status_code=202)
def start_task(
    body: StartTask,
    request: Request,
    response: Response,
    header_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Create a task and its first run segment.

    With an idempotency key, the same key and body returns the original
    response; the same key with a different body is a 409.
    """
    _require_write_capability(body)
    store = _store()
    workspace_id = _workspace_id(request, body.workspace_id)
    references = _reference_paths(store, workspace_id, body.references)
    key = body.idempotency_key or header_key

    def handler() -> tuple[int, dict[str, Any]]:
        from ..storage.retention import require_space
        require_space(store)
        task = store.create_task(
            workspace_id=workspace_id,
            prompt=body.prompt,
            mode=body.mode,
            read_only=body.read_only,
            title=body.title,
            references=references,
        )
        if body.limits is not None:
            wanted = {name: value for name, value in body.limits.model_dump().items() if value is not None}
            if wanted:
                store.extend_budget(task["id"], task["budget"]["revision"], **wanted)
        created = store.task(task["id"])
        return 202, {
            "task": created,
            "run": created["runs"][0] if created["runs"] else None,
            "last_event_seq": created["last_event_seq"],
        }

    if not key:
        return handler()[1]
    status, payload, replayed = store.run_idempotent(
        key,
        {"endpoint": "POST /tasks", **body.model_dump(exclude={"idempotency_key"})},
        handler,
    )
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


@router.get("/tasks")
def list_tasks(
    request: Request,
    workspace_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    after: str | None = Query(default=None),
) -> dict[str, Any]:
    if status is not None and status not in TASK_STATES:
        raise ApiError("invalid_request", f"Unknown task status: {status}", status_code=422)
    store = _store()
    resolved = store.workspace(workspace_id)["id"] if workspace_id else _open_workspace_or_none(request)
    return store.list_tasks(workspace_id=resolved, status=status, limit=limit, after=after)


@router.get("/tasks/{task_id}")
def get_task(task_id: TaskId) -> dict[str, Any]:
    store = _store()
    task = store.task(task_id)
    task["worker_lease"] = store.worker_lease()
    task["workspace_lease"] = store.workspace_lease(task["workspace_id"])
    # A reload needs the exact transcript, not a second model call. The journal
    # carries changed events; both are read from the same durable store.
    task["messages"] = store.messages(task_id)
    return task


@router.get('/tasks/{task_id}/artifacts')
def task_artifacts(task_id:TaskId):
    """History discovery only: never reconstruct, dispatch, or silently clean."""
    from harness.task_runtime import task_directory
    from harness.worktrees.snapshot import _is_link_path
    store=_store();task=store.task(task_id);directory=task_directory(store,task_id)
    def available(name):
        path=directory/name
        return not _is_link_path(directory) and not _is_link_path(path) and path.is_dir()
    with store.db.read() as db:
        operations=[dict(row) for row in db.execute('SELECT id,state,created_at,updated_at FROM apply_operations WHERE task_id=? ORDER BY created_at DESC LIMIT 100',(task_id,))]
        uncertain=[dict(row) for row in db.execute("SELECT operation_id,invocation_key,state FROM actions WHERE task_id=? AND state IN ('unknown','dispatching','running') ORDER BY created_at",(task_id,))]
    return {'task_id':task_id,'status':task['status'],'working_available':available('working'),'baseline_available':available('baseline'),'apply_operations':operations,'unresolved_operations':uncertain}


@router.get('/tasks/{task_id}/recovery')
def recovery_status(task_id:TaskId):
    from harness.recovery import inspect_recovery
    return inspect_recovery(_store(),task_id)


class RecoveryStop(BaseModel):
    confirm:bool


@router.post('/tasks/{task_id}/recovery/stop-orphans')
def recovery_stop(task_id:TaskId,body:RecoveryStop,request:Request):
    from harness.recovery import stop_orphans
    if _state(request).is_running(_store().task(task_id)['thread_id']):raise ApiError('workspace_busy','The task still runs in this engine.',status_code=409)
    return stop_orphans(_store(),task_id,confirm=body.confirm)


class RecoveryKeep(BaseModel):
    confirm:bool
    expected_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/recovery/keep-current')
def recovery_keep(task_id:TaskId,body:RecoveryKeep):
    from harness.recovery import keep_current
    return {'task':keep_current(_store(),task_id,**body.model_dump())}


class RecoveryRepin(BaseModel):
    confirm:bool
    expected_working_revision:int=Field(ge=1)
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_skill_hash:str|None=Field(default=None,pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/recovery/skill-repins/{operation_id}/rollback')
def recovery_repin(task_id:TaskId,operation_id:str,body:RecoveryRepin):
    from harness.skill_repin import rollback_repin
    return rollback_repin(_store(),task_id,operation_id,**body.model_dump())


class RecoveryMigration(BaseModel):
    confirm:bool
    expected_working_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_baseline_hash:str=Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/tasks/{task_id}/recovery/migrate-snapshot')
def recovery_migrate(task_id:TaskId,body:RecoveryMigration):
    from harness.recovery import migrate_snapshot
    return {'task':migrate_snapshot(_store(),task_id,**body.model_dump())}


class StopTask(BaseModel):
    idempotency_key: str = Field(min_length=1,max_length=200)


@router.post('/tasks/{task_id}/stop')
async def stop_task(task_id: TaskId, body: StopTask, request: Request):
    store=_store()
    def handler():
        task=store.task(task_id)
        workspace=store.workspace(task['workspace_id'])
        if FilePath(workspace['root']).resolve()!=_state(request).workspace.root.resolve():
            raise ApiError('conflict','Open this task workspace before stopping.',status_code=409)
        from harness.worktrees.candidate_checks import stop_candidate
        accepted=stop_candidate(store,task_id) or _controller_call(lambda:_state(request).controller.stop(task_id))
        return 202,{'accepted':accepted,'task':store.task(task_id)}
    # Docker kill/rm may wait on child processes. Keep journal/SSE responsive.
    status,result,replayed=await asyncio.to_thread(store.run_idempotent,body.idempotency_key,{'endpoint':'stop','task_id':task_id},handler)
    return JSONResponse(result,status_code=status,headers={'Idempotent-Replayed':'true'} if replayed else None)


@router.post("/tasks/{task_id}/messages")
def send_message(
    task_id: TaskId,
    body: SendMessage,
    response: Response,
    header_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Append a message without starting a second segment.

    If a command is running, the message waits in product storage with no
    delivery receipt. `SteeringHook` hands it to the next model turn and writes
    the receipt only after the turn has it. If no run is active, the next
    `continuations` or `plan-proposals` call reads it as pending steering.
    """
    store = _store()
    task = store.task(task_id)
    _check_task_revision(store, task_id, body.expected_revision)
    references = _reference_paths(store, task["workspace_id"], body.references)
    key = body.idempotency_key or header_key

    def handler() -> tuple[int, dict[str, Any]]:
        message = store.append_message(task_id, text=body.text, references=references)
        updated = store.task(task_id)
        updated["messages"] = store.messages(task_id)
        return 200, {"message": message, "task": updated}

    if not key:
        return handler()[1]
    status, payload, replayed = store.run_idempotent(
        key,
        {"endpoint": "POST /tasks/{task_id}/messages", "task_id": task_id, **body.model_dump(exclude={"idempotency_key"})},
        handler,
    )
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


@router.post("/tasks/{task_id}/plan-proposals", status_code=202)
async def propose_plan(
    task_id: TaskId,
    body: PlanProposal,
    response: Response,
    request: Request,
    header_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Start a read-only planning pass, optionally with a correction message.

    The correction is durable before the pass starts, so the transcript and the
    model prompt agree. A proposal never mutates files: the run receives the
    read-only mode and the plan gate.
    """
    store = _store()
    task = store.task(task_id)
    instruction = (body.instruction or "").strip() or None
    references = _reference_paths(store, task["workspace_id"], body.references)
    key = body.idempotency_key or header_key

    def handler() -> tuple[int, dict[str, Any]]:
        _check_task_revision(store, task_id, body.expected_revision)
        if store.task(task_id)['status']=='closed':
            # A finished answer is not the end of a conversation. A new message
            # starts a read-only pass on the same durable thread, revoking the
            # old execution approval before considering any new request.
            store.clear_plan_approval(task_id, reason='followup_message')
            store.set_task_status(task_id, 'paused', reason='followup_message')
        message = store.append_message(task_id, text=instruction, references=references) if instruction else None
        current = _state(request).controller
        updated = _controller_call(lambda: _state(request).submit('plan',task_id,instruction))
        return 202, {"task": updated, "plan": updated.get("plan"), "message": message}

    if not key:
        return handler()[1]
    status, payload, replayed = store.run_idempotent(
        key,
        {"endpoint": "POST /tasks/{task_id}/plan-proposals", "task_id": task_id, **body.model_dump(exclude={"idempotency_key"})},
        handler,
    )
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


@router.post("/tasks/{task_id}/continuations", status_code=202)
async def continue_task(
    task_id: TaskId,
    response: Response,
    request: Request,
    body: Continuation | None = None,
    header_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Open an execution segment for the approved plan revision.

    Approval alone does not run anything. This is the separate product action
    the UI takes after the user confirms, and it re-checks the approval here.
    """
    store = _store()
    task = store.task(task_id)
    payload_body = body or Continuation()
    if payload_body.expected_plan_revision is not None:
        plan = store.plan(task_id)
        current = plan["revision"] if plan else 0
        if current != payload_body.expected_plan_revision:
            raise ApiError(
                "selection_stale",
                "The plan changed after you approved it. Review the current revision.",
                status_code=409,
                current_revision=current,
                details={"expected_revision": payload_body.expected_plan_revision},
            )
    key = payload_body.idempotency_key or header_key

    def handler() -> tuple[int, dict[str, Any]]:
        current = _state(request).controller
        updated = _controller_call(lambda: _state(request).submit('execute',task_id))
        return 202, {"task": updated, "plan": updated.get("plan"), "run": updated["runs"][-1] if updated["runs"] else None}

    if not key:
        return handler()[1]
    status, payload, replayed = store.run_idempotent(
        key,
        {"endpoint": "POST /tasks/{task_id}/continuations", "task_id": task_id, **payload_body.model_dump(exclude={"idempotency_key"})},
        handler,
    )
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload


def _sse_frame(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['event_id']}\nevent: {event['type']}\ndata: {data}\n\n"


@router.get("/tasks/{task_id}/events")
def task_events(
    task_id: TaskId,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
):
    """The durable journal from a cursor.

    JSON keeps the existing page contract. `Accept: text/event-stream` returns
    the same envelopes as SSE frames and follows the journal until the task
    leaves an active state. Reconnecting with `after_seq` replays committed
    events only; it never asks the harness to run anything.
    """
    store = _store()
    store.task(task_id)  # 404 before touching an empty journal
    if "text/event-stream" not in request.headers.get("accept", ""):
        return store.events(task_id, after_seq=after_seq, limit=limit)

    async def frames():
        cursor = after_seq
        while True:
            page = store.events(task_id, after_seq=cursor, limit=limit)
            for event in page["items"]:
                cursor = int(event["sequence"])
                yield _sse_frame(event)
            if page["items"] and len(page["items"]) >= limit:
                continue
            try:
                status = store.task(task_id)["status"]
            except ApiError:
                yield "event: error\ndata: {\"code\":\"not_found\",\"message\":\"Task not found.\"}\n\n"
                return
            if status not in STREAMING_STATES:
                yield "event: done\ndata: [DONE]\n\n"
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/tasks/{task_id}")
def delete_task(task_id: TaskId, request: Request, consent: bool = Query(default=False)) -> dict[str, bool]:
    """Delete a finished task. Active and recovery-required tasks are refused."""
    if not consent:
        raise ApiError("forbidden", "Deleting a task needs explicit consent.", status_code=403)
    if any(s['state'] in {'starting','installing','running','ready','stopping','unknown'} for s in request.app.state.harness.outputs.list(task_id)):
        raise ApiError('workspace_busy','پیش از حذف گفتگو، اجرای خروجی آن را متوقف کن.',status_code=409)
    _store().delete_task(task_id, consent=True)
    return {"deleted": True}


def _open_workspace_or_none(request: Request) -> str | None:
    try:
        root = str(_state(request).workspace.root)
    except HTTPException:
        root = settings.load().get("current_workspace") or ""
    if not root:
        return None
    workspace = _store().workspace_by_root(root)
    return workspace["id"] if workspace else None


def default_limits() -> dict[str, int]:
    """The budget ceilings a new task starts with (kept in the contract)."""
    return dict(LIMITS)
