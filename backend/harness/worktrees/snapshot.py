"""Workspace snapshots: the exact bytes that leave the user's folder.

A task never mounts the user's workspace. It gets a copy, built from this
manifest, and every file is hashed so the copy can be compared with the
baseline later. What is copied, what is left behind, and why is recorded - an
agent cannot ask for a secret file by name if the file was never there.

Rules:

- Default excludes: VCS metadata, the harness's own folder, dependency and
  build folders (`node_modules`, `.venv`, `dist`, ...), caches.
- Secret files (`.env`, keys, `.npmrc`, ...) are never copied.
- Symlinks, junctions and other reparse points are never followed and never
  copied: a link inside the workspace can point at `C:\\Users\\...`.
- Paths are validated before anything touches disk: no `..`, no absolute
  paths, no drive letters, no NUL/control characters, no reserved device
  names, no trailing dots or spaces.
- Limits are hard: 50,000 files and 500 MB by default. A larger folder is an
  error, not a silently truncated sandbox.

`sync` is incremental: unchanged files are skipped, changed files replaced
atomically, and files removed from the source are pruned from the copy.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

MAX_FILES = 50_000
MAX_BYTES = 500_000_000
_HASH_CHUNK = 1024 * 1024
_SNIFF = 8192

_EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".harness",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".next",
    ".turbo",
    ".gradle",
    "dist",
    "build",
    "out",
    "target",
    "coverage",
    ".idea",
    ".vscode",
    ".DS_Store",
    "Thumbs.db",
}
_EXCLUDED_PATTERNS = (
    "*.tsbuildinfo",
    "*.pyc",
    "*.pyo",
    "*.class",
    "*.log",
    "*.tmp",
    "*.swp",
)

# Names that should never be handed to a sandbox, even if they look harmless.
_SECRET_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.yml",
    "secrets.yaml",
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
    ".kube",
}
_SECRET_PATTERNS = (
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*_rsa",
    "*_ed25519",
    "*credentials*.json",
)

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_DRIVE = re.compile(r"^[A-Za-z]:")
_EXCLUDED_LOWER = {item.lower() for item in _EXCLUDED_NAMES}
_SECRET_LOWER = {item.lower() for item in _SECRET_NAMES}


class UnsafePath(ValueError):
    """A path that may not be copied or read, with the reason why."""


class SnapshotTooLarge(RuntimeError):
    """The workspace exceeds the snapshot limits; nothing is silently dropped."""


def validate_relative(value: str) -> PurePosixPath:
    """Validate one workspace-relative path and return it normalized to `/`."""
    if not isinstance(value, str) or not value.strip():
        raise UnsafePath("The path is empty.")
    if "\x00" in value or any(ord(char) < 32 for char in value):
        raise UnsafePath("The path contains a control character.")
    text = value.replace("\\", "/")
    if text.startswith("/") or text.startswith("//") or _DRIVE.match(text):
        raise UnsafePath(f"The path must be relative: {value}")
    parts: list[str] = []
    for part in text.split("/"):
        if not part or part == ".":
            raise UnsafePath(f"The path is not normalized: {value}")
        if part == "..":
            raise UnsafePath(f"The path leaves the workspace: {value}")
        if part != part.rstrip(" ."):
            raise UnsafePath(f"The path has a trailing dot or space: {value}")
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise UnsafePath(f"The path uses a reserved device name: {value}")
        parts.append(part)
    return PurePosixPath(*parts)


def within(root: Path, candidate: Path) -> bool:
    """True when `candidate` stays under `root` after resolving links."""
    try:
        resolved = candidate.resolve()
        base = root.resolve()
    except OSError:
        return False
    if os.name == "nt":
        return str(resolved).lower() == str(base).lower() or str(resolved).lower().startswith(str(base).lower() + os.sep)
    return resolved == base or base in resolved.parents


def excluded(relative: PurePosixPath, *, extra: Iterable[str] = (), include_secrets: bool = False) -> str | None:
    """Why a path is left out of the snapshot, or None when it is copied.

    Every component is checked, not just the file name: `node_modules/pkg/x.js`
    and `.ssh/config` are excluded because of a folder in the middle of the
    path, which is also how the context search stays inside the same rules.
    """
    parts = relative.parts
    for part in parts:
        if part in _EXCLUDED_NAMES or part.lower() in _EXCLUDED_LOWER:
            return "dependency, cache or harness folder"
    for part in parts:
        lowered = part.lower()
        for pattern in (*_EXCLUDED_PATTERNS, *tuple(extra)):
            if fnmatch.fnmatch(lowered, pattern.lower()):
                return f"excluded by {pattern}"
    if include_secrets:
        return None
    for part in parts:
        if part in _SECRET_NAMES or part.lower() in _SECRET_LOWER:
            return "secret file"
        for pattern in _SECRET_PATTERNS:
            if fnmatch.fnmatch(part.lower(), pattern.lower()):
                return "secret file"
    return None


def _is_reparse(entry: os.DirEntry[str], info: os.stat_result) -> bool:
    if entry.is_symlink():
        return True
    if os.name == "nt":
        return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _sniff(path: Path, size: int) -> tuple[str, str, bool]:
    """Return (encoding, newline, is_binary) without loading the whole file."""
    try:
        with path.open("rb") as handle:
            sample = handle.read(min(size, _SNIFF))
    except OSError:
        return "unknown", "unknown", True
    binary = b"\x00" in sample
    if sample.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8"
    newline = "crlf" if b"\r\n" in sample else "lf"
    return encoding, newline, binary


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str
    encoding: str
    newline: str
    binary: bool
    mtime_ns: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "encoding": self.encoding,
            "newline": self.newline,
            "binary": self.binary,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            path=str(data["path"]),
            size=int(data["size"]),
            sha256=str(data["sha256"]),
            encoding=str(data.get("encoding", "unknown")),
            newline=str(data.get("newline", "unknown")),
            binary=bool(data.get("binary", False)),
            mtime_ns=int(data.get("mtime_ns", 0)),
        )


@dataclass(frozen=True)
class Snapshot:
    root: Path
    files: tuple[FileEntry, ...]
    excluded: tuple[dict[str, str], ...]
    total_bytes: int
    created_at: float
    version: int = 1

    def manifest(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": str(self.root),
            "created_at": self.created_at,
            "total_bytes": self.total_bytes,
            "files": [entry.as_dict() for entry in self.files],
            "excluded": list(self.excluded),
        }

    def by_path(self) -> dict[str, FileEntry]:
        return {entry.path: entry for entry in self.files}


def build(
    root: str | Path,
    *,
    extra_excludes: Iterable[str] = (),
    include_secrets: bool = False,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_BYTES,
) -> Snapshot:
    """Walk the workspace and return its manifest. Reads only; writes nothing."""
    base = Path(root).resolve()
    if not base.is_dir():
        raise NotADirectoryError(f"Not a workspace folder: {base}")
    excludes = tuple(extra_excludes)
    files: list[FileEntry] = []
    skipped: list[dict[str, str]] = []
    total = 0
    stack: list[tuple[Path, PurePosixPath]] = [(base, PurePosixPath())]
    while stack:
        folder, relative = stack.pop()
        with os.scandir(folder) as scan:
            entries = sorted(scan, key=lambda item: item.name)
        for entry in entries:
            child = relative / entry.name
            try:
                path = validate_relative(str(child))
            except UnsafePath as error:
                skipped.append({"path": str(child), "reason": str(error)})
                continue
            reason = excluded(path, extra=excludes, include_secrets=include_secrets)
            if reason:
                skipped.append({"path": str(path), "reason": reason})
                continue
            info = entry.stat(follow_symlinks=False)
            if _is_reparse(entry, info):
                skipped.append({"path": str(path), "reason": "link or junction (never followed)"})
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append((Path(entry.path), path))
                continue
            if not entry.is_file(follow_symlinks=False):
                skipped.append({"path": str(path), "reason": "not a regular file"})
                continue
            digest, size = _hash_file(Path(entry.path))
            total += size
            if len(files) + 1 > max_files:
                raise SnapshotTooLarge(f"The workspace has more than {max_files:,} files; the snapshot was not taken.")
            if total > max_bytes:
                raise SnapshotTooLarge(f"The workspace is larger than {max_bytes:,} bytes; the snapshot was not taken.")
            encoding, newline, binary = _sniff(Path(entry.path), size)
            files.append(
                FileEntry(
                    path=str(path),
                    size=size,
                    sha256=digest,
                    encoding=encoding,
                    newline=newline,
                    binary=binary,
                    mtime_ns=getattr(info, "st_mtime_ns", int(info.st_mtime * 1e9)),
                )
            )
    files.sort(key=lambda item: item.path)
    return Snapshot(root=base, files=tuple(files), excluded=tuple(skipped), total_bytes=total, created_at=time.time())


@dataclass
class SyncReport:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"copied": list(self.copied), "skipped": list(self.skipped), "removed": list(self.removed)}


def manifest_path(destination: Path) -> Path:
    """The manifest lives beside the mounted folder, not inside what the agent sees."""
    return destination.with_name(destination.name + ".manifest.json")


def write_manifest(snapshot: Snapshot, destination: Path | None = None, path: Path | None = None) -> Path:
    target = path or (manifest_path(destination) if destination else None)
    if target is None:
        raise ValueError("Give a destination or a manifest path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot.manifest(), ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return target


def load_manifest(path: Path) -> Snapshot | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    root = Path(data.get("root", "."))
    return Snapshot(
        root=root,
        files=tuple(FileEntry.from_dict(item) for item in data.get("files", [])),
        excluded=tuple(data.get("excluded", [])),
        total_bytes=int(data.get("total_bytes", 0)),
        created_at=float(data.get("created_at", 0)),
        version=int(data.get("version", 1)),
    )


def sync(
    snapshot: Snapshot,
    destination: str | Path,
    *,
    previous: Snapshot | None = None,
    write_manifest_file: bool = True,
) -> SyncReport:
    """Make `destination` an exact copy of the snapshot, incrementally.

    Only bytes are copied: BOMs, CRLF endings and binary files stay as they
    were. A changed file is written to a temporary name and replaced, so a
    crash cannot leave half a source file in the sandbox.
    """
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=True)
    report = SyncReport()
    old = previous.by_path() if previous else {}
    desired = snapshot.by_path()
    for entry in snapshot.files:
        relative = validate_relative(entry.path)
        file = target.joinpath(*relative.parts)
        if not within(target, file):
            raise UnsafePath(f"The snapshot path leaves the copy: {entry.path}")
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.is_file() and old.get(entry.path, FileEntry("", 0, "", "", "", False, 0)).sha256 == entry.sha256:
            report.skipped.append(entry.path)
            continue
        source = snapshot.root.joinpath(*relative.parts)
        if not within(snapshot.root, source) or _is_link_path(source):
            raise UnsafePath(f"The snapshot source is a link or leaves the workspace: {entry.path}")
        temporary = file.with_name(file.name + ".harness-tmp")
        digest = hashlib.sha256()
        try:
            with source.open("rb") as read, temporary.open("wb") as write:
                while chunk := read.read(_HASH_CHUNK):
                    digest.update(chunk)
                    write.write(chunk)
            if digest.hexdigest() != entry.sha256:
                raise OSError(f"The source changed while it was being copied: {entry.path}")
            os.replace(temporary, file)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        report.copied.append(entry.path)
    for path in sorted(old):
        if path in desired:
            continue
        stale = target.joinpath(*validate_relative(path).parts)
        if within(target, stale) and stale.is_file():
            stale.unlink()
            report.removed.append(path)
    if write_manifest_file:
        write_manifest(snapshot, target)
    return report


def _is_link_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt":
        return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False
