"""Context: bounded searches, sliced reads, and path/secret rules."""

from __future__ import annotations

import pytest

from harness.worktrees import context
from harness.worktrees.snapshot import UnsafePath


@pytest.fixture
def root(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "app.py").write_text("first line\nTODO: گزارش فروش\nlast line\n", encoding="utf-8")
    (workspace / "src" / "notes.md").write_text("یک یادداشت درباره گزارش\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "dep.js").write_text("TODO: not ours\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=TODO-secret\n", encoding="utf-8")
    (workspace / "binary.bin").write_bytes(b"TODO\x00\x01\x02")
    return workspace


def test_search_is_literal_and_skips_dependencies_secrets_and_binaries(root):
    result = context.search(root, "TODO")

    assert [match.path for match in result.matches] == ["src/app.py"]
    assert result.matches[0].line == 2 and result.matches[0].column == 1
    assert result.scanned >= 2
    assert result.skipped >= 2


def test_search_finds_utf8_and_can_be_case_sensitive(root):
    assert len(context.search(root, "گزارش").matches) == 2
    assert context.search(root, "todo", case_sensitive=True).matches == []


def test_search_can_filter_by_glob_and_cap_results(root):
    (root / "src" / "many.txt").write_text("\n".join("hit" for _ in range(20)), encoding="utf-8")

    only = context.search(root, "hit", glob="*.txt")
    assert only.matches and {match.path for match in only.matches} == {"src/many.txt"}

    capped = context.search(root, "hit", max_results=3)
    assert len(capped.matches) == 3 and capped.truncated is True


def test_search_does_not_follow_a_link_outside_the_workspace(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle", encoding="utf-8")
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are not available: {error}")

    result = context.search(root, "needle")

    assert result.matches == []


def test_read_slice_strips_the_bom_but_reports_it_and_keeps_crlf_info(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "bom.txt").write_bytes("\ufeffline one\r\nline two\r\nline three\r\n".encode("utf-8"))

    window = context.read_slice(workspace, "bom.txt", start_line=2, end_line=2)

    assert window.content == "line two"
    assert (window.start_line, window.end_line, window.total_lines) == (2, 2, 3)
    assert window.bom is True and window.encoding == "utf-8-sig" and window.newline == "crlf"
    assert window.truncated is False


def test_read_slice_enforces_line_and_byte_caps(root):
    lines = context.read_slice(root, "src/app.py", start_line=1, end_line=99, max_lines=2)
    assert lines.end_line == 2 and lines.truncated is True

    clipped = context.read_slice(root, "src/app.py", max_bytes=5)
    assert len(clipped.content.encode("utf-8")) <= 5 and clipped.truncated is True


def test_read_slice_refuses_outside_paths_and_secrets(root):
    with pytest.raises(UnsafePath):
        context.read_slice(root, "../outside.txt")
    with pytest.raises(UnsafePath):
        context.read_slice(root, ".env")


def test_clip_context_is_a_byte_budget():
    text = "سلام" * 100
    clipped, truncated = context.clip_context(text, 10)

    assert truncated is True
    assert len(clipped.encode("utf-8")) <= 10
    assert context.clip_context("short", 10) == ("short", False)
