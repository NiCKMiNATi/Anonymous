"""Application-layer tests over the real SQLite adapter with model/storage test doubles."""

from __future__ import annotations

import sqlite3
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from anonymous.adapters.model.fake import FakeModelAdapter
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.model import ModelIdentity, ModelRequest
from anonymous.domain.errors import (
    ConversationBusy,
    ConversationNotFound,
    IdempotencyConflict,
    InvalidIdentifier,
    InvalidMessage,
    StorageFailure,
    StorageOutcomeUnknown,
)
from anonymous.domain.ids import UserId, new_uuid
from anonymous.domain.models import MessageRole, RunStatus
from tests.conftest import Services
from tests.doubles import (
    START,
    STORAGE_FAILURE,
    STORAGE_UNKNOWN,
    FaultyExecutionStore,
    ManualClock,
    RecordingModel,
    SequenceClock,
    failing_model,
)


def send(services: Services, owner: UserId, cid: str, text: str = "hello", sid: str | None = None):  # type: ignore[no-untyped-def]
    return services.conversations.send_message(owner, cid, sid or new_uuid(), text)


# -- happy path and provenance -----------------------------------------------------------------


def test_send_commits_both_messages_and_links_response_to_its_run(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, RecordingModel("hi back"))
    conversation = services.conversations.create_conversation(owner, "Chat")
    outcome = send(services, owner, conversation.id, "hello")

    assert outcome.replayed is False
    assert outcome.user_message.role is MessageRole.USER and outcome.user_message.position == 1
    assistant = outcome.assistant_message
    assert assistant is not None and assistant.position == 2
    assert assistant.content == "hi back" and assistant.role is MessageRole.ASSISTANT
    assert assistant.produced_by_run_id == outcome.run.id
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert outcome.run.triggering_message_id == outcome.user_message.id
    assert (outcome.run.model_id, outcome.run.runtime_id) == ("test-model-1", "test-runtime-1")

    history = services.conversations.open_conversation(owner, conversation.id)
    assert [m.id for m in history.messages] == [outcome.user_message.id, assistant.id]
    assert history.runs == (outcome.run,)


def test_fake_model_adapter_end_to_end_is_deterministic(store: SqliteStore, owner: UserId) -> None:
    services = Services(store, FakeModelAdapter())
    one = services.conversations.create_conversation(owner)
    two = services.conversations.create_conversation(owner)
    a = send(services, owner, one.id, "hello").assistant_message
    b = send(services, owner, two.id, "hello").assistant_message
    assert a is not None and b is not None
    assert a.content == b.content == "Fake reply to: hello (context messages: 1)"
    follow = send(services, owner, one.id, "again").assistant_message
    assert follow is not None and "context messages: 3" in follow.content


