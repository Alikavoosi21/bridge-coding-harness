"""Turn runtime events into the canonical product journal.

The harness speaks in `run_started`, `text`, `tool_started` and so on. The UI
speaks the API contract: `message_started`, `text_delta`, `action_started`, ...
This module is the one bridge between them. It writes every converted event to
product storage inside the same journal the plan/state events use, so the SSE
endpoint can replay a segment after a reconnect without asking the runtime to
run anything again.

Two rules kept here on purpose:

- a text offset counts Unicode code points, matching Python ``len`` and the
  projector's ``Array.from``; a reconnect therefore never appends a word twice;
- ``finish`` ends a *message segment*, not the task. The task state is written
  separately by the controller after the run settles.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .events import Event

_WRITE_TOOLS = {"write_file", "create_file", "edit_file", "apply_patch"}


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _finish_reason(stop_reason: str | None) -> str:
    if stop_reason in {"awaiting_approval", "stopped_by_user"}:
        return "interrupted"
    if stop_reason == "error":
        return "error"
    if stop_reason in {"model_call_limit", "tool_call_limit", "time_limit", "cost_limit", "circuit_open"}:
        return "length"
    return "stop"


class TaskEventRecorder:
    """Write one run's events into a task's durable journal."""

    def __init__(self, store: Any, task_id: str, run_id: str | None) -> None:
        self.store = store
        self.task_id = task_id
        self.run_id = run_id
        self.message_id: str | None = None
        self.part_id: str | None = None
        self.offset = 0
        self.messages = 0
        self.closed = False

    # ── public ────────────────────────────────────────────────────────────────

    def record(self, event: Event) -> None:
        handler = getattr(self, f"_on_{event.type}", None)
        if handler is not None:
            handler(event.data)

    def finish(self, stop_reason: str | None) -> None:
        """Close the open assistant message, once, when the segment settles."""
        if self.closed:
            return
        self.closed = True
        if self.message_id is None or self.part_id is None:
            return
        self._emit(
            "message_finished",
            {
                "message_id": self.message_id,
                "part_id": self.part_id,
                "finish_reason": _finish_reason(stop_reason),
            },
        )

    # ── runtime events ────────────────────────────────────────────────────────

    def _on_text(self, data: dict[str, Any]) -> None:
        if self.closed:
            return
        delta = str(data.get("text") or "")
        if not delta:
            return
        if self.message_id is None:
            self._start_message()
        assert self.part_id is not None
        self._emit(
            "text_delta",
            {
                "message_id": self.message_id,
                "part_id": self.part_id,
                "offset": self.offset,
                "delta": delta,
            },
        )
        self.offset += len(delta)

    def _on_tool_started(self, data: dict[str, Any]) -> None:
        call_id = data.get("call_id")
        if not call_id:
            return
        operation=self.store.action_by_invocation(self.task_id,'tool:'+str(call_id))
        self._emit(
            "action_started",
            {
                "operation_id": operation['operation_id'] if operation else f"op_{call_id}",
                "action_id": str(call_id),
                "tool": str(data.get("tool") or ""),
                "state": "running",
                "summary": self._summary(data.get("args")),
            },
        )

    def _on_tool_finished(self, data: dict[str, Any]) -> None:
        call_id = data.get("call_id")
        if not call_id:
            return
        if self.store.action_by_invocation(self.task_id,'tool:'+str(call_id)):
            return  # gateway commits the canonical result, including unknown
        self._emit(
            "action_finished",
            {
                "operation_id": f"op_{call_id}",
                "action_id": str(call_id),
                "tool": str(data.get("tool") or ""),
                "state": "succeeded" if data.get("ok") else "failed",
                "summary": str(data.get("output") or "")[:600] or None,
            },
        )

    def _on_file_changed(self, data: dict[str, Any]) -> None:
        path = str(data.get("path") or data.get("tool") or "")
        if not path:
            return
        self._emit(
            "file_changed",
            {
                "file_id": f"file_{_digest(path)}",
                "path": path,
                "change_kind": "modified",
            },
        )

    def _on_approval_required(self, data: dict[str, Any]) -> None:
        from server.storage.approvals import ApprovalStore
        durable = ApprovalStore(self.store).list(self.task_id)
        for action in data.get("actions") or []:
            if not isinstance(action, dict):
                continue
            args = action.get("args") or {}
            if any(row['request'] and row['request']['tool']==action.get('tool') and row['request']['args']==args for row in durable):
                continue  # gateway already committed the real approval_id
            approval_id = f"approval_{_digest([action.get('tool'), args])}"
            scope = []
            for key in ("file_path", "path"):
                value = args.get(key) if isinstance(args, dict) else None
                if isinstance(value, str) and value:
                    scope.append(value)
            self._emit(
                "approval_required",
                {
                    "approval_id": approval_id,
                    "action_hash": _digest(args),
                    "tool": action.get("tool"),
                    "summary": action.get("description") or None,
                    "scope": scope,
                },
            )

    def _on_verification(self, data: dict[str, Any]) -> None:
        problems = [str(item) for item in data.get("problems") or []]
        self._emit(
            "repair_started",
            {
                "repair_index": int(data.get("round") or 1),
                "reason": problems[0] if problems else None,
            },
        )

    def _on_run_finished(self, data: dict[str, Any]) -> None:
        self.finish(str(data.get("stop_reason") or "completed"))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _start_message(self) -> None:
        self.messages += 1
        self.offset = 0
        self.message_id = f"msg_{uuid.uuid4().hex[:16]}"
        self.part_id = f"{self.message_id}:text"
        self._emit(
            "message_started",
            {"message_id": self.message_id, "part_id": self.part_id, "message_index": self.messages},
        )

    def _emit(self, type_: str, payload: dict[str, Any]) -> None:
        self.store.record_event(self.task_id, type_, payload, run_id=self.run_id)

    @staticmethod
    def _summary(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value[:300]
        try:
            return json.dumps(value, ensure_ascii=False)[:300]
        except (TypeError, ValueError):
            return str(value)[:300]
