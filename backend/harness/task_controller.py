"""The task controller: propose a plan, then execute only the approved one.

One graph exists per task thread. The controller never builds a second loop:
it asks the existing `Runner` to stream, and `RunManager` pumps that stream in
the background so a browser can connect and disconnect without stopping work.

The phases are deliberately separate:

    propose(task)   read-only inspection -> write_todos -> awaiting_plan
    decide(...)     the user approves one exact revision
    execute(task)   a new segment on the same thread, gated on that approval
    resume(...)     continues an interrupted segment on the same thread

A restart does not execute anything by itself: `execute` reads the stored
approval before opening a segment, so an unapproved plan simply stays waiting.
Budgets are never reset; the counters in `execution_budgets` are shared by every
segment and are updated with the monotonic duration of the segment that ran.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from langchain_core.tools import BaseTool

from .config import Limits, ModelSpec, RunRequest
from .events import Event
from .hooks.plan import PlanGate
from .task_events import TaskEventRecorder
from .worktrees.coordination import serialize_entry

PLAN_PROMPT = (
    "Respond to the user's latest message first. A greeting, general question, explanation, "
    "or clarification can be answered directly: do not read project files, load unrelated skills "
    "or create a plan merely because tools exist. Ask one short question if essential context is missing. "
    "Only for a requested code change or repository-specific investigation, inspect the minimum relevant "
    "files with read-only tools and propose concrete steps using write_todos. Do not change files yet."
    " For a new standalone file, propose one short step; do not inspect unrelated documents or create a long plan."
)

EXECUTE_PROMPT = (
    "The plan for this task is approved. Execute the approved plan now, keeping each todo's status current. "
    "Do not replace the plan with a materially different one; if that is necessary, stop and explain."
    " Keep existing todo titles unchanged when updating progress. If permission blocks an action, explain once and stop; do not change todos or retry it."
)


class TaskControllerError(RuntimeError):
    """A refusal that the HTTP layer can turn into an ApiError without guessing."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        current_revision: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.current_revision = current_revision
        self.details = details or {}


