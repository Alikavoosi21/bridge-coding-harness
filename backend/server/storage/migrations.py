"""Versioned schema, backup before upgrade, and import of pre-storage data.

Rules that the rest of the storage layer relies on:

- Every migration runs once. `schema_migrations` records version, name, checksum
  and time; a changed checksum for an already-applied version is a hard error
  (someone edited history instead of adding a migration).
- The first migration over a non-empty database copies the file aside first.
- Importing legacy data is idempotent: running it twice cannot duplicate a
  workspace or a task, because natural keys have UNIQUE constraints and the
  importer uses `ON CONFLICT DO NOTHING`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from .. import settings
from .db import Database

from .contract import SCHEMA_VERSION

_V1 = """
CREATE TABLE workspaces (
    id              TEXT PRIMARY KEY,
    root            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    profile         TEXT,
    exclusions      TEXT NOT NULL DEFAULT '[]',
    manifest_hash   TEXT,
    created_at      REAL NOT NULL,
    last_seen_at    REAL NOT NULL
);

CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    thread_id       TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    status          TEXT NOT NULL,
    outcome         TEXT,
    mode            TEXT NOT NULL,
    read_only       INTEGER NOT NULL DEFAULT 0,
    revision        INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX tasks_workspace_status ON tasks(workspace_id, status);

CREATE TABLE runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    segment         INTEGER NOT NULL CHECK (segment > 0),
    state           TEXT NOT NULL,
    budget_id       TEXT NOT NULL,
    worker_lease_id TEXT,
    created_at      REAL NOT NULL,
    started_at      REAL,
    ended_at        REAL,
    UNIQUE (task_id, segment)
);
CREATE INDEX runs_state ON runs(state);

CREATE TABLE execution_budgets (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE RESTRICT,
    active_ms           INTEGER NOT NULL DEFAULT 0 CHECK (active_ms >= 0),
    model_calls         INTEGER NOT NULL DEFAULT 0 CHECK (model_calls >= 0),
    tool_calls          INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls >= 0),
    max_active_ms       INTEGER NOT NULL,
    max_model_calls     INTEGER NOT NULL,
    max_tool_calls      INTEGER NOT NULL,
    revision            INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at          REAL NOT NULL
);

CREATE TABLE worker_leases (
    id              TEXT PRIMARY KEY,
    owner           TEXT NOT NULL,
    fencing_token   INTEGER NOT NULL,
    state           TEXT NOT NULL,
    heartbeat_at    REAL NOT NULL,
    acquired_at     REAL NOT NULL,
    released_at     REAL
);
-- One active worker for the whole machine, enforced by the database, not by a flag.
CREATE UNIQUE INDEX worker_single_active ON worker_leases(state) WHERE state = 'active';

CREATE TABLE workspace_leases (
    id                  TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    owner_operation_id  TEXT NOT NULL,
    kind                TEXT NOT NULL,
    fencing_token       INTEGER NOT NULL,
    state               TEXT NOT NULL,
    acquired_at         REAL NOT NULL,
    expires_at          REAL
);
-- One writer per workspace: an agent command, manual edit, candidate check,
-- apply and restore all take this same lease.
CREATE UNIQUE INDEX workspace_single_writer ON workspace_leases(workspace_id) WHERE state = 'active';

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    role            TEXT NOT NULL,
    parts           TEXT NOT NULL,
    offset          INTEGER NOT NULL,
    created_at      REAL NOT NULL,
    UNIQUE (task_id, offset)
);

CREATE TABLE plans (
    task_id             TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE RESTRICT,
    revision            INTEGER NOT NULL CHECK (revision > 0),
    steps               TEXT NOT NULL,
    scope               TEXT NOT NULL,
    profile_hash        TEXT,
    approved_revision   INTEGER,
    updated_at          REAL NOT NULL
);

CREATE TABLE actions (
    operation_id    TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    invocation_key  TEXT NOT NULL,
    origin_run_id   TEXT,
    tool_call_id    TEXT,
    args_hash       TEXT NOT NULL,
    plan_revision   INTEGER,
    state           TEXT NOT NULL,
    runtime_exec_id TEXT,
    result_ref      TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    UNIQUE (task_id, invocation_key)
);
CREATE INDEX actions_state ON actions(state);

