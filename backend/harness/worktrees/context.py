"""Bounded context from a workspace: search, sliced reads, and a byte budget.

The model never receives a whole folder. It asks for matches or a line window,
and every answer has a ceiling: files that are too large or binary are
skipped, results are capped, and text is clipped at a byte budget. BOMs are
stripped for display while CRLF is preserved, so a read does not silently
rewrite what a later edit compares against.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .snapshot import UnsafePath, excluded, validate_relative, within

DEFAULT_MAX_RESULTS = 50
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_CONTEXT_BYTES = 65_536
DEFAULT_MAX_LINES = 2_000


@dataclass(frozen=True)
class Match:
    path: str
    line: int
    column: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "column": self.column, "text": self.text}


@dataclass
class SearchResult:
    matches: list[Match] = field(default_factory=list)
    truncated: bool = False
    scanned: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "matches": [match.as_dict() for match in self.matches],
            "truncated": self.truncated,
            "scanned": self.scanned,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class Slice:
    path: str
    content: str
    start_line: int
    end_line: int
    total_lines: int
    truncated: bool
    encoding: str
    newline: str
    bom: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "total_lines": self.total_lines,
            "truncated": self.truncated,
            "encoding": self.encoding,
            "newline": self.newline,
            "bom": self.bom,
        }


def _resolve(root: Path, relative: str) -> Path:
    path = validate_relative(relative)
    candidate = root.joinpath(*path.parts)
    if not within(root, candidate):
        raise UnsafePath(f"The path leaves the workspace: {relative}")
    if candidate.is_symlink():
        raise UnsafePath(f"The path is a link and is not followed: {relative}")
    return candidate


def _decode(raw: bytes) -> tuple[str, str, bool]:
    """Decode text and report (encoding, newline, had_bom)."""
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        text = raw.decode("utf-8-sig", errors="replace")
        encoding = "utf-8-sig"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
        encoding = "utf-16"
    else:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8"
    newline = "crlf" if b"\r\n" in raw[:8192] else "lf"
    return text, encoding, newline, bom


def read_slice(
    root: str | Path,
    relative: str,
    *,
    start_line: int = 1,
    end_line: int | None = None,
    max_bytes: int = DEFAULT_CONTEXT_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
    extra_excludes: Iterable[str] = (),
) -> Slice:
    """Read a line window with a byte ceiling. Line numbers are 1-based."""
    base = Path(root).resolve()
    path = validate_relative(relative)
    if excluded(path, extra=extra_excludes):
        raise UnsafePath(f"The file is not available to the sandbox: {relative}")
    file = _resolve(base, relative)
    if not file.is_file():
        raise FileNotFoundError(f"No such file: {relative}")
    raw = file.read_bytes()
    text, encoding, newline, bom = _decode(raw)
    lines = text.splitlines()
    total = len(lines)
    first = max(1, start_line)
    last = total if end_line is None else max(first, min(end_line, total))
    if last - first + 1 > max_lines:
        last = first + max_lines - 1
    window = lines[first - 1 : last] if first <= total else []
    content = "\n".join(window)
    truncated = last < (end_line or total) or len(window) < (last - first + 1)
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        content = encoded[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
    return Slice(
        path=str(path),
        content=content,
        start_line=first,
        end_line=first + max(0, len(window) - 1),
        total_lines=total,
        truncated=truncated,
        encoding=encoding,
        newline=newline,
        bom=bom,
    )


def search(
    root: str | Path,
    query: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    case_sensitive: bool = False,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    extra_excludes: Iterable[str] = (),
) -> SearchResult:
    """Literal search across text files, bounded by results and file size."""
    if not query:
        raise ValueError("The query is empty.")
    base = Path(root).resolve()
    start = _resolve(base, path) if path else base
    if not start.is_dir():
        raise NotADirectoryError(f"Not a folder: {path}")
    needle = query if case_sensitive else query.lower()
    result = SearchResult()
    for file in sorted(start.rglob("*")):
        if result.truncated:
            break
        relative = PurePosixPath(file.relative_to(base).as_posix())
        if excluded(relative, extra=extra_excludes):
            result.skipped += 1
            continue
        if not file.is_file() or file.is_symlink():
            result.skipped += 1
            continue
        if not within(base, file):
            result.skipped += 1
            continue
        if glob and not (fnmatch.fnmatch(relative.name, glob) or fnmatch.fnmatch(str(relative), glob)):
            continue
        try:
            if file.stat().st_size > max_file_bytes:
                result.skipped += 1
                continue
            raw = file.read_bytes()
        except OSError:
            result.skipped += 1
            continue
        if b"\x00" in raw[:8192]:
            result.skipped += 1
            continue
        text, _, _, _ = _decode(raw)
        result.scanned += 1
        for number, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            offset = haystack.find(needle)
            if offset < 0:
                continue
            if len(result.matches) >= max_results:
                result.truncated = True
                break
            result.matches.append(Match(path=str(relative), line=number, column=offset + 1, text=line[:500]))
    return result


def clip_context(text: str, limit: int = DEFAULT_CONTEXT_BYTES) -> tuple[str, bool]:
    """Trim text to a byte budget on a character boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True
