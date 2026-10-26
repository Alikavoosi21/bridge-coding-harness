"""Plans: edit one revision, then approve or reject exactly that revision.

The plan is product state, not a checkpoint: a restart, a new segment and a
reconnect all read the same row. Editing is revision-checked so two tabs cannot
silently overwrite each other. Approval is bound to the revision the user saw;
a later material edit clears it and revokes grants in the same transaction.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Path, Response
from pydantic import BaseModel, Field

from ..storage import Store

router = APIRouter(tags=["plans"])

TaskId = Annotated[str, Path(min_length=1, max_length=80)]


class PlanStep(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "in_progress", "completed"] = "pending"
    detail: str | None = Field(default=None, max_length=4000)


class PatchPlan(BaseModel):
    expected_revision: int = Field(ge=0)
    steps: list[PlanStep] = Field(min_length=1)
    scope: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class PlanDecision(BaseModel):
    decision: Literal["approve", "reject"]
    expected_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, max_length=200)


def _store() -> Store:
    return Store()


def _state(request: Request) -> AppState:
    return request.app.state.harness


@router.patch("/tasks/{task_id}/plan")
def update_plan(task_id: TaskId, body: PatchPlan) -> dict[str, Any]:
    """Write a new plan revision. A material edit clears approval and grants."""
    store = _store()
    plan = store.save_plan(
        task_id,
        expected_revision=body.expected_revision,
        steps=[step.model_dump(exclude_none=True) for step in body.steps],
        scope=body.scope,
        checks=body.checks,
    )
    return {"plan": plan, "task": store.task(task_id)}


@router.post("/tasks/{task_id}/plan-decisions")
def decide_plan(
    task_id: TaskId,
    body: PlanDecision,
    response: Response,
    header_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Approve or reject the exact revision the caller read.

    Deciding twice with the same key and body returns the first answer; the
    same key with a different body is a conflict. Approval does not start work
    by itself: the controller opens a segment only when asked to execute, and
    only while the approved revision is still current.
    """
    store = _store()
    key = body.idempotency_key or header_key

    def handler() -> tuple[int, dict[str, Any]]:
        plan = store.decide_plan(task_id, expected_revision=body.expected_revision, approve=body.decision == "approve")
        return 200, {"plan": plan, "task": store.task(task_id)}

    if not key:
        return handler()[1]
    status, payload, replayed = store.run_idempotent(
        key,
        {"endpoint": "POST /tasks/{task_id}/plan-decisions", "task_id": task_id, **body.model_dump(exclude={"idempotency_key"})},
        handler,
    )
    response.status_code = status
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payload
