"""The 0B-1 lifecycle under failures injected at the real SQLite COMMIT (remediation finding 3).

Faults are injected through the real connection (``tests/commit_faults.py``), not at a service or
store method: a statement that fails (known rollback), a COMMIT that never happens (unknown, not
durable) and a COMMIT that happens but is not acknowledged (unknown, durable). For every lifecycle
write the tests assert the same few things:

* a durable success is preserved and never repeated; a rolled-back write is not assumed;
* an unknown outcome is resolved by *reading*, never by invoking the runtime again;
* the instants and provenance that were durably recorded are the ones read back later;
* replay is idempotent and the history has no duplicate message;
* the execution slot is released only when a settlement was durably committed on admissible
  evidence, and never otherwise.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import astuple

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.model import ProbeKind, ProbeResult
from anonymous.application.ports.persistence import SubmissionOutcome
from anonymous.domain.errors import ConversationBusy, RuntimeQuarantined, StorageOutcomeUnknown
from anonymous.domain.evidence import EvidenceBasis, Handoff, HandoffOutcome, LifetimeScope
from anonymous.domain.ids import ConversationId, RunId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import ModelRun, RunStatus
from tests.application.test_reconcile import orphan
from tests.commit_faults import (
    AFTER_COMMIT,
    BEFORE_COMMIT,
    STATEMENT,
    CommitFaultPlan,
    faulting_commits,
)
from tests.conftest import Services

B = EvidenceBasis


def send(
    services: Services, owner: UserId, cid: ConversationId, sid: str | None = None
) -> SubmissionOutcome:
    return services.coordinator.submit(
        owner=owner,
        conversation_id=cid,
        submission_id=SubmissionId(sid or new_uuid()),
        content="q",
    )


def roles(store: SqliteStore, owner: UserId, cid: ConversationId) -> list[str]:
    return [m.role.value for m in store.get_history(owner, cid).messages]


def run_of(store: SqliteStore, owner: UserId, cid: ConversationId, index: int = 0) -> ModelRun:
    return store.get_history(owner, cid).runs[index]


def frozen(run: ModelRun) -> tuple[object, ...]:
    """Every durable field of a run, for "nothing changed" comparisons."""
    return astuple(run)


@pytest.fixture
def faults(monkeypatch: pytest.MonkeyPatch) -> Iterator[CommitFaultPlan]:
    with faulting_commits(monkeypatch) as plan:
        yield plan


@pytest.fixture
def system(store: SqliteStore, owner: UserId) -> tuple[Services, ScriptedRuntime, ConversationId]:
    runtime = ScriptedRuntime()
    services = Services(store, runtime)
    return services, runtime, services.conversations.create_conversation(owner).id


# -- T1: admission -------------------------------------------------------------------------------


def test_admission_commit_that_failed_before_durability_saves_nothing_and_can_be_resent(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    sid = new_uuid()
    faults.arm("admit_submission", BEFORE_COMMIT)
    with pytest.raises(StorageOutcomeUnknown):
        send(services, owner, cid, sid)
    assert roles(store, owner, cid) == [] and store.get_history(owner, cid).runs == ()
    assert runtime.calls == []  # nothing was prepared, authorized or invoked
    resent = send(services, owner, cid, sid)  # the same submission id: nothing durable existed
    assert resent.replayed is False and resent.run.status is RunStatus.SUCCEEDED
    assert roles(store, owner, cid) == ["user", "assistant"]
    assert len(runtime.calls_of("start")) == 1


@pytest.mark.parametrize("recovered_by", ["next_request", "restart"])
def test_admission_commit_that_was_durable_is_preserved_never_dispatched_and_recovered(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
    recovered_by: str,
) -> None:
    services, runtime, cid = system
    sid = new_uuid()
    faults.arm("admit_submission", AFTER_COMMIT)
    with pytest.raises(StorageOutcomeUnknown):  # the caller cannot know ...
        send(services, owner, cid, sid)
    first_user = store.get_history(owner, cid).messages[0]
    assert roles(store, owner, cid) == ["user"]  # ... but it is durable
    pending = run_of(store, owner, cid)
    assert pending.status is RunStatus.PENDING and runtime.calls == []

    replay = send(services, owner, cid, sid)  # replay returns the original, creates nothing
    assert replay.replayed is True
    assert replay.user_message == first_user  # same id and instant
    assert roles(store, owner, cid) == ["user"] and runtime.calls == []

    if recovered_by == "restart":
        successor_runtime = ScriptedRuntime()
        revived = Services(store, successor_runtime, boot_id="boot-after-crash")
        assert revived.coordinator.startup().pending_settled == 1
        follow_up = send(revived, owner, cid)
        assert len(successor_runtime.calls_of("start")) == 1
    else:
        follow_up = send(services, owner, cid)  # the request itself reconciles the orphan first
        assert len(runtime.calls_of("start")) == 1
    settled = run_of(store, owner, cid)
    assert (
        settled.status is RunStatus.FAILED and settled.failure_code == "interrupted_before_dispatch"
    )
    assert settled.termination_basis is B.NEVER_DISPATCHED
    assert follow_up.run.status is RunStatus.SUCCEEDED
    assert roles(store, owner, cid) == ["user", "user", "assistant"]  # no duplicate of the first


@pytest.mark.parametrize("table", ["messages", "model_runs", "submissions"])
def test_a_failing_admission_statement_rolls_back_every_fact_and_is_a_known_failure(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
    db_path: object,
    table: str,
) -> None:
    from anonymous.domain.errors import StorageFailure

    services, runtime, cid = system
    rule = faults.arm("admit_submission", STATEMENT, pattern=f"INSERT INTO {table}")
    with pytest.raises(StorageFailure) as raised:
        send(services, owner, cid)
    assert not isinstance(raised.value, StorageOutcomeUnknown)  # known: it was rolled back
    assert rule.fired
    assert roles(store, owner, cid) == [] and store.get_history(owner, cid).runs == ()
    conn = sqlite3.connect(str(db_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0
    finally:
        conn.close()
    assert runtime.calls == []
    assert send(services, owner, cid).run.status is RunStatus.SUCCEEDED


# -- T3 / T3b / T3c: dispatch and handoff ----------------------------------------------------------


def test_dispatch_authorization_that_failed_before_durability_never_invokes_the_runtime(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("authorize_dispatch", BEFORE_COMMIT)
    with pytest.raises(StorageOutcomeUnknown):
        send(services, owner, cid)
    run = run_of(store, owner, cid)
    assert run.status is RunStatus.PENDING and run.slot_id is None  # the slot was never taken
    assert [c.operation for c in runtime.calls if c.operation != "prepare"] == []
    assert store.generation_state().quarantined_runs == ()
    report = services.coordinator.reconcile()  # the orphan is provably never dispatched (B1)
    assert report.pending_settled == 1
    settled = run_of(store, owner, cid)
    assert settled.status is RunStatus.FAILED and settled.termination_basis is B.NEVER_DISPATCHED
    assert send(services, owner, cid).run.status is RunStatus.SUCCEEDED
    assert roles(store, owner, cid) == ["user", "user", "assistant"]


def test_dispatch_statement_failure_is_a_known_rollback_settled_as_never_dispatched(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    rule = faults.arm("authorize_dispatch", STATEMENT, pattern="UPDATE model_runs")
    outcome = send(services, owner, cid)
    assert rule.fired
    run = run_of(store, owner, cid)
    assert outcome.assistant_message is None
    assert run.status is RunStatus.FAILED and run.failure_code == "dispatch_not_recorded"
    assert run.termination_basis is B.NEVER_DISPATCHED and run.slot_id is None
    assert [c.operation for c in runtime.calls if c.operation != "prepare"] == []


def test_handoff_marker_statement_failure_never_calls_start_and_reconcile_settles_b1(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    from anonymous.domain.errors import StorageFailure

    services, runtime, cid = system
    rule = faults.arm("mark_handoff_started", STATEMENT, pattern="UPDATE model_runs")
    with pytest.raises(StorageFailure):  # a known rollback, reported as such
        send(services, owner, cid)
    assert rule.fired
    run = run_of(store, owner, cid)
    assert run.status is RunStatus.IN_FLIGHT and run.handoff is Handoff.NONE  # authorized only
    assert runtime.calls_of("start") == []
    report = services.coordinator.reconcile()  # no worker is live: durable NONE proves B1
    assert report.settled == 1
    settled = run_of(store, owner, cid)
    assert settled.status is RunStatus.FAILED and settled.termination_basis is B.NEVER_DISPATCHED
    assert runtime.calls_of("start") == [] and store.generation_state().quarantined_runs == ()
    assert send(services, owner, cid).run.status is RunStatus.SUCCEEDED


def test_dispatch_authorization_that_was_durable_is_recognized_and_invoked_exactly_once(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("authorize_dispatch", AFTER_COMMIT)
    outcome = send(services, owner, cid)
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 1  # the unacknowledged T3 was not re-won or repeated
    run = run_of(store, owner, cid)
    # Provenance, binding and boot recorded by the one durable T3 are what is read back.
    assert run.model_id == "scripted-model" and run.runtime_id == "scripted-runtime"
    assert run.provenance is not None and run.binding is not None
    assert run.execution_boot_id == services.boot_id and run.slot_id is not None
    assert run.dispatched_at is not None and run.configuration_digest is not None
    assert roles(store, owner, cid) == ["user", "assistant"]


def test_handoff_marker_that_failed_before_durability_never_calls_start(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("mark_handoff_started", BEFORE_COMMIT)
    outcome = send(services, owner, cid)
    run = run_of(store, owner, cid)
    assert runtime.calls_of("start") == [] and runtime.calls_of("await_result") == []
    assert outcome.assistant_message is None
    assert run.status is RunStatus.FAILED and run.handoff is Handoff.NONE
    assert run.termination_basis is B.NEVER_DISPATCHED  # durable proof: no handoff was recorded
    assert store.generation_state().quarantined_runs == ()  # settled, so the slot is free
    assert roles(store, owner, cid) == ["user"]
    assert send(services, owner, cid).run.status is RunStatus.SUCCEEDED


def test_handoff_marker_that_was_durable_is_recognized_and_start_is_called_once(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("mark_handoff_started", AFTER_COMMIT)
    outcome = send(services, owner, cid)
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 1 and len(runtime.calls_of("await_result")) == 1
    assert run_of(store, owner, cid).handoff is Handoff.STARTED


@pytest.mark.parametrize(
    ("point", "recorded"),
    [(BEFORE_COMMIT, None), (AFTER_COMMIT, HandoffOutcome.ACCEPTED)],
)
def test_handoff_outcome_is_best_effort_and_never_changes_the_result(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
    point: str,
    recorded: HandoffOutcome | None,
) -> None:
    services, runtime, cid = system
    faults.arm("record_handoff_outcome", point)
    outcome = send(services, owner, cid)
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 1
    run = run_of(store, owner, cid)
    assert run.handoff_outcome is recorded  # an unrecorded outcome stays conservatively unknown
    assert roles(store, owner, cid) == ["user", "assistant"]


# -- T4: publication -------------------------------------------------------------------------------


def test_publication_that_failed_before_durability_is_published_again_once(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("publish_response", BEFORE_COMMIT)
    outcome = send(services, owner, cid)
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert faults.fired("publish_response", BEFORE_COMMIT) == 1
    assert len(runtime.calls_of("start")) == 1  # the model was NOT invoked again to re-publish
    assert roles(store, owner, cid) == ["user", "assistant"]  # exactly one response
    assert run_of(store, owner, cid).termination_basis is B.RUNTIME_REPORTED_TERMINAL


def test_publication_that_was_durable_preserves_the_success_and_its_instants(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("publish_response", AFTER_COMMIT)
    outcome = send(services, owner, cid)
    assert outcome.run.status is RunStatus.SUCCEEDED and outcome.assistant_message is not None
    history = store.get_history(owner, cid)
    stored = (history.messages[1], history.runs[0])
    # Replays and a reconcile return and leave exactly what was durably written.
    assert send(services, owner, cid, None) is not None  # a new message is a new, separate turn
    services.coordinator.reconcile()
    again = store.get_history(owner, cid)
    assert (again.messages[1], again.runs[0]) == stored
    assert [m.role.value for m in again.messages][:2] == ["user", "assistant"]
    assert len(runtime.calls_of("start")) == 2  # one per turn, none for the repeated publication


def test_repeated_unknown_publication_ends_in_b3_settlement_without_a_second_invocation(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    rule = faults.arm("publish_response", BEFORE_COMMIT, repeat=True)  # every attempt is unknown
    outcome = send(services, owner, cid)
    assert rule.seen == 3  # bounded: exactly ``republish_attempts``
    run = run_of(store, owner, cid)
    assert outcome.assistant_message is None
    assert run.status is RunStatus.FAILED and run.failure_code == "response_not_saved"
    assert run.termination_basis is B.RUNTIME_REPORTED_TERMINAL  # B3: the bound instance delivered
    assert run.closed_at is not None and run.settled_at is not None
    assert roles(store, owner, cid) == ["user"]
    assert len(runtime.calls_of("start")) == 1
    assert store.generation_state().quarantined_runs == ()  # settled on evidence: the slot is free
    faults._rules.clear()
    retried = services.coordinator.retry(
        owner=owner,
        conversation_id=cid,
        retry_id=new_uuid(),
        message_id=store.get_history(owner, cid).messages[0].id,
    )
    assert retried.run.status is RunStatus.SUCCEEDED
    assert roles(store, owner, cid) == ["user", "assistant"]  # the retry reused the user message


def test_publication_statement_failure_rolls_back_and_leaves_no_orphan_message(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    # The second statement of publication (the run update) fails every time: the message insert
    # of the same transaction must disappear with it.
    faults.arm("publish_response", STATEMENT, pattern="UPDATE model_runs", repeat=True)
    outcome = send(services, owner, cid)
    run = run_of(store, owner, cid)
    assert outcome.assistant_message is None
    assert run.status is RunStatus.FAILED and run.failure_code == "response_not_saved"
    assert roles(store, owner, cid) == ["user"]  # no assistant message without its run
    assert run.termination_basis is B.RUNTIME_REPORTED_TERMINAL
    assert len(runtime.calls_of("start")) == 1


def test_unknown_publication_with_an_unreadable_store_is_undetermined_and_changes_nothing_more(
    store: SqliteStore,
    owner: UserId,
    system: tuple[Services, ScriptedRuntime, ConversationId],
    faults: CommitFaultPlan,
) -> None:
    services, runtime, cid = system
    faults.arm("publish_response", AFTER_COMMIT)  # case C: the write landed, nobody can tell
    faults.arm("get_run", STATEMENT, pattern="BEGIN", nth=2)  # the read-back fails once
    with pytest.raises(StorageOutcomeUnknown):
        send(services, owner, cid)
    assert faults.fired("get_run", STATEMENT) == 1
    run = run_of(store, owner, cid)  # the truth: the response was committed
    assert run.status is RunStatus.SUCCEEDED and roles(store, owner, cid) == ["user", "assistant"]
    assert len(runtime.calls_of("start")) == 1
    before = frozen(run)
    services.coordinator.reconcile()
    assert frozen(run_of(store, owner, cid)) == before  # nothing re-run or rewritten


# -- T5: failure settlement ------------------------------------------------------------------------


def failing(runtime: ScriptedRuntime) -> ScriptedRuntime:
    runtime.reply = ""  # a known failure from the bound instance: ``empty_output`` (B3)
    return runtime


def baseline_version(store: SqliteStore, owner: UserId) -> int:
    """``state_version`` of the same failure with no fault: the number of writes it takes."""
    services = Services(store, failing(ScriptedRuntime()))
    cid = services.conversations.create_conversation(owner).id
    send(services, owner, cid)
    return run_of(store, owner, cid).state_version


def test_failure_settlement_that_failed_before_durability_is_applied_again_exactly_once(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    baseline = baseline_version(store, owner)
    runtime = failing(ScriptedRuntime())
    services = Services(store, runtime)
    cid = services.conversations.create_conversation(owner).id
    faults.arm("settle_in_flight", BEFORE_COMMIT)
    outcome = send(services, owner, cid)
    run = run_of(store, owner, cid)
    assert faults.fired("settle_in_flight", BEFORE_COMMIT) == 1
    assert outcome.run.status is RunStatus.FAILED
    assert (
        run.failure_code == "empty_output" and run.termination_basis is B.RUNTIME_REPORTED_TERMINAL
    )
    assert run.state_version == baseline  # one settlement write landed, not two
    assert len(runtime.calls_of("start")) == 1 and roles(store, owner, cid) == ["user"]


def test_failure_settlement_that_was_durable_is_recognized_not_repeated(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    baseline = baseline_version(store, owner)
    runtime = failing(ScriptedRuntime())
    services = Services(store, runtime)
    cid = services.conversations.create_conversation(owner).id
    faults.arm("settle_in_flight", AFTER_COMMIT)
    outcome = send(services, owner, cid)
    run = run_of(store, owner, cid)
    assert outcome.run.status is RunStatus.FAILED  # the real outcome
    assert run.state_version == baseline and run.settled_at is not None
    settled = frozen(run)
    services.coordinator.reconcile()
    assert frozen(run_of(store, owner, cid)) == settled  # idempotent: nothing rewritten
    assert len(runtime.calls_of("start")) == 1


def test_failure_settlement_that_never_lands_holds_the_slot_until_evidence_exists(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    runtime = failing(ScriptedRuntime())
    services = Services(store, runtime, boot_id="boot-1")
    cid = services.conversations.create_conversation(owner).id
    faults.arm("settle_in_flight", BEFORE_COMMIT, repeat=True)
    with pytest.raises(StorageOutcomeUnknown):  # bounded attempts, then it is reported honestly
        send(services, owner, cid)
    stuck = run_of(store, owner, cid)
    assert stuck.status is RunStatus.IN_FLIGHT and stuck.termination_basis is None
    other = store.create_conversation(owner, None).id
    with pytest.raises(ConversationBusy):
        send(services, owner, cid)
    assert len(runtime.calls_of("start")) == 1  # nothing was re-invoked

    faults._rules.clear()
    # Same boot: a reconcile cannot treat the guard as evidence, so the run is quarantined —
    # the slot is NOT released on a guess.
    same_boot = services.coordinator.reconcile()
    assert same_boot.still_unresolved == 1
    assert run_of(store, owner, cid).status is RunStatus.INDETERMINATE
    with pytest.raises(RuntimeQuarantined):
        send(services, owner, other)
    # A later boot holding the exclusive guard IS evidence (B4) for an owning-process binding.
    revived = Services(store, ScriptedRuntime(), boot_id="boot-2")
    assert revived.coordinator.startup().settled == 1
    settled = run_of(store, owner, cid)
    assert (
        settled.status is RunStatus.FAILED and settled.termination_basis is B.PROCESS_EXIT_VERIFIED
    )
    assert send(revived, owner, other).run.status is RunStatus.SUCCEEDED


# -- T6 / T7: quarantine and its release -----------------------------------------------------------


def external_quarantine(
    store: SqliteStore, owner: UserId
) -> tuple[ConversationId, RunId, Services]:
    cid, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    first = Services(store, ScriptedRuntime(scope=LifetimeScope.EXTERNAL), boot_id="boot-2")
    assert first.coordinator.startup().still_unresolved == 1
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE
    evidence = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    evidence.instance_ref = "instance-1"  # the persisted binding's instance
    evidence.probe_default = ProbeResult(ProbeKind.CONFIRMED_ENDED, B.PROCESS_EXIT_VERIFIED)
    return cid, run_id, Services(store, evidence, boot_id="boot-3")


def test_t7_that_failed_before_durability_is_applied_once_without_releasing_early(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    _, run_id, actor = external_quarantine(store, owner)
    version = store.get_run(run_id).state_version
    faults.arm("settle_indeterminate", BEFORE_COMMIT)
    report = actor.coordinator.reconcile()
    assert faults.fired("settle_indeterminate", BEFORE_COMMIT) == 1
    run = store.get_run(run_id)
    assert report.settled == 1 and run.status is RunStatus.FAILED
    assert run.termination_basis is B.PROCESS_EXIT_VERIFIED
    assert run.state_version == version + 1  # exactly one T7 landed
    assert store.generation_state().quarantined_runs == ()
    assert actor.coordinator.reconcile().examined == 0  # idempotent


def test_t7_that_was_durable_is_recognized_and_the_release_happens_once(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    cid, run_id, actor = external_quarantine(store, owner)
    version = store.get_run(run_id).state_version
    faults.arm("settle_indeterminate", AFTER_COMMIT)
    report = actor.coordinator.reconcile()
    run = store.get_run(run_id)
    assert report.settled == 1 and run.status is RunStatus.FAILED
    assert run.state_version == version + 1  # the retry saw a terminal run and wrote nothing
    settled = frozen(run)
    assert actor.coordinator.reconcile().examined == 0
    assert frozen(store.get_run(run_id)) == settled
    assert send(actor, owner, cid).run.status is RunStatus.SUCCEEDED


def test_t7_that_never_lands_keeps_the_quarantine_and_a_later_reconcile_settles(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan
) -> None:
    cid, run_id, actor = external_quarantine(store, owner)
    faults.arm("settle_indeterminate", BEFORE_COMMIT, repeat=True)
    report = actor.coordinator.reconcile()  # contained: the fault does not escape reconcile
    assert report.settled == 0 and report.still_unresolved == 1
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE
    assert store.generation_state().quarantined_runs == (run_id,)  # the slot is still held
    with pytest.raises(RuntimeQuarantined):  # in any other conversation
        send(actor, owner, store.create_conversation(owner, None).id)
    faults._rules.clear()
    assert actor.coordinator.reconcile().settled == 1
    assert store.get_run(run_id).status is RunStatus.FAILED
    assert send(actor, owner, cid).run.status is RunStatus.SUCCEEDED


@pytest.mark.parametrize("point", [BEFORE_COMMIT, AFTER_COMMIT])
def test_quarantining_commit_with_an_unknown_outcome_never_releases_the_slot(
    store: SqliteStore, owner: UserId, faults: CommitFaultPlan, point: str
) -> None:
    _, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    services = Services(store, ScriptedRuntime(scope=LifetimeScope.EXTERNAL), boot_id="boot-2")
    faults.arm("mark_indeterminate", point)
    report = (
        services.coordinator.startup()
    )  # contained: startup does not fail on one unknown commit
    assert report.still_unresolved == 1 and report.settled == 0
    run = store.get_run(run_id)
    assert run.status in (RunStatus.IN_FLIGHT, RunStatus.INDETERMINATE)  # closed, never settled
    assert run.closed_at is not None and run.termination_basis is None
    assert store.generation_state().quarantined_runs or run.status is RunStatus.IN_FLIGHT
    with pytest.raises((ConversationBusy, RuntimeQuarantined)):
        send(services, owner, store.create_conversation(owner, None).id)
    faults._rules.clear()
    services.coordinator.reconcile()
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE  # converged; still held
