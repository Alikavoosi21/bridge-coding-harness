"""Worktree tools: snapshots, context, diff, apply and restore.

`snapshot` decides what leaves the user's folder and writes the hash manifest.
`context` turns that folder into bounded, line-addressed reads and searches.
`diff`/`apply`/`restore` arrive with T013.
"""

from __future__ import annotations

from .context import clip_context, read_slice, search
from .snapshot import (
    MAX_BYTES,
    MAX_FILES,
    FileEntry,
    Snapshot,
    SnapshotTooLarge,
    SyncReport,
    UnsafePath,
    build,
    load_manifest,
    manifest_path,
    sync,
    validate_relative,
    within,
    write_manifest,
)

__all__ = [
    "MAX_BYTES",
    "MAX_FILES",
    "FileEntry",
    "Snapshot",
    "SnapshotTooLarge",
    "SyncReport",
    "UnsafePath",
    "build",
    "clip_context",
    "load_manifest",
    "manifest_path",
    "read_slice",
    "search",
    "sync",
    "validate_relative",
    "within",
    "write_manifest",
]
