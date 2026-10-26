"""Read-only files: what a task gets when no sandbox is available.

Every mutating operation is refused with a clear error. Reads and searches work
normally, so a task can still research and explain; it cannot change the
user's files by accident or by a prompt injection.
"""

from __future__ import annotations

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, FileUploadResponse, WriteResult

_MESSAGE = "This task is read-only: a sandbox is not available, so nothing may be changed."


class ReadOnlyBackend(FilesystemBackend):
    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=_MESSAGE)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:  # noqa: FBT001, FBT002
        return EditResult(error=_MESSAGE)

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=_MESSAGE)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]
