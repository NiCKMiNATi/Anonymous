"""What the SQLite development adapter guarantees about message commit instants (FR-15/LM-03).

Implementation fact, stated precisely (see docs/implementation/slice-0a.md, "Commit instants"):

* the instant is read from the injected clock *inside* the message's own write transaction, after
  ``BEGIN IMMEDIATE`` has acquired the exclusive write lock and after admission checks, immediately
  before the INSERT statements, and in the same atomic transaction that makes the message durable;
* it is therefore never earlier than lock acquisition, never later than the durable COMMIT, and no
  other writer can commit between the sample and the COMMIT;
* the row has to carry the value before COMMIT runs, so the engine's own COMMIT instant is not
  observable by the application and the stored value is *at or before* it, by the duration of the
  remaining statements and the durable flush. These tests do not claim equality with that instant.

Equal or non-monotonic instants never decide order (covered in ``test_store_behavior.py`` and
``test_execution.py``); ordering is the integer position.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite import store as store_module
from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.context import ContextBuilder
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import ModelIdentity, ModelOutput, ModelRequest
from anonymous.application.ports.persistence import SubmissionOutcome
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid

T0 = datetime(2026, 10, 10, 9, 0, 0, tzinfo=UTC)


class ControlledClock:
    """A clock the test moves by hand; it records when it is read relative to SQL statements."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.current = T0
        self.reads = 0
        self._events = events

    def now(self) -> datetime:
        self.reads += 1
        if self._events is not None:
            self._events.append("CLOCK")
        return self.current


class RecordingConnection:
    """Delegating proxy that logs the leading keyword of every executed statement."""

    def __init__(self, inner: object, events: list[str]) -> None:
        self._inner = inner
        self._events = events

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def execute(self, sql: str, *args: object) -> object:
        keyword = sql.strip().split(None, 1)[0].upper()
        if keyword == "BEGIN" or keyword == "COMMIT" or keyword in {"INSERT", "UPDATE"}:
            self._events.append(keyword)
        return self._inner.execute(sql, *args)  # type: ignore[attr-defined]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def admit(
    store: SqliteStore, owner: UserId, cid: ConversationId, text: str = "hello"
) -> SubmissionOutcome:
    return store.admit_submission(
        owner=owner,
        conversation_id=cid,
        submission_id=SubmissionId(new_uuid()),
        content=text,
        content_sha256=digest(text),
    )


@pytest.fixture
def owner_and_conversation(db_path: Path, store: SqliteStore) -> tuple[UserId, ConversationId]:
    owner = store.ensure_dev_owner()
    return owner, store.create_conversation(owner, None).id


def _hold_write_lock(db_path: Path) -> sqlite3.Connection:
    """Another connection owns the database write lock, as a slow concurrent writer would."""
    blocker = connect(db_path)
    blocker.execute("BEGIN IMMEDIATE")
    return blocker


def _run_when_blocked(
    action: Callable[[], object],
) -> tuple[threading.Thread, dict[str, object]]:
    result: dict[str, object] = {}

    def target() -> None:
        try:
            result["value"] = action()
        except BaseException as error:
            result["error"] = error

    thread = threading.Thread(target=target)
    thread.start()
    return thread, result


def test_user_instant_reflects_when_the_write_lock_was_won_not_when_the_request_arrived(
    db_path: Path, owner_and_conversation: tuple[UserId, ConversationId]
) -> None:
    """Delayed-commit fixture: the commit is delayed by lock contention, after the request began."""
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = SqliteStore(db_path, clock)
    blocker = _hold_write_lock(db_path)
    reads_before = clock.reads

    thread, result = _run_when_blocked(lambda: admit(store, owner, cid))
    time.sleep(0.3)  # the request has arrived and is waiting on the lock
    assert clock.reads == reads_before  # no instant was taken while waiting to commit
    clock.current = T0 + timedelta(minutes=5)  # the lock is won much later than arrival
    blocker.execute("COMMIT")
    blocker.close()
    thread.join(timeout=10)

    assert "error" not in result, result.get("error")
    outcome = result["value"]
    assert outcome.user_message.committed_at == T0 + timedelta(minutes=5)  # type: ignore[attr-defined]
    assert clock.reads == reads_before + 1  # one instant for the whole admission transaction
    stored = store.get_history(owner, cid).messages[0]
    assert stored.committed_at == T0 + timedelta(minutes=5)


