"""The execution runtime: a Docker container, or nothing.

There is no host-shell fallback. If Docker is missing or the sandbox image is
not present, `capability()` says so and the caller keeps the task read-only;
it does not quietly run the command on the user's machine.
"""

from __future__ import annotations

from .docker import (
    COMMAND_TIMEOUT_S,
    DEFAULT_BASE_IMAGE,
    DEFAULT_IMAGE,
    DOCKERFILE,
    INSTALL_TIMEOUT_S,
    OUTPUT_BYTES,
    ContainerConfig,
    DockerRuntime,
    ExecResult,
    RuntimeUnavailable,
    build_image_args,
    build_run_args,
    image_contract,
)

__all__ = [
    "COMMAND_TIMEOUT_S",
    "DEFAULT_BASE_IMAGE",
    "DEFAULT_IMAGE",
    "DOCKERFILE",
    "INSTALL_TIMEOUT_S",
    "OUTPUT_BYTES",
    "ContainerConfig",
    "DockerRuntime",
    "ExecResult",
    "RuntimeUnavailable",
    "build_image_args",
    "build_run_args",
    "image_contract",
]
