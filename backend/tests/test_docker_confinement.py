"""Real confinement: run the template on Docker and look at what is inside.

The pure-argv tests in `test_runtime.py` prove the command *would* be locked
down. They are not proof of confinement: only a real container shows which
uid runs, what the kernel reports for capabilities, whether the network is
reachable and whether the mount is the snapshot or the user's folder.

This module skips as a whole when Docker or the sandbox image is missing. The
skip reason is explicit so a green suite is never mistaken for proof.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from harness.runtime.docker import DEFAULT_IMAGE, DockerRuntime


def _unavailable() -> str | None:
    if shutil.which("docker") is None:
        return "Docker CLI is not installed; real confinement was NOT verified."
    try:
        version = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Docker did not answer ({error}); real confinement was NOT verified."
    if version.returncode != 0:
        return "Docker is installed but its engine is not running; real confinement was NOT verified."
    image = subprocess.run(["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, text=True, timeout=15, check=False)
    if image.returncode != 0:
        return f"The sandbox image {DEFAULT_IMAGE} is not built; real confinement was NOT verified."
    return None


REASON = _unavailable()
pytestmark = pytest.mark.skipif(REASON is not None, reason=REASON or "")


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "note.txt").write_text("inside", encoding="utf-8")
    return folder


@pytest.fixture
def runtime() -> DockerRuntime:
    return DockerRuntime()


def _run(runtime: DockerRuntime, snapshot: Path, command: str, **kwargs):
    return runtime.execute(command, snapshot=snapshot, exec_id=f"conf-{uuid.uuid4().hex[:10]}", **kwargs)


def test_the_command_runs_as_the_non_root_sandbox_user(runtime, snapshot):
    result = _run(runtime, snapshot, "id -u; id -g; whoami")

    assert result.exit_code == 0, result.output
    uid, gid, name = result.output.split()
    assert (uid, gid) == ("1000", "1000")
    assert name == "sandbox"


def test_the_root_filesystem_is_read_only(runtime, snapshot):
    write_root = _run(runtime, snapshot, "echo x > /not-allowed.txt")
    write_bin = _run(runtime, snapshot, "echo x > /usr/local/bin/not-allowed")

    assert write_root.exit_code != 0
    assert write_bin.exit_code != 0
    assert "Read-only file system" in (write_root.output + write_bin.output)


def test_the_network_is_off(runtime, snapshot):
    result = _run(runtime, snapshot, "curl -sS --max-time 3 https://example.com > /dev/null || echo BLOCKED")

    assert result.exit_code == 0, result.output
    assert "BLOCKED" in result.output


def test_capabilities_are_dropped_and_no_new_privileges_is_set(runtime, snapshot):
    result = _run(runtime, snapshot, "grep -E '^(CapEff|NoNewPrivs):' /proc/self/status")

    lines = dict(line.split(":", 1) for line in result.output.strip().splitlines())
    assert int(lines["CapEff"].strip(), 16) == 0
    assert lines["NoNewPrivs"].strip() == "1"


def test_the_workspace_mount_is_the_snapshot_not_the_users_folder(runtime, snapshot, tmp_path):
    user_folder = tmp_path / "user-project"
    user_folder.mkdir()
    (user_folder / "real.txt").write_text("do not touch", encoding="utf-8")

    result = _run(runtime, snapshot, "cat /workspace/note.txt; echo made > /workspace/made.txt; ls /workspace")

    assert result.exit_code == 0, result.output
    assert "inside" in result.output and "made.txt" in result.output
    assert (snapshot / "made.txt").read_text(encoding="utf-8").strip() == "made"
    assert not (user_folder / "made.txt").exists()
    assert (user_folder / "real.txt").read_text(encoding="utf-8") == "do not touch"


def test_the_host_environment_and_paths_are_not_visible(runtime, snapshot, monkeypatch):
    monkeypatch.setenv("HARNESS_TOKEN", "host-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-host-secret")

    result = _run(runtime, snapshot, "env")

    assert "host-secret" not in result.output
    assert "sk-host-secret" not in result.output
    assert "HARNESS_TOKEN" not in result.output
    assert "ANTHROPIC_API_KEY" not in result.output


def test_tmp_is_a_size_limited_tmpfs_and_cannot_execute(runtime, snapshot):
    mounted = _run(runtime, snapshot, "grep ' /tmp ' /proc/mounts")
    execute = _run(runtime, snapshot, "cp /bin/true /tmp/true 2>/dev/null && /tmp/true")

    assert "/tmp" in mounted.output and "noexec" in mounted.output
    assert execute.exit_code != 0


def test_memory_and_pid_ceilings_are_visible_to_the_kernel(runtime, snapshot):
    result = _run(runtime, snapshot, "cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max")

    limits = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert result.exit_code == 0, result.output
    assert limits[0].isdigit() and int(limits[0]) == 4 * 1024**3
    assert limits[1].isdigit() and int(limits[1]) == 256


def test_a_timeout_kills_the_container_and_leaves_nothing_behind(runtime, snapshot):
    exec_id = f"conf-{uuid.uuid4().hex[:10]}"
    result = runtime.execute("sleep 60", snapshot=snapshot, exec_id=exec_id, timeout=1)
    remaining = subprocess.run(["docker", "ps", "-a", "--filter", f"name=harness-{exec_id}", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=15, check=False)

    assert result.timed_out is True and result.exit_code == 124
    assert result.unknown is False, "the kill was confirmed"
    assert remaining.stdout.strip() == ""
