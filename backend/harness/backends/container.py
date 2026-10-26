"""A backend whose files are the sandbox snapshot and whose shell is Docker.

File operations are ordinary filesystem calls against the snapshot folder,
which the container sees as `/workspace`. `execute` never runs a process on the
host: it asks the runtime, which builds a locked-down `docker run` command.

Execution identity comes from the caller, not from the command text. The task
controller (T006) stores one `operation_id` per logical invocation in the
journal and binds it here before the tool runs:

    backend.bind_operation(action["operation_id"])
    backend.execute(command)          # -> container name harness-op_...

So an intentional second call with the same command is a different operation,
while resuming the same invocation after a pause or restart reuses the id it
already has. A command hash cannot express either of those. When nothing is
bound (a direct call in a test), a random id is used, never one derived from
the command.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import DeleteResult, EditResult, ExecuteResponse, FileUploadResponse, SandboxBackendProtocol, WriteResult

from ..runtime.docker import COMMAND_TIMEOUT_S, OUTPUT_BYTES, DockerRuntime, ExecResult, RuntimeUnavailable
from ..worktrees.lease import WriterLease

_OPERATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,72}$")


class ContainerBackend(FilesystemBackend, SandboxBackendProtocol):
    @property
    def skills_root(self):
        return self._skills

    def __init__(
        self,
        root_dir: str | Path,
        runtime: DockerRuntime,
        *,
        exec_prefix: str = "exec",
        timeout: int = COMMAND_TIMEOUT_S,
        max_output: int = OUTPUT_BYTES,
        skills: str | Path | None = None,
        lease: WriterLease | None = None,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True)
        self._runtime = runtime
        self._exec_prefix = exec_prefix
        self._timeout = timeout
        self._max_output = max_output
        self._skills = skills
        self._network_until:ContextVar[float|None]=ContextVar('network_until',default=None)
        self._operation_id: ContextVar[str | None] = ContextVar('operation_id',default=None)
        self._receipt: ContextVar[Any] = ContextVar('receipt',default=None)
        self._lease = lease
        self.last_receipt = None

    def set_lease(self, lease: WriterLease | None) -> None:
        """Install the writer lease every mutation must still hold."""
        self._lease = lease
        if hasattr(self._runtime, "set_lease"):
            self._runtime.set_lease(lease)

    def _check_lease(self, action: str) -> None:
        if self._lease is not None:
            self._lease.check(action)

    @property
    def id(self) -> str:
        return f"container:{self.cwd.name}"

    def bind_operation(self, operation_id: str | None) -> None:
        """Bind the stored operation id (journal/controller) for the next call.

        `None` clears the binding. This is deliberately not derived from the
        command: two deliberate runs of the same text are two operations.
        """
        if operation_id is not None and not _OPERATION_ID.fullmatch(operation_id):
            raise ValueError(f"Unsafe operation id: {operation_id}")
        self._operation_id.set(operation_id)

    @property
    def operation_id(self) -> str | None:
        return self._operation_id.get()

    @contextmanager
    def network_scope(self,deadline):
        token=self._network_until.set(deadline)
        try:yield
        finally:self._network_until.reset(token)

    @contextmanager
    def operation_scope(self, operation_id: str):
        previous=self.operation_id
        self.bind_operation(operation_id)
        # Framework tool handlers can run in a child asyncio task. ContextVar
        # assignments in that task do not flow back; a per-operation cell does.
        receipt_token=self._receipt.set({'value':None})
        try:
            yield
        finally:
            self._receipt.reset(receipt_token)
            self.bind_operation(previous)

    @property
    def last_receipt(self):
        value=self._receipt.get()
        return value.get('value') if isinstance(value,dict) else value

    @last_receipt.setter
    def last_receipt(self,value):
        cell=self._receipt.get()
        if isinstance(cell,dict):cell['value']=value
        else:self._receipt.set(value)

    # ── mutations hold the workspace lease ───────────────────────────────────
    def write(self, file_path: str, content: str) -> WriteResult:
        self._check_lease("write")
        return super().write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:  # noqa: FBT001, FBT002
        self._check_lease("edit")
        return super().edit(file_path, old_string, new_string, replace_all)

    def delete(self, file_path: str) -> DeleteResult:
        self._check_lease("delete")
        return super().delete(file_path)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self._check_lease("upload")
        return super().upload_files(files)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.last_receipt=None
        self._check_lease("execute")
        identifier = self.operation_id or f"{self._exec_prefix}-{secrets.token_hex(8)}"
        try:
            result = self._runtime.execute(
                command,
                snapshot=self.cwd,
                exec_id=identifier,
                timeout=timeout or self._timeout,
                skills=self._skills,
                max_output=self._max_output,
                network_until=self._network_until.get(),
            )
        except RuntimeUnavailable as error:
            output=f"Execution is unavailable: {error}"
            self.last_receipt=ExecResult(identifier,126,output,operation_id=identifier)
            return ExecuteResponse(output=output, exit_code=126)
        self.last_receipt = result
        return ExecuteResponse(output=result.output, exit_code=result.exit_code, truncated=result.truncated)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        def execute_with_receipt():
            result=self.execute(command,timeout=timeout)
            return result,self.last_receipt
        result,receipt=await asyncio.to_thread(execute_with_receipt)
        self.last_receipt=receipt
        return result

    def kill_all(self) -> None:
        self._runtime.cancel_all()

    def capability(self) -> dict[str, Any]:
        return self._runtime.capability().as_dict()
