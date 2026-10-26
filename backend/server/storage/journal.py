"""Durable event journal.

The sequence is per task and monotonic. `append` runs inside the caller's write
transaction, so the event is committed before any caller can publish it: a
stream that dies mid-flight can always be resumed from the last committed
sequence, and a duplicate publish cannot create a second row because
`(task_id, sequence)` and `event_id` are UNIQUE.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from .contract import EVENT_SCHEMA_VERSION
from .db import Database


def append(
    connection: sqlite3.Connection,
    task_id: str,
    type_: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    event_id: str | None = None,
    occurred_at: float | None = None,
) -> dict[str, Any]:
    """Add one event inside an open write transaction and return the envelope."""
    row = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM events WHERE task_id = ?", (task_id,)).fetchone()
    sequence = int(row["next"])
    envelope = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "sequence": sequence,
        "event_id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": type_,
        "occurred_at": occurred_at if occurred_at is not None else time.time(),
        "payload": payload,
    }
    connection.execute(
        "INSERT INTO events (task_id, sequence, event_id, run_id, schema_version, type, payload, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, sequence, envelope["event_id"], run_id, EVENT_SCHEMA_VERSION, type_, json.dumps(payload, ensure_ascii=False), envelope["occurred_at"]),
    )
    return envelope


def list_after(db: Database, task_id: str, after_seq: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    """Events after a cursor, oldest first. Callers resume from the last sequence they saw."""
    with db.read() as connection:
        rows = connection.execute(
            "SELECT * FROM events WHERE task_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
            (task_id, after_seq, limit),
        ).fetchall()
    return [_envelope(row) for row in rows]


def last_sequence(db: Database, task_id: str) -> int:
    with db.read() as connection:
        row = connection.execute("SELECT COALESCE(MAX(sequence), 0) AS last FROM events WHERE task_id = ?", (task_id,)).fetchone()
    return int(row["last"])


def _envelope(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": row["schema_version"],
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "sequence": row["sequence"],
        "event_id": row["event_id"],
        "type": row["type"],
        "occurred_at": row["occurred_at"],
        "payload": json.loads(row["payload"]),
    }
