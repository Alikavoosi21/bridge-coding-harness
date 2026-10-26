"""Where the product's own data lives, and how a connection is opened.

Two SQLite files, both outside any workspace and outside the repository, in the
machine's app-data folder:

    product.db      every domain row (tasks, plans, actions, events, leases)
    checkpoints.db  LangGraph checkpoints only

The agent never gets a mount to either file. Keeping them separate means a
checkpoint write cannot hold the product journal's write lock, and the product
can migrate or back up its own data without touching framework state.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .. import settings


def product_db_path() -> Path:
    return settings.home() / "product.db"


def checkpoints_db_path() -> Path:
    return settings.home() / "checkpoints.db"


class Database:
    """A small wrapper: one file, explicit write transactions, no ORM.

    `write()` takes the SQLite write lock up front (`BEGIN IMMEDIATE`), so two
    connections cannot both read a counter and then write an incremented value.
    SQLite has no interactive transactions across commits; keeping the block
    short is the contract every caller follows.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else product_db_path()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
