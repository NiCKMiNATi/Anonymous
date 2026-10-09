"""Schema-level guarantees, tested directly against the SQLite development adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.domain.ids import UserId, new_uuid

NOW = "2026-01-01T12:00:00.000000Z"


def seed_conversation(conn: sqlite3.Connection, owner: str) -> str:
    cid = new_uuid()
    conn.execute(
        "INSERT INTO conversations (id, owner_user_id, title, created_at) VALUES (?, ?, NULL, ?)",
        (cid, owner, NOW),
    )
    return cid


def insert_user_message(conn: sqlite3.Connection, cid: str, position: int = 1) -> str:
    mid = new_uuid()
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
        " produced_by_run_id) VALUES (?, ?, ?, 'user', 'hi', ?, NULL)",
        (mid, cid, position, NOW),
    )
    return mid


def insert_run(conn: sqlite3.Connection, cid: str, mid: str, status: str = "pending") -> str:
    rid = new_uuid()
    extra = ""
    if status == "in_flight":
        extra = f", model_id='m', runtime_id='r', dispatched_at='{NOW}'"
    conn.execute(
        "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status, requested_at)"
        " VALUES (?, ?, ?, 'pending', ?)",
        (rid, cid, mid, NOW),
    )
    if status == "in_flight":
        conn.execute(f"UPDATE model_runs SET status='in_flight'{extra} WHERE id=?", (rid,))
    return rid


def test_every_connection_enforces_foreign_keys(db_path: Path, store: SqliteStore) -> None:
    for _ in range(3):
        conn = connect(db_path)
        try:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()
    # A bare connection does NOT enforce them: this is why the adapter sets and verifies it.
    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        raw.close()


def test_orphan_rows_are_rejected(db_path: Path, owner: UserId, store: SqliteStore) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            insert_user_message(conn, new_uuid())  # conversation does not exist
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            seed_conversation(conn, new_uuid())  # owner does not exist
        cid = seed_conversation(conn, owner)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            insert_run(conn, cid, new_uuid())  # triggering message does not exist
    finally:
        conn.close()


def test_run_cannot_reference_message_of_another_conversation(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        a, b = seed_conversation(conn, owner), seed_conversation(conn, owner)
        message_in_a = insert_user_message(conn, a)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            insert_run(conn, b, message_in_a)
    finally:
        conn.close()


def test_positions_are_unique_per_conversation(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        insert_user_message(conn, cid, position=1)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            insert_user_message(conn, cid, position=1)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            insert_user_message(conn, cid, position=0)
    finally:
        conn.close()


def test_committed_messages_are_immutable_and_undeletable(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        mid = insert_user_message(conn, cid)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE messages SET content = 'rewritten' WHERE id = ?", (mid,))
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM messages WHERE id = ?", (mid,))
        assert (
            conn.execute("SELECT content FROM messages WHERE id = ?", (mid,)).fetchone()[0] == "hi"
        )
    finally:
        conn.close()


def test_assistant_message_requires_in_flight_run_and_user_message_forbids_one(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        mid = insert_user_message(conn, cid)
        pending = insert_run(conn, cid, mid, "pending")

        def assistant(position: int, run_id: str | None, role: str = "assistant") -> None:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, position, role, content,"
                " committed_at, produced_by_run_id) VALUES (?, ?, ?, ?, 'x', ?, ?)",
                (new_uuid(), cid, position, role, NOW, run_id),
            )

        # BEFORE INSERT triggers fire ahead of CHECKs, so either guard may report the rejection.
        with pytest.raises(sqlite3.IntegrityError, match=r"CHECK|in-flight"):
            assistant(2, None)  # assistant without run
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            assistant(2, pending, role="user")  # user message claiming a run
        with pytest.raises(sqlite3.IntegrityError, match="in-flight"):
            assistant(2, pending)  # run not dispatched
        with pytest.raises(sqlite3.IntegrityError, match=r"FOREIGN KEY|in-flight"):
            assistant(2, new_uuid())  # nonexistent run
    finally:
        conn.close()


def test_one_response_per_run_and_success_requires_response(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        mid = insert_user_message(conn, cid)
        rid = insert_run(conn, cid, mid, "in_flight")
        with pytest.raises(sqlite3.IntegrityError, match="requires its assistant message"):
            conn.execute(
                "UPDATE model_runs SET status='succeeded', settled_at=? WHERE id=?", (NOW, rid)
            )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
            " produced_by_run_id) VALUES (?, ?, 2, 'assistant', 'a', ?, ?)",
            (new_uuid(), cid, NOW, rid),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
                " produced_by_run_id) VALUES (?, ?, 3, 'assistant', 'b', ?, ?)",
                (new_uuid(), cid, NOW, rid),
            )
    finally:
        conn.close()


def test_at_most_one_unsettled_run_per_conversation(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        first = insert_user_message(conn, cid, 1)
        second = insert_user_message(conn, cid, 2)
        run = insert_run(conn, cid, first)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            insert_run(conn, cid, second)
        conn.execute(
            "UPDATE model_runs SET status='failed', failure_code='x', settled_at=? WHERE id=?",
            (NOW, run),
        )
        insert_run(conn, cid, second)  # allowed once the first is settled
    finally:
        conn.close()


def test_settled_runs_and_run_identity_are_immutable(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        mid = insert_user_message(conn, cid)
        rid = insert_run(conn, cid, mid)
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            conn.execute("UPDATE model_runs SET triggering_message_id = ? WHERE id = ?", (mid, rid))
        conn.execute(
            "UPDATE model_runs SET status='failed', failure_code='x', settled_at=? WHERE id=?",
            (NOW, rid),
        )
        with pytest.raises(sqlite3.IntegrityError, match="settled runs are immutable"):
            conn.execute("UPDATE model_runs SET failure_code = 'y' WHERE id = ?", (rid,))
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM model_runs WHERE id = ?", (rid,))
    finally:
        conn.close()


def test_run_state_consistency_checks(db_path: Path, owner: UserId, store: SqliteStore) -> None:
    conn = connect(db_path)
    try:
        cid = seed_conversation(conn, owner)
        mid = insert_user_message(conn, cid)
        rid = insert_run(conn, cid, mid)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # failed needs a code
            conn.execute(
                "UPDATE model_runs SET status='failed', settled_at=? WHERE id=?", (NOW, rid)
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # in_flight needs identities
            conn.execute("UPDATE model_runs SET status='in_flight' WHERE id=?", (rid,))
    finally:
        conn.close()


def test_timestamp_encoding_is_enforced(db_path: Path, owner: UserId, store: SqliteStore) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                "INSERT INTO conversations (id, owner_user_id, created_at) VALUES (?, ?, ?)",
                (new_uuid(), owner, "yesterday"),
            )
    finally:
        conn.close()
