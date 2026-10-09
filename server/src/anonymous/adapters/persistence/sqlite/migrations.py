"""Minimal forward-only migration runner.

Numbered ``NNNN_name.sql`` files in the ``versions`` package directory. Each applied migration
is recorded with a SHA-256 checksum in ``schema_migrations``. The runner:

* applies pending migrations in order, each inside one transaction;
* refuses to start if an applied migration's file changed (history is not rewritten silently);
* refuses to start if the database records a migration this code does not know (newer schema);
* never drops or rewrites existing data on its own.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.domain.errors import StorageFailure

logger = logging.getLogger("anonymous.persistence.sqlite.migrations")

_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    if directory is None:
        entries = [
            (entry.name, entry.read_text(encoding="utf-8"))
            for entry in resources.files(__package__ + ".versions").iterdir()
            if entry.name.endswith(".sql")
        ]
    else:
        entries = [(p.name, p.read_text(encoding="utf-8")) for p in directory.glob("*.sql")]
    migrations: list[Migration] = []
    for filename, sql in entries:
        match = _NAME.match(filename)
        if match is None:
            raise StorageFailure(f"Invalid migration file name: {filename}")
        migrations.append(Migration(int(match.group(1)), match.group(2), sql))
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise StorageFailure("Migration versions must be contiguous starting at 1.")
    return migrations


def migrate(db_path: str | Path, migrations: list[Migration] | None = None) -> int:
    """Bring the database to the latest schema and return its schema version."""
    known = migrations if migrations is not None else discover_migrations()
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
            " checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"]: (row["name"], row["checksum"])
            for row in conn.execute("SELECT version, name, checksum FROM schema_migrations")
        }
        by_version = {m.version: m for m in known}
        unknown = sorted(v for v in applied if v not in by_version)
        if unknown:
            raise StorageFailure(
                "The database has a newer schema than this application understands."
            )
        for version, (name, checksum) in applied.items():
            migration = by_version[version]
            if migration.name != name or migration.checksum != checksum:
                raise StorageFailure(
                    f"Applied migration {version:04d} no longer matches its recorded checksum."
                )
        for migration in known:
            if migration.version in applied:
                continue
            _apply(conn, migration)
            logger.info("applied migration %04d_%s", migration.version, migration.name)
        return len(known)
    except sqlite3.Error as error:
        raise StorageFailure("Database migration failed.") from error
    finally:
        conn.close()


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    applied_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # executescript issues its own COMMIT first, so the transaction is part of the script. The
    # interpolated values are an int, a name validated by _NAME, and hex/ISO text.
    script = (
        "BEGIN IMMEDIATE;\n"
        f"{migration.sql}\n"
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES "
        f"({migration.version}, '{migration.name}', '{migration.checksum}', '{applied_at}');\n"
        "COMMIT;"
    )
    try:
        conn.executescript(script)
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