CREATE TABLE action_run_links (
    operation_id    TEXT NOT NULL REFERENCES actions(operation_id) ON DELETE RESTRICT,
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE RESTRICT,
    linked_at       REAL NOT NULL,
    PRIMARY KEY (operation_id, run_id)
);

CREATE TABLE approvals (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    action_id       TEXT NOT NULL REFERENCES actions(operation_id) ON DELETE RESTRICT,
    action_hash     TEXT NOT NULL,
    revision        INTEGER NOT NULL,
    state           TEXT NOT NULL,
    decision        TEXT,
    decided_at      REAL,
    created_at      REAL NOT NULL
);
CREATE INDEX approvals_task_state ON approvals(task_id, state);

CREATE TABLE grants (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    capability      TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    expiry          REAL,
    revoked_at      REAL,
    created_at      REAL NOT NULL
);

CREATE TABLE verification_profiles (
    workspace_id    TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE RESTRICT,
    revision        INTEGER NOT NULL CHECK (revision > 0),
    commands        TEXT NOT NULL,
    required        TEXT NOT NULL,
    timeouts        TEXT NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE verification_results (
    id                      TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    run_id                  TEXT,
    target_kind             TEXT NOT NULL,
    selection_id            TEXT,
    profile_hash            TEXT NOT NULL,
    input_manifest_hash     TEXT NOT NULL,
    runtime_fingerprint     TEXT NOT NULL,
    outcome                 TEXT NOT NULL,
    output_ref              TEXT,
    created_at              REAL NOT NULL
);
CREATE INDEX verification_task_target ON verification_results(task_id, target_kind);

CREATE TABLE repair_budgets (
    task_id         TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE RESTRICT,
    allowed         INTEGER NOT NULL DEFAULT 2 CHECK (allowed >= 0),
    total_attempts  INTEGER NOT NULL DEFAULT 0 CHECK (total_attempts >= 0),
    revision        INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0)
);

CREATE TABLE file_changes (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    path            TEXT NOT NULL,
    baseline_hash   TEXT,
    working_hash    TEXT,
    kind            TEXT NOT NULL,
    UNIQUE (task_id, path)
);

CREATE TABLE apply_selections (
    id                      TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    revision                INTEGER NOT NULL CHECK (revision > 0),
    working_revision        INTEGER NOT NULL,
    file_ids                TEXT NOT NULL,
    original_manifest_hash  TEXT NOT NULL,
    candidate_manifest_hash TEXT NOT NULL,
    profile_hash            TEXT NOT NULL,
    runtime_fingerprint     TEXT NOT NULL,
    check_refs              TEXT NOT NULL DEFAULT '[]',
    quality_status          TEXT NOT NULL,
    created_at              REAL NOT NULL
);

CREATE TABLE apply_operations (
    id                          TEXT PRIMARY KEY,
    task_id                     TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    selection_id                TEXT NOT NULL REFERENCES apply_selections(id) ON DELETE RESTRICT,
    expected_working_revision   INTEGER NOT NULL,
    lease_token                 TEXT NOT NULL,
    quality_ack                 TEXT,
    idempotency_key             TEXT NOT NULL UNIQUE,
    state                       TEXT NOT NULL,
    journal_ref                 TEXT,
    created_at                  REAL NOT NULL,
    updated_at                  REAL NOT NULL
);

CREATE TABLE apply_files (
    operation_id    TEXT NOT NULL REFERENCES apply_operations(id) ON DELETE RESTRICT,
    path            TEXT NOT NULL,
    before_hash     TEXT,
    current_hash    TEXT,
    after_hash      TEXT,
    state           TEXT NOT NULL,
    PRIMARY KEY (operation_id, path)
);

CREATE TABLE skill_sources (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    scope       TEXT NOT NULL,
    hash        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    trust       TEXT NOT NULL,
    copy_ref    TEXT,
    created_at  REAL NOT NULL,
    UNIQUE (source, scope)
);

