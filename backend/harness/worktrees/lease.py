"""The writer lease every mutating backend call must hold.

A storage row is not a lock by itself: the lease is the permission to write,
and the fencing token is its version. A backend that mutates files or starts a
command checks the lease first, with the row it was granted, so a task that
lost its lease (expired, released, or replaced by a newer one) cannot finish a
write that a competing task has already taken over.

The check is deliberately injectable: T004 defines the interface and proves it
with a fake lookup, while T006/T013 supply the real `Store.workspace_lease`
lookup. Expiry is checked here too, because an expired lease authorizes
nothing; it is still not proof that a running process stopped - that is the
runtime's `unknown`/reconcile path, which is a separate decision.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


class LeaseLost(RuntimeError):
    """The workspace lease is no longer valid; the mutation must not happen."""


@dataclass(frozen=True)
class WriterLease:
    workspace_id: str
    lease_id: str
    fencing_token: int
    lookup: Callable[[str], Mapping[str, Any] | None]
    now: Callable[[], float] = field(default=time.time)

    def check(self, action: str) -> None:
        row = self.lookup(self.workspace_id)
        if row is None or row.get("id") != self.lease_id or int(row.get("fencing_token", -1)) != self.fencing_token:
            raise LeaseLost(f"{action} refused: the workspace lease is no longer valid.")
        expires_at = row.get("expires_at")
        if expires_at is not None and float(expires_at) <= self.now():
            raise LeaseLost(f"{action} refused: the workspace lease has expired.")
