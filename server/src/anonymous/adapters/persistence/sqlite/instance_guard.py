"""Single-process ownership of a development dataset (LD-04 §4.8, assumption A-1).

Startup disposition and reconciliation are only safe if no other process can use the dataset
while an old worker could still resume. The guard therefore:

* derives the lock from a **canonical, validated** dataset identity — every alias (symlinks,
  ``..``, relative forms) resolves to the same file, hence the same lock; a hard-linked dataset
  (another name for the same inode that would bypass the lock) is refused; the dataset must be a
  regular file or absent; special names (``:memory:``, URIs) are refused;
* holds an exclusive OS-level lock for the life of the process (released by the OS on any death,
  including SIGKILL);
* is released ONLY when every supervised worker has terminated (``release_when_quiescent``). A hung
  shutdown never releases it: the process must exit, which ends the worker with it.

Limits (still ADR-0011/0012 gates, not claimed here): network filesystems, bind mounts and other
aliases that cannot be detected portably; case-insensitive aliases are covered only because the
filesystem maps them to the same lock file.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from anonymous.domain.errors import OwnershipError, StorageFailure


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    path: Path  # canonical: absolute, symlinks resolved

    @classmethod
    def validate(cls, db_path: str | Path) -> DatasetIdentity:
        text = os.fspath(db_path)
        if not text or "\x00" in text or text == ":memory:" or text.startswith("file:"):
            raise OwnershipError("The dataset path is not an acceptable local file.")
        resolved = Path(text).expanduser().resolve(strict=False)
        parent = resolved.parent
        if not parent.is_dir():
            raise OwnershipError("The dataset directory does not exist.")
        try:
            info = os.stat(resolved)
        except FileNotFoundError:
            return cls(resolved)
        except OSError as error:
            raise OwnershipError("The dataset could not be inspected.") from error
        if not stat.S_ISREG(info.st_mode):
            raise OwnershipError("The dataset must be a regular file.")
        if info.st_nlink != 1:
            raise OwnershipError(
                "The dataset has more than one hard link; another name for it would bypass the"
                " ownership lock."
            )
        return cls(resolved)

    @property
    def lock_path(self) -> Path:
        return Path(f"{self.path}.instance-lock").resolve(strict=False)


class InstanceGuard:
    def __init__(self, db_path: str | Path) -> None:
        self.identity = DatasetIdentity.validate(db_path)
        self._lock_path = str(self.identity.lock_path)
        self._conn: sqlite3.Connection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

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
            raise OwnershipError(
                "Another Anonymous server appears to be using this database; refusing to start."
            ) from error
        self._conn = conn

    def release(self) -> None:
        """Unconditional release. Use only when no supervised worker can exist (e.g. a failed
        start before any worker was created). Normal shutdown uses ``release_when_quiescent``."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def release_when_quiescent(self, workers_alive: Callable[[], bool]) -> bool:
        """Release only if no supervised worker is alive; otherwise keep ownership and say so."""
        if workers_alive():
            return False
        self.release()
        return True
