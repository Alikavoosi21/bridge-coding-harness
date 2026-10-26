"""The renderer and the API must describe the same contract.

`backend/server/storage/contract.py` owns the vocabulary. `src/lib/harness/schema.ts`
is generated from it and `tests/contracts/*.json` are checked against it. If any
of the three disagree, this test fails - which is the point: two hand-maintained
lists drift, one generated copy cannot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.storage import Database, Store, contract, migrate
from server.storage.contract import ERROR_CODES, EVENT_TYPES, TASK_STATES

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_TS = ROOT / "src" / "lib" / "harness" / "schema.ts"
CONTRACTS = ROOT / "tests" / "contracts"


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    database = Database()
    migrate(database)
    return Store(database)


def _fixture(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_the_committed_typescript_is_exactly_the_generated_file():
    assert SCHEMA_TS.exists(), "run: python -m server.storage.contract --write"
    assert SCHEMA_TS.read_text(encoding="utf-8") == contract.generate_typescript()


def test_the_typescript_lists_match_python():
    source = SCHEMA_TS.read_text(encoding="utf-8")
    for name, values in (
        ("TASK_STATES", TASK_STATES),
        ("EVENT_TYPES", EVENT_TYPES),
        ("ERROR_CODES", ERROR_CODES),
    ):
        block = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
        assert block, f"{name} is missing from schema.ts"
        found = re.findall(r"'([^']+)'", block.group(1))
        assert found == list(values)


def test_the_contract_snapshot_fixture_does_not_drift():
    assert _fixture("contract.json") == contract.snapshot()


def test_no_secret_or_local_path_leaks_into_the_renderer_contract():
    text = SCHEMA_TS.read_text(encoding="utf-8")
    for forbidden in ("api_key", "HARNESS_TOKEN", "sk-", "C:\\", "/home/"):
        assert forbidden not in text
    assert "checkpoints.db" not in text and "product.db" not in text


def test_the_task_api_fixture_matches_the_store(store):
    fixture = _fixture("task-api.json")
    workspace = store.upsert_workspace("C:/work/contract", "Contract")
    task = store.create_task(workspace_id=workspace["id"], prompt="contract")
    action = store.ensure_action(task["id"], "call-1", "hash")
    event = store.events(task["id"])["items"][0]

    assert list(task.keys()) == fixture["task_keys"]
    assert list(task["runs"][0].keys()) == fixture["run_keys"]
    assert list(task["budget"].keys()) == fixture["budget_keys"]
    assert list(store.messages(task["id"])[0].keys()) == fixture["message_keys"]
    assert list(action.keys()) == [*fixture["action_keys"], "replayed_identity"]
    assert list(event.keys()) == fixture["event_keys"]

    assert fixture["schema_version"] == contract.SCHEMA_VERSION
    assert fixture["event_schema_version"] == contract.EVENT_SCHEMA_VERSION
    assert {endpoint["path"] for endpoint in fixture["endpoints"]} == {
        "/tasks",
        "/tasks/{task_id}",
        "/tasks/{task_id}/events",
        "/tasks/{task_id}/messages",
        "/tasks/{task_id}/plan-proposals",
        "/tasks/{task_id}/continuations",
        "/tasks/{task_id}/plan",
        "/tasks/{task_id}/plan-decisions",
        "/tasks/{task_id}",
    }


def test_the_task_request_fixture_matches_the_pydantic_model():
    from server.routes.tasks import StartTask

    fixture = _fixture("task-api.json")
    assert list(StartTask.model_fields.keys()) == fixture["task_request_keys"]
