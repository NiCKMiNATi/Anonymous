"""Connection and transaction handling for the SQLite development adapter.

* Every connection explicitly enables and *verifies* ``foreign_keys`` (it is off by default and
  per-connection; the Mac experiment confirmed this).
* Write transactions are ``BEGIN IMMEDIATE`` so writers serialize up front instead of failing on
  lock upgrade, and so commit instants and positions are assigned while the write lock is held.
* Errors are classified for the application: a failure before COMMIT is ``StorageFailure`` (known
  not committed); a failure *during* COMMIT is ``StorageOutcomeUnknown``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anonymous.domain.errors import StorageFailure, StorageOutcomeUnknown

logger = logging.getLogger("anonymous.persistence.sqlite")

DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0


def connect(
    path: str | Path, *, busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS
) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(
            str(path),
            timeout=busy_timeout_seconds,
            isolation_level=None,  # explicit BEGIN/COMMIT only
        )
    except sqlite3.Error as error:
        logger.error("cannot open database type=%s", type(error).__name__)
        raise StorageFailure("The database could not be opened.") from error
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if enabled != 1:
            raise StorageFailure("Foreign key enforcement could not be enabled.")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
    except sqlite3.Error as error:
        conn.close()
        raise StorageFailure("The database could not be configured.") from error
    except StorageFailure:
        conn.close()
        raise
    return conn


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    except sqlite3.Error:
        logger.error("rollback failed")


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as error:
        raise StorageFailure("The database is unavailable for writing.") from error
    try:
        yield conn
    except BaseException as error:
        _rollback(conn)
        if isinstance(error, sqlite3.Error):
            logger.error("write failed type=%s", type(error).__name__)
            raise StorageFailure("A storage operation failed; nothing was saved.") from error
        raise
    try:
        conn.execute("COMMIT")
    except sqlite3.Error as error:
        _rollback(conn)
        logger.error("commit failed type=%s", type(error).__name__)
        raise StorageOutcomeUnknown(
            "The database could not confirm whether the change was saved."
        ) from error


@contextmanager
def read_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A deferred transaction so several reads see one consistent snapshot."""
    try:
        conn.execute("BEGIN")
    except sqlite3.Error as error:
        raise StorageFailure("The database is unavailable for reading.") from error
    try:
        yield conn
    except sqlite3.Error as error:
        logger.error("read failed type=%s", type(error).__name__)
        raise StorageFailure("A storage read failed.") from error
    finally:
        _rollback(conn)
