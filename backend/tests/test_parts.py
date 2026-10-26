"""Unit tests for the pieces that have rules of their own."""

from __future__ import annotations

import sys

import pytest

from harness.permissions import build_policy, load_rules
from harness.sandbox import build_backend
from harness.skills import list_skills
from harness.subagents import list_agents
from harness.tools import build_tools
from harness.tools.calc import evaluate


# ── exact arithmetic ──


@pytest.mark.parametrize(("expression", "expected"), [("2 + 3 * 4", 14), ("(2840 - 3050) / 3050 * 100", -6.885245901639344), ("round(10 / 3, 2)", 3.33), ("max(1, 2, 3) - abs(-1)", 2)])
def test_calculate(expression, expected):
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize("expression", ["__import__('os').system('x')", "open('x')", "a + 1", "2 ** 1000", "(1).__class__"])
def test_calculate_refuses_anything_but_arithmetic(expression):
    with pytest.raises((ValueError, SyntaxError)):
        evaluate(expression)


# ── tables ──


def test_aggregate_table_totals_by_group(workspace):
    (workspace.root / "sales.csv").write_text("city,amount\nتهران,\"1,200\"\nاصفهان,300\nتهران,800\n", encoding="utf-8")
    tools = build_tools(workspace)

    result = tools["aggregate_table"].invoke({"path": "/sales.csv", "value_column": "amount", "group_by": "city"})

    assert "تهران: 2000.0" in result and "اصفهان: 300.0" in result


def test_table_tools_cannot_leave_the_workspace(workspace, tmp_path):
    (tmp_path / "secret.csv").write_text("a\n1\n", encoding="utf-8")
    result = build_tools(workspace)["read_table"].invoke({"path": "/../secret.csv"})

    assert result.startswith("Error:")


def test_rows_are_added_to_csv_and_excel_without_touching_what_is_there(workspace):
    from openpyxl import Workbook, load_workbook

    add = build_tools(workspace)["add_table_rows"]
    (workspace.root / "expenses.csv").write_text("date,title,amount\n1405/07/01,Rent,900", encoding="utf-8")
    book = Workbook()
    book.active.append(["date", "title", "amount"])
    book.active.append(["1405/07/01", "Rent", 900])
    book.active["E1"] = "=SUM(C:C)"
    book.save(workspace.root / "expenses.xlsx")

    for name in ("/expenses.csv", "/expenses.xlsx"):
        assert add.invoke({"path": name, "rows": [{"date": "1405/07/12", "title": "تاکسی", "amount": 250}, {"title": "Lunch"}]}).startswith("Added 2 rows")
        assert add.invoke({"path": name, "rows": [{"price": 1}]}).startswith("Error: no such columns: price")

    assert (workspace.root / "expenses.csv").read_text(encoding="utf-8").splitlines() == ["date,title,amount", "1405/07/01,Rent,900", "1405/07/12,تاکسی,250", ",Lunch,"]
    sheet = load_workbook(workspace.root / "expenses.xlsx").active
    assert [cell.value for cell in sheet[3]][:3] == ["1405/07/12", "تاکسی", 250] and sheet["E1"].value == "=SUM(C:C)"
    assert add.invoke({"path": "/../outside.csv", "rows": [{"a": 1}]}).startswith("Error:")


def test_adding_rows_follows_the_file_rules_like_any_other_write(workspace):
    assert _policy(workspace, "ask").decide("add_table_rows", {"path": "/expenses.xlsx", "rows": []}) == "ask"
    assert _policy(workspace, "read_only").decide("add_table_rows", {"path": "/expenses.xlsx", "rows": []}) == "deny"


# ── permissions ──


def _policy(workspace, mode):
    return build_policy(load_rules(workspace.rules_file), mode)


def test_ask_mode_follows_the_rules_file(workspace):
    policy = _policy(workspace, "ask")

    assert policy.decide("write_file", {"file_path": "/report.md"}) == "ask"
    assert policy.decide("write_file", {"file_path": "/.harness/runs/t1/note.md"}) == "allow"
    assert policy.decide("read_file", {"file_path": "/report.md"}) == "allow"
    assert policy.decide("execute", {"command": "dir"}) == "ask"


def test_auto_mode_turns_ask_into_allow_but_keeps_deny(workspace):
    rules = """
files:
  - {paths: ['/finance/**'], operations: [write], access: deny}
  - {paths: ['/**'], operations: [write], access: ask}
tools: {execute: ask}
"""
    workspace.rules_file.write_text(rules, encoding="utf-8")
    policy = _policy(workspace, "auto")

    assert policy.decide("edit_file", {"file_path": "/finance/budget.xlsx"}) == "deny"
    assert policy.decide("write_file", {"file_path": "/report.md"}) == "allow"
    assert policy.decide("execute", {}) == "allow"


def test_read_only_mode_denies_writes_and_the_shell(workspace):
    policy = _policy(workspace, "read_only")

    assert policy.decide("write_file", {"file_path": "/report.md"}) == "deny"
    assert policy.decide("read_file", {"file_path": "/report.md"}) == "allow"
    assert not policy.allow_shell


def test_a_rule_about_a_folder_covers_the_folder_itself(workspace):
    rules = """
files:
  - {paths: ['/secrets/**'], operations: [read], access: deny}
"""
    workspace.rules_file.write_text(rules, encoding="utf-8")
    policy = _policy(workspace, "ask")

    assert policy.decide("ls", {"path": "/secrets"}) == "deny"
    assert policy.decide("read_file", {"file_path": "/secrets/keys.txt"}) == "deny"
    assert policy.decide("ls", {"path": "/"}) == "allow"


