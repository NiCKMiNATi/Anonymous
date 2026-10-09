"""Single-instance guard for the development database.

Startup disposition (settling never-dispatched runs, marking in-flight runs indeterminate) is only
safe if no other server process is using the same database. The guard holds an exclusive SQLite
lock on a sidecar file for the life of the process; a second process fails closed instead of
starting. The OS releases the lock if the holder dies (including SIGKILL).

This is a small development safeguard. It is NOT the ADR-0011 exclusive authoritative-instance
lock and does not claim to satisfy ADR-0011/ADR-0012's gates (aliases, network storage, copied
datasets, Windows behavior are unevaluated).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from anonymous.domain.errors import StorageFailure


class InstanceGuard:
    def __init__(self, db_path: str | Path) -> None:
        self._lock_path = f"{db_path}.instance-lock"
        self._conn: sqlite3.Connection | None = None

    def acquire(self) -> None:
        if self._conn is not None:
            return
        try:
            conn = sqlite3.connect(self._lock_path, timeout=0, isolation_level=None)
        except sqlite3.Error as error:
            raise StorageFailure("The instance lock file could not be opened.") from error
        try:
            conn.execute("PRAGMA locking_mode = EXCLUSIVE")
            conn.execute("CREATE TABLE IF NOT EXISTS instance_guard (x INTEGER)")
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.Error as error:
            conn.close()
            raise StorageFailure(
                "Another Anonymous server appears to be using this database; refusing to start."
            ) from error
        self._conn = conn

    def release(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
