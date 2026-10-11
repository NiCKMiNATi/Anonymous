"""Migration 0002 over populated Slice 0A datasets (LD-04 §5.5, §11.3).

Legacy facts are preserved unchanged; unresolved legacy executions are neither invented a binding
nor settled; and the migration STOPS SAFELY (rolls back, dataset untouched) only on structural
inconsistency — never merely because unresolved executions exist.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.migrations import discover_migrations, migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.persistence import WriteResult
from anonymous.domain.errors import StorageFailure
from anonymous.domain.evidence import ClosureReason, CompletionObserved, EvidenceBasis
from anonymous.domain.ids import RunId, UserId, new_uuid
from tests.doubles import ManualClock

NOW = "2026-01-01T12:00:00.000000Z"
USER = "00000000-0000-4000-8000-000000000001"

LEGACY_TABLES = {
    "users": "SELECT * FROM users ORDER BY id",
    "conversations": "SELECT id, owner_user_id, title, created_at FROM conversations ORDER BY id",
    "messages": "SELECT * FROM messages ORDER BY id",
    "submissions": "SELECT * FROM submissions ORDER BY submission_id",
    "model_runs": "SELECT id, conversation_id, triggering_message_id, status, model_id,"
    " runtime_id, failure_code, failure_message, requested_at, dispatched_at, settled_at"
    " FROM model_runs ORDER BY id",
}


def legacy_db(path: Path) -> sqlite3.Connection:
    """A database at schema 0001 (what Slice 0A produced)."""
    migrate(path, [discover_migrations()[0]])
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO users (id, created_at) VALUES (?, ?)", (USER, NOW))
    return conn


def add_conversation(conn: sqlite3.Connection, title: str = "c") -> str:
    cid = new_uuid()
    conn.execute(
        "INSERT INTO conversations (id, owner_user_id, title, created_at) VALUES (?, ?, ?, ?)",
        (cid, USER, title, NOW),
    )
    return cid


def add_turn(
    conn: sqlite3.Connection, cid: str, status: str, *, text: str = "hello", position: int = 1
) -> str:
    """One user message and one 0A run in ``status`` (0A semantics)."""
    mid, rid = new_uuid(), new_uuid()
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
        " produced_by_run_id) VALUES (?, ?, ?, 'user', ?, ?, NULL)",
        (mid, cid, position, text, NOW),
    )
    conn.execute(
        "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status, requested_at)"
        " VALUES (?, ?, ?, 'pending', ?)",
        (rid, cid, mid, NOW),
    )
    conn.execute(
        "INSERT INTO submissions (owner_user_id, submission_id, conversation_id, content_sha256,"
        " user_message_id, run_id, created_at) VALUES (?, ?, ?, 'x', ?, ?, ?)",
        (USER, new_uuid(), cid, mid, rid, NOW),
    )
    if status == "pending":
        return rid
    if status == "failed":
        conn.execute(
            "UPDATE model_runs SET status='failed', failure_code='old', failure_message='m',"
            " settled_at=? WHERE id=?",
            (NOW, rid),
        )
        return rid
    conn.execute(
        "UPDATE model_runs SET status='in_flight', model_id='fake-echo-1',"
        " runtime_id='fake-in-process-runtime-1', dispatched_at=? WHERE id=?",
        (NOW, rid),
    )
    if status == "succeeded":
        conn.execute(
            "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
            " produced_by_run_id) VALUES (?, ?, ?, 'assistant', 'reply', ?, ?)",
            (new_uuid(), cid, position + 1, NOW, rid),
        )
        conn.execute(
            "UPDATE model_runs SET status='succeeded', settled_at=? WHERE id=?", (NOW, rid)
        )
    elif status == "indeterminate":
        conn.execute("UPDATE model_runs SET status='indeterminate' WHERE id=?", (rid,))
    return rid


def snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    conn = sqlite3.connect(path)
    try:
        return {t: [tuple(r) for r in conn.execute(q).fetchall()] for t, q in LEGACY_TABLES.items()}
    finally:
        conn.close()


def dump(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def populated(path: Path) -> dict[str, str]:
    conn = legacy_db(path)
    runs = {
        "done": add_turn(conn, add_conversation(conn, "done"), "succeeded"),
        "failed": add_turn(conn, add_conversation(conn, "failed"), "failed"),
        "pending": add_turn(conn, add_conversation(conn, "pending"), "pending"),
        "in_flight_a": add_turn(conn, add_conversation(conn, "if-a"), "in_flight"),
        "in_flight_b": add_turn(conn, add_conversation(conn, "if-b"), "in_flight"),
        "indeterminate_a": add_turn(conn, add_conversation(conn, "ind-a"), "indeterminate"),
        "indeterminate_b": add_turn(conn, add_conversation(conn, "ind-b"), "indeterminate"),
    }
    conn.commit()
    conn.close()
    return runs


# -- preservation --------------------------------------------------------------------------------


def test_every_legacy_fact_is_preserved_and_nothing_is_invented(db_path: Path) -> None:
    runs = populated(db_path)
    before = snapshot(db_path)
    assert migrate(db_path) == 2
    assert snapshot(db_path) == before  # byte-for-byte on every pre-existing column

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM model_runs").fetchall()
        assert len(rows) == len(runs)
        for row in rows:
            assert row["record_epoch"] == "legacy_0a" and row["state_version"] == 0
            for column in (
                "closed_at",
                "closure_reason",
                "handoff",
                "handoff_outcome",
                "execution_boot_id",
                "slot_id",
                "binding_format",
                "binding_instance_ref",
                "configuration_digest",
                "provenance_json",
                "termination_basis",
                "completion_observed",
            ):
                assert row[column] is None, column  # no binding, fence, slot or evidence invented
        assert {
            r["epoch"] for r in conn.execute("SELECT record_epoch AS epoch FROM conversations")
        } == {"legacy_0a"}
        assert (
            conn.execute("SELECT COUNT(*) FROM conversation_configuration_bindings").fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM effective_configurations").fetchone()[0] == 0
    finally:
        conn.close()


def test_migration_never_settles_an_execution(db_path: Path) -> None:
    runs = populated(db_path)
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    try:
        statuses = {
            name: conn.execute("SELECT status FROM model_runs WHERE id=?", (rid,)).fetchone()[0]
            for name, rid in runs.items()
        }
    finally:
        conn.close()
    assert statuses == {
        "done": "succeeded",
        "failed": "failed",
        "pending": "pending",
        "in_flight_a": "in_flight",
        "in_flight_b": "in_flight",
        "indeterminate_a": "indeterminate",
        "indeterminate_b": "indeterminate",
    }


# -- several unresolved legacy executions --------------------------------------------------------


def test_several_unresolved_legacy_runs_hold_no_slot_and_block_every_dispatch(
    db_path: Path,
) -> None:
    runs = populated(db_path)
    migrate(db_path)
    store = SqliteStore(db_path, ManualClock())
    state = store.generation_state()
    assert {b.run_id for b in state.legacy_blockers} == {
        RunId(runs[k]) for k in ("in_flight_a", "in_flight_b", "indeterminate_a", "indeterminate_b")
    }
    assert state.quarantined_runs == ()  # 0B quarantine is a different concept
    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM model_runs WHERE slot_id IS NOT NULL").fetchone()[0]
            == 0
        )
    finally:
        conn.close()
    # Reading still works for every conversation.
    for conversation in store.list_conversations(UserId(USER)):
        assert store.get_history(UserId(USER), conversation.id).messages


def test_no_settlement_path_exists_for_binding_less_runs(db_path: Path) -> None:
    runs = populated(db_path)
    migrate(db_path)
    store = SqliteStore(db_path, ManualClock())
    for name in ("in_flight_a", "indeterminate_a"):
        run_id = RunId(runs[name])
        for basis in EvidenceBasis:  # including a "scripted CONFIRMED_ENDED"-style basis
            via_t5 = store.settle_in_flight(
                run_id,
                basis=basis,
                code="c",
                message="m",
                completion=CompletionObserved.UNKNOWN,
                reason=ClosureReason.ORPHAN_RECONCILE,
            )
            via_t7 = store.settle_indeterminate(
                run_id,
                basis=basis,
                code="c",
                message="m",
                completion=CompletionObserved.UNKNOWN,
                expected_version=0,
            )
            assert via_t5.result in (WriteResult.NO_ADMISSIBLE_BASIS, WriteResult.WRONG_SOURCE)
            assert via_t7.result in (WriteResult.NO_ADMISSIBLE_BASIS, WriteResult.WRONG_SOURCE)
        assert (
            store.close_run(run_id, ClosureReason.ORPHAN_RECONCILE).result
            is WriteResult.WRONG_SOURCE
        )
        assert store.mark_indeterminate(run_id, 0).result is WriteResult.WRONG_SOURCE
    # The trigger backs the store: raw SQL cannot settle them either (label match irrelevant).
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE model_runs SET status='failed', failure_code='x', settled_at=?,"
                " termination_basis='process_exit_verified', completion_observed='unknown',"
                " closed_at=?, closure_reason='deadline', state_version=state_version+1"
                " WHERE id=?",
                (NOW, NOW, runs["indeterminate_a"]),
            )
    finally:
        conn.close()
    assert snapshot(db_path)["model_runs"] == snapshot(db_path)["model_runs"]
    assert {r[3] for r in snapshot(db_path)["model_runs"]} >= {"in_flight", "indeterminate"}


def test_a_legacy_pending_run_is_provably_never_dispatched_and_settles_normally(
    db_path: Path,
) -> None:
    runs = populated(db_path)
    migrate(db_path)
    store = SqliteStore(db_path, ManualClock())
    assert store.recover_pending_runs() == 1
    run = store.get_run(RunId(runs["pending"]))
    assert run.status.value == "failed" and run.failure_code == "interrupted_before_dispatch"
    assert run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert run.record_epoch.value == "legacy_0a" and run.model_id is None  # 0A facts untouched


# -- stopping safely -----------------------------------------------------------------------------


def _assert_stops_safely(db_path: Path) -> None:
    before = dump(db_path)
    with pytest.raises(StorageFailure):
        migrate(db_path)
    assert dump(db_path) == before  # rolled back: the dataset is untouched
    conn = sqlite3.connect(db_path)
    try:
        assert [r[0] for r in conn.execute("SELECT version FROM schema_migrations")] == [1]
        columns = [r[1] for r in conn.execute("PRAGMA table_info(model_runs)")]
        assert "record_epoch" not in columns
    finally:
        conn.close()


def test_migration_stops_on_an_assistant_message_belonging_to_a_non_succeeded_run(
    db_path: Path,
) -> None:
    conn = legacy_db(db_path)
    cid = add_conversation(conn)
    rid = add_turn(conn, cid, "in_flight")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
        " produced_by_run_id) VALUES (?, ?, 2, 'assistant', 'a', ?, ?)",
        (new_uuid(), cid, NOW, rid),
    )
    conn.execute(
        "UPDATE model_runs SET status='failed', failure_code='x', settled_at=? WHERE id=?",
        (NOW, rid),
    )
    conn.commit()
    conn.close()
    _assert_stops_safely(db_path)


def test_migration_stops_when_a_message_was_accepted_after_an_unsettled_run(db_path: Path) -> None:
    conn = legacy_db(db_path)
    cid = add_conversation(conn)
    add_turn(conn, cid, "indeterminate")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
        " produced_by_run_id) VALUES (?, ?, 2, 'user', 'later', ?, NULL)",
        (new_uuid(), cid, NOW),
    )
    conn.commit()
    conn.close()
    _assert_stops_safely(db_path)


def test_unresolved_legacy_executions_alone_do_not_stop_the_migration(db_path: Path) -> None:
    conn = legacy_db(db_path)
    add_turn(conn, add_conversation(conn), "indeterminate")
    conn.commit()
    conn.close()
    assert migrate(db_path) == 2  # representable, so it proceeds; dispatch stays blocked


def test_failed_prechecks_name_the_violated_precondition_without_row_content(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    conn = legacy_db(db_path)
    cid = add_conversation(conn)
    add_turn(conn, cid, "pending", text="SECRET-CONTENT")
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
        " produced_by_run_id) VALUES (?, ?, 2, 'user', 'later', ?, NULL)",
        (new_uuid(), cid, NOW),
    )
    conn.commit()
    conn.close()
    with pytest.raises(StorageFailure):
        migrate(db_path)
    assert "preflight_message_accepted_after_unsettled_run" in caplog.text
    assert "SECRET-CONTENT" not in caplog.text