def test_a_rule_cannot_be_dodged_by_spelling_the_path_differently(workspace):
    workspace.rules_file.write_text("files:\n  - {paths: ['/finance/**'], operations: [write], access: deny}\n", encoding="utf-8")
    policy = _policy(workspace, "auto")

    for spelling in ("/finance/budget.md", "finance/budget.md", "/notes/../finance/budget.md", "//finance/budget.md", "\\finance\\budget.md"):
        assert policy.decide("write_file", {"file_path": spelling}) == "deny", spelling
    if sys.platform != "linux":
        assert policy.decide("write_file", {"file_path": "/Finance/budget.md"}) == "deny"


def test_an_agent_never_changes_its_own_rules_without_approval(workspace):
    workspace.rules_file.write_text("files:\n  - {paths: ['/**'], operations: [write], access: allow}\n", encoding="utf-8")

    assert _policy(workspace, "auto").decide("write_file", {"file_path": "/.harness/rules.yaml"}) == "ask"
    assert _policy(workspace, "auto").decide("delete", {"file_path": "/x/../.harness/rules.yaml"}) == "ask"
    assert _policy(workspace, "read_only").decide("edit_file", {"file_path": "/.harness/rules.yaml"}) == "deny"


def test_missing_or_broken_rules_never_mean_everything_is_allowed(workspace):
    workspace.rules_file.unlink()
    assert _policy(workspace, "ask").decide("execute", {"command": "dir"}) == "ask"

    for broken in ("files: [unclosed", "just a sentence", "tools: {execute: sometimes}", "files:\n  - {access: allow}\n"):
        workspace.rules_file.write_text(broken, encoding="utf-8")
        with pytest.raises(ValueError):
            load_rules(workspace.rules_file)


def test_a_half_written_agent_or_skill_file_is_skipped(workspace):
    (workspace.agents_dir / "broken.yaml").write_text("name: [unclosed", encoding="utf-8")
    (workspace.skills_dir / "broken").mkdir()
    (workspace.skills_dir / "broken" / "SKILL.md").write_text("---\nname: [unclosed\n---\nbody", encoding="utf-8")

    assert [agent.id for agent in list_agents(workspace)] == ["code-reviewer"]
    assert {skill.id for skill in list_skills(workspace)} == {"coding-checks", "broken"}


def test_a_task_id_is_a_plain_name(workspace):
    with pytest.raises(ValueError):
        workspace.run_dir("../outside")


# ── no host shell ──


def test_the_host_shell_backend_is_gone():
    import harness.sandbox as sandbox

    assert not hasattr(sandbox, "GuardedShellBackend")
    assert not hasattr(sandbox, "LocalShellBackend")


@pytest.mark.parametrize("allow_shell", [True, False])
def test_a_command_never_runs_on_the_host_without_a_sandbox(workspace, allow_shell):
    backend = build_backend(workspace, allow_shell=allow_shell)

    # No execution surface at all: deepagents never registers a shell tool.
    assert not hasattr(backend, "execute")
    assert not (workspace.root / "from-shell.txt").exists()


@pytest.mark.parametrize("allow_shell", [True, False])
def test_file_tools_are_read_only_without_a_sandbox(workspace, allow_shell):
    (workspace.root / "note.txt").write_text("hello", encoding="utf-8")
    backend = build_backend(workspace, allow_shell=allow_shell)

    assert backend.read("/note.txt").file_data["content"] == "hello"
    assert backend.write("/new.txt", "x").error
    assert backend.edit("/note.txt", "hello", "bye").error
    assert backend.delete("/note.txt").error
    assert not (workspace.root / "new.txt").exists()
    assert (workspace.root / "note.txt").read_text(encoding="utf-8") == "hello"


def test_custom_write_tools_are_not_registered_without_a_sandbox(workspace):
    from harness.core import available_tools
    from harness.permissions import WRITE_TOOLS

    backend = build_backend(workspace, allow_shell=True)
    names = set(available_tools(workspace, backend))

    assert not (names & WRITE_TOOLS), "a tool that bypasses the backend must not exist without a sandbox"
    assert {"read_table", "read_document", "list_archive", "calculate"} <= names


async def test_without_a_sandbox_the_browser_cannot_write_a_screenshot(workspace):
    tools = build_tools(workspace, allow_writes=False)

    result = await tools["browse_page"].ainvoke({"url": "https://example.com", "screenshot": True})

    assert "read-only" in result
    assert not (workspace.harness / "artifacts" / "screenshots").exists(), "a screenshot would be a project write"


async def test_the_agent_cannot_reach_the_local_mutation_endpoints():
    from harness.tools.browser import _refusal

    # The browser tool is the only channel out of the agent; local addresses are refused,
    # so it cannot call the human-only PUT/POST endpoints of the app on loopback.
    assert await _refusal("http://127.0.0.1:8765/files/content") is not None
    assert await _refusal("http://localhost:8765/workspace") is not None
    assert await _refusal("http://[::1]:8765/memory") is not None


# ── knowledge on disk ──


def test_scaffold_creates_readable_defaults_and_never_overwrites(workspace):
    assert [skill.id for skill in list_skills(workspace)] == ["coding-checks"]
    assert [agent.id for agent in list_agents(workspace)] == ["code-reviewer"]

    workspace.rules_file.write_text("files: []\n", encoding="utf-8")
    workspace.scaffold()
    assert workspace.rules_file.read_text(encoding="utf-8") == "files: []\n"