CREATE TABLE skill_pins (
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    skill_id    TEXT NOT NULL REFERENCES skill_sources(id) ON DELETE RESTRICT,
    hash        TEXT NOT NULL,
    pinned_at   REAL NOT NULL,
    PRIMARY KEY (task_id, skill_id)
);

CREATE TABLE events (
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    sequence        INTEGER NOT NULL CHECK (sequence > 0),
    event_id        TEXT NOT NULL UNIQUE,
    run_id          TEXT,
    schema_version  INTEGER NOT NULL,
    type            TEXT NOT NULL,
    payload         TEXT NOT NULL,
    occurred_at     REAL NOT NULL,
    PRIMARY KEY (task_id, sequence)
);

CREATE TABLE command_request_keys (
    key             TEXT PRIMARY KEY,
    request_hash    TEXT NOT NULL,
    status_code     INTEGER,
    response_body   TEXT,
    created_at      REAL NOT NULL,
    completed_at    REAL
);
"""

# A plan carries the checks it promises, alongside its steps and file scope.
# Added as its own migration: an installed database is upgraded in place and
# keeps every plan and approval it already has.
_V2 = """
ALTER TABLE plans ADD COLUMN checks TEXT NOT NULL DEFAULT '[]';
"""

# A user message can carry files it points at, and steering is durable: a
# message queued while a command runs waits in the table until a model turn
# actually receives it. `delivered_at` is that receipt.
_V3 = """
ALTER TABLE messages ADD COLUMN reference_paths TEXT NOT NULL DEFAULT '[]';
ALTER TABLE messages ADD COLUMN delivered_at REAL;
"""

_V4 = """
ALTER TABLE approvals ADD COLUMN request_json TEXT;
"""

_V5 = """
CREATE TABLE working_copies (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    manifest_hash TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "initial", _V1),
    (2, "plan_checks", _V2),
    (3, "message_delivery", _V3),
    (4, "approval_request", _V4),
    (5, "working_copy_revision", _V5),
)


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:32]


def _applied(connection: sqlite3.Connection) -> dict[int, str]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at REAL NOT NULL)"
    )
    return {row["version"]: row["checksum"] for row in connection.execute("SELECT version, checksum FROM schema_migrations")}


def backup_if_needed(db: Database) -> Path | None:
    """Copy the database aside before the first upgrade of a non-empty file."""
    if not db.path.exists() or db.path.stat().st_size == 0:
        return None
    with db.read() as connection:
        tables = [
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
            if row["name"] != "schema_migrations"
        ]
    if not tables:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = db.path.with_name(f"{db.path.name}.bak-{stamp}")
    shutil.copy2(db.path, target)
    return target


def migrate(db: Database | None = None) -> dict[str, Any]:
    """Bring the database to `SCHEMA_VERSION`. Safe to call on every start."""
    database = db or Database()
    with database.read() as connection:
        applied = _applied(connection)
    for version, name, sql in MIGRATIONS:
        if version in applied and applied[version] != _checksum(sql):
            raise RuntimeError(f"migration {version} ({name}) was changed after being applied")
    pending = [entry for entry in MIGRATIONS if entry[0] not in applied]
    backup = backup_if_needed(database) if pending else None
    applied_now: list[int] = []
    with database.write() as connection:
        applied = _applied(connection)
        for version, name, sql in pending:
            digest = _checksum(sql)
            for statement in _statements(sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                (version, name, digest, time.time()),
            )
            applied_now.append(version)
    return {
        "version": SCHEMA_VERSION,
        "applied": applied_now,
        "backup": str(backup) if backup else None,
        "current": max(_applied_safe(database), default=0),
    }


def _statements(sql: str) -> list[str]:
    """Split a DDL script into statements, dropping chunks that are only comments.

    `executescript` would COMMIT the open transaction first, which would let a
    failed migration leave half a schema behind. The migrations here contain no
    semicolons inside literals, so a plain split is exact.
    """
    statements: list[str] = []
    for chunk in sql.split(";"):
        lines = [line for line in chunk.strip().splitlines() if line.strip() and not line.strip().startswith("--")]
        if lines:
            statements.append("\n".join(lines))
    return statements


