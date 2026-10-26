"""Product storage: the durable domain store and the journal it writes.

Public surface:

    Database      thin SQLite connection wrapper with explicit write transactions
    Store         tasks, runs, actions, budgets, leases, idempotency, events
    migrate       bring product.db to the current schema version
    preview_legacy / import_legacy
                  preview and copy pre-storage data exactly once
    product_db_path / checkpoints_db_path
                  where the two files live (app data, never the workspace)
"""

from __future__ import annotations

from .db import Database, checkpoints_db_path, product_db_path
from .migrations import import_legacy, migrate, preview_legacy
from .repository import Lease, Store

__all__ = [
    "Database",
    "Lease",
    "Store",
    "checkpoints_db_path",
    "import_legacy",
    "migrate",
    "preview_legacy",
    "product_db_path",
]
