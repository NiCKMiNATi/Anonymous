from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.instance_guard import InstanceGuard
from anonymous.adapters.persistence.sqlite.migrations import (
    Migration,
    discover_migrations,
    migrate,
)
from anonymous.domain.errors import OwnershipError, StorageFailure


def rows(db_path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        return [tuple(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def test_migrate_creates_schema_and_is_idempotent(db_path: Path) -> None:
    assert migrate(db_path) == 2
    first = rows(db_path, "SELECT version, name, checksum, applied_at FROM schema_migrations")
    assert migrate(db_path) == 2  # nothing re-applied
    assert (
        rows(db_path, "SELECT version, name, checksum, applied_at FROM schema_migrations") == first
    )
    tables = {r[0] for r in rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "conversations", "messages", "model_runs", "submissions"} <= tables


def test_shipped_migrations_are_contiguous_and_named() -> None:
    found = discover_migrations()
    assert [m.version for m in found] == list(range(1, len(found) + 1))


def test_changed_applied_migration_is_refused(db_path: Path) -> None:
    migrate(db_path)
    original = discover_migrations()
    tampered = [
        Migration(original[0].version, original[0].name, original[0].sql + "\n-- edited"),
        *original[1:],
    ]
    with pytest.raises(StorageFailure, match="checksum"):
        migrate(db_path, tampered)


def test_database_newer_than_code_is_refused(db_path: Path) -> None:
    migrate(db_path)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO schema_migrations VALUES (99, 'future', 'abc', '2030-01-01T00:00:00.000000Z')"
    )
    conn.close()
    with pytest.raises(StorageFailure, match="newer schema"):
        migrate(db_path)


def test_new_migration_evolves_database_without_losing_data(db_path: Path) -> None:
    migrate(db_path)
    conn = connect(db_path)
    conn.execute("INSERT INTO users (id, created_at) VALUES ('u1', '2026-01-01T00:00:00.000000Z')")
    conn.close()
    base = discover_migrations()
    v3 = Migration(3, "add_nickname", "ALTER TABLE users ADD COLUMN nickname TEXT;")
    assert migrate(db_path, [*base, v3]) == 3
    assert rows(db_path, "SELECT id, nickname FROM users") == [("u1", None)]
    assert [r[0] for r in rows(db_path, "SELECT version FROM schema_migrations")] == [1, 2, 3]


def test_failed_migration_rolls_back_completely(db_path: Path) -> None:
    migrate(db_path)
    base = discover_migrations()
    broken = Migration(3, "broken", "CREATE TABLE half_done (x); THIS IS NOT SQL;")
    with pytest.raises(StorageFailure):
        migrate(db_path, [*base, broken])
    assert rows(db_path, "SELECT name FROM sqlite_master WHERE name='half_done'") == []
    assert [r[0] for r in rows(db_path, "SELECT version FROM schema_migrations")] == [1, 2]


def test_instance_guard_excludes_a_second_holder_until_released(db_path: Path) -> None:
    first, second = InstanceGuard(db_path), InstanceGuard(db_path)
    first.acquire()
    try:
        with pytest.raises(OwnershipError, match="Another Anonymous server"):
            second.acquire()
    finally:
        first.release()
    second.acquire()  # free again after release
    second.release()