def _applied_safe(db: Database) -> list[int]:
    with db.read() as connection:
        try:
            return [row["version"] for row in connection.execute("SELECT version FROM schema_migrations")]
        except sqlite3.OperationalError:
            return []


def preview_legacy(db: Database | None = None) -> dict[str, Any]:
    """What would be imported, without writing anything.

    Legacy source of truth is the machine settings file (known workspaces) plus
    each workspace's `.harness/runs/<thread_id>` folders.
    """
    database = db or Database()
    data = settings.load()
    rows: list[dict[str, Any]] = []
    tasks = 0
    for root in data.get("workspaces", []):
        folder = Path(root)
        runs = sorted((folder / ".harness" / "runs").glob("*")) if (folder / ".harness" / "runs").is_dir() else []
        thread_ids = [item.name for item in runs if item.is_dir()]
        tasks += len(thread_ids)
        rows.append({"root": str(folder), "name": settings.workspace_name(data, str(folder)), "tasks": thread_ids})

    existing = {"workspaces": 0, "tasks": 0}
    if database.path.exists():
        with database.read() as connection:
            try:
                existing["workspaces"] = connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
                existing["tasks"] = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            except sqlite3.OperationalError:
                pass
    return {"legacy": rows, "legacy_task_count": tasks, "existing": existing, "would_import": tasks}


def import_legacy(db: Database | None = None) -> dict[str, int]:
    """Copy legacy workspaces and run folders into the product database.

    Idempotent by construction: workspace `root` and task `thread_id` are UNIQUE
    and conflicting rows are skipped. A task already known keeps its status; the
    importer never rewrites live state.
    """
    database = db or Database()
    migrate(database)
    now = time.time()
    imported_workspaces = 0
    imported_tasks = 0
    data = settings.load()
    with database.write() as connection:
        for root in data.get("workspaces", []):
            folder = Path(root)
            if not folder.exists():
                continue
            existing = connection.execute("SELECT id FROM workspaces WHERE root = ?", (str(folder),)).fetchone()
            if existing:
                workspace_id = existing["id"]
            else:
                workspace_id = f"ws_{hashlib.sha1(str(folder).encode()).hexdigest()[:16]}"
                connection.execute(
                    "INSERT INTO workspaces (id, root, name, profile, exclusions, manifest_hash, created_at, last_seen_at) "
                    "VALUES (?, ?, ?, NULL, '[]', NULL, ?, ?)",
                    (workspace_id, str(folder), settings.workspace_name(data, str(folder)), now, now),
                )
                imported_workspaces += 1
            runs_dir = folder / ".harness" / "runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(item for item in runs_dir.iterdir() if item.is_dir()):
                thread_id = run_dir.name
                if connection.execute("SELECT id FROM tasks WHERE thread_id = ?", (thread_id,)).fetchone():
                    continue
                task_id = f"task_{thread_id}"
                connection.execute(
                    "INSERT INTO tasks (id, workspace_id, thread_id, title, prompt, status, outcome, mode, read_only, revision, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'recovery_required', 'unknown', 'confirm', 0, 1, ?, ?)",
                    (task_id, workspace_id, thread_id, thread_id, "", now, now),
                )
                connection.execute(
                    "INSERT INTO execution_budgets (id, task_id, max_active_ms, max_model_calls, max_tool_calls, updated_at) "
                    "VALUES (?, ?, 600000, 40, 80, ?)",
                    (f"budget_{task_id}", task_id, now),
                )
                imported_tasks += 1
                connection.execute(
                    "INSERT INTO events (task_id, sequence, event_id, schema_version, type, payload, occurred_at) "
                    "VALUES (?, 1, ?, 1, 'task_state_changed', ?, ?)",
                    (task_id, f"evt_{task_id}_1", json.dumps({"state": "recovery_required", "reason": "legacy_import"}), now),
                )
    return {"workspaces": imported_workspaces, "tasks": imported_tasks}
