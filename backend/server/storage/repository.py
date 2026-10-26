"""The product repository: tasks, runs, actions, budgets, leases, idempotency.

Everything here is deliberately explicit SQL. The invariants that matter are
enforced by the database (UNIQUE, partial UNIQUE indexes, CHECK) and by using a
single `BEGIN IMMEDIATE` write transaction per operation, so a second process
(or a second request in the same process) cannot interleave a read-modify-write.

Identity rules, in one place:

- `tasks.thread_id` is UNIQUE: a task has one graph thread for its lifetime.
- `runs(task_id, segment)` is UNIQUE: a new segment is a new row, not a reset.
- `actions(task_id, invocation_key)` is UNIQUE: the same logical invocation
  resolved again after resume returns the same `operation_id`.
- `actions.operation_id` is created and stored *before* dispatch. A new run does
  not create a new operation for an existing invocation, and two deliberate
  invocations of the same command have different `invocation_key`s and therefore
  different `operation_id`s - the argv hash is not identity.
- `events(task_id, sequence)` and `event_id` are UNIQUE: the journal cannot
  silently duplicate a position.
- `execution_budgets` is one row per task: counters survive pause, approval,
  reconnect, restart and a new segment.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ..errors import ApiError
from . import journal
from .contract import ACCESS_MODES, LIMITS, SCHEMA_VERSION
from .db import Database
from .migrations import migrate

_ACTIVE_TASK_STATES = {
    "draft",
    "queued",
    "planning",
    "awaiting_plan",
    "executing",
    "awaiting_action",
    "verifying",
    "repairing",
    "awaiting_decision",
    "paused_limit",
    "stopping",
    "paused",
    "recovery_required",
}


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Lease:
    id: str
    fencing_token: int


class Store:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def ensure_schema(self) -> dict[str, Any]:
        return migrate(self.db)

    # ── workspaces ────────────────────────────────────────────────────────────
    def upsert_workspace(self, root: str, name: str | None = None, profile: str | None = None) -> dict[str, Any]:
        now = _now()
        workspace_id = f"ws_{hashlib.sha1(root.encode('utf-8')).hexdigest()[:16]}"
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM workspaces WHERE root = ?", (root,)).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO workspaces (id, root, name, profile, exclusions, manifest_hash, created_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?, '[]', NULL, ?, ?)",
                    (workspace_id, root, name or root.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], profile, now, now),
                )
            else:
                workspace_id = row["id"]
                connection.execute(
                    "UPDATE workspaces SET last_seen_at = ?, name = COALESCE(?, name), profile = COALESCE(?, profile) WHERE id = ?",
                    (now, name, profile, workspace_id),
                )
        return self.workspace(workspace_id)

    def workspace(self, workspace_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if row is None:
            raise ApiError("not_found", "Workspace not found.", status_code=404)
        return _workspace(row)

    def workspace_by_root(self, root: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM workspaces WHERE root = ?", (root,)).fetchone()
        return _workspace(row) if row else None

    # ── tasks ─────────────────────────────────────────────────────────────────
    def create_task(
        self,
        *,
        workspace_id: str,
        prompt: str,
        mode: str = "ask",
        read_only: bool = False,
        thread_id: str | None = None,
        title: str | None = None,
        references: list[str] | None = None,
    ) -> dict[str, Any]:
        if mode not in ACCESS_MODES:
            raise ApiError("invalid_request", f"Unknown access mode: {mode}", status_code=422)
        thread = thread_id or uuid.uuid4().hex[:12]
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        budget_id = f"budget_{uuid.uuid4().hex[:16]}"
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        now = _now()
        auto_title = (title or (prompt.strip().splitlines()[0] if prompt.strip() else "کار تازه"))[:80]
        parts = [{"id": f"{message_id}:text", "text": prompt, "state": "done"}]
        with self.db.write() as connection:
            try:
                connection.execute(
                    "INSERT INTO tasks (id, workspace_id, thread_id, title, prompt, status, outcome, mode, read_only, revision, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'queued', NULL, ?, ?, 1, ?, ?)",
                    (task_id, workspace_id, thread, auto_title, prompt, mode, int(read_only), now, now),
                )
            except sqlite3.IntegrityError as error:
                raise ApiError("conflict", "This thread already has a task.", status_code=409, details={"thread_id": thread}) from error
            connection.execute(
                "INSERT INTO execution_budgets (id, task_id, max_active_ms, max_model_calls, max_tool_calls, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (budget_id, task_id, LIMITS["active_ms"], LIMITS["model_calls"], LIMITS["tool_calls"], now),
            )
            connection.execute(
                "INSERT INTO repair_budgets (task_id, allowed, total_attempts, revision) VALUES (?, ?, 0, 1)",
                (task_id, LIMITS["repairs_allowed"]),
            )
            connection.execute(
                "INSERT INTO runs (id, task_id, segment, state, budget_id, created_at) VALUES (?, ?, 1, 'queued', ?, ?)",
                (run_id, task_id, budget_id, now),
            )
            connection.execute(
                "INSERT INTO messages (id, task_id, role, parts, reference_paths, offset, delivered_at, created_at) VALUES (?, ?, 'user', ?, ?, 1, ?, ?)",
                (message_id, task_id, json.dumps(parts, ensure_ascii=False), json.dumps(list(references or []), ensure_ascii=False), now, now),
            )
            journal.append(connection, task_id, "task_state_changed", {"state": "queued", "reason": "created"}, run_id=run_id, occurred_at=now)
            journal.append(connection, task_id, "budget_updated", self._budget_payload(connection, task_id), run_id=run_id, occurred_at=now)
        return self.task(task_id)

    def task(self, task_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            budget = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
            runs = connection.execute("SELECT * FROM runs WHERE task_id = ? ORDER BY segment", (task_id,)).fetchall()
            plan = connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
            last = connection.execute("SELECT COALESCE(MAX(sequence), 0) AS seq FROM events WHERE task_id = ?", (task_id,)).fetchone()
        return {
            **_task(row),
            "budget": _budget(budget) if budget else None,
            "runs": [_run(item) for item in runs],
            "plan": _plan(plan) if plan else None,
            "last_event_seq": int(last["seq"]),
        }

    def task_by_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT id FROM tasks WHERE thread_id = ?", (thread_id,)).fetchone()
        return self.task(row["id"]) if row else None

    def list_tasks(self, *, workspace_id: str | None = None, status: str | None = None, limit: int = 50, after: str | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if after:
            clauses.append("created_at < (SELECT created_at FROM tasks WHERE id = ?)")
            params.append(after)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 200)))
        with self.db.read() as connection:
            rows = connection.execute(f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        return {"items": [_task(row) for row in rows], "next": rows[-1]["id"] if len(rows) == limit else None}

    # ── messages and steering ─────────────────────────────────────────────────
    def messages(self, task_id: str) -> list[dict[str, Any]]:
        with self.db.read() as connection:
            rows = connection.execute("SELECT * FROM messages WHERE task_id = ? ORDER BY offset", (task_id,)).fetchall()
        return [_message(row) for row in rows]

    def append_message(
        self,
        task_id: str,
        *,
        text: str,
        references: list[str] | None = None,
        role: str = "user",
        delivered: bool = False,
    ) -> dict[str, Any]:
        """Persist one message. `delivered_at` is the receipt that the model saw it.

        The first message of a task is written by `create_task`; later messages
        go through here. A message sent while a command runs stays undelivered
        until the steering hook hands it to the next model turn.
        """
        message_id = f"msg_{uuid.uuid4().hex[:16]}"
        now = _now()
        parts = [{"id": f"{message_id}:text", "text": text, "state": "done"}]
        with self.db.write() as connection:
            row = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            if row["status"] in {"closed", "failed", "cancelled"}:
                raise ApiError("conflict", "This task is finished.", status_code=409)
            offset = connection.execute("SELECT COALESCE(MAX(offset), 0) + 1 AS next FROM messages WHERE task_id = ?", (task_id,)).fetchone()["next"]
            connection.execute(
                "INSERT INTO messages (id, task_id, role, parts, reference_paths, offset, delivered_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (message_id, task_id, role, json.dumps(parts, ensure_ascii=False), json.dumps(list(references or []), ensure_ascii=False), offset, now if delivered else None, now),
            )
            stored = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return _message(stored)

    def pending_messages(self, task_id: str) -> list[dict[str, Any]]:
        """User messages that a running turn has not received yet, oldest first."""
        with self.db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE task_id = ? AND role = 'user' AND delivered_at IS NULL ORDER BY offset",
                (task_id,),
            ).fetchall()
        return [_message(row) for row in rows]

    def mark_messages_delivered(self, message_ids: list[str]) -> None:
        if not message_ids:
            return
        now = _now()
        with self.db.write() as connection:
            connection.executemany(
                "UPDATE messages SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL",
                [(now, message_id) for message_id in message_ids],
            )

    # ── plans ─────────────────────────────────────────────────────────────────
    def plan(self, task_id: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
        return _plan(row) if row else None

    def save_plan(
        self,
        task_id: str,
        *,
        steps: list[dict[str, Any]],
        scope: list[str] | None = None,
        checks: list[str] | None = None,
        expected_revision: int | None = None,
        profile_hash: str | None = None,
    ) -> dict[str, Any]:
        """Write the plan, or update it, as one revision-checked transaction.

        A material edit (steps, scope, checks or profile) is a new revision and
        clears the approval; every grant that depended on the old plan is
        revoked in the same transaction. A progress-only edit (a step moving
        from pending to in_progress) keeps the revision and the approval, so
        the user follows the run without approving it again.
        """
        normalized = _normalize_steps(steps)
        normalized_scope = _string_list(scope, "scope")
        normalized_checks = _string_list(checks, "checks")
        now = _now()
        with self.db.write() as connection:
            task = connection.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            if task["status"] in {"closed", "failed", "cancelled"}:
                raise ApiError("conflict", "A finished task no longer accepts plan changes.", status_code=409)
            row = connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
            current = row["revision"] if row else 0
            if expected_revision is not None and expected_revision != current:
                raise ApiError(
                    "selection_stale",
                    "The plan changed since it was read.",
                    status_code=409,
                    current_revision=current,
                    details={"expected_revision": expected_revision},
                )

            material = row is None or _plan_material(
                normalized, normalized_scope, normalized_checks, profile_hash
            ) != _plan_material(
                json.loads(row["steps"]),
                json.loads(row["scope"]),
                json.loads(row["checks"]),
                row["profile_hash"],
            )
            revision = current + 1 if material else current
            approved = None if material else row["approved_revision"]
            if row is None:
                revision = 1
            connection.execute(
                "INSERT INTO plans (task_id, revision, steps, scope, checks, profile_hash, approved_revision, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET revision = excluded.revision, steps = excluded.steps, "
                "scope = excluded.scope, checks = excluded.checks, profile_hash = excluded.profile_hash, "
                "approved_revision = excluded.approved_revision, updated_at = excluded.updated_at",
                (
                    task_id,
                    revision,
                    json.dumps(normalized, ensure_ascii=False),
                    json.dumps(normalized_scope, ensure_ascii=False),
                    json.dumps(normalized_checks, ensure_ascii=False),
                    profile_hash,
                    approved,
                    now,
                ),
            )
            plan = _plan(connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone())
            journal.append(connection, task_id, "plan_updated", _plan_payload(plan), occurred_at=now)
            if material:
                # Permission is tied to the plan that was approved. Any new
                # material revision revokes it before the agent can act again.
                connection.execute(
                    "UPDATE grants SET revoked_at = ? WHERE task_id = ? AND revoked_at IS NULL",
                    (now, task_id),
                )
                if task["status"] not in {"planning", "awaiting_plan"}:
                    connection.execute(
                        "UPDATE tasks SET status = 'awaiting_plan', revision = revision + 1, updated_at = ? WHERE id = ?",
                        (now, task_id),
                    )
                    journal.append(
                        connection,
                        task_id,
                        "task_state_changed",
                        {"state": "awaiting_plan", "reason": "plan_changed"},
                        occurred_at=now,
                    )
        return plan

    def decide_plan(self, task_id: str, *, expected_revision: int, approve: bool) -> dict[str, Any]:
        """Approve or reject the exact plan revision the caller saw."""
        if approve:
            from harness.skill_repin import require_fresh_plan
            require_fresh_plan(self,task_id)
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "This task has no plan yet.", status_code=404)
            if row["revision"] != expected_revision:
                raise ApiError(
                    "selection_stale",
                    "The plan changed since it was read.",
                    status_code=409,
                    current_revision=row["revision"],
                    details={"expected_revision": expected_revision},
                )
            approved = row["revision"] if approve else None
            workspace_profile=connection.execute('SELECT w.profile FROM workspaces w JOIN tasks t ON t.workspace_id=w.id WHERE t.id=?',(task_id,)).fetchone()[0]
            profile=json.loads(workspace_profile) if workspace_profile else {}
            profile_hash=profile.get('profile_hash')
            if approve and row['profile_hash'] is not None and row['profile_hash']!=profile_hash:
                raise ApiError('selection_stale','Verification profile changed; revise the plan before approving.',status_code=409,current_revision=row['revision'])
            pinned_profile=profile_hash if approve else row['profile_hash']
            if row["approved_revision"] != approved or row['profile_hash']!=pinned_profile:
                connection.execute(
                    "UPDATE plans SET approved_revision = ?, profile_hash=?, updated_at = ? WHERE task_id = ?",
                    (approved, pinned_profile, now, task_id),
                )
            plan = _plan(connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone())
            journal.append(connection, task_id, "plan_updated", _plan_payload(plan), occurred_at=now)
        return plan

    def clear_plan_approval(self, task_id: str, *, reason: str = "plan_revision_requested") -> dict[str, Any] | None:
        """A request to revise the plan withdraws approval before the new pass.

        Waiting for the model to maybe change a step is too late: the old
        revision must not stay executable while the user is asking for
        something else. Grants tied to that approval are revoked in the same
        transaction.
        """
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            if row["approved_revision"] is not None:
                connection.execute(
                    "UPDATE plans SET approved_revision = NULL, updated_at = ? WHERE task_id = ?",
                    (now, task_id),
                )
                connection.execute(
                    "UPDATE grants SET revoked_at = ? WHERE task_id = ? AND revoked_at IS NULL",
                    (now, task_id),
                )
            plan = _plan(connection.execute("SELECT * FROM plans WHERE task_id = ?", (task_id,)).fetchone())
            journal.append(connection, task_id, "plan_updated", _plan_payload(plan), occurred_at=now)
        return plan

    def set_task_status(self, task_id: str, status: str, *, outcome: str | None = None, reason: str | None = None) -> dict[str, Any]:
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT revision FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            revision = row["revision"] + 1
            connection.execute(
                "UPDATE tasks SET status = ?, outcome = COALESCE(?, outcome), revision = ?, updated_at = ? WHERE id = ?",
                (status, outcome, revision, now, task_id),
            )
            journal.append(connection, task_id, "task_state_changed", {"state": status, "reason": reason, "revision": revision, **({'outcome':outcome} if outcome is not None else {})}, occurred_at=now)
        return self.task(task_id)

    def close_task(self, task_id: str, outcome: str = "closed") -> dict[str, Any]:
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT status, revision FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            revision = row["revision"] + 1
            connection.execute(
                "UPDATE tasks SET status = 'closed', outcome = ?, revision = ?, updated_at = ? WHERE id = ?",
                (outcome, revision, now, task_id),
            )
            connection.execute("UPDATE grants SET revoked_at = ? WHERE task_id = ? AND revoked_at IS NULL", (now, task_id))
            journal.append(connection, task_id, "task_state_changed", {"state": "closed", "reason": "closed", "revision": revision}, occurred_at=now)
        return self.task(task_id)

    def delete_task(self, task_id: str, *, consent: bool = False) -> None:
        """Delete only a finished task, and never while an effect is unknown.

        Active and recovery-required tasks hold the only evidence of what may
        have happened on disk. Deleting them would destroy the record the
        operator needs, so it is refused rather than "cleaned up".
        """
        if not consent:
            raise ApiError("forbidden", "Deleting a task needs explicit consent.", status_code=403)
        with self.db.write() as connection:
            row = connection.execute("SELECT status, outcome FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            if row["status"] in _ACTIVE_TASK_STATES or row["outcome"] == "unknown":
                raise ApiError(
                    "conflict",
                    "This task still holds recovery evidence and cannot be deleted.",
                    status_code=409,
                    details={"status": row["status"], "outcome": row["outcome"]},
                )
            open_actions = connection.execute(
                "SELECT COUNT(*) AS n FROM actions WHERE task_id = ? AND state IN ('pending','dispatching','running','unknown')", (task_id,)
            ).fetchone()["n"]
            open_applies = connection.execute(
                "SELECT COUNT(*) AS n FROM apply_operations WHERE task_id = ? AND state IN ('pending','unknown')", (task_id,)
            ).fetchone()["n"]
            if open_actions or open_applies:
                raise ApiError("conflict", "Unresolved actions must be reconciled before deletion.", status_code=409)
            for table in ("events", "messages", "plans", "approvals", "grants", "file_changes", "apply_files", "skill_pins"):
                if table == "apply_files":
                    connection.execute(
                        "DELETE FROM apply_files WHERE operation_id IN (SELECT id FROM apply_operations WHERE task_id = ?)", (task_id,)
                    )
                elif table == "skill_pins":
                    connection.execute("DELETE FROM skill_pins WHERE task_id = ?", (task_id,))
                else:
                    connection.execute(f"DELETE FROM {table} WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM apply_operations WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM apply_selections WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM verification_results WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM action_run_links WHERE operation_id IN (SELECT operation_id FROM actions WHERE task_id = ?)", (task_id,))
            connection.execute("DELETE FROM actions WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM runs WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM execution_budgets WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM repair_budgets WHERE task_id = ?", (task_id,))
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # ── runs ──────────────────────────────────────────────────────────────────
    def start_segment(self, task_id: str) -> dict[str, Any]:
        """Open the next run segment. The budget row is reused, never reset."""
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            budget = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
            segment = connection.execute("SELECT COALESCE(MAX(segment), 0) + 1 AS next FROM runs WHERE task_id = ?", (task_id,)).fetchone()["next"]
            run_id = _id("run")
            revision = row["revision"] + 1
            connection.execute(
                "INSERT INTO runs (id, task_id, segment, state, budget_id, created_at) VALUES (?, ?, ?, 'active', ?, ?)",
                (run_id, task_id, segment, budget["id"], now),
            )
            connection.execute(
                "UPDATE tasks SET status = 'executing', revision = ?, updated_at = ? WHERE id = ?",
                (revision, now, task_id),
            )
            journal.append(
                connection,
                task_id,
                "task_state_changed",
                {"state": "executing", "reason": "segment_started", "segment": segment, "revision": revision},
                run_id=run_id,
                occurred_at=now,
            )
        return {"id": run_id, "task_id": task_id, "segment": segment, "state": "active"}

    def link_run(self, operation_id: str, run_id: str) -> None:
        """Record that a run participated in an operation; resumes add rows, they don't replace identity."""
        with self.db.write() as connection:
            connection.execute(
                "INSERT INTO action_run_links (operation_id, run_id, linked_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (operation_id, run_id, _now()),
            )

    # ── actions ───────────────────────────────────────────────────────────────
    def ensure_action(self, task_id: str, invocation_key: str, args_hash: str, *, origin_run_id: str | None = None, tool_call_id: str | None = None) -> dict[str, Any]:
        """Return the operation for a logical invocation, creating it once.

        Called before dispatch. A second call for the same invocation (after a
        restart, pause, or a duplicate approval click) returns the same
        operation_id. A deliberate second invocation has a different
        invocation_key and gets its own operation.
        """
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM actions WHERE task_id = ? AND invocation_key = ?", (task_id, invocation_key)).fetchone()
            if row is not None:
                if row["args_hash"] != args_hash:
                    raise ApiError(
                        "conflict",
                        "The same invocation was resumed with different arguments.",
                        status_code=409,
                        details={"invocation_key": invocation_key, "operation_id": row["operation_id"]},
                    )
                if origin_run_id:
                    run = connection.execute('SELECT task_id FROM runs WHERE id=?', (origin_run_id,)).fetchone()
                    if run is None or run['task_id'] != task_id:
                        raise ApiError('conflict', 'The run does not belong to this task.', status_code=409)
                    connection.execute('INSERT INTO action_run_links(operation_id,run_id,linked_at) VALUES(?,?,?) ON CONFLICT DO NOTHING', (row['operation_id'],origin_run_id,now))
                return _action(row) | {"replayed_identity": True}
            operation_id = _id("op")
            connection.execute(
                "INSERT INTO actions (operation_id, task_id, invocation_key, origin_run_id, tool_call_id, args_hash, plan_revision, state, runtime_exec_id, result_ref, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, 'pending', NULL, NULL, ?, ?)",
                (operation_id, task_id, invocation_key, origin_run_id, tool_call_id, args_hash, now, now),
            )
            if origin_run_id:
                connection.execute(
                    "INSERT INTO action_run_links (operation_id, run_id, linked_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (operation_id, origin_run_id, now),
                )
            row = connection.execute("SELECT * FROM actions WHERE operation_id = ?", (operation_id,)).fetchone()
        return _action(row) | {"replayed_identity": False}

    def set_action_state(
        self,
        operation_id: str,
        state: str,
        *,
        runtime_exec_id: str | None = None,
        result_ref: str | None = None,
        error: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Move an action forward. `unknown` is terminal until a human reconciles it."""
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM actions WHERE operation_id = ?", (operation_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Action not found.", status_code=404)
            connection.execute(
                "UPDATE actions SET state = ?, runtime_exec_id = COALESCE(?, runtime_exec_id), result_ref = COALESCE(?, result_ref), updated_at = ? WHERE operation_id = ?",
                (state, runtime_exec_id, result_ref, now, operation_id),
            )
            journal.append(
                connection,
                row["task_id"],
                "action_finished" if state in {"succeeded", "failed", "denied", "unknown"} else "action_started",
                {"operation_id": operation_id, "state": state, "error": error, "result_ref": result_ref, **({"receipt": receipt} if receipt is not None else {})},
                run_id=row["origin_run_id"],
                occurred_at=now,
            )
        return self.action(operation_id)

    def action(self, operation_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM actions WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            raise ApiError("not_found", "Action not found.", status_code=404)
        return _action(row)

    def action_by_invocation(self, task_id: str, invocation_key: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM actions WHERE task_id = ? AND invocation_key = ?", (task_id, invocation_key)).fetchone()
        return _action(row) if row else None

    # ── budget ────────────────────────────────────────────────────────────────
    def budget(self, task_id: str) -> dict[str, Any]:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise ApiError("not_found", "Task not found.", status_code=404)
        return _budget(row)

    def _budget_payload(self, connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
        return _budget(row)

    def consume(self, task_id: str, *, active_ms: int = 0, model_calls: int = 0, tool_calls: int = 0) -> dict[str, Any]:
        """Account for real work. Counters never go down, and a ceiling stops new dispatch."""
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            active = row["active_ms"] + max(0, active_ms)
            models = row["model_calls"] + max(0, model_calls)
            tools = row["tool_calls"] + max(0, tool_calls)
            exhausted = active > row["max_active_ms"] or models > row["max_model_calls"] or tools > row["max_tool_calls"]
            connection.execute(
                "UPDATE execution_budgets SET active_ms = ?, model_calls = ?, tool_calls = ?, updated_at = ? WHERE task_id = ?",
                (active, models, tools, now, task_id),
            )
            payload = self._budget_payload(connection, task_id)
            journal.append(connection, task_id, "budget_updated", payload, occurred_at=now)
            if exhausted:
                connection.execute(
                    "UPDATE tasks SET status = 'paused_limit', revision = revision + 1, updated_at = ? WHERE id = ?",
                    (now, task_id),
                )
                journal.append(connection, task_id, "task_state_changed", {"state": "paused_limit", "reason": "budget_exhausted"}, occurred_at=now)
        if exhausted:
            raise ApiError(
                "budget_exhausted",
                "The execution budget is used up. Continue needs an explicit decision.",
                status_code=409,
                details=payload,
            )
        return payload

    def extend_budget(self, task_id: str, expected_revision: int, **limits: int) -> dict[str, Any]:
        """Raise a ceiling explicitly. Consumed counters are kept."""
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM execution_budgets WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                raise ApiError("not_found", "Task not found.", status_code=404)
            if row["revision"] != expected_revision:
                raise ApiError(
                    "budget_revision_mismatch",
                    "The budget changed since it was read.",
                    status_code=409,
                    current_revision=row["revision"],
                    details={"expected_revision": expected_revision},
                )
            allowed = {"max_active_ms": "active_ms", "max_model_calls": "model_calls", "max_tool_calls": "tool_calls"}
            updates: list[str] = []
            params: list[Any] = []
            for key, value in limits.items():
                if key not in allowed or value is None:
                    continue
                if not isinstance(value, int) or value <= 0:
                    raise ApiError("invalid_request", f"{key} must be a positive integer.", status_code=422)
                updates.append(f"{key} = ?")
                params.append(value)
            if not updates:
                raise ApiError("invalid_request", "No limit was given.", status_code=422)
            params.extend([row["revision"] + 1, now, task_id])
            connection.execute(f"UPDATE execution_budgets SET {', '.join(updates)}, revision = ?, updated_at = ? WHERE task_id = ?", params)
            payload = self._budget_payload(connection, task_id)
            journal.append(connection, task_id, "budget_updated", payload, occurred_at=now)
        return payload

    # ── leases ────────────────────────────────────────────────────────────────
    def acquire_worker(self, owner: str, ttl_s: float = 60.0) -> Lease:
        """One active worker for the whole machine.

        An expired lease is not proof that the old process is gone, so this does
        not silently take over: the caller must mark the previous lease expired
        after a definite stop. Until then the slot stays busy.
        """
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM worker_leases WHERE state = 'active'").fetchone()
            if row is not None:
                if now - row["heartbeat_at"] <= ttl_s:
                    raise ApiError("workspace_busy", "A worker is already active.", status_code=409, details={"lease_id": row["id"]})
                raise ApiError(
                    "recovery_required",
                    "The previous worker lease expired without a confirmed stop; reconcile before starting another.",
                    status_code=409,
                    details={"lease_id": row["id"], "heartbeat_at": row["heartbeat_at"]},
                )
            fencing = connection.execute("SELECT COALESCE(MAX(fencing_token), 0) + 1 AS next FROM worker_leases").fetchone()["next"]
            lease_id = _id("wlease")
            connection.execute(
                "INSERT INTO worker_leases (id, owner, fencing_token, state, heartbeat_at, acquired_at) VALUES (?, ?, ?, 'active', ?, ?)",
                (lease_id, owner, fencing, now, now),
            )
        return Lease(lease_id, int(fencing))

    def heartbeat_worker(self, lease_id: str, fencing_token: int, ttl_s: float = 60.0) -> None:
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM worker_leases WHERE id = ?", (lease_id,)).fetchone()
            if row is None or row["fencing_token"] != fencing_token or row["state"] != "active":
                raise ApiError("lease_lost", "This worker lease is no longer valid.", status_code=409)
            connection.execute("UPDATE worker_leases SET heartbeat_at = ? WHERE id = ?", (_now(), lease_id))

    def release_worker(self, lease_id: str, fencing_token: int) -> None:
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM worker_leases WHERE id = ?", (lease_id,)).fetchone()
            if row is None or row["fencing_token"] != fencing_token:
                raise ApiError("lease_lost", "This worker lease is no longer valid.", status_code=409)
            connection.execute("UPDATE worker_leases SET state = 'released', released_at = ? WHERE id = ?", (now, lease_id))

    def expire_worker(self, lease_id: str) -> None:
        """Mark a lease expired after a confirmed stop; the slot becomes free."""
        with self.db.write() as connection:
            connection.execute("UPDATE worker_leases SET state = 'expired', released_at = ? WHERE id = ? AND state = 'active'", (_now(), lease_id))

    def acquire_workspace_lease(self, workspace_id: str, operation_id: str, kind: str, ttl_s: float = 120.0) -> Lease:
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM workspace_leases WHERE workspace_id = ? AND state IN ('active','quarantined')", (workspace_id,)).fetchone()
            if row is not None:
                raise ApiError(
                    "workspace_busy",
                    "Another writer is active in this workspace.",
                    status_code=409,
                    details={"lease_id": row["id"], "kind": row["kind"], "operation_id": row["owner_operation_id"]},
                )
            fencing = connection.execute("SELECT COALESCE(MAX(fencing_token), 0) + 1 AS next FROM workspace_leases").fetchone()["next"]
            lease_id = _id("wslease")
            connection.execute(
                "INSERT INTO workspace_leases (id, workspace_id, owner_operation_id, kind, fencing_token, state, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (lease_id, workspace_id, operation_id, kind, fencing, now, now + ttl_s),
            )
        return Lease(lease_id, int(fencing))

    def release_workspace_lease(self, lease_id: str, fencing_token: int) -> None:
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM workspace_leases WHERE id = ?", (lease_id,)).fetchone()
            if row is None or row["fencing_token"] != fencing_token:
                raise ApiError("lease_lost", "This workspace lease is no longer valid.", status_code=409)
            connection.execute("UPDATE workspace_leases SET state = 'released' WHERE id = ?", (lease_id,))

    def workspace_lease(self, workspace_id: str) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM workspace_leases WHERE workspace_id = ? AND state = 'active'", (workspace_id,)).fetchone()
        return dict(row) if row else None

    def worker_lease(self) -> dict[str, Any] | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT * FROM worker_leases WHERE state = 'active'").fetchone()
        return dict(row) if row else None

    # ── idempotency ───────────────────────────────────────────────────────────
    def run_idempotent(self, key: str, body: Any, handler: Callable[[], tuple[int, Any]]) -> tuple[int, Any, bool]:
        """Run a command at most once per key.

        Same key + same body returns the stored result. Same key + different body
        is a 409. A second call while the first is still running gets 409
        `request_in_progress` instead of repeating the side effect.
        """
        request_hash = _hash(body)
        now = _now()
        with self.db.write() as connection:
            row = connection.execute("SELECT * FROM command_request_keys WHERE key = ?", (key,)).fetchone()
            if row is not None:
                if row["request_hash"] != request_hash:
                    raise ApiError("idempotency_conflict", "This idempotency key was used with a different body.", status_code=409)
                if row["response_body"] is None:
                    raise ApiError("request_in_progress", "The original request is still running.", status_code=409, retryable=True)
                return int(row["status_code"]), json.loads(row["response_body"]), True
            connection.execute(
                "INSERT INTO command_request_keys (key, request_hash, status_code, response_body, created_at) VALUES (?, ?, NULL, NULL, ?)",
                (key, request_hash, now),
            )
        try:
            status, response = handler()
        except BaseException:
            with self.db.write() as connection:
                connection.execute("DELETE FROM command_request_keys WHERE key = ? AND response_body IS NULL", (key,))
            raise
        with self.db.write() as connection:
            connection.execute(
                "UPDATE command_request_keys SET status_code = ?, response_body = ?, completed_at = ? WHERE key = ?",
                (status, json.dumps(response, ensure_ascii=False), _now(), key),
            )
        return status, response, False

    # ── events ────────────────────────────────────────────────────────────────
    def record_event(self, task_id: str, type_: str, payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        """Append one canonical event outside a wider transaction.

        The runtime bridge calls this for text chunks, tool activity and files.
        Sequence numbers come from the same journal as plan/state events, so a
        merged stream stays gap-free even when two producers interleave.
        """
        with self.db.write() as connection:
            return journal.append(connection, task_id, type_, payload, run_id=run_id)

    def latest_run_id(self, task_id: str) -> str | None:
        with self.db.read() as connection:
            row = connection.execute("SELECT id FROM runs WHERE task_id = ? ORDER BY segment DESC LIMIT 1", (task_id,)).fetchone()
        return row["id"] if row else None

    def events(self, task_id: str, after_seq: int = 0, limit: int = 500) -> dict[str, Any]:
        items = journal.list_after(self.db, task_id, after_seq, limit)
        return {"items": items, "last_event_seq": journal.last_sequence(self.db, task_id)}


def _workspace(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "root": row["root"],
        "name": row["name"],
        "profile": row["profile"],
        "exclusions": json.loads(row["exclusions"]),
        "manifest_hash": row["manifest_hash"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
    }


def _task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "thread_id": row["thread_id"],
        "title": row["title"],
        "prompt": row["prompt"],
        "status": row["status"],
        "outcome": row["outcome"],
        "mode": row["mode"],
        "read_only": bool(row["read_only"]),
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "role": row["role"],
        "parts": json.loads(row["parts"]),
        "references": json.loads(row["reference_paths"]),
        "offset": row["offset"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "segment": row["segment"],
        "state": row["state"],
        "budget_id": row["budget_id"],
        "worker_lease_id": row["worker_lease_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
    }


def _budget(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "active_ms": row["active_ms"],
        "model_calls": row["model_calls"],
        "tool_calls": row["tool_calls"],
        "max_active_ms": row["max_active_ms"],
        "max_model_calls": row["max_model_calls"],
        "max_tool_calls": row["max_tool_calls"],
        "revision": row["revision"],
        "updated_at": row["updated_at"],
    }


def _plan(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "revision": row["revision"],
        "steps": json.loads(row["steps"]),
        "scope": json.loads(row["scope"]),
        "checks": json.loads(row["checks"]),
        "profile_hash": row["profile_hash"],
        "approved_revision": row["approved_revision"],
        "updated_at": row["updated_at"],
    }


_PLAN_STEP_STATUSES = {"pending", "in_progress", "completed"}


def _normalize_steps(steps: Any) -> list[dict[str, Any]]:
    """The one plan-step shape: ``{id, title, status, detail?}``.

    Models propose todos as ``{content, status}``; the API edits them as
    ``{id, title}``. Both become the same rows here, so the renderer and the
    controller never need two readers.
    """
    if not isinstance(steps, list) or not steps:
        raise ApiError("invalid_request", "A plan needs at least one step.", status_code=422)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(steps, start=1):
        if not isinstance(raw, dict):
            raise ApiError("invalid_request", "Every plan step must be an object.", status_code=422)
        title = str(raw.get("title") or raw.get("content") or "").strip()
        if not title:
            raise ApiError("invalid_request", "Every plan step needs a title.", status_code=422)
        step_id = str(raw.get("id") or f"step-{index}").strip()
        if not step_id or step_id in seen:
            raise ApiError("invalid_request", "Plan step ids must be non-empty and unique.", status_code=422)
        seen.add(step_id)
        status = str(raw.get("status") or "pending")
        if status not in _PLAN_STEP_STATUSES:
            raise ApiError("invalid_request", f"Unknown plan step status: {status}", status_code=422)
        step: dict[str, Any] = {"id": step_id, "title": title, "status": status}
        detail = raw.get("detail")
        if isinstance(detail, str) and detail.strip():
            step["detail"] = detail.strip()
        normalized.append(step)
    return normalized


def _string_list(values: Any, name: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or any(not isinstance(item, str) for item in values):
        raise ApiError("invalid_request", f"`{name}` must be a list of strings.", status_code=422)
    return [item.strip() for item in values if item.strip()]


def _plan_material(steps: list[dict[str, Any]], scope: list[str], checks: list[str], profile_hash: str | None) -> dict[str, Any]:
    """What makes a plan a different plan; step progress alone does not."""
    return {
        "steps": [{key: value for key, value in step.items() if key != "status"} for step in steps],
        "scope": scope,
        "checks": checks,
        "profile_hash": profile_hash,
    }


def _plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": plan["revision"],
        "steps": plan["steps"],
        "scope": plan["scope"],
        "checks": plan["checks"],
        "profile_hash": plan["profile_hash"],
        "approved_revision": plan["approved_revision"],
    }



def _action(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "operation_id": row["operation_id"],
        "task_id": row["task_id"],
        "invocation_key": row["invocation_key"],
        "origin_run_id": row["origin_run_id"],
        "tool_call_id": row["tool_call_id"],
        "args_hash": row["args_hash"],
        "plan_revision": row["plan_revision"],
        "state": row["state"],
        "runtime_exec_id": row["runtime_exec_id"],
        "result_ref": row["result_ref"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
