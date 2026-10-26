"""The one source of truth for names, states and limits shared with the UI.

Python owns the vocabulary: task states, event types, error codes, verification
outcomes, quality states and the default limits. `schema.ts` in the renderer is
generated from this file, and a test fails if the committed file drifts. That
keeps the API contract from becoming two hand-maintained lists.

Regenerate after changing anything here:

    python -m server.storage.contract --write
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 5
EVENT_SCHEMA_VERSION = 1

TASK_STATES = (
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
    "closed",
    "failed",
    "cancelled",
)

RUN_STATES = ("queued", "active", "paused", "stopping", "done", "failed", "unknown")

ACTION_STATES = ("pending", "awaiting_approval", "dispatching", "running", "succeeded", "failed", "denied", "unknown")

LEASE_STATES = ("active", "released", "expired", "quarantined")

ACCESS_MODES = ("ask", "grant", "auto")

EVENT_TYPES = (
    "message_started",
    "text_delta",
    "message_finished",
    "plan_updated",
    "approval_required",
    "approval_decided",
    "action_started",
    "action_finished",
    "budget_updated",
    "lease_state_changed",
    "selection_quality_changed",
    "file_changed",
    "verification_finished",
    "repair_started",
    "task_state_changed",
    "apply_file_finished",
    "recovery_required",
)

VERIFICATION_TARGETS = ("working_copy", "apply_candidate")
VERIFICATION_OUTCOMES = ("passed", "failed", "skipped", "not_configured", "stopped", "timed_out")
QUALITY_STATUSES = ("verified_snapshot", "not_verified", "stale", "failed")
FILE_CHANGE_KINDS = ("added", "modified", "deleted", "binary", "unsupported")

ERROR_CODES = (
    "invalid_request",
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "idempotency_conflict",
    "request_in_progress",
    "workspace_busy",
    "selection_stale",
    "lease_lost",
    "budget_revision_mismatch",
    "budget_exhausted",
    "action_not_approved",
    "runtime_unavailable",
    "recovery_required",
    "rate_limited",
    "unavailable",
    "error",
)

# Defaults from the specification. They are ceilings, raised only by an explicit
# decision that keeps the consumed counters.
LIMITS: dict[str, int] = {
    "active_ms": 600_000,
    "model_calls": 40,
    "tool_calls": 80,
    "repairs_allowed": 2,
    "command_timeout_s": 120,
    "install_timeout_s": 600,
    "output_bytes": 1_000_000,
    "context_bytes": 65_536,
    "snapshot_bytes": 500_000_000,
    "snapshot_files": 50_000,
}


def _ts_list(name: str, type_name: str, values: tuple[str, ...]) -> str:
    lines = ",\n".join(f"  '{value}'" for value in values)
    return f"export const {name} = [\n{lines},\n] as const;\nexport type {type_name} = (typeof {name})[number];\n"


def generate_typescript() -> str:
    """The renderer-safe contract. No secrets, no paths, no Python types."""
    header = (
        "// GENERATED FILE - do not edit by hand.\n"
        "// Source: backend/server/storage/contract.py\n"
        "// Regenerate: python -m server.storage.contract --write\n\n"
    )
    parts = [header, f"export const SCHEMA_VERSION = {SCHEMA_VERSION} as const;\n"]
    for name, type_name, values in (
        ("TASK_STATES", "TaskState", TASK_STATES),
        ("RUN_STATES", "RunState", RUN_STATES),
        ("ACTION_STATES", "ActionState", ACTION_STATES),
        ("LEASE_STATES", "LeaseState", LEASE_STATES),
        ("ACCESS_MODES", "AccessMode", ACCESS_MODES),
        ("EVENT_TYPES", "EventType", EVENT_TYPES),
        ("VERIFICATION_TARGETS", "VerificationTarget", VERIFICATION_TARGETS),
        ("VERIFICATION_OUTCOMES", "VerificationOutcome", VERIFICATION_OUTCOMES),
        ("QUALITY_STATUSES", "QualityStatus", QUALITY_STATUSES),
        ("FILE_CHANGE_KINDS", "FileChangeKind", FILE_CHANGE_KINDS),
        ("ERROR_CODES", "ErrorCode", ERROR_CODES),
    ):
        parts.append(_ts_list(name, type_name, values))
    limits = json.dumps(LIMITS, indent=2)
    parts.append(f"export const LIMITS = {limits} as const;\n")
    parts.append(
        "export type ApiErrorBody = {\n"
        "  code: (typeof ERROR_CODES)[number];\n"
        "  message: string;\n"
        "  details: Record<string, unknown>;\n"
        "  retryable: boolean;\n"
        "  current_revision?: number;\n"
        "};\n\n"
        "export type EventEnvelope<T = unknown> = {\n"
        "  schema_version: number;\n"
        "  task_id: string;\n"
        "  run_id: string | null;\n"
        "  sequence: number;\n"
        "  event_id: string;\n"
        "  type: (typeof EVENT_TYPES)[number];\n"
        "  occurred_at: number;\n"
        "  payload: T;\n"
        "};\n"
    )
    return "".join(parts)


def typescript_path() -> Path:
    return Path(__file__).resolve().parents[3] / "src" / "lib" / "harness" / "schema.ts"


def write_typescript(path: Path | None = None) -> Path:
    target = path or typescript_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_typescript(), encoding="utf-8", newline="\n")
    return target


def snapshot() -> dict[str, Any]:
    """Everything the contract test compares, in one object."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "task_states": list(TASK_STATES),
        "run_states": list(RUN_STATES),
        "action_states": list(ACTION_STATES),
        "lease_states": list(LEASE_STATES),
        "access_modes": list(ACCESS_MODES),
        "event_types": list(EVENT_TYPES),
        "verification_targets": list(VERIFICATION_TARGETS),
        "verification_outcomes": list(VERIFICATION_OUTCOMES),
        "quality_statuses": list(QUALITY_STATUSES),
        "file_change_kinds": list(FILE_CHANGE_KINDS),
        "error_codes": list(ERROR_CODES),
        "limits": LIMITS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the renderer copy of the contract.")
    parser.add_argument("--write", action="store_true", help="rewrite src/lib/harness/schema.ts")
    parser.add_argument("--print", action="store_true", help="print the contract as JSON")
    args = parser.parse_args(argv)
    if args.write:
        print(write_typescript())
    if args.print or not args.write:
        print(json.dumps(snapshot(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
