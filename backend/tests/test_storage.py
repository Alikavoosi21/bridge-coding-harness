"""The product store: migrations, journal, identity, leases and budgets.

These tests use the real SQLite file in a throwaway home, not a mock: the
invariants they check are enforced by the database itself.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from server import settings
from server.errors import ApiError
from server.storage import Database, Store, import_legacy, migrate, preview_legacy
from server.storage import migrations
from server.storage.db import checkpoints_db_path, product_db_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HARNESS_HOME", str(home))
    return home


@pytest.fixture
def db(home) -> Database:
    return Database()


@pytest.fixture
def store(db) -> Store:
    migrate(db)
    return Store(db)


def _workspace(store: Store, root: str = "C:/work/ws") -> dict:
    return store.upsert_workspace(root, "Demo")


def _task(store: Store, **overrides) -> dict:
    workspace = _workspace(store)
    return store.create_task(workspace_id=workspace["id"], prompt=overrides.pop("prompt", "گزارش فروش را بنویس"), **overrides)


# ── files and migrations ─────────────────────────────────────────────────────


def test_the_two_databases_live_in_the_app_home_not_the_repo(home):
    assert product_db_path() == home / "product.db"
    assert checkpoints_db_path() == home / "checkpoints.db"


def test_migration_is_versioned_and_a_second_run_changes_nothing(db, home):
    first = migrate(db)
    second = migrate(db)

    assert first["applied"] == [1, 2, 3, 4, 5] and first["current"] == 5
    assert second["applied"] == [] and second["current"] == 5
    with db.read() as connection:
        rows = connection.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
    assert [row["version"] for row in rows] == [1, 2, 3, 4, 5]
    assert [row["name"] for row in rows] == ["initial", "plan_checks", "message_delivery", "approval_request", "working_copy_revision"]


def test_v4_upgrade_preserves_task_and_backup_before_adding_working_revision(db,home,monkeypatch):
    original=migrations.MIGRATIONS
    with monkeypatch.context() as legacy:
        legacy.setattr(migrations,'MIGRATIONS',original[:4])
        assert migrate(db)['current']==4
        store=Store(db)
        workspace=store.upsert_workspace(str(home/'fixture-project'))
        task=store.create_task(workspace_id=workspace['id'],prompt='keep this existing task')
    upgraded=migrate(db)
    assert upgraded['applied']==[5] and upgraded['backup'] is not None
    assert Store(db).task(task['id'])['prompt']=='keep this existing task'
    with sqlite3.connect(upgraded['backup']) as backup:
        assert backup.execute('SELECT prompt FROM tasks WHERE id=?',(task['id'],)).fetchone()[0]=='keep this existing task'
        assert backup.execute("SELECT name FROM sqlite_master WHERE name='working_copies'").fetchone() is None
    with db.read() as connection:assert connection.execute('SELECT COUNT(*) FROM working_copies').fetchone()[0]==0
    assert migrate(db)['applied']==[]


def test_a_non_empty_database_is_backed_up_before_it_is_upgraded(db, home):
    with db.write() as connection:
        connection.execute("CREATE TABLE legacy_note (id TEXT PRIMARY KEY)")
        connection.execute("DROP TABLE IF EXISTS schema_migrations")
    backup = migrate(db)["backup"]

    assert backup is not None
    assert Path(backup).exists()
    assert Path(backup).name.startswith("product.db.bak-")
    with sqlite3.connect(backup) as old:
        assert old.execute("SELECT name FROM sqlite_master WHERE name = 'legacy_note'").fetchone()
    # Running again does not take another backup.
    assert migrate(db)["backup"] is None


def test_editing_an_applied_migration_is_refused(db, monkeypatch):
    migrate(db)
    original = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, "MIGRATIONS", ((1, "initial", original[0][2] + "\nCREATE TABLE sneaky (id TEXT);"),))

    with pytest.raises(RuntimeError, match="changed after being applied"):
        migrate(db)


def test_legacy_import_previews_and_imports_exactly_once(home):
    workspace = home.parent / "legacy-ws"
    (workspace / ".harness" / "runs" / "abc123").mkdir(parents=True)
    settings.save({"workspaces": [str(workspace)], "workspace_names": {str(workspace): "قدیمی"}, "current_workspace": str(workspace)})

    preview = preview_legacy()
    assert preview["would_import"] == 1
    assert preview["legacy"][0]["name"] == "قدیمی"

    first = import_legacy()
    second = import_legacy()
    assert first == {"workspaces": 1, "tasks": 1}
    assert second == {"workspaces": 0, "tasks": 0}

    store = Store()
    imported = store.task_by_thread("abc123")
    assert imported is not None
    assert imported["status"] == "recovery_required" and imported["outcome"] == "unknown"
    assert imported["last_event_seq"] == 1
    with store.db.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_the_workspace_row_is_reused_when_opened_again(store):
    first = _workspace(store)
    second = _workspace(store)

    assert first["id"] == second["id"]
    with store.db.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1


# ── tasks and journal ────────────────────────────────────────────────────────


def test_creating_a_task_writes_a_budget_run_and_opening_events(store):
    task = _task(store)

    assert task["status"] == "queued" and task["revision"] == 1
    assert task["budget"]["active_ms"] == 0
    assert task["runs"][0]["segment"] == 1 and task["runs"][0]["budget_id"] == task["budget"]["id"]
    assert [event["type"] for event in store.events(task["id"])["items"]] == ["task_state_changed", "budget_updated"]


def test_thread_ids_are_unique(store):
    task = _task(store)
    workspace = store.workspace(task["workspace_id"])

    with pytest.raises(ApiError) as error:
        store.create_task(workspace_id=workspace["id"], prompt="another", thread_id=task["thread_id"])
    assert error.value.status_code == 409 and error.value.code == "conflict"


def test_the_event_sequence_is_durable_contiguous_and_unique(store):
    task = _task(store)
    store.set_task_status(task["id"], "planning", reason="test")
    store.set_task_status(task["id"], "executing", reason="test")

    events = store.events(task["id"])["items"]
    assert [event["sequence"] for event in events] == [1, 2, 3, 4]
    assert store.events(task["id"])["last_event_seq"] == 4
    # Reading from a cursor returns exactly the tail.
    assert [event["sequence"] for event in store.events(task["id"], after_seq=2)["items"]] == [3, 4]

    with pytest.raises(sqlite3.IntegrityError):
        with store.db.write() as connection:
            connection.execute(
                "INSERT INTO events (task_id, sequence, event_id, run_id, schema_version, type, payload, occurred_at) "
                "VALUES (?, 4, 'evt_duplicate', NULL, 1, 'task_state_changed', '{}', ?)",
                (task["id"], time.time()),
            )


def test_a_restart_keeps_the_journal_and_the_cursor(store):
    task = _task(store)

    reopened = Store(Database())
    assert [event["sequence"] for event in reopened.events(task["id"])["items"]] == [1, 2]
    assert reopened.task(task["id"])["last_event_seq"] == 2


# ── idempotency ──────────────────────────────────────────────────────────────


def test_the_same_key_and_body_replays_the_stored_answer(store):
    calls: list[int] = []

    def handler() -> tuple[int, dict]:
        calls.append(1)
        return 202, {"ok": True}

    first = store.run_idempotent("key-1", {"prompt": "x"}, handler)
    second = store.run_idempotent("key-1", {"prompt": "x"}, handler)

    assert first == (202, {"ok": True}, False)
    assert second == (202, {"ok": True}, True)
    assert calls == [1]


def test_the_same_key_with_a_different_body_is_a_conflict(store):
    store.run_idempotent("key-1", {"prompt": "x"}, lambda: (202, {}))

    with pytest.raises(ApiError) as error:
        store.run_idempotent("key-1", {"prompt": "y"}, lambda: (202, {}))
    assert error.value.status_code == 409 and error.value.code == "idempotency_conflict"


def test_a_second_call_while_the_first_is_running_does_not_repeat_the_side_effect(store):
    def handler() -> tuple[int, dict]:
        store.run_idempotent("key-1", {"prompt": "x"}, lambda: (202, {}))
        return 202, {}

    with pytest.raises(ApiError) as error:
        store.run_idempotent("key-1", {"prompt": "x"}, handler)
    assert error.value.code == "request_in_progress" and error.value.retryable is True
    # The failed attempt released the key, so a retry can run.
    assert store.run_idempotent("key-1", {"prompt": "x"}, lambda: (202, {"ok": True}))[0] == 202


# ── deletion guard ───────────────────────────────────────────────────────────


def test_deleting_needs_consent_and_a_finished_task(store):
    task = _task(store)

    with pytest.raises(ApiError) as no_consent:
        store.delete_task(task["id"])
    assert no_consent.value.status_code == 403

    with pytest.raises(ApiError) as active:
        store.delete_task(task["id"], consent=True)
    assert active.value.status_code == 409

    store.set_task_status(task["id"], "recovery_required", outcome="unknown")
    with pytest.raises(ApiError) as recovery:
        store.delete_task(task["id"], consent=True)
    assert recovery.value.status_code == 409

    store.set_task_status(task["id"], "closed", outcome="completed")
    store.delete_task(task["id"], consent=True)
    with pytest.raises(ApiError) as gone:
        store.task(task["id"])
    assert gone.value.status_code == 404


def test_open_actions_block_deletion_even_when_the_task_is_closed(store):
    task = _task(store)
    store.set_task_status(task["id"], "closed", outcome="completed")
    store.ensure_action(task["id"], "call-1", "hash", origin_run_id=task["runs"][0]["id"])

    with pytest.raises(ApiError) as error:
        store.delete_task(task["id"], consent=True)
    assert error.value.status_code == 409


# ── leases ───────────────────────────────────────────────────────────────────


def test_one_worker_at_a_time_and_a_released_slot_can_be_reacquired(store):
    first = store.acquire_worker("engine")
    with pytest.raises(ApiError) as busy:
        store.acquire_worker("second")
    assert busy.value.code == "workspace_busy"

    with pytest.raises(ApiError) as lost:
        store.heartbeat_worker(first.id, first.fencing_token + 1)
    assert lost.value.code == "lease_lost"

    store.release_worker(first.id, first.fencing_token)
    second = store.acquire_worker("engine")
    assert second.fencing_token == first.fencing_token + 1


def test_an_expired_worker_is_reconciled_not_silently_taken_over(store):
    lease = store.acquire_worker("engine")
    with store.db.write() as connection:
        connection.execute("UPDATE worker_leases SET heartbeat_at = 0 WHERE id = ?", (lease.id,))

    with pytest.raises(ApiError) as recovery:
        store.acquire_worker("engine")
    assert recovery.value.code == "recovery_required"

    store.expire_worker(lease.id)
    assert store.acquire_worker("engine").fencing_token == lease.fencing_token + 1


def test_one_writer_per_workspace(store):
    task = _task(store)
    workspace_id = task["workspace_id"]
    first = store.acquire_workspace_lease(workspace_id, "op-1", "command")

    with pytest.raises(ApiError) as busy:
        store.acquire_workspace_lease(workspace_id, "op-2", "apply")
    assert busy.value.code == "workspace_busy"

    with pytest.raises(ApiError) as stale:
        store.release_workspace_lease(first.id, first.fencing_token + 1)
    assert stale.value.code == "lease_lost"

    store.release_workspace_lease(first.id, first.fencing_token)
    assert store.workspace_lease(workspace_id) is None
    second = store.acquire_workspace_lease(workspace_id, "op-2", "apply")
    assert second.fencing_token == first.fencing_token + 1


# ── operation identity ───────────────────────────────────────────────────────


def test_an_invocation_keeps_one_operation_id_across_segments(store):
    task = _task(store)
    first_run = task["runs"][0]["id"]
    operation = store.ensure_action(task["id"], "llm-call-1", "args-hash", origin_run_id=first_run)

    second_segment = store.start_segment(task["id"])
    replayed = store.ensure_action(task["id"], "llm-call-1", "args-hash", origin_run_id=second_segment["id"])

    assert replayed["operation_id"] == operation["operation_id"]
    assert replayed["replayed_identity"] is True
    store.link_run(operation["operation_id"], second_segment["id"])
    with store.db.read() as connection:
        linked = connection.execute("SELECT run_id FROM action_run_links WHERE operation_id = ?", (operation["operation_id"],)).fetchall()
    assert {row["run_id"] for row in linked} == {first_run, second_segment["id"]}


def test_two_deliberate_invocations_with_the_same_arguments_get_different_operations(store):
    task = _task(store)
    first = store.ensure_action(task["id"], "call-1", "same-args")
    second = store.ensure_action(task["id"], "call-2", "same-args")

    assert first["operation_id"] != second["operation_id"]
    assert first["invocation_key"] != second["invocation_key"]


def test_resuming_an_invocation_with_different_arguments_is_refused(store):
    task = _task(store)
    store.ensure_action(task["id"], "call-1", "args-a")

    with pytest.raises(ApiError) as error:
        store.ensure_action(task["id"], "call-1", "args-b")
    assert error.value.code == "conflict" and error.value.details["invocation_key"] == "call-1"


# ── budget ───────────────────────────────────────────────────────────────────


def test_budget_counters_survive_a_new_segment(store):
    task = _task(store)
    budget_id = task["budget"]["id"]
    store.consume(task["id"], active_ms=1_500, model_calls=2, tool_calls=3)
    store.start_segment(task["id"])

    budget = store.budget(task["id"])
    assert budget["id"] == budget_id
    assert (budget["active_ms"], budget["model_calls"], budget["tool_calls"]) == (1_500, 2, 3)


def test_the_budget_can_only_be_raised_at_the_revision_that_was_read(store):
    task = _task(store)
    revision = task["budget"]["revision"]
    raised = store.extend_budget(task["id"], revision, max_model_calls=100)

    assert raised["max_model_calls"] == 100 and raised["revision"] == revision + 1
    with pytest.raises(ApiError) as stale:
        store.extend_budget(task["id"], revision, max_model_calls=200)
    assert stale.value.code == "budget_revision_mismatch" and stale.value.current_revision == revision + 1


def test_exhausting_the_budget_pauses_the_task_without_resetting_the_counters(store):
    task = _task(store)

    with pytest.raises(ApiError) as exhausted:
        store.consume(task["id"], active_ms=task["budget"]["max_active_ms"] + 1)
    assert exhausted.value.code == "budget_exhausted"

    assert store.task(task["id"])["status"] == "paused_limit"
    assert store.budget(task["id"])["active_ms"] == task["budget"]["max_active_ms"] + 1


# ── typed errors ─────────────────────────────────────────────────────────────


def test_errors_have_one_machine_readable_shape():
    error = ApiError("workspace_busy", "Another writer is active.", status_code=409, details={"kind": "apply"}, current_revision=4)

    assert error.body() == {
        "code": "workspace_busy",
        "message": "Another writer is active.",
        "details": {"kind": "apply"},
        "retryable": False,
        "current_revision": 4,
    }
