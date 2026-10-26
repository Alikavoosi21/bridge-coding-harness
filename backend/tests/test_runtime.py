"""The Docker template and the runtime adapter.

These tests prove the command that *would* run is locked down. They do not
prove confinement: without Docker on the machine there is no container to
inspect, so the real proof lives in `test_docker_confinement.py` and stays
skipped here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.backends.container import ContainerBackend
from harness.runtime.docker import (
    Capability,
    ContainerConfig,
    DockerRuntime,
    ExecResult,
    RuntimeUnavailable,
    build_image_args,
    build_run_args,
    image_contract,
)
from harness.worktrees.lease import LeaseLost, WriterLease


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    folder = tmp_path / "snapshot"
    folder.mkdir()
    (folder / "note.txt").write_text("hello", encoding="utf-8")
    return folder


def test_the_container_template_is_locked_down(snapshot):
    args = build_run_args(ContainerConfig(), snapshot, "exec-1", "echo hi")

    joined = " ".join(args)
    assert args[:2] == ["docker", "run"]
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--user 1000:1000" in joined
    assert "--memory 4g" in joined and "--memory-swap 4g" in joined
    assert "--cpus 2" in joined and "--pids-limit 256" in joined
    assert f"{snapshot.resolve()}:/workspace:rw" in args
    assert "--tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m" in joined
    # Nothing that would publish a port or mount a host folder other than the snapshot.
    assert "-p" not in args and "--publish" not in args
    assert "--privileged" not in args
    assert "--network" in args and "host" not in args[args.index("--network") + 1]
    assert "docker.sock" not in joined, "the Docker socket is never mounted"
    assert args.count("-v") == 1, "only the snapshot is mounted"
    assert args[-4:] == ["bridge-coding-sandbox:0.2", "sh", "-lc", "echo hi"]
    # No host environment is forwarded.
    assert "--env-file" not in args
    assert not any(arg.startswith(("HARNESS_TOKEN=", "ANTHROPIC_API_KEY=")) for arg in args)


def test_skills_are_mounted_read_only(snapshot, tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    args = build_run_args(ContainerConfig(), snapshot, "exec-1", "ls", skills=skills)

    assert f"{skills.resolve()}:/skills:ro" in args


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exec_id": "../escape"},
        {"workdir": "/etc"},
        {"extra_env": {"ANTHROPIC_API_KEY": "sk-secret"}},
        {"extra_env": {"LANG": "x\ny"}},
    ],
)
def test_unsafe_settings_are_refused(snapshot, kwargs):
    exec_id = kwargs.pop("exec_id", "exec-1")
    with pytest.raises(ValueError):
        build_run_args(ContainerConfig(), snapshot, exec_id, "echo", **kwargs)


def test_a_missing_snapshot_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_run_args(ContainerConfig(), tmp_path / "missing", "exec-1", "echo")


def test_capability_reports_a_missing_docker_honestly():
    runtime = DockerRuntime(which=lambda name: None)

    capability = runtime.capability()

    assert capability.available is False
    assert "not installed" in capability.reason
    with pytest.raises(RuntimeUnavailable):
        runtime.execute("echo hi", snapshot=Path("."))


def test_capability_reports_a_stopped_engine_and_a_missing_image():
    stopped = DockerRuntime(which=lambda name: "docker", run=lambda *args, **kwargs: _completed(1, "", "error"))
    assert stopped.capability().available is False

    def run(argv, **kwargs):
        if argv[1] == "version":
            return _completed(0, "27.0.0")
        return _completed(1, "", "no such image")

    missing = DockerRuntime(which=lambda name: "docker", run=run)
    capability = missing.capability()
    assert capability.server_version == "27.0.0"
    assert capability.image_present is False and capability.available is False


def test_a_missing_image_can_be_built_after_consent():
    """The one case that needs a build must not first demand the image it builds."""
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "version":
            return _completed(0, "27.0.0")
        return _completed(0, "built", "")

    runtime = DockerRuntime(which=lambda name: "docker", run=run)

    result = runtime.build_image()

    assert result["built"] is True
    assert [call[1] for call in calls] == ["version", "build"]


def test_building_without_a_reachable_engine_is_unavailable_not_a_crash():
    runtime = DockerRuntime(which=lambda name: None)

    with pytest.raises(RuntimeUnavailable, match="not installed"):
        runtime.build_image()


def test_execute_passes_only_the_built_argv_and_captures_output(snapshot, monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(argv)
        return _completed(0, "hello\n", "")

    runtime = DockerRuntime(which=lambda name: "docker", run=run)
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    result = runtime.execute("echo hello", snapshot=snapshot, exec_id="exec-1")

    assert result.exit_code == 0 and result.output == "hello\n"
    assert len(calls) == 1
    assert calls[0][1] == "run" and calls[0][-1] == "echo hello"
    assert "PATH" not in calls[0]


def test_execute_caps_the_output(snapshot, monkeypatch):
    runtime = DockerRuntime(which=lambda name: "docker", run=lambda argv, **kwargs: _completed(0, "x" * 100))
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))

    result = runtime.execute("cat big", snapshot=snapshot, exec_id="exec-1", max_output=10)

    assert result.truncated is True and len(result.output) == 10


def test_a_timeout_kills_the_named_container_and_reports_124(snapshot, monkeypatch):
    killed: list[str] = []
    runtime = DockerRuntime(which=lambda name: "docker", run=lambda argv, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 1)))
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    monkeypatch.setattr(runtime, "_kill", lambda name, wait=True: killed.append(name) or (True, True))

    result = runtime.execute("sleep 999", snapshot=snapshot, exec_id="exec-9", timeout=1)

    assert result.timed_out is True and result.exit_code == 124
    assert result.unknown is False
    assert killed == ["harness-exec-9"]


def test_an_unconfirmed_kill_is_unknown_never_success(snapshot, monkeypatch):
    runtime = DockerRuntime(which=lambda name: "docker", run=lambda argv, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(argv, 1)))
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    monkeypatch.setattr(runtime, "_kill", lambda name, wait=True: (False, False))

    result = runtime.execute("sleep 999", snapshot=snapshot, exec_id="exec-9", timeout=1)

    assert result.unknown is True and result.exit_code == 124
    assert result.operation_id == "exec-9"
    assert runtime.pending_unknown() == ("exec-9",)


def test_an_unknown_operation_blocks_the_next_dispatch_until_reconcile(snapshot, monkeypatch):
    def run(argv, **kwargs):
        if argv[1] == "ps":
            return _completed(0, "", "")  # the container is gone
        raise subprocess.TimeoutExpired(argv, 1)

    runtime = DockerRuntime(which=lambda name: "docker", run=run)
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    monkeypatch.setattr(runtime, "_kill", lambda name, wait=True: (False, False))

    first = runtime.execute("sleep 999", snapshot=snapshot, exec_id="exec-9", timeout=1)
    assert first.unknown is True
    with pytest.raises(RuntimeUnavailable, match="unknown"):
        runtime.execute("echo next", snapshot=snapshot, exec_id="exec-10")

    assert runtime.reconcile() == {"resolved": ["exec-9"], "unresolved": []}
    assert runtime.pending_unknown() == ()


def test_an_unresolved_unknown_operation_keeps_blocking(snapshot, monkeypatch):
    def run(argv, **kwargs):
        if argv[1] == "ps":
            return _completed(1, "", "daemon error")
        raise subprocess.TimeoutExpired(argv, 1)

    runtime = DockerRuntime(which=lambda name: "docker", run=run)
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    monkeypatch.setattr(runtime, "_kill", lambda name, wait=True: (False, False))

    runtime.execute("sleep 999", snapshot=snapshot, exec_id="exec-9", timeout=1)
    assert runtime.reconcile() == {"resolved": [], "unresolved": ["exec-9"]}
    with pytest.raises(RuntimeUnavailable, match="unknown"):
        runtime.execute("echo next", snapshot=snapshot, exec_id="exec-10")


def test_a_stale_writer_lease_stops_files_and_commands_before_they_run(snapshot):
    granted = {"id": "wslease_1", "fencing_token": 4, "expires_at": 9_999_999_999.0}
    lookup = {"row": dict(granted)}
    lease = WriterLease("ws_1", "wslease_1", 4, lambda workspace_id: lookup["row"])
    runtime = _FakeRuntime()
    backend = ContainerBackend(snapshot, runtime, lease=lease)

    backend.write("/ok.txt", "first")
    assert (snapshot / "ok.txt").read_text(encoding="utf-8") == "first"

    # A newer writer holds the workspace: the fencing token no longer matches.
    lookup["row"] = {"id": "wslease_2", "fencing_token": 5, "expires_at": 9_999_999_999.0}
    with pytest.raises(LeaseLost):
        backend.write("/late.txt", "second")
    with pytest.raises(LeaseLost):
        backend.execute("echo hi")

    assert not (snapshot / "late.txt").exists()
    assert runtime.commands == []


def test_an_expired_writer_lease_is_not_a_permission(snapshot):
    row = {"id": "wslease_1", "fencing_token": 1, "expires_at": 100.0}
    lease = WriterLease("ws_1", "wslease_1", 1, lambda workspace_id: row, now=lambda: 101.0)
    backend = ContainerBackend(snapshot, _FakeRuntime(), lease=lease)

    with pytest.raises(LeaseLost, match="expired"):
        backend.write("/late.txt", "no")


def test_a_cancelled_command_is_stopped(snapshot, monkeypatch):
    runtime = DockerRuntime(which=lambda name: "docker", run=lambda argv, **kwargs: _completed(130, "", ""))
    monkeypatch.setattr(runtime, "require", lambda: Capability(True, "ok"))
    monkeypatch.setattr(runtime, "_kill", lambda name, wait=True: (True, True))

    def cancel_during_call(exec_id: str) -> None:
        runtime._cancelled.add(exec_id)

    runtime.cancel("exec-1")  # called before the process starts, as the stop button can
    result = runtime.execute("long", snapshot=snapshot, exec_id="exec-1")

    assert result.stopped is True and result.exit_code == 130
    assert result.unknown is False


@pytest.mark.parametrize('confirmed',[True,False])
def test_stop_during_execute_has_correct_confirmation_polarity(snapshot,monkeypatch,confirmed):
    def run(argv,**kwargs):
        runtime._cancelled.add('exec-stop')
        return _completed(130)
    runtime=DockerRuntime(which=lambda name:'docker',run=run)
    monkeypatch.setattr(runtime,'require',lambda:Capability(True,'fixture'))
    monkeypatch.setattr(runtime,'_kill',lambda name,wait=True:(confirmed,confirmed))
    result=runtime.execute('fixture-no-real-shell',snapshot=snapshot,exec_id='exec-stop')
    assert result.stopped and result.unknown is (not confirmed)


def test_pin_image_uses_actual_id_in_subsequent_container_configuration(monkeypatch):
    runtime=DockerRuntime(which=lambda name:'docker',run=lambda argv,**kwargs:_completed(0,'sha256:'+'a'*64))
    monkeypatch.setattr(runtime,'require',lambda:Capability(True,'fixture'))
    assert runtime.pin_image()=='sha256:'+'a'*64
    assert runtime.config.image=='sha256:'+'a'*64


async def test_adapter_refusal_has_a_failed_receipt_instead_of_the_previous_success(snapshot):
    class Unavailable:
        def execute(self,*args,**kwargs):raise RuntimeUnavailable('fixture unavailable')
    backend=ContainerBackend(snapshot,Unavailable())
    backend.last_receipt=ExecResult('old',0,'old success')
    with backend.operation_scope('op_refused'):
        result=await backend.aexecute('fixture-no-shell')
        assert result.exit_code==126
        assert backend.last_receipt.operation_id=='op_refused'
        assert backend.last_receipt.exit_code==126


class _FakeRuntime:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.exec_ids: list[str] = []

    def execute(self, command: str, **kwargs) -> ExecResult:
        self.commands.append(command)
        self.exec_ids.append(kwargs["exec_id"])
        return ExecResult(exec_id=kwargs.get("exec_id", "exec-1"), exit_code=0, output="ran")

    def cancel_all(self) -> None:
        pass

    def capability(self) -> Capability:
        return Capability(True, "fake")


def test_the_container_backend_reads_snapshot_files_and_delegates_execute(snapshot):
    runtime = _FakeRuntime()
    backend = ContainerBackend(snapshot, runtime)

    assert backend.read("/note.txt").file_data["content"] == "hello"
    assert backend.write("/made.txt", "written").error is None
    assert (snapshot / "made.txt").read_text(encoding="utf-8") == "written"
    assert backend.execute("echo hi").output == "ran"
    assert runtime.commands == ["echo hi"]
    assert backend.id.startswith("container:")


def test_two_deliberate_identical_commands_are_different_operations(snapshot):
    runtime = _FakeRuntime()
    backend = ContainerBackend(snapshot, runtime)

    backend.bind_operation("op_first")
    backend.execute("echo same")
    backend.bind_operation("op_second")
    backend.execute("echo same")

    assert runtime.exec_ids == ["op_first", "op_second"]


def test_resuming_the_same_invocation_reuses_its_operation_id(snapshot):
    runtime = _FakeRuntime()
    backend = ContainerBackend(snapshot, runtime)

    backend.bind_operation("op_resume")
    backend.execute("echo same")
    # A restart or a new run segment binds the stored id again; the runtime sees one operation.
    backend.bind_operation("op_resume")
    backend.execute("echo same")

    assert runtime.exec_ids == ["op_resume", "op_resume"]


def test_an_unbound_call_gets_a_random_id_not_one_derived_from_the_command(snapshot):
    runtime = _FakeRuntime()
    backend = ContainerBackend(snapshot, runtime)

    backend.execute("echo same")
    backend.execute("echo same")

    assert runtime.exec_ids[0] != runtime.exec_ids[1]
    assert not any(str(abs(hash("echo same"))) in identifier for identifier in runtime.exec_ids)


def test_an_unsafe_operation_id_is_refused(snapshot):
    backend = ContainerBackend(snapshot, _FakeRuntime())

    with pytest.raises(ValueError):
        backend.bind_operation("../escape")


def test_the_image_definition_is_reproducible_and_non_root():
    contract = image_contract()
    dockerfile = Path(contract["dockerfile"])

    assert contract["image"] == "bridge-coding-sandbox:0.2"
    assert dockerfile.name == "Dockerfile" and dockerfile.is_file()
    text = dockerfile.read_text(encoding="utf-8")
    assert "USER 1000:1000" in text
    assert "groupadd --gid 1000 sandbox" in text
    assert "ARG BASE_IMAGE=" in text
    assert "sha256:<digest>" in text, "release builds must pin the base image by digest"
    assert "HARNESS_TOKEN" not in text and "API_KEY" not in text
    assert "WORKDIR /workspace" in text
    assert contract["build"][:2] == ["docker", "build"]
    assert "--build-arg" in contract["build"]


def test_a_release_image_must_pin_its_base_by_digest():
    pinned = "python:3.12-slim-bookworm@sha256:" + "a" * 64
    assert build_image_args(pinned, release=True)[:4] == ["docker", "build", "--build-arg", f"BASE_IMAGE={pinned}"]
    with pytest.raises(ValueError, match="digest"):
        build_image_args("python:3.12-slim-bookworm", release=True)
    with pytest.raises(ValueError):
        build_image_args("python:3.12; rm -rf /", release=False)