class TaskController:
    def __init__(
        self,
        manager: Any,
        store: Any,
        *,
        model_resolver: Callable[[], ModelSpec | None],
        extra_tools: Sequence[BaseTool] = (),
    ) -> None:
        self.manager = manager
        self.store = store
        self.model_resolver = model_resolver
        self.extra_tools = tuple(extra_tools)

    # ── public ────────────────────────────────────────────────────────────────

    @serialize_entry
    def propose(self, task_id: str, instruction: str | None = None) -> dict[str, Any]:
        """Inspect and propose, without any mutating capability.

        `instruction` is the user's correction after a plan was shown. It is a
        new read-only pass on the same thread; approval of the old revision is
        withdrawn first so nothing can execute while the revision is in flight.
        """
        task = self._task(task_id)
        self._idle(task)
        if task["status"] in {"closed", "failed", "cancelled"}:
            raise TaskControllerError("conflict", "This task is finished.", details={"status": task["status"]})
        if instruction:
            self.store.clear_plan_approval(task_id, reason="revision_requested")
        gate = PlanGate(self.store, task_id)
        # Resolve the model and the remaining budget before moving the task:
        # a missing model must not leave it stuck in `planning`.
        prompt = PLAN_PROMPT if not instruction else f"{PLAN_PROMPT}\n\nUser correction: {instruction}"
        request = self._request(task, prompt, mode="read_only", phase="plan")
        run_id = self.store.latest_run_id(task_id)
        self.store.set_task_status(task_id, "planning", reason="plan_proposal")
        self.manager.launch(
            task["thread_id"],
            self._settle(task, phase="plan", run_id=run_id, stream=self.manager.runner.start(request, plan_gate=gate)),
        )
        return self.store.task(task_id)

    def approve(self, task_id: str, expected_revision: int) -> dict[str, Any]:
        plan = self.store.decide_plan(task_id, expected_revision=expected_revision, approve=True)
        return plan

    def reject(self, task_id: str, expected_revision: int) -> dict[str, Any]:
        plan = self.store.decide_plan(task_id, expected_revision=expected_revision, approve=False)
        if self.store.task(task_id)["status"] not in {"closed", "failed", "cancelled"}:
            self.store.set_task_status(task_id, "awaiting_plan", reason="plan_rejected")
        return plan

    @serialize_entry
    def execute(self, task_id: str) -> dict[str, Any]:
        """Open a new segment on the same thread, only for the approved revision."""
        task = self._task(task_id)
        self._idle(task)
        if task["status"] in {"closed", "failed", "cancelled"}:
            raise TaskControllerError("conflict", "This task is finished.", details={"status": task["status"]})
        plan = self.store.plan(task_id)
        if plan is None:
            raise TaskControllerError("action_not_approved", "There is no plan to execute.", current_revision=0)
        if plan["approved_revision"] != plan["revision"]:
            raise TaskControllerError(
                "action_not_approved",
                "The plan has not been approved, or it changed after approval.",
                current_revision=plan["revision"],
            )
        gate = PlanGate(self.store, task_id)
        mode = "read_only" if task["read_only"] else task["mode"]
        request = self._request(task, EXECUTE_PROMPT, mode=mode, phase="execute")
        run = self.store.start_segment(task_id)
        self.manager.launch(task["thread_id"], self._settle(task, phase="execute", run_id=run["id"], stream=self.manager.runner.start(request, plan_gate=gate)))
        return self.store.task(task_id)
    @serialize_entry
    def resume(self, task_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Continue after an approval pause, on the same thread and the same plan."""
        task = self._task(task_id)
        self._idle(task)
        plan = self.store.plan(task_id)
        if plan is None or plan["approved_revision"] != plan["revision"]:
            raise TaskControllerError("action_not_approved", "The plan is no longer approved.", current_revision=plan["revision"] if plan else 0)
        gate = PlanGate(self.store, task_id)
        mode = "read_only" if task["read_only"] else task["mode"]
        request = self._request(task, task["prompt"], mode=mode, phase="execute")
        runs = task["runs"]
        run_id = runs[-1]["id"] if runs else None
        # Resuming continues the same run segment; only the state moves.
        self.store.set_task_status(task_id, "executing", reason="resumed")
        self.manager.launch(task["thread_id"], self._settle(task, phase="execute", run_id=run_id, stream=self.manager.runner.resume(request, decisions, plan_gate=gate)))
        return self.store.task(task_id)

    def stop(self, task_id: str) -> bool:
        task=self._task(task_id)
        if task['status'] in {'closed','failed','cancelled','recovery_required','paused'}:return False
        self.store.set_task_status(task_id,'stopping',reason='stop_requested')
        with self.store.db.write() as db:
            db.execute("UPDATE approvals SET state='cancelled' WHERE task_id=? AND action_id IN (SELECT operation_id FROM actions WHERE task_id=? AND state IN ('pending','awaiting_approval'))",(task_id,task_id))
            db.execute("UPDATE actions SET state='denied' WHERE task_id=? AND state IN ('pending','awaiting_approval')",(task_id,))
            db.execute('UPDATE grants SET revoked_at=? WHERE task_id=? AND revoked_at IS NULL',(time.time(),task_id))
        try:
            accepted=bool(self.manager.runner.stop(task['thread_id']))
        except Exception as error:
            self.store.set_task_status(task_id,'recovery_required',reason='stop_not_confirmed')
            raise TaskControllerError('recovery_required','The runtime could not confirm the stop.') from error
        if accepted:return True  # stopping is a request receipt, never stopped proof
        if self.manager.is_running(task['thread_id']):return False  # segment is settling its final receipt
        with self.store.db.read() as db:
            uncertain=db.execute("SELECT 1 FROM actions WHERE task_id=? AND state IN ('unknown','dispatching','running') LIMIT 1",(task_id,)).fetchone()
        current=self.store.task(task_id)
        if current['status'] in {'closed','failed','cancelled','recovery_required'}:return False
        if not uncertain and task['status'] in {'draft','queued','awaiting_plan','awaiting_action','awaiting_decision','paused_limit'}:
            self.store.set_task_status(task_id,'paused',outcome='stopped_by_user',reason='stopped_by_user')
        else:
            self.store.set_task_status(task_id,'recovery_required',reason='runtime_missing_during_stop')
        return False

    # ── internals ─────────────────────────────────────────────────────────────

    def _task(self, task_id: str) -> dict[str, Any]:
        try:
            return self.store.task(task_id)
        except Exception as error:  # ApiError is a storage concern here
            if getattr(error, "code", None) == "not_found":
                raise TaskControllerError("not_found", "Task not found.", status_code=404) from error
            raise

    def _idle(self, task: dict[str, Any]) -> None:
        if task['status']=='recovery_required':
            raise TaskControllerError('recovery_required','Resolve the pending recovery before continuing.')
        if self.manager.is_running(task["thread_id"]):
            raise TaskControllerError("workspace_busy", "This task is already running.")
        worker=self.store.worker_lease()
        if worker and worker['owner']!='task:'+task['id']:
            raise TaskControllerError('workspace_busy','Another operation holds the shared worker; retry after it finishes.')
        with self.store.db.read() as db:
            if db.execute("SELECT 1 FROM apply_operations WHERE task_id=? AND state IN ('prepared','applying','unknown','partial') LIMIT 1",(task['id'],)).fetchone():
                raise TaskControllerError('recovery_required','An apply operation needs reconciliation before continuing.')
            if db.execute("SELECT 1 FROM actions WHERE task_id=? AND (invocation_key LIKE 'manual-edit:%' OR invocation_key LIKE 'candidate-check:%' OR invocation_key LIKE 'restore:%' OR invocation_key LIKE 'skill-repin:%') AND state IN ('dispatching','running','unknown') LIMIT 1",(task['id'],)).fetchone():
                raise TaskControllerError('recovery_required','A human file operation needs reconciliation before continuing.')

    def _request(self, task: dict[str, Any], prompt: str, *, mode: str, phase: str) -> RunRequest:
        model = self.model_resolver()
        if model is None:
            raise TaskControllerError("runtime_unavailable", "No model is configured.", status_code=503)
        budget = self.store.budget(task["id"])
        remaining_ms = budget["max_active_ms"] - budget["active_ms"]
        if remaining_ms <= 0:
            raise TaskControllerError("budget_exhausted", "The execution budget is used up.", current_revision=budget["revision"])
        limits = Limits(
            max_model_calls=max(1, budget["max_model_calls"] - budget["model_calls"]),
            max_tool_calls=max(1, budget["max_tool_calls"] - budget["tool_calls"]),
            max_seconds=max(1, remaining_ms // 1000),
        )
        initial=self.store.messages(task['id'])
        references=initial[0].get('references',[]) if initial else []
        goal=f"User task:\n{task['prompt']}"
        if task['read_only']:
            goal+='\n\nThis task is read-only. Answer directly in chat, including requested code. Do not propose creating files or promise file changes. Explain once that saving files needs editing enabled.'
        if references:goal+='\n\nUser reference files:\n'+'\n'.join('- '+path for path in references)
        if phase=='execute':
            from .command_context import saved_profile
            commands=[row['command'] for row in saved_profile(self.store,task).get('commands',[]) if row.get('required')]
            if commands:
                import json
                goal+='\n\nRequired checks (execute cwd=/workspace; call each exact string without cd or wrappers, before editing for baseline and again after changes):\n'+json.dumps(commands,ensure_ascii=False)
        return RunRequest(thread_id=task["thread_id"], prompt=goal+'\n\n'+prompt, model=model, mode=mode, limits=limits, phase=phase)  # type: ignore[arg-type]

    async def _settle(self, task: dict[str, Any], *, phase: str, stream: AsyncIterator[Event], run_id: str | None = None) -> AsyncIterator[Event]:
        """Pass the run through unchanged, then account for it and set the task state."""
        started = time.monotonic()
        stop_reason: str | None = None
        summary: dict[str, Any] = {}
        recorder = TaskEventRecorder(self.store, task["id"], run_id or self.store.latest_run_id(task["id"]))
        with self.store.db.write() as db:
            db.execute("UPDATE runs SET state='active',started_at=COALESCE(started_at,?),ended_at=NULL WHERE id=?",(time.time(),recorder.run_id))
        finished_normally = False
        try:
            if self.store.task(task['id'])['status']=='stopping':
                stop_reason='stopped_by_user';finished_normally=True
                return
            async for event in stream:
                recorder.record(event)
                if event.type == "run_finished":
                    stop_reason = event.data.get("stop_reason")
                    summary = event.data
                yield event
            finished_normally = True
        finally:
            recorder.finish(stop_reason if finished_normally else "error")
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            exhausted = False
            try:
                self.store.consume(
                    task["id"],
                    active_ms=0 if summary.get('budget_recorded') else elapsed_ms,
                    model_calls=0 if summary.get('budget_recorded') else int(summary.get("model_calls") or 0),
                    tool_calls=0 if summary.get('budget_recorded') else int(summary.get("tool_calls") or 0),
                )
            except Exception as error:  # budget_exhausted already persisted paused_limit
                exhausted = getattr(error, "code", None) == "budget_exhausted"
                if not exhausted:
                    raise
            if not exhausted:
                self._finish(task["id"], phase=phase, stop_reason=stop_reason)
            with self.store.db.write() as db:
                db.execute('UPDATE runs SET state=?,ended_at=? WHERE id=?',(self.store.task(task['id'])['status'],time.time(),recorder.run_id))

    def _finish(self, task_id: str, *, phase: str, stop_reason: str | None) -> None:
        task = self.store.task(task_id)
        if task["status"] in {"closed", "failed", "cancelled", "paused_limit", "recovery_required"}:
            return
        if stop_reason=='stopped_by_user':
            self.store.set_task_status(task_id,'paused',outcome='stopped_by_user',reason='stopped_by_user')
            return
        plan = self.store.plan(task_id)
        if phase == "plan":
            if stop_reason == "error":
                self.store.set_task_status(task_id, "failed", outcome="error", reason="plan_failed")
            elif plan is not None and plan['steps'] and all(step.get('status')=='completed' for step in plan['steps']) and stop_reason=='completed':
                self.store.set_task_status(task_id, 'closed', outcome='completed', reason='answered_without_new_plan')
            elif plan is not None:
                if stop_reason in {None,'completed'}:
                    from .skill_repin import finish_replan
                    finish_replan(self.store,task_id)
                self.store.set_task_status(task_id, "awaiting_plan", reason="plan_proposed")
            elif stop_reason == "completed":
                self.store.set_task_status(task_id, "closed", outcome="completed", reason="answered_without_plan")
            else:
                self.store.set_task_status(task_id, "paused", reason=stop_reason or "paused")
            return

        if stop_reason == 'permission_required':
            self.store.set_task_status(task_id,'awaiting_decision',reason='permission_required')
        elif plan is not None and plan["approved_revision"] != plan["revision"]:
            self.store.set_task_status(task_id, "awaiting_plan", reason="plan_changed")
        elif stop_reason == "awaiting_approval":
            self.store.set_task_status(task_id, "awaiting_action", reason="approval_required")
        elif stop_reason == "quality_decision":
            self.store.set_task_status(task_id, "awaiting_decision", reason="quality_requires_human_decision")
        elif stop_reason == "completed":
            from .task_runtime import task_directory,runtime_descriptor
            from .verification.observe import current_quality
            working=task_directory(self.store,task_id)/'working'
            descriptor=runtime_descriptor(self.store,task_id)
            quality=None if task['read_only'] else current_quality(self.store,task_id,working if working.is_dir() else None,descriptor['runtime_id'] if descriptor else 'unavailable')
            if quality is not None and quality['quality_status']!='verified_snapshot':
                self.store.set_task_status(task_id,'awaiting_decision',reason='required_checks_not_verified')
            else:
                self.store.set_task_status(task_id, "closed", outcome="completed", reason="completed")
        elif stop_reason == "stopped_by_user":
            self.store.set_task_status(task_id, "paused", outcome="stopped_by_user", reason="stopped_by_user")
        elif stop_reason == "error":
            self.store.set_task_status(task_id, "failed", outcome="error", reason="run_error")
        else:
            self.store.set_task_status(task_id, "paused", reason=stop_reason or "paused")
