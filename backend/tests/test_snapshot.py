"""Snapshots: what is copied, what is left out, and that the copy is exact."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from harness.worktrees import snapshot as snap


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "docs").mkdir(parents=True)
    (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("راهنما\n", encoding="utf-8")
    (root / "data.bin").write_bytes(bytes(range(256)))
    return root


def test_default_exclusions_keep_dependencies_and_secrets_out(tmp_path):
    root = _workspace(tmp_path)
    for folder in ("node_modules", ".venv", "venv", "__pycache__", ".git", ".harness"):
        (root / folder).mkdir()
        (root / folder / "inside.txt").write_text("x", encoding="utf-8")
    (root / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (root / "id_rsa").write_text("private", encoding="utf-8")
    (root / "server.pem").write_text("cert", encoding="utf-8")

    manifest = snap.build(root)

    assert [entry.path for entry in manifest.files] == ["app.py", "data.bin", "docs/guide.md"]
    reasons = {item["path"]: item["reason"] for item in manifest.excluded}
    assert reasons[".env"] == "secret file"
    assert reasons["id_rsa"] == "secret file"
    assert reasons["node_modules"] == "dependency, cache or harness folder"
    assert reasons[".harness"] == "dependency, cache or harness folder"
    # Nothing inside an excluded folder is walked, so no nested path is listed.
    assert all(not path.startswith(".harness/") for path in reasons)


def test_a_persian_folder_and_file_name_with_spaces_is_copied_exactly(tmp_path):
    root = _workspace(tmp_path)
    folder = root / "پروژهٔ من" / "اسناد کاری"
    folder.mkdir(parents=True)
    (folder / "گزارش نهایی.md").write_text("سلام دنیا\n", encoding="utf-8")

    manifest = snap.build(root)
    destination = tmp_path / "snapshot"
    report = snap.sync(manifest, destination)

    assert "پروژهٔ من/اسناد کاری/گزارش نهایی.md" in [entry.path for entry in manifest.files]
    assert "پروژهٔ من/اسناد کاری/گزارش نهایی.md" in report.copied
    assert (destination / "پروژهٔ من" / "اسناد کاری" / "گزارش نهایی.md").read_text(encoding="utf-8") == "سلام دنیا\n"


def test_hashes_are_of_the_raw_bytes_and_bom_newline_are_recorded(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    raw = "\ufeffخط اول\r\nخط دوم\r\n".encode("utf-8")
    (root / "bom.txt").write_bytes(raw)

    entry = snap.build(root).files[0]

    assert entry.encoding == "utf-8-sig"
    assert entry.newline == "crlf"
    assert entry.size == len(raw)
    assert entry.sha256 == hashlib.sha256(raw).hexdigest()


def test_sync_is_exact_and_incremental(tmp_path):
    root = _workspace(tmp_path)
    destination = tmp_path / "snapshot"
    first = snap.build(root)

    report = snap.sync(first, destination)
    assert sorted(report.copied) == ["app.py", "data.bin", "docs/guide.md"]
    assert (destination / "docs" / "guide.md").read_text(encoding="utf-8") == "راهنما\n"
    assert (destination / "data.bin").read_bytes() == (root / "data.bin").read_bytes()
    assert snap.manifest_path(destination).exists()

    # Nothing changed: the second sync copies nothing and reports why.
    again = snap.sync(snap.build(root), destination, previous=first)
    assert again.copied == [] and again.removed == []
    assert sorted(again.skipped) == ["app.py", "data.bin", "docs/guide.md"]

    # One changed file is the only file rewritten.
    (root / "app.py").write_text("print('changed')\n", encoding="utf-8")
    second = snap.build(root)
    changed = snap.sync(second, destination, previous=first)
    assert changed.copied == ["app.py"]
    assert (destination / "app.py").read_text(encoding="utf-8") == "print('changed')\n"

    # A file removed from the source is pruned from the copy only.
    (root / "data.bin").unlink()
    third = snap.build(root)
    removed = snap.sync(third, destination, previous=second)
    assert removed.removed == ["data.bin"]
    assert not (destination / "data.bin").exists()
    assert (root / "app.py").exists()


def test_sync_preserves_bom_and_crlf_bytes(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    raw = "\ufeffa\r\nb\r\n".encode("utf-8")
    (root / "bom.txt").write_bytes(raw)
    destination = tmp_path / "snapshot"

    snap.sync(snap.build(root), destination)

    assert (destination / "bom.txt").read_bytes() == raw


def test_the_manifest_file_sits_beside_the_copy(tmp_path):
    root = _workspace(tmp_path)
    destination = tmp_path / "snapshot"
    snap.sync(snap.build(root), destination)

    manifest = snap.load_manifest(snap.manifest_path(destination))
    assert manifest is not None
    assert [entry.path for entry in manifest.files] == ["app.py", "data.bin", "docs/guide.md"]
    # It is not inside the folder the agent sees.
    assert not (destination / snap.manifest_path(destination).name).exists()


def test_limits_are_hard_not_silent(tmp_path):
    root = _workspace(tmp_path)

    with pytest.raises(snap.SnapshotTooLarge):
        snap.build(root, max_files=1)
    with pytest.raises(snap.SnapshotTooLarge):
        snap.build(root, max_bytes=10)


@pytest.mark.parametrize("value", ["../x", "/etc/passwd", "C:\\Windows\\win.ini", "a/../../b", "CON", "aux.txt", "bad\x00name", "trailing. ", "a//b", "./a"])
def test_unsafe_paths_are_rejected(value):
    with pytest.raises(snap.UnsafePath):
        snap.validate_relative(value)


def test_a_normal_relative_path_is_normalized():
    assert str(snap.validate_relative("docs/guide.md")) == "docs/guide.md"
    assert str(snap.validate_relative("docs\\guide.md")) == "docs/guide.md"


def test_within_refuses_an_outside_path(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert snap.within(root, root / "inside.txt")
    assert not snap.within(root, tmp_path / "outside.txt")


def test_a_junction_is_never_followed(tmp_path):
    if os.name != "nt":
        pytest.skip("junctions are a Windows feature")
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "linked"
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True, check=False)
    if created.returncode != 0:
        pytest.skip(f"could not create a junction: {created.stderr or created.stdout}")

    manifest = snap.build(root)

    assert manifest.files == ()
    assert any(item["path"] == "linked" and "link" in item["reason"] for item in manifest.excluded)


def test_a_symlink_is_never_followed(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlinks are not available: {error}")

    manifest = snap.build(root)

    assert manifest.files == ()
    assert any(item["path"] == "link.txt" for item in manifest.excluded)


def test_the_source_is_not_modified(tmp_path):
    root = _workspace(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    snap.build(root)

    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
