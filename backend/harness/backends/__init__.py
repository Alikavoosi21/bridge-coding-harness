"""Backends the agent talks to: container files, read-only files, legacy files."""

from __future__ import annotations

from .container import ContainerBackend
from .readonly import ReadOnlyBackend

__all__ = ["ContainerBackend", "ReadOnlyBackend"]