def test_model_receives_constructed_view_of_the_committed_prefix(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel("r")
    services = Services(store, model)
    one = services.conversations.create_conversation(owner)
    other = services.conversations.create_conversation(owner)
    send(services, owner, other.id, "secret from another conversation")
    send(services, owner, one.id, "first")
    send(services, owner, one.id, "second")
    last: ModelRequest = model.requests[-1]
    assert [(m.role, m.content) for m in last.messages] == [
        (MessageRole.USER, "first"),
        (MessageRole.ASSISTANT, "r"),
        (MessageRole.USER, "second"),
    ]


# -- durability ordering ----------------------------------------------------------------------


def test_user_message_and_dispatch_are_durable_before_the_model_runs(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    observed: dict[str, object] = {}

    def inspect(_: ModelRequest) -> None:
        # A different connection and a brand-new store: only committed data is visible.
        fresh = SqliteStore(db_path, ManualClock())
        history = fresh.get_history(owner, conversation_id)
        observed["messages"] = [(m.role, m.content) for m in history.messages]
        observed["run"] = history.runs[0]

    model = RecordingModel("ok", on_generate=inspect)
    services = Services(store, model)
    conversation_id = services.conversations.create_conversation(owner).id
    send(services, owner, conversation_id, "durable first")

    assert observed["messages"] == [(MessageRole.USER, "durable first")]  # no assistant yet
    run = observed["run"]
    assert run.status is RunStatus.IN_FLIGHT  # type: ignore[attr-defined]
    assert (run.model_id, run.runtime_id) == ("test-model-1", "test-runtime-1")  # type: ignore[attr-defined]


def test_model_is_not_invoked_when_admission_cannot_be_saved(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel()
    faulty = FaultyExecutionStore(store)
    faulty.fail_admit = STORAGE_FAILURE
    services = Services(faulty, model)
    conversation = store.create_conversation(owner, None)
    with pytest.raises(StorageFailure):
        send(services, owner, conversation.id)
    assert model.requests == []
    assert store.get_history(owner, conversation.id).messages == ()


def test_model_is_not_invoked_when_dispatch_cannot_be_recorded(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel()
    faulty = FaultyExecutionStore(store)
    faulty.fail_dispatch = STORAGE_FAILURE
    services = Services(faulty, model)
    conversation = store.create_conversation(owner, None)
    outcome = send(services, owner, conversation.id)
    assert model.requests == []
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "dispatch_not_recorded"
    assert outcome.assistant_message is None
    assert len(store.get_history(owner, conversation.id).messages) == 1  # user message kept


# -- ordering and time ------------------------------------------------------------------------


def test_order_is_server_assigned_even_when_instants_are_equal_or_decreasing(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    # Instants: equal for the first three commits, then going BACKWARDS.
    instants = [START, START, START, START, START, START - timedelta(days=1)]
    clocked = SqliteStore(db_path, SequenceClock(instants))
    services = Services(clocked, RecordingModel("r"))
    conversation = services.conversations.create_conversation(owner)
    first = send(services, owner, conversation.id, "q1")
    second = send(services, owner, conversation.id, "q2")

    history = services.conversations.open_conversation(owner, conversation.id)
    assert [m.position for m in history.messages] == [1, 2, 3, 4]
    assert [m.content for m in history.messages] == ["q1", "r", "q2", "r"]
    committed = [m.committed_at for m in history.messages]
    assert committed != sorted(committed)  # time order disagrees with authoritative order
    assert first.assistant_message is not None and second.assistant_message is not None
    assert second.assistant_message.committed_at < first.user_message.committed_at


def test_commit_instant_is_absolute_and_unchanged_by_reads_and_retries(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, RecordingModel())
    conversation = services.conversations.create_conversation(owner)
    sid = new_uuid()
    original = send(services, owner, conversation.id, "hello", sid)
    for _ in range(3):
        again = send(services, owner, conversation.id, "hello", sid)
        assert again.user_message.committed_at == original.user_message.committed_at
    reread = services.conversations.open_conversation(owner, conversation.id).messages[0]
    assert reread.committed_at == original.user_message.committed_at
    assert reread.committed_at.tzinfo is not None
    assert reread.committed_at.utcoffset() == timedelta(0)


# -- failure behavior --------------------------------------------------------------------------


def test_model_failure_preserves_user_message_and_fabricates_no_response(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, failing_model())
    conversation = services.conversations.create_conversation(owner)
    outcome = send(services, owner, conversation.id, "will fail")
    assert outcome.assistant_message is None
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "boom_code"
    assert outcome.run.failure_message == "Simulated runtime failure."
    history = services.conversations.open_conversation(owner, conversation.id)
    assert [(m.role, m.content) for m in history.messages] == [(MessageRole.USER, "will fail")]
    assert history.runs[0].status is RunStatus.FAILED
    # The conversation is not left blocked: a later message is admitted.
    ok = Services(store, RecordingModel("fine"))
    assert send(ok, owner, conversation.id, "next").assistant_message is not None


def test_unexpected_adapter_exception_is_contained_and_not_leaked(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel(error=RuntimeError("secret detail: /home/user/model.bin"))
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    outcome = send(services, owner, conversation.id)
    assert outcome.run.status is RunStatus.FAILED and outcome.run.failure_code == "runtime_error"
    assert "secret" not in (outcome.run.failure_message or "")
    assert outcome.assistant_message is None


@pytest.mark.parametrize("reply", ["", "   \n"])
def test_empty_model_output_is_a_failure_not_an_empty_assistant_message(
    store: SqliteStore, owner: UserId, reply: str
) -> None:
    services = Services(store, RecordingModel(reply))
    conversation = services.conversations.create_conversation(owner)
    outcome = send(services, owner, conversation.id)
    assert outcome.run.failure_code == "empty_output" and outcome.assistant_message is None


def test_output_from_a_different_model_than_dispatched_is_refused(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel(output_identity=ModelIdentity("other-model", "test-runtime-1"))
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    outcome = send(services, owner, conversation.id)
    assert outcome.run.failure_code == "runtime_identity_mismatch"
    assert outcome.assistant_message is None


def test_save_failure_after_generation_is_recorded_as_failed_without_assistant_message(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.fail_publish = STORAGE_FAILURE
    services = Services(faulty, RecordingModel("lost output"))
    conversation = services.conversations.create_conversation(owner)
    outcome = send(services, owner, conversation.id, "q")
    assert outcome.assistant_message is None
    assert outcome.run.failure_code == "response_not_saved"
    history = store.get_history(owner, conversation.id)
    assert [m.role for m in history.messages] == [MessageRole.USER]
    assert history.runs[0].status is RunStatus.FAILED


def test_unknown_save_outcome_is_reported_as_unknown_and_reconciled_by_replay(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.fail_publish = STORAGE_UNKNOWN
    model = RecordingModel("maybe saved")
    services = Services(faulty, model)
    conversation = services.conversations.create_conversation(owner)
    sid = new_uuid()
    with pytest.raises(StorageOutcomeUnknown):
        send(services, owner, conversation.id, "q", sid)

    # Nothing is claimed: the run is still unsettled and the conversation stays closed.
    history = store.get_history(owner, conversation.id)
    assert history.runs[0].status is RunStatus.IN_FLIGHT
    with pytest.raises(ConversationBusy):
        send(services, owner, conversation.id, "another")

    # Reconciliation by replay reports the real state and never runs inference again.
    replay = send(services, owner, conversation.id, "q", sid)
    assert replay.replayed and replay.run.status is RunStatus.IN_FLIGHT
    assert len(model.requests) == 1


def test_failure_that_cannot_be_recorded_is_not_hidden(store: SqliteStore, owner: UserId) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.fail_settle = STORAGE_FAILURE
    services = Services(faulty, failing_model())
    conversation = services.conversations.create_conversation(owner)
    with pytest.raises(StorageFailure):
        send(services, owner, conversation.id)
    assert store.get_history(owner, conversation.id).runs[0].status is RunStatus.IN_FLIGHT


@pytest.mark.skipif(
    hasattr(__import__("os"), "geteuid") and __import__("os").geteuid() == 0,
    reason="root ignores file permissions",
)
def test_real_storage_failure_on_a_read_only_database_saves_nothing(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    model = RecordingModel()
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    send(services, owner, conversation.id, "before")
    # Make the database unwritable for new connections.
    paths = [p for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")) if p.exists()]
    for p in paths:
        p.chmod(0o444)
    try:
        calls = len(model.requests)
        with pytest.raises(StorageFailure):
            send(services, owner, conversation.id, "during outage")
        assert len(model.requests) == calls  # no inference without a durable user message
    finally:
        for p in paths:
            p.chmod(0o644)
    texts = [m.content for m in store.get_history(owner, conversation.id).messages]
    assert "during outage" not in texts and texts[0] == "before"


# -- validation and identifiers ---------------------------------------------------------------


def test_invalid_input_never_reaches_storage_or_model(store: SqliteStore, owner: UserId) -> None:
    model = RecordingModel()
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    for bad in ["", "   ", "\n"]:
        with pytest.raises(InvalidMessage):
            send(services, owner, conversation.id, bad)
    with pytest.raises(InvalidIdentifier):
        services.conversations.send_message(owner, conversation.id, "not-a-uuid", "hi")
    with pytest.raises(InvalidIdentifier):
        send(services, owner, "not-a-uuid")
    with pytest.raises(InvalidIdentifier):
        services.conversations.open_conversation(owner, "../etc/passwd")
    assert model.requests == []
    assert services.conversations.open_conversation(owner, conversation.id).messages == ()


def test_missing_conversation(store: SqliteStore, owner: UserId) -> None:
    services = Services(store, RecordingModel())
    with pytest.raises(ConversationNotFound):
        send(services, owner, new_uuid())
    with pytest.raises(ConversationNotFound):
        services.conversations.open_conversation(owner, new_uuid())


# -- idempotency, busy admission, recovery ----------------------------------------------------


def test_retransmitted_submission_creates_no_duplicates_and_no_second_run(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel("once")
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    sid = new_uuid()
    first = send(services, owner, conversation.id, "hello", sid)
    second = send(services, owner, conversation.id, "hello", sid)
    assert second.replayed and not first.replayed
    assert second.user_message == first.user_message
    assert second.run == first.run and second.assistant_message == first.assistant_message
    assert len(model.requests) == 1
    history = services.conversations.open_conversation(owner, conversation.id)
    assert len(history.messages) == 2 and len(history.runs) == 1


def test_same_text_with_a_new_submission_id_is_a_new_message(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, RecordingModel())
    conversation = services.conversations.create_conversation(owner)
    send(services, owner, conversation.id, "hello")
    send(services, owner, conversation.id, "hello")
    assert len(services.conversations.open_conversation(owner, conversation.id).messages) == 4


def test_reusing_a_submission_id_for_different_content_is_refused_and_changes_nothing(
    store: SqliteStore, owner: UserId
) -> None:
    services = Services(store, RecordingModel())
    conversation = services.conversations.create_conversation(owner)
    sid = new_uuid()
    send(services, owner, conversation.id, "original", sid)
    before = services.conversations.open_conversation(owner, conversation.id)
    with pytest.raises(IdempotencyConflict):
        send(services, owner, conversation.id, "changed", sid)
    assert services.conversations.open_conversation(owner, conversation.id) == before


def test_replaying_a_failed_submission_returns_the_failure_without_a_new_run(
    store: SqliteStore, owner: UserId
) -> None:
    model = failing_model()
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    sid = new_uuid()
    first = send(services, owner, conversation.id, "q", sid)
    again = send(services, owner, conversation.id, "q", sid)
    assert again.replayed and again.run == first.run and again.run.status is RunStatus.FAILED
    assert len(model.requests) == 1  # no implicit retry of a failed attempt


def test_second_send_while_generating_is_refused_not_queued(
    store: SqliteStore, owner: UserId
) -> None:
    entered, release = threading.Event(), threading.Event()

    def block(_: ModelRequest) -> None:
        entered.set()
        assert release.wait(10)

    model = RecordingModel("slow", on_generate=block)
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    results: list[object] = []
    first = threading.Thread(
        target=lambda: results.append(send(services, owner, conversation.id, "first"))
    )
    first.start()
    try:
        assert entered.wait(10)
        with pytest.raises(ConversationBusy):
            send(services, owner, conversation.id, "second")
        # A retransmission of the in-progress submission is resolved, not treated as new work.
        history = services.conversations.open_conversation(owner, conversation.id)
        assert [m.content for m in history.messages] == ["first"]
        assert history.runs[0].status is RunStatus.IN_FLIGHT
    finally:
        release.set()
        first.join(10)
    assert len(results) == 1
    history = services.conversations.open_conversation(owner, conversation.id)
    assert [m.content for m in history.messages] == ["first", "slow"]  # "second" never appended
    assert len(model.requests) == 1


def test_simultaneous_sends_admit_exactly_one(store: SqliteStore, owner: UserId) -> None:
    barrier = threading.Barrier(2)
    model = RecordingModel("r")
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    outcomes: list[object] = []

    def attempt(text: str) -> None:
        barrier.wait(10)
        try:
            outcomes.append(send(services, owner, conversation.id, text))
        except ConversationBusy as error:
            outcomes.append(error)
        except Exception as error:  # surfaced below
            outcomes.append(error)

    threads = [threading.Thread(target=attempt, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    # Either one wins outright and the other is refused, or the first fully settled before the
    # second was considered (then both are legitimately admitted in server order).
    busy = [o for o in outcomes if isinstance(o, ConversationBusy)]
    other_errors = [o for o in outcomes if isinstance(o, Exception) and o not in busy]
    assert other_errors == []
    history = services.conversations.open_conversation(owner, conversation.id)
    assert [m.position for m in history.messages] == list(range(1, len(history.messages) + 1))
    assert len(history.messages) == 2 * (len(outcomes) - len(busy))
    assert all(r.status is RunStatus.SUCCEEDED for r in history.runs)


def test_restart_leaves_unresolved_work_closed_and_never_replays_it(
    db_path: Path, owner: UserId, store: SqliteStore
) -> None:
    model = RecordingModel()
    services = Services(store, model)
    conversation = services.conversations.create_conversation(owner)
    admitted = store.admit_submission(
        owner=owner,
        conversation_id=conversation.id,
        submission_id=new_uuid(),  # type: ignore[arg-type]
        content="interrupted",
        content_sha256="x",
    )
    store.record_dispatch(admitted.run.id, "test-model-1", "test-runtime-1")

    restarted = SqliteStore(db_path, ManualClock())  # "process restart"
    report = restarted.recover_unsettled_runs()
    assert report.marked_indeterminate == 1
    restarted_services = Services(restarted, model)
    with pytest.raises(ConversationBusy):
        send(restarted_services, owner, conversation.id, "new")
    history = restarted_services.conversations.open_conversation(owner, conversation.id)
    assert history.runs[0].status is RunStatus.INDETERMINATE
    assert [m.content for m in history.messages] == ["interrupted"]
    assert model.requests == []  # recovery never re-invokes the model


def test_sqlite_error_type_never_leaks_through_storage_failures(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE submissions")  # sabotage the schema
    conn.commit()
    conn.close()
    services = Services(store, RecordingModel())
    conversation = services.conversations.create_conversation(owner)
    with pytest.raises(StorageFailure) as caught:
        send(services, owner, conversation.id)
    assert "sqlite" not in caught.value.public_message.lower()
    assert "submissions" not in caught.value.public_message
