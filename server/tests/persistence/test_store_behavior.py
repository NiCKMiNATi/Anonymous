"""Store behavior through the application-owned ports."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.persistence import SubmissionOutcome, WriteResult
from anonymous.domain.errors import ConversationBusy, ConversationNotFound, IdempotencyConflict
from anonymous.domain.evidence import ClosureReason, CompletionObserved, EvidenceBasis, Handoff
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import MessageRole, RunStatus
from tests.dispatching import BOOT, authorize, dispatch, record
from tests.doubles import BoundStore, ManualClock


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def admit(
    store: SqliteStore,
    owner: UserId,
    cid: ConversationId,
    text: str = "hello",
    sid: str | None = None,
) -> SubmissionOutcome:
    return store.admit_submission(
        owner=owner,
        conversation_id=cid,
        submission_id=SubmissionId(sid or new_uuid()),
        content=text,
        content_sha256=digest(text),
    )


def test_create_list_and_open_conversation(store: SqliteStore, owner: UserId) -> None:
    first = store.create_conversation(owner, "First")
    second = store.create_conversation(owner, None)
    assert first.id != second.id
    assert [c.id for c in store.list_conversations(owner)] == [second.id, first.id]
    history = store.get_history(owner, first.id)
    assert history.conversation.title == "First"
    assert history.messages == () and history.runs == ()


def test_conversations_are_owner_scoped(store: SqliteStore, owner: UserId, db_path: Path) -> None:
    conversation = store.create_conversation(owner, None)
    other = UserId(new_uuid())
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users VALUES (?, '2026-01-01T00:00:00.000000Z')", (other,))
    conn.commit()
    conn.close()
    assert store.list_conversations(other) == ()
    with pytest.raises(ConversationNotFound):
        store.get_history(other, conversation.id)
    with pytest.raises(ConversationNotFound):
        admit(store, other, conversation.id)


def test_missing_conversation(store: SqliteStore, owner: UserId) -> None:
    with pytest.raises(ConversationNotFound):
        store.get_history(owner, ConversationId(new_uuid()))
    with pytest.raises(ConversationNotFound):
        admit(store, owner, ConversationId(new_uuid()))


def test_admission_commits_user_message_pending_run_and_submission_together(
    store: SqliteStore, owner: UserId
) -> None:
    conversation = store.create_conversation(owner, None)
    outcome = admit(store, owner, conversation.id)
    assert outcome.replayed is False
    assert outcome.user_message.role is MessageRole.USER
    assert outcome.user_message.position == 1
    assert outcome.run.status is RunStatus.PENDING
    assert outcome.run.triggering_message_id == outcome.user_message.id
    history = store.get_history(owner, conversation.id)
    assert [m.id for m in history.messages] == [outcome.user_message.id]
    assert [r.id for r in history.runs] == [outcome.run.id]


def test_busy_conversation_refuses_without_appending(store: SqliteStore, owner: UserId) -> None:
    conversation = store.create_conversation(owner, None)
    admit(store, owner, conversation.id, "one")
    with pytest.raises(ConversationBusy):
        admit(store, owner, conversation.id, "two")
    assert len(store.get_history(owner, conversation.id).messages) == 1


def test_replay_returns_original_and_conflicts_are_refused(
    store: SqliteStore, owner: UserId
) -> None:
    conversation = store.create_conversation(owner, None)
    other = store.create_conversation(owner, None)
    sid = new_uuid()
    first = admit(store, owner, conversation.id, "same", sid)
    replay = admit(store, owner, conversation.id, "same", sid)
    assert replay.replayed is True
    assert replay.user_message == first.user_message and replay.run.id == first.run.id
    with pytest.raises(IdempotencyConflict):
        admit(store, owner, conversation.id, "different", sid)
    with pytest.raises(IdempotencyConflict):
        admit(store, owner, other.id, "same", sid)
    assert len(store.get_history(owner, conversation.id).messages) == 1
    assert store.get_history(owner, other.id).messages == ()


def test_dispatch_publish_and_settle_state_machine(store: SqliteStore, owner: UserId) -> None:
    conversation = store.create_conversation(owner, None)
    admitted = admit(store, owner, conversation.id)
    run_id = admitted.run.id
    early = store.publish_response(run_id, "too early")  # never dispatched
    assert early.result is WriteResult.WRONG_SOURCE and early.published is None
    authorized = authorize(store, run_id)
    assert authorized.status is RunStatus.IN_FLIGHT and authorized.handoff is Handoff.NONE
    assert (authorized.model_id, authorized.runtime_id) == ("m", "r")
    assert store.authorize_dispatch(run_id, record()).result is WriteResult.WRONG_SOURCE
    # Publication needs a started handoff (T3b), not just an authorization (T3).
    assert store.publish_response(run_id, "no handoff").result is WriteResult.WRONG_SOURCE
    assert store.mark_handoff_started(run_id, BOOT).result is WriteResult.APPLIED
    assert store.mark_handoff_started(run_id, BOOT).result is WriteResult.ALREADY_STARTED
    published = store.publish_response(run_id, "answer")
    assert published.result is WriteResult.APPLIED and published.published is not None
    assert published.published.run.status is RunStatus.SUCCEEDED
    assert published.published.message.role is MessageRole.ASSISTANT
    assert published.published.message.position == 2
    assert published.published.message.produced_by_run_id == run_id
    again = store.publish_response(run_id, "second answer")  # one response per run
    assert again.result is WriteResult.PUBLISHED
    assert again.published is not None and again.published.message.content == "answer"
    closed = store.close_run(run_id, ClosureReason.DEADLINE)
    assert closed.result is WriteResult.PUBLISHED  # closure cannot undo a committed result
    settled = store.settle_in_flight(
        run_id,
        basis=EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
        code="x",
        message="y",
        completion=CompletionObserved.UNKNOWN,
        reason=ClosureReason.DEADLINE,
    )
    assert settled.result is WriteResult.PUBLISHED  # settled runs stay settled
    history = store.get_history(owner, conversation.id)
    assert [m.content for m in history.messages] == ["hello", "answer"]


def test_publish_is_atomic_when_the_run_update_fails(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    conversation = store.create_conversation(owner, None)
    run = admit(store, owner, conversation.id).run
    dispatch(store, run.id)
    # Break the second statement of publication: an extra trigger aborts the run update.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TRIGGER sabotage BEFORE UPDATE ON model_runs WHEN NEW.status='succeeded'"
        " BEGIN SELECT RAISE(ABORT, 'sabotage'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(Exception):  # noqa: B017 - StorageFailure wrapping the sqlite error
        store.publish_response(run.id, "answer")
    history = store.get_history(owner, conversation.id)
    assert [m.role for m in history.messages] == [MessageRole.USER]  # no orphan assistant message
    assert history.runs[0].status is RunStatus.IN_FLIGHT


def test_failed_settlement_commits_no_message(store: SqliteStore, owner: UserId) -> None:
    conversation = store.create_conversation(owner, None)
    run = admit(store, owner, conversation.id).run
    failed = store.settle_pending(run.id, "never_dispatched", "msg")
    assert failed.result is WriteResult.APPLIED
    assert failed.run.status is RunStatus.FAILED and failed.run.model_id is None
    assert failed.run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert len(store.get_history(owner, conversation.id).messages) == 1
    admit(store, owner, conversation.id, "next")  # admission released


def test_positions_are_assigned_in_commit_order_not_by_time(db_path: Path, owner: UserId) -> None:
    from datetime import timedelta

    from tests.doubles import START, SequenceClock

    # Equal, then decreasing instants.
    clock = SequenceClock([START, START, START - timedelta(hours=5)])
    store = BoundStore(db_path, clock)
    conversation = store.create_conversation(owner, None)  # consumes START
    first = admit(store, owner, conversation.id, "q")  # consumes START
    dispatch(store, first.run.id)  # consumes the earlier instant (dispatch time)
    answer = store.publish_response(first.run.id, "a").published
    assert answer is not None
    assert [m.position for m in store.get_history(owner, conversation.id).messages] == [1, 2]
    assert answer.message.committed_at < first.user_message.committed_at
    ordered = store.get_history(owner, conversation.id).messages
    assert [m.role for m in ordered] == [MessageRole.USER, MessageRole.ASSISTANT]


def test_recover_pending_runs_settles_only_never_dispatched_work(
    store: SqliteStore, owner: UserId
) -> None:
    pending_conv = store.create_conversation(owner, None)
    flight_conv = store.create_conversation(owner, None)
    done_conv = store.create_conversation(owner, None)
    pending = admit(store, owner, pending_conv.id).run
    in_flight = admit(store, owner, flight_conv.id).run
    dispatch(store, in_flight.id, slot="slot-a")
    done = admit(store, owner, done_conv.id).run
    dispatch(store, done.id, slot="slot-b")
    store.publish_response(done.id, "ok")

    assert store.recover_pending_runs() == 1  # only the run that provably never dispatched

    pending_after = store.get_history(owner, pending_conv.id).runs[0]
    assert pending_after.status is RunStatus.FAILED and pending_after.id == pending.id
    assert pending_after.failure_code == "interrupted_before_dispatch"
    assert pending_after.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    # A possibly-invoked run is NOT guessed at: it stays in flight until evidence resolves it.
    flight_after = store.get_history(owner, flight_conv.id).runs[0]
    assert flight_after.status is RunStatus.IN_FLIGHT
    assert [r.id for r in store.list_unresolved_runs()] == [in_flight.id]
    assert store.get_history(owner, done_conv.id).runs[0].status is RunStatus.SUCCEEDED

    admit(store, owner, pending_conv.id, "again")  # never-dispatched work released the gate
    with pytest.raises(ConversationBusy):  # unresolved work keeps the conversation closed
        admit(store, owner, flight_conv.id, "again")
    assert store.recover_pending_runs() == 1  # only the newly admitted pending run; idempotent
    assert store.recover_pending_runs() == 0


def test_history_survives_reopening_the_database(
    store: SqliteStore, owner: UserId, db_path: Path, clock: ManualClock
) -> None:
    conversation = store.create_conversation(owner, "Persisted")
    run = admit(store, owner, conversation.id, "hello").run
    dispatch(store, run.id)
    store.publish_response(run.id, "hi there")
    before = store.get_history(owner, conversation.id)

    reopened = BoundStore(db_path, ManualClock())  # a brand new store object and connections
    assert reopened.ensure_dev_owner() == owner
    after = reopened.get_history(owner, conversation.id)
    assert after == before  # identities, order, content, instants, run association: unchanged
    assert after.messages[1].produced_by_run_id == after.runs[0].id


def test_read_messages_through_is_a_fixed_prefix(store: SqliteStore, owner: UserId) -> None:
    conversation = store.create_conversation(owner, None)
    first = admit(store, owner, conversation.id, "one")
    dispatch(store, first.run.id)
    store.publish_response(first.run.id, "reply")
    second = admit(store, owner, conversation.id, "two")
    prefix = store.read_messages_through(conversation.id, first.user_message.id)
    assert [m.content for m in prefix] == ["one"]  # later messages never enter the boundary
    full = store.read_messages_through(conversation.id, second.user_message.id)
    assert [m.content for m in full] == ["one", "reply", "two"]


def test_dev_owner_is_stable_across_calls(store: SqliteStore) -> None:
    assert store.ensure_dev_owner() == store.ensure_dev_owner()
