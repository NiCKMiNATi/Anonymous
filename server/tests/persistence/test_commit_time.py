"""Commit instants in the SQLite development adapter (FR-15/LM-03, accepted contract).

Accepted contract (FR-15 as accepted by the owner 2026-10-11; docs/02-requirements.md):
the commit timestamp is sampled within the committing transaction after write authority was
obtained and before the commit attempt; it is authoritative only if the message commits; after an
uncertain outcome nothing is assumed (no rollback is inferred) and reconciliation determines
whether the operation committed -- if so the originally persisted timestamp is preserved, if not a
later successful operation samples its own; no equality with, or numeric bound on the difference
from, the physical commit-completion instant is promised; order never depends on timestamps.

Stated in terms of the order of *events*, not of wall-clock values (a wall clock can step
backwards, so no numeric inequality between a stored instant and any other reading is promised):

* the clock is read inside the message's own write transaction, after ``BEGIN IMMEDIATE`` has
  acquired the exclusive write lock and the admission checks, before the INSERT statements and
  before ``COMMIT`` is issued, in the same atomic transaction that makes the message durable;
* no other writer can commit between that read and this transaction's commit attempt;
* the row must carry the value before ``COMMIT`` runs, so the engine's own commit-completion
  instant is not observable by the application and equality with it is neither provided nor tested.

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
from anonymous.application.ports.model import ModelIdentity, ModelOutput, ModelRequest
from anonymous.application.ports.persistence import SubmissionOutcome
from anonymous.domain.errors import StorageOutcomeUnknown
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from tests.conftest import Services
from tests.dispatching import dispatch
from tests.doubles import BoundStore

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
    store = BoundStore(db_path, clock)
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
    store = BoundStore(db_path, clock)
    run = admit(store, owner, cid).run
    dispatch(store, run.id)  # dispatched at T0
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
    store = BoundStore(db_path, clock)

    class SlowModel:
        identity = ModelIdentity("slow-model", "slow-runtime")

        def generate(self, request: ModelRequest) -> ModelOutput:
            clock.current += timedelta(minutes=30)  # generation takes half an hour
            return ModelOutput("late answer", self.identity)

    outcome = Services(store, SlowModel()).coordinator.submit(
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
    store = BoundStore(db_path, clock)
    real_connect = connect
    monkeypatch.setattr(
        store_module, "connect", lambda path: RecordingConnection(real_connect(path), events)
    )

    outcome = Services(store, _FixedModel()).coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.assistant_message is not None

    transactions: list[list[str]] = []
    for event in events:
        if event == "BEGIN":
            transactions.append([])
        if transactions:
            transactions[-1].append(event)
    writes = [t for t in transactions if "COMMIT" in t]
    # admission, dispatch authorization (T3), handoff marker (T3b), handoff outcome (T3c),
    # publication. T3b/T3c carry no instant and read no clock.
    assert len(writes) == 5
    sampling = [t for t in writes if "CLOCK" in t]
    assert len(sampling) == 3  # admission, dispatch, publication
    for transaction in sampling:
        assert transaction.count("CLOCK") == 1
        clock_at = transaction.index("CLOCK")
        first_write = min(
            transaction.index(kind) for kind in ("INSERT", "UPDATE") if kind in transaction
        )
        assert (
            0 == transaction.index("BEGIN") < clock_at < first_write < transaction.index("COMMIT")
        )
    assert all("CLOCK" not in t for t in writes if t not in sampling)


def test_instant_is_read_before_the_commit_attempt_not_at_commit(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    """The value stored is the one read before the commit attempt, even if time passes after.

    The test clock is advanced by 90 s when COMMIT is issued. This only demonstrates *which*
    reading is stored (the earlier one, taken before the commit attempt) with a controlled clock.
    It is NOT evidence of correspondence with the physical commit-completion instant, and no
    inequality between wall-clock readings is promised for a real, steppable clock.
    """
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
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
    assert outcome.user_message.committed_at != commit_clock_values[0]
    assert outcome.user_message.committed_at == T0  # taken before the delay, as documented


def test_instants_do_not_decrease_with_position_under_a_monotone_clock(
    db_path: Path, owner_and_conversation: tuple[UserId, ConversationId]
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
    coordinator = Services(store, _FixedModel()).coordinator
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


class UncertainCommit(RecordingConnection):
    """Makes the first COMMIT report an error. ``durable`` decides whether it really committed."""

    def __init__(self, inner: object, *, durable: bool, fired: list[str]) -> None:
        super().__init__(inner, [])
        self._durable = durable
        self._fired = fired

    def execute(self, sql: str, *args: object) -> object:
        if sql.strip().upper() == "COMMIT" and not self._fired:
            self._fired.append("fired")
            if self._durable:
                self._inner.execute(sql, *args)  # type: ignore[attr-defined]
            raise sqlite3.OperationalError("injected: commit outcome unknown")
        return self._inner.execute(sql, *args)  # type: ignore[attr-defined]


def _inject_uncertain_commit(monkeypatch: pytest.MonkeyPatch, *, durable: bool) -> None:
    real_connect = connect
    fired: list[str] = []
    monkeypatch.setattr(
        store_module,
        "connect",
        lambda path: UncertainCommit(real_connect(path), durable=durable, fired=fired),
    )


class FailsAfterSampling(RecordingConnection):
    """A statement after the clock read fails definitively, so the transaction cannot commit."""

    def __init__(self, inner: object) -> None:
        super().__init__(inner, [])

    def execute(self, sql: str, *args: object) -> object:
        if sql.lstrip().upper().startswith("INSERT INTO MODEL_RUNS"):
            raise sqlite3.IntegrityError("injected: definite failure before commit")
        return self._inner.execute(sql, *args)  # type: ignore[attr-defined]


def test_a_reading_taken_for_an_attempt_known_not_to_have_committed_is_not_retained(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
    real_connect = connect

    with monkeypatch.context() as patch:
        patch.setattr(store_module, "connect", lambda path: FailsAfterSampling(real_connect(path)))
        with pytest.raises(Exception) as failure:
            admit(store, owner, cid)
    assert not isinstance(failure.value, StorageOutcomeUnknown)  # a known failure, not unknown
    assert clock.reads == 1  # the instant was sampled for the attempt ...
    assert len(store.get_history(owner, cid).messages) == 0  # ... and nothing was persisted with it

    clock.current = T0 + timedelta(hours=1)
    later = admit(store, owner, cid)
    assert later.user_message.committed_at == T0 + timedelta(hours=1)  # its own reading, not T0


def test_uncertain_commit_that_was_durable_keeps_its_original_instant_on_reconciliation(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
    submission = SubmissionId(new_uuid())

    def admit_with(sid: SubmissionId) -> SubmissionOutcome:
        return store.admit_submission(
            owner=owner,
            conversation_id=cid,
            submission_id=sid,
            content="q",
            content_sha256=digest("q"),
        )

    with monkeypatch.context() as patch:
        _inject_uncertain_commit(patch, durable=True)
        with pytest.raises(StorageOutcomeUnknown):  # nothing is presented as confirmed
            admit_with(submission)

    clock.current = T0 + timedelta(hours=1)  # reconciliation happens much later
    replay = admit_with(submission)
    assert replay.replayed
    assert replay.user_message.committed_at == T0  # the originally persisted instant
    assert len(store.get_history(owner, cid).messages) == 1  # no duplicate


def test_uncertain_commit_that_did_not_persist_establishes_nothing_and_a_retry_samples_anew(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
    submission = SubmissionId(new_uuid())

    def admit_with(sid: SubmissionId) -> SubmissionOutcome:
        return store.admit_submission(
            owner=owner,
            conversation_id=cid,
            submission_id=sid,
            content="q",
            content_sha256=digest("q"),
        )

    with monkeypatch.context() as patch:
        _inject_uncertain_commit(patch, durable=False)
        with pytest.raises(StorageOutcomeUnknown):
            admit_with(submission)
    assert len(store.get_history(owner, cid).messages) == 0  # the sampled instant was not retained

    clock.current = T0 + timedelta(hours=1)
    retry = admit_with(submission)
    assert not retry.replayed
    assert retry.user_message.committed_at == T0 + timedelta(hours=1)  # a new, later sample


def test_uncertain_publication_that_was_durable_keeps_the_instant_it_was_sampled_with(
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_and_conversation: tuple[UserId, ConversationId],
) -> None:
    owner, cid = owner_and_conversation
    clock = ControlledClock()
    store = BoundStore(db_path, clock)
    run = admit(store, owner, cid).run
    dispatch(store, run.id)
    clock.current = T0 + timedelta(minutes=3)

    with monkeypatch.context() as patch:
        _inject_uncertain_commit(patch, durable=True)
        with pytest.raises(StorageOutcomeUnknown):
            store.publish_response(run.id, "answer")

    clock.current = T0 + timedelta(days=1)  # whenever the state is next read
    messages = store.get_history(owner, cid).messages
    assert [m.role.value for m in messages] == ["user", "assistant"]
    assert messages[1].committed_at == T0 + timedelta(minutes=3)
    assert messages[0].committed_at == T0