def test_assistant_instant_reflects_publication_not_dispatch(
    db_path: Path, owner_and_conversation: tuple[UserId, ConversationId]
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = SqliteStore(db_path, clock)
    run = admit(store, owner, cid).run
    store.record_dispatch(run.id, "model-x", "runtime-x")  # dispatched at T0
    blocker = _hold_write_lock(db_path)
    reads_before = clock.reads

    thread, result = _run_when_blocked(lambda: store.publish_response(run.id, "answer"))
    time.sleep(0.3)
    assert clock.reads == reads_before
    clock.current = T0 + timedelta(minutes=7)
    blocker.execute("COMMIT")
    blocker.close()
    thread.join(timeout=10)

    assert "error" not in result, result.get("error")
    history = store.get_history(owner, cid)
    user, assistant = history.messages
    assert user.committed_at == T0  # the user message keeps its own original instant
    assert assistant.committed_at == T0 + timedelta(minutes=7)
    assert [m.position for m in history.messages] == [1, 2]


def test_assistant_instant_is_not_the_generation_start_or_the_user_commit(
    db_path: Path, owner_and_conversation: tuple[UserId, ConversationId]
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = SqliteStore(db_path, clock)

    class SlowModel:
        identity = ModelIdentity("slow-model", "slow-runtime")

        def generate(self, request: ModelRequest) -> ModelOutput:
            clock.current += timedelta(minutes=30)  # generation takes half an hour
            return ModelOutput("late answer", self.identity)

    outcome = ExecutionCoordinator(store, ContextBuilder(store), SlowModel()).submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.assistant_message is not None
    assert outcome.user_message.committed_at == T0
    assert outcome.assistant_message.committed_at == T0 + timedelta(minutes=30)
    history = store.get_history(owner, cid).messages
    assert [m.committed_at for m in history] == [T0, T0 + timedelta(minutes=30)]


def test_each_write_transaction_samples_the_clock_once_inside_itself(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    """Pins the order BEGIN IMMEDIATE (lock) < clock read < first write < COMMIT per transaction."""
    owner, cid = owner_and_conversation
    events: list[str] = []
    clock = ControlledClock(events)
    store = SqliteStore(db_path, clock)
    real_connect = connect
    monkeypatch.setattr(
        store_module, "connect", lambda path: RecordingConnection(real_connect(path), events)
    )

    outcome = ExecutionCoordinator(
        store,
        ContextBuilder(store),
        _FixedModel(),
    ).submit(owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q")
    assert outcome.assistant_message is not None

    transactions: list[list[str]] = []
    for event in events:
        if event == "BEGIN":
            transactions.append([])
        if transactions:
            transactions[-1].append(event)
    writes = [t for t in transactions if "COMMIT" in t]
    assert len(writes) == 3  # admission, dispatch, publication
    for transaction in writes:
        assert transaction.count("CLOCK") == 1
        clock_at = transaction.index("CLOCK")
        first_write = min(
            transaction.index(kind) for kind in ("INSERT", "UPDATE") if kind in transaction
        )
        assert (
            0 == transaction.index("BEGIN") < clock_at < first_write < transaction.index("COMMIT")
        )


def test_instant_is_never_later_than_the_commit_it_belongs_to(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    """The upper bound: the stored instant is at or before the moment COMMIT was issued.

    Deliberately an inequality. The remaining gap (statements + durable flush) is not asserted
    to be zero because the engine's COMMIT instant cannot be stored in the committing row.
    """
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = SqliteStore(db_path, clock)
    real_connect = connect
    commit_clock_values: list[datetime] = []

    class Delaying(RecordingConnection):
        def execute(self, sql: str, *args: object) -> object:
            if sql.strip().upper() == "COMMIT":
                clock.current += timedelta(seconds=90)  # time passes before the commit lands
                commit_clock_values.append(clock.current)
            return self._inner.execute(sql, *args)  # type: ignore[attr-defined]

    monkeypatch.setattr(store_module, "connect", lambda path: Delaying(real_connect(path), []))
    outcome = admit(store, owner, cid)

    assert commit_clock_values
    assert outcome.user_message.committed_at <= commit_clock_values[0]
    assert outcome.user_message.committed_at == T0  # taken before the delay, as documented


def test_instants_do_not_decrease_with_position_under_a_monotone_clock(
    db_path: Path, owner_and_conversation: tuple[UserId, ConversationId]
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = SqliteStore(db_path, clock)
    coordinator = ExecutionCoordinator(store, ContextBuilder(store), _FixedModel())
    for index in range(3):
        clock.current += timedelta(seconds=1)
        coordinator.submit(
            owner=owner,
            conversation_id=cid,
            submission_id=SubmissionId(new_uuid()),
            content=f"q{index}",
        )
    messages = store.get_history(owner, cid).messages
    assert [m.position for m in messages] == [1, 2, 3, 4, 5, 6]
    instants = [m.committed_at for m in messages]
    assert instants == sorted(instants)


class _FixedModel:
    identity = ModelIdentity("fixed-model", "fixed-runtime")

    def generate(self, request: ModelRequest) -> ModelOutput:
        return ModelOutput("fixed answer", self.identity)
