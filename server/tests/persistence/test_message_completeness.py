"""Message completeness (ADR-0016, migration 0003): additive, immutable, atomic with T4.

Synthetic data only. Nothing here opens the preserved smoke database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.migrations import discover_migrations, migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.persistence import WriteResult
from anonymous.domain.errors import StorageFailure
from anonymous.domain.evidence import ClosureReason, CompletionObserved, EvidenceBasis
from anonymous.domain.ids import ConversationId, RunId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import Completeness, MessageRole, RunStatus
from tests.commit_faults import BEFORE_COMMIT, STATEMENT, faulting_commits
from tests.dispatching import dispatch
from tests.doubles import BoundStore, ManualClock
from tests.persistence.test_migration_0002 import add_conversation, add_turn, legacy_db

MESSAGE_COLUMNS = "id, conversation_id, position, role, content, committed_at, produced_by_run_id"


def started_run(
    store: SqliteStore, owner: UserId, text: str = "hello"
) -> tuple[ConversationId, RunId]:
    conversation = store.create_conversation(owner, None)
    admitted = store.admit_submission(
        owner=owner,
        conversation_id=conversation.id,
        submission_id=SubmissionId(new_uuid()),
        content=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    dispatch(store, admitted.run.id)
    return conversation.id, admitted.run.id


def assistant_rows(db_path: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT role, completeness FROM messages WHERE role = 'assistant'"
        ).fetchall()
    finally:
        conn.close()


# -- migration 0003 is additive and invents nothing ----------------------------------------------


def test_the_migration_adds_one_nullable_column_and_rewrites_nothing(db_path: Path) -> None:
    conn = legacy_db(db_path)
    done = add_turn(conn, add_conversation(conn, "done"), "succeeded")
    add_turn(conn, add_conversation(conn, "pending"), "pending")
    conn.commit()
    conn.close()
    assert migrate(db_path, discover_migrations()[:2]) == 2

    def snapshot() -> list[tuple[object, ...]]:
        c = sqlite3.connect(db_path)
        try:
            return c.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages ORDER BY id").fetchall()
        finally:
            c.close()

    before = snapshot()
    assert any(row[3] == "assistant" for row in before)  # a legacy assistant message exists
    assert migrate(db_path) == 3
    assert snapshot() == before  # every pre-existing column is byte-for-byte unchanged
    c = sqlite3.connect(db_path)
    try:
        values = c.execute("SELECT DISTINCT completeness FROM messages").fetchall()
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations")]
        run_status = c.execute("SELECT status FROM model_runs WHERE id = ?", (done,)).fetchone()
    finally:
        c.close()
    assert values == [(None,)]  # nothing is backfilled: legacy messages stay unclassified
    assert versions == [1, 2, 3] and run_status == ("succeeded",)
    assert migrate(db_path) == 3  # idempotent


def test_a_migrated_dataset_still_reads_its_history_through_the_store(
    db_path: Path, clock: ManualClock
) -> None:
    conn = legacy_db(db_path)
    cid = add_conversation(conn, "old")
    add_turn(conn, cid, "succeeded")
    conn.commit()
    conn.close()
    migrate(db_path)
    store = BoundStore(db_path, clock)
    owner = store.ensure_dev_owner()
    history = store.get_history(owner, ConversationId(cid))
    assert [m.role for m in history.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert all(m.completeness is None for m in history.messages)


# -- the allowed values, user messages and immutability --------------------------------------------


def test_only_the_two_values_or_null_are_storable(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    cid, run_id = started_run(store, owner)
    conn = sqlite3.connect(db_path)
    try:
        for bad in ("Truncated", "partial", "", "yes"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, position, role, content,"
                    " committed_at, produced_by_run_id, completeness)"
                    " VALUES (?, ?, 2, 'assistant', 'x', '2026-01-01T00:00:00.000000Z', ?, ?)",
                    (new_uuid(), cid, run_id, bad),
                )
    finally:
        conn.close()
    assert assistant_rows(db_path) == []


def test_a_user_message_can_never_carry_a_completeness(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    cid = store.create_conversation(owner, None).id
    conn = sqlite3.connect(db_path)
    try:
        for value in ("complete", "truncated"):
            with pytest.raises(sqlite3.DatabaseError, match="only an assistant message"):
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, position, role, content,"
                    " committed_at, produced_by_run_id, completeness)"
                    " VALUES (?, ?, 1, 'user', 'x', '2026-01-01T00:00:00.000000Z', NULL, ?)",
                    (new_uuid(), cid, value),
                )
        conn.execute(  # an unclassified user message is the ordinary case
            "INSERT INTO messages (id, conversation_id, position, role, content, committed_at,"
            " produced_by_run_id) VALUES (?, ?, 1, 'user', 'x',"
            " '2026-01-01T00:00:00.000000Z', NULL)",
            (new_uuid(), cid),
        )
    finally:
        conn.close()


@pytest.mark.parametrize("stored", [Completeness.TRUNCATED, Completeness.COMPLETE, None])
def test_a_published_completeness_can_never_be_changed(
    store: SqliteStore, owner: UserId, db_path: Path, stored: Completeness | None
) -> None:
    _, run_id = started_run(store, owner)
    store.publish_response(run_id, "answer", stored)
    conn = sqlite3.connect(db_path)
    try:
        for new in ("complete", "truncated", None):
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                conn.execute(
                    "UPDATE messages SET completeness = ? WHERE role = 'assistant'", (new,)
                )
        with pytest.raises(sqlite3.DatabaseError, match="cannot be deleted"):
            conn.execute("DELETE FROM messages WHERE role = 'assistant'")
    finally:
        conn.close()
    assert assistant_rows(db_path) == [("assistant", stored.value if stored else None)]


# -- T4 stores it atomically and claims nothing more ---------------------------------------------


def test_a_truncated_publication_is_stored_with_the_run_success_and_the_usual_stamps(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = started_run(store, owner)
    outcome = store.publish_response(run_id, "cut off mid-sen", Completeness.TRUNCATED)
    assert outcome.result is WriteResult.APPLIED and outcome.published is not None
    message, run = outcome.published.message, outcome.published.run
    assert message.completeness is Completeness.TRUNCATED and message.content == "cut off mid-sen"
    assert run.status is RunStatus.SUCCEEDED
    # T4 is unchanged: the same stamps as any accepted delivery, so nothing is claimed about the
    # process or about natural completion.
    assert run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert run.completion_observed is CompletionObserved.YES
    history = store.get_history(owner, cid)
    assert history.messages[-1].completeness is Completeness.TRUNCATED
    assert history.messages[0].completeness is None  # the user message is unclassified


def test_a_normal_and_an_unspecified_publication(store: SqliteStore, owner: UserId) -> None:
    _, first = started_run(store, owner)
    done = store.publish_response(first, "fine", Completeness.COMPLETE)  # releases the one slot
    _, second = started_run(store, owner)
    bare = store.publish_response(second, "no label")
    assert done.published is not None and bare.published is not None
    assert done.published.message.completeness is Completeness.COMPLETE
    assert bare.published.message.completeness is None  # a caller that does not say: unclassified


def test_a_second_publication_returns_the_original_message_and_its_completeness(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = started_run(store, owner)
    store.publish_response(run_id, "first", Completeness.TRUNCATED)
    again = store.publish_response(run_id, "second", Completeness.COMPLETE)
    assert again.result is WriteResult.PUBLISHED and again.published is not None
    assert again.published.message.content == "first"
    assert again.published.message.completeness is Completeness.TRUNCATED  # not restated


def test_publication_after_closure_is_refused_whatever_its_completeness(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    cid, run_id = started_run(store, owner)
    store.close_run(run_id, ClosureReason.DEADLINE)
    late = store.publish_response(run_id, "late", Completeness.TRUNCATED)
    assert late.result is WriteResult.ALREADY_CLOSED and late.published is None
    assert assistant_rows(db_path) == []
    assert len(store.get_history(owner, cid).messages) == 1


@pytest.mark.parametrize("point", [STATEMENT, BEFORE_COMMIT])
def test_a_failed_publication_leaves_neither_a_message_nor_a_success(
    store: SqliteStore,
    owner: UserId,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    cid, run_id = started_run(store, owner)
    with faulting_commits(monkeypatch) as plan:
        rule = plan.arm(
            "publish_response", point, pattern="UPDATE model_runs" if point == STATEMENT else None
        )
        with pytest.raises(Exception) as caught:
            store.publish_response(run_id, "answer", Completeness.TRUNCATED)
        assert rule.hits == 1
    assert isinstance(caught.value, StorageFailure) or "confirm" in str(caught.value).lower()
    assert assistant_rows(db_path) == []  # no misleading half-published message
    run = store.get_run(run_id)
    assert run.status is RunStatus.IN_FLIGHT and run.closed_at is None  # and no false success
    retry = store.publish_response(run_id, "answer", Completeness.TRUNCATED)
    assert retry.result is WriteResult.APPLIED  # the same fence can still publish exactly once
    assert assistant_rows(db_path) == [("assistant", "truncated")]
    assert len(store.get_history(owner, cid).messages) == 2


def test_the_completeness_survives_reopening_the_database(
    store: SqliteStore, owner: UserId, db_path: Path, clock: ManualClock
) -> None:
    cid, run_id = started_run(store, owner)
    store.publish_response(run_id, "cut off", Completeness.TRUNCATED)
    reopened = BoundStore(db_path, clock)
    assert migrate(db_path) == 3  # opening again changes nothing
    history = reopened.get_history(owner, cid)
    assert [m.completeness for m in history.messages] == [None, Completeness.TRUNCATED]
