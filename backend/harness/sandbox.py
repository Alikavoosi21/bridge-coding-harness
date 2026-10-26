"""The backend for a run: files, and a shell only inside a real sandbox.

There is no host-shell fallback. `LocalShellBackend` and the regex-guarded
`subprocess` runner are gone: a command that cannot run in a container is not
run at all.

Until the task controller (T006) is wired to the container backend, the legacy
`/runs` engine gets `ReadOnlyBackend`: it may read, search and answer, but it
cannot write the user's project and it has no `execute` session, so deepagents
never registers a shell tool. That matches the product contract: no Docker
means read-only, not "run on the host with a timeout".

`build_container_backend` is the real path. It takes a synced workspace
snapshot (`worktrees/snapshot.py`) and mounts that copy, never the user's
folder.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from deepagents.backends.protocol import BackendProtocol

from .backends import ContainerBackend, ReadOnlyBackend
from .runtime.docker import DockerRuntime
from .worktrees.snapshot import Snapshot
from .workspace import Workspace


def build_backend(
    workspace: Workspace,
    *,
    allow_shell: bool,
    on_stop: list[Callable[[], None]] | None = None,
) -> BackendProtocol:
    """The backend for the transitional runner: always read-only.

    `allow_shell` is kept in the signature because the policy still computes it
    and T006 will use it; it cannot grant a shell here because this assembly has
    no runtime to put the command in. Files are read-only for the same reason:
    without a sandbox a write would land on the user's real project.

    A bare `ReadOnlyBackend` is returned, not a `CompositeBackend`: the
    composite class exposes `execute` unconditionally, which would make
    deepagents register a shell tool that can only fail. Without the attribute
    the tool is never offered.
    """
    del allow_shell, on_stop  # no runtime and no writable surface in this path
    return ReadOnlyBackend(root_dir=workspace.root, virtual_mode=True)


def can_execute(backend: BackendProtocol) -> bool:
    """True only when the assembled backend has a real (sandboxed) shell."""
    target = getattr(backend, "default", backend)
    return callable(getattr(target, "execute", None))


def build_container_backend(
    workspace: Workspace,
    snapshot: Snapshot,
    runtime: DockerRuntime,
    *,
    on_stop: list[Callable[[], None]] | None = None,
    skills: Path | None = None,
) -> ContainerBackend:
    """The backend for a task with a real sandbox: snapshot files + Docker exec.

    The snapshot must already be synced to `snapshot.root` (see
    `worktrees/snapshot.py`). The user's workspace is never mounted.
    """
    del workspace  # the copy is the only thing the container sees
    backend = ContainerBackend(snapshot.root, runtime, skills=skills)
    if on_stop is not None:
        on_stop.append(backend.kill_all)
    return backend
