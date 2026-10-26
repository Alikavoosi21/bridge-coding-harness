"""Plan gate: no file change or command runs before the current plan is approved.

The plan lives in product storage, not in the model's conversation. A hook that
only trusted the checkpoint would let a restarted process continue with a plan
the user edited or never approved. So every mutating call asks the gate for the
revision pair (current, approved) at the moment it is about to run.

`write_todos` is allowed: proposing or updating a plan is how a plan is made.
Every other changing tool is stopped unless ``approved_revision == revision``.
A material plan change clears the approval and revokes grants in the same
transaction, so this single comparison is enough.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from ..permissions import WRITE_TOOLS

# The shell is not in WRITE_TOOLS because it is a tool, not a file operation.
MUTATING_TOOLS = WRITE_TOOLS | {"execute"}


class PlanSource(Protocol):
    """The two operations the gate needs, kept free of storage imports."""

    def plan(self, task_id: str) -> dict[str, Any] | None: ...

    def save_plan(self, task_id: str, *, steps: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]: ...


class PlanGate:
    """One task's plan, read fresh before every mutation."""

    def __init__(self, store: PlanSource, task_id: str) -> None:
        self.store = store
        self.task_id = task_id

    def denial(self) -> str | None:
        from ..skill_repin import require_fresh_plan
        try:require_fresh_plan(self.store,self.task_id)
        except Exception as error:
            if getattr(error,'code',None) in {'action_not_approved','recovery_required'}:return str(error)
            raise
        plan = self.store.plan(self.task_id)
        if plan is None:
            return "There is no plan yet. Inspect the workspace with read-only tools and call write_todos first; wait for the user to approve it."
        if plan["approved_revision"] != plan["revision"]:
            return (
                "This plan is not approved, or it changed after approval. "
                "Do not change files or run commands; explain what you would do and wait for the user."
            )
        return None

    def record_todos(self, todos: Any) -> None:
        """Persist the model's todo list without losing what the user approved.

        A progress update carries only the steps. Scope, checks and profile come
        from the stored plan, and the revision the hook read is passed back: if
        the user edited the plan while this step was running, the old progress
        must not overwrite the newer revision.
        """
        if not isinstance(todos, list) or not todos:
            return
        plan = self.store.plan(self.task_id)
        if plan is None:
            self.store.save_plan(self.task_id, steps=todos)
            return
        try:
            profile_hash=plan['profile_hash']
            if plan.get('approved_revision') is None and hasattr(self.store,'task') and hasattr(self.store,'workspace'):
                from ..command_context import saved_profile
                profile_hash=saved_profile(self.store,self.store.task(self.task_id)).get('profile_hash')
            self.store.save_plan(
                self.task_id,
                steps=todos,
                scope=plan["scope"],
                checks=plan["checks"],
                profile_hash=profile_hash,
                expected_revision=plan["revision"],
            )
        except Exception as error:
            if getattr(error, "code", None) != "selection_stale":
                raise

    def approve(self) -> dict[str, Any]:
        plan = self.store.plan(self.task_id)
        if plan is None:
            raise ValueError("no plan")
        return self.store.decide_plan(self.task_id, expected_revision=plan["revision"], approve=True)


def _todos(result: Any) -> Any:
    """The todo list carried by the `write_todos` Command, or None."""
    update = getattr(result, "update", None)
    return update.get("todos") if isinstance(update, dict) else None


class PlanGateHook(AgentMiddleware):
    def __init__(self, gate: PlanGate) -> None:
        self.gate = gate

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        name = request.tool_call["name"]
        if name == "write_todos":
            result = await handler(request)
            self.gate.record_todos(_todos(result))
            return result
        if name in MUTATING_TOOLS:
            reason = self.gate.denial()
            if reason is not None:
                return ToolMessage(
                    content=f"Error: {reason}",
                    tool_call_id=request.tool_call.get("id", ""),
                    name=name,
                    status="error",
                )
        return await handler(request)
