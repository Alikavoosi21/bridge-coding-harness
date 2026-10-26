"""Docker runtime: one disposable, locked-down container per command.

The template is the security boundary, so it is built in one pure function and
tested as data:

- non-root user, read-only root filesystem, every capability dropped,
  `no-new-privileges`
- no network (`--network none`), no published ports
- memory, CPU and PID ceilings
- only the snapshot is mounted read-write; skills are read-only; `/tmp` is a
  size-limited tmpfs
- a minimal environment; the host's environment, including provider keys and
  the API token, is never passed with `-e` or `--env-file`

Commands are identified by an execution id, so Stop can kill exactly one
container. If the kill cannot be confirmed the result is `unknown`, never
"succeeded".
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..worktrees.lease import WriterLease

# Mirrors of the contract limits, kept here so the harness does not import the
# HTTP layer. `server/storage/contract.py` is the user-facing copy.
COMMAND_TIMEOUT_S = 120
INSTALL_TIMEOUT_S = 600
OUTPUT_BYTES = 1_000_000

DEFAULT_IMAGE = "bridge-coding-sandbox:0.2"
SANDBOX_DIR = Path(__file__).with_name("sandbox")
DOCKERFILE = SANDBOX_DIR / "Dockerfile"
_SAFE_HOST_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "WINDIR", "TEMP", "TMP")
_EXEC_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class RuntimeUnavailable(RuntimeError):
    """Docker or the sandbox image is not usable; the caller must stay read-only."""


@dataclass(frozen=True)
class ContainerConfig:
    image: str = DEFAULT_IMAGE
    user: str = "1000:1000"
    cpus: str = "2"
    memory: str = "4g"
    pids: int = 256
    tmpfs_size: str = "512m"
    workspace: str = "/workspace"
    skills: str = "/skills"

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_./:@-]+", self.image):
            raise ValueError(f"Unsafe image name: {self.image}")
        for value in (self.user, self.cpus, self.memory, self.tmpfs_size, self.workspace, self.skills):
            if not re.fullmatch(r"[A-Za-z0-9_./:@-]+", value):
                raise ValueError(f"Unsafe container setting: {value}")


@dataclass(frozen=True)
class ExecResult:
    exec_id: str
    exit_code: int
    output: str
    truncated: bool = False
    timed_out: bool = False
    stopped: bool = False
    unknown: bool = False
    # The stored/controller id, not a hash of the command. Resuming the same
    # invocation carries the same value; two deliberate runs do not.
    operation_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "exec_id": self.exec_id,
            "operation_id": self.operation_id,
            "exit_code": self.exit_code,
            "output": self.output,
            "truncated": self.truncated,
            "timed_out": self.timed_out,
            "stopped": self.stopped,
            "unknown": self.unknown,
        }


@dataclass(frozen=True)
class Capability:
    available: bool
    reason: str
    server_version: str | None = None
    image: str = DEFAULT_IMAGE
    image_present: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "server_version": self.server_version,
            "image": self.image,
            "image_present": self.image_present,
        }


DEFAULT_BASE_IMAGE = "python:3.12-slim-bookworm"


def build_image_args(base_image: str = DEFAULT_BASE_IMAGE, *, release: bool = False) -> list[str]:
    """The reproducible `docker build` command for the sandbox image.

    A release build must name the base image by digest, so rebuilding the same
    tag on another day cannot silently pull different bytes. The developer
    default is a tag only, which is fine for local work and refused for release.
    """
    if not re.fullmatch(r"[A-Za-z0-9_./:@-]+", base_image):
        raise ValueError(f"Unsafe base image: {base_image}")
    if release and "@sha256:" not in base_image:
        raise ValueError("A release build must pin BASE_IMAGE by digest (@sha256:...).")
    return ["docker", "build", "--build-arg", f"BASE_IMAGE={base_image}", "-t", DEFAULT_IMAGE, str(SANDBOX_DIR)]


def image_contract(base_image: str = DEFAULT_BASE_IMAGE, *, release: bool = False) -> dict[str, Any]:
    """The reproducible image definition, for health output and tests."""
    return {
        "image": DEFAULT_IMAGE,
        "dockerfile": str(DOCKERFILE),
        "base_image": base_image,
        "release": release,
        "build": build_image_args(base_image, release=release),
    }


def build_run_args(
    config: ContainerConfig,
    snapshot: str | Path,
    exec_id: str,
    command: str,
    *,
    skills: str | Path | None = None,
    workdir: str | None = None,
    extra_env: dict[str, str] | None = None,
    network: bool = False,
) -> list[str]:
    """The complete `docker run` argv for one command. Pure: easy to audit."""
    config.validate()
    if not isinstance(network,bool):raise ValueError('Network access must be an explicit boolean.')
    if not _EXEC_ID.fullmatch(exec_id):
        raise ValueError(f"Unsafe execution id: {exec_id}")
    snapshot_dir = Path(snapshot).resolve()
    if not snapshot_dir.is_dir():
        raise FileNotFoundError(f"Snapshot folder does not exist: {snapshot_dir}")
    cwd = workdir or config.workspace
    if not cwd.startswith(config.workspace):
        raise ValueError(f"The working folder must be inside {config.workspace}: {cwd}")
    allowed_env = {"LANG", "LC_ALL", "TERM", "CI", "NO_COLOR"}
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"harness-{exec_id}",
        "--network",
        "bridge" if network else "none",
        "--ipc",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        config.user,
        "--memory",
        config.memory,
        "--memory-swap",
        config.memory,
        "--cpus",
        config.cpus,
        "--pids-limit",
        str(config.pids),
        "--ulimit",
        "nofile=1024:1024",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={config.tmpfs_size}",
        "--hostname",
        "sandbox",
        "--workdir",
        cwd,
        "-v",
        f"{snapshot_dir}:{config.workspace}:rw",
    ]
    if skills is not None:
        skills_dir = Path(skills).resolve()
        if not skills_dir.is_dir():
            raise FileNotFoundError(f"Skills folder does not exist: {skills_dir}")
        args += ["-v", f"{skills_dir}:{config.skills}:ro"]
    args += ["-e", "LANG=C.UTF-8", "-e", "LC_ALL=C.UTF-8", "-e", "TERM=dumb"]
    for key, value in (extra_env or {}).items():
        if key not in allowed_env:
            raise ValueError(f"Environment variable is not allowed in the sandbox: {key}")
        if "\n" in value or "\x00" in value:
            raise ValueError(f"Unsafe environment value for {key}")
        args += ["-e", f"{key}={value}"]
    args += [config.image, "sh", "-lc", command]
    return args


class DockerRuntime:
    """Runs commands in disposable containers. No shell ever runs on the host."""

    def __init__(
        self,
        config: ContainerConfig | None = None,
        *,
        lease: WriterLease | None = None,
        which: Callable[[str], str | None] = shutil.which,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.config = config or ContainerConfig()
        self._lease = lease
        self._which = which
        self._run = run
        self._cancelled: set[str] = set()
        self._confirmed_stops: set[str] = set()
        self._containers: dict[str, str] = {}
        # An operation whose stop could not be confirmed. Until reconcile says
        # otherwise, no competing dispatch is allowed from this runtime.
        self._unknown: set[str] = set()

    def set_lease(self, lease: WriterLease | None) -> None:
        """Install the writer lease checked before every command."""
        self._lease = lease

    # ── capability ───────────────────────────────────────────────────────────
    def _server_version(self) -> tuple[str | None, str | None]:
        """The Docker engine's version, or why it cannot be reached.

        This deliberately says nothing about the sandbox image: building a
        missing image needs a reachable engine, and checking for the image
        first would refuse the very build that creates it.
        """
        binary = self._which("docker")
        if not binary:
            return None, "Docker is not installed. The task stays read-only."
        try:
            version = self._run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._host_env(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, f"Docker did not answer: {error}"
        if version.returncode != 0:
            return None, "Docker is installed but its engine is not running. The task stays read-only."
        return (version.stdout or "").strip() or None, None

    def capability(self) -> Capability:
        server, reason = self._server_version()
        if reason is not None:
            return Capability(False, reason, image=self.config.image)
        image = self._run(
            ["docker", "image", "inspect", self.config.image],
            capture_output=True,
            text=True,
            timeout=15,
            env=self._host_env(),
            check=False,
        )
        if image.returncode != 0:
            return Capability(
                False,
                f"The sandbox image {self.config.image} is missing. Build it before running commands.",
                server_version=server,
                image=self.config.image,
            )
        return Capability(True, "Docker and the sandbox image are ready.", server_version=server, image=self.config.image, image_present=True)

    def require(self) -> Capability:
        capability = self.capability()
        if not capability.available:
            raise RuntimeUnavailable(capability.reason)
        return capability

    def pin_image(self) -> str:
        """Resolve the mutable configured tag to the immutable local image ID."""
        self.require()
        result=self._run(['docker','image','inspect','--format','{{.Id}}',self.config.image],capture_output=True,text=True,timeout=15,env=self._host_env(),check=False)
        identifier=(result.stdout or '').strip()
        if result.returncode or not re.fullmatch(r'sha256:[0-9a-f]{64}',identifier):
            raise RuntimeUnavailable('The sandbox image could not be pinned to an immutable ID.')
        from dataclasses import replace
        self.config=replace(self.config,image=identifier)
        return identifier

    def build_image(self, base_image: str = DEFAULT_BASE_IMAGE, *, release: bool = False, timeout: int = INSTALL_TIMEOUT_S) -> dict[str, Any]:
        """Build the sandbox image from the fixed contract. Never a user command.

        Called only after the user consents (`POST /runtime/prepare`). A release
        build must pin the base image by digest; the developer build may use a tag.
        """
        # Building is exactly the case where the image is missing, so check the
        # engine rather than `require()` (which also demands the image).
        _server, reason = self._server_version()
        if reason is not None:
            raise RuntimeUnavailable(reason)
        argv = build_image_args(base_image, release=release)
        try:
            completed = self._run(argv, capture_output=True, text=True, timeout=timeout, env=self._host_env(), check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeUnavailable(f"The sandbox image could not be built: {error}") from error
        output = (_text(completed.stdout) + _text(completed.stderr)).strip()
        if completed.returncode != 0:
            raise RuntimeUnavailable(f"The sandbox image could not be built: {_clip(output, 2_000)[0]}")
        return {"image": self.config.image, "built": True, "output": _clip(output, 4_000)[0]}

    # ── execution ────────────────────────────────────────────────────────────
    def execute(
        self,
        command: str,
        *,
        snapshot: str | Path,
        exec_id: str | None = None,
        timeout: int = COMMAND_TIMEOUT_S,
        workdir: str | None = None,
        skills: str | Path | None = None,
        env: dict[str, str] | None = None,
        max_output: int = OUTPUT_BYTES,
        network_until: float | None = None,
    ) -> ExecResult:
        """Run one command to completion, or stop it at `timeout` seconds."""
        if self._lease is not None:
            self._lease.check("execute")
        if self._unknown:
            pending = ", ".join(sorted(self._unknown))
            raise RuntimeUnavailable(f"An earlier command's result is unknown ({pending}); reconcile before dispatching another.")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("The command is empty.")
        if timeout <= 0:
            raise ValueError("The timeout must be positive.")
        if network_until is not None:
            remaining=int(network_until-time.time())
            if remaining<1:raise RuntimeUnavailable('Sandbox network permission expired before dispatch.')
            timeout=min(timeout,remaining)
        identifier = exec_id or f"exec-{secrets.token_hex(8)}"
        if not _EXEC_ID.fullmatch(identifier):
            raise ValueError(f"Unsafe execution id: {identifier}")
        if identifier in self._cancelled:
            self._cancelled.discard(identifier)
            self._confirmed_stops.discard(identifier)
            return ExecResult(identifier,130,'Stopped before dispatch.',stopped=True,operation_id=identifier)
        self.require()
        argv = build_run_args(self.config, snapshot, identifier, command, skills=skills, workdir=workdir, extra_env=env,network=network_until is not None)
        name = f"harness-{identifier}"
        self._containers[identifier] = name
        started = time.monotonic()
        try:
            completed = self._run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=self._host_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            killed, confirmed = self._kill(name)
            output = _text(expired.stdout) + _text(expired.stderr)
            if not confirmed:
                self._unknown.add(identifier)
            return ExecResult(
                exec_id=identifier,
                operation_id=identifier,
                exit_code=124,
                output=_clip(output, max_output)[0],
                truncated=len(output.encode("utf-8")) > max_output,
                timed_out=True,
                unknown=not confirmed,
            )
        finally:
            self._containers.pop(identifier, None)
        output = _text(completed.stdout) + _text(completed.stderr)
        clipped, truncated = _clip(output, max_output)
        stopped = identifier in self._cancelled
        self._cancelled.discard(identifier)
        unknown = False
        if stopped:
            if identifier in self._confirmed_stops:
                self._confirmed_stops.discard(identifier)
            else:
                _killed, confirmed = self._kill(name, wait=False)
                unknown = not confirmed
        if unknown:
            self._unknown.add(identifier)
        return ExecResult(
            exec_id=identifier,
            operation_id=identifier,
            exit_code=int(completed.returncode if stopped is False else 130),
            output=clipped,
            truncated=truncated,
            stopped=stopped,
            unknown=unknown,
        )

    def cancel(self, exec_id: str) -> None:
        """Stop one running command. The result is `stopped`, or `unknown` if unconfirmed."""
        self._cancelled.add(exec_id)
        name = self._containers.get(exec_id) or f"harness-{exec_id}"
        _killed,confirmed=self._kill(name)
        if confirmed:self._confirmed_stops.add(exec_id)

    def cancel_all(self) -> None:
        for identifier in list(self._containers):
            self.cancel(identifier)

    def pending_unknown(self) -> tuple[str, ...]:
        """Operations whose process state is still unknown."""
        return tuple(sorted(self._unknown))

    def reconcile(self, exec_ids=()) -> dict[str, list[str]]:
        """Settle every unknown operation before another dispatch is allowed.

        A container that is gone is resolved (its effect may still be unknown,
        but no process is running). A container that is still there is killed
        and removed; only a confirmed removal is resolved. A failed lookup
        leaves the operation unknown, so it keeps blocking new work.
        """
        for identifier in exec_ids:
            if not _EXEC_ID.fullmatch(identifier):raise ValueError('Invalid recovery execution identity.')
            self._unknown.add(identifier)
        resolved: list[str] = []
        unresolved: list[str] = []
        for identifier in sorted(self._unknown):
            listed = None
            try:
                listed = self._run(
                    ["docker", "ps", "-a", "--filter", f"name=^harness-{identifier}$", "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=self._host_env(),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                unresolved.append(identifier)
                continue
            if listed.returncode != 0:
                unresolved.append(identifier)
                continue
            if not listed.stdout.strip():
                self._unknown.discard(identifier)
                resolved.append(identifier)
                continue
            _killed, removed = self._kill(f"harness-{identifier}")
            if removed:
                self._unknown.discard(identifier)
                resolved.append(identifier)
            else:
                unresolved.append(identifier)
        return {"resolved": resolved, "unresolved": unresolved}

    # ── internals ────────────────────────────────────────────────────────────
    def _kill(self, name: str, *, wait: bool = True) -> tuple[bool, bool]:
        """Kill and remove a container. Returns (killed, removal_confirmed)."""
        try:
            killed = self._run(
                ["docker", "kill", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=self._host_env(),
                check=False,
            )
            removed = self._run(
                ["docker", "rm", "-f", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=self._host_env(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, False
        return killed.returncode == 0, removed.returncode == 0

    def _host_env(self) -> dict[str, str]:
        """What the Docker CLI itself needs. Never the user's keys or the API token."""
        keep = (*_SAFE_HOST_ENV, "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG")
        return {name: os.environ[name] for name in keep if name in os.environ}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _clip(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True
