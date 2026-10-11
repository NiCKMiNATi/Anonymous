"""Invocation handoff, closure, stop and publication under controlled scheduling (LD-04 §4).

Every interleaving is forced with named checkpoints and gates, not with sleeps used as proof. The
scripted runtime records exactly which external calls were made and with which instance identity,
so each test can assert both *what reached the runtime* and *in what order*.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import replace

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.model import (
    Failed,
    Knowledge,
    ProbeKind,
    ProbeResult,
    StartAck,
)
from anonymous.application.worker import ExecutionHandle
from anonymous.domain.errors import StorageOutcomeUnknown
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    LifetimeScope,
)
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import MessageRole, RunStatus
from tests.conftest import FAST, Services
from tests.doubles import Fault, FaultyExecutionStore, Scheduler


def start_run(
    services: Services, owner: UserId, cid: ConversationId, text: str = "q"
) -> ExecutionHandle:
    return services.coordinator.begin_submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content=text
    )


def in_thread(call: Callable[[], object]) -> tuple[threading.Thread, list[object]]:
    box: list[object] = []
    thread = threading.Thread(target=lambda: box.append(call()), daemon=True)
    thread.start()
    return thread, box


def operations(runtime: ScriptedRuntime) -> list[str]:
    return [c.operation for c in runtime.calls]


def fixture(real_store: SqliteStore, owner: UserId, **kw):  # type: ignore[no-untyped-def]
    runtime = kw.pop("runtime", None) or ScriptedRuntime()
    scheduler = Scheduler()
    wrapped = kw.pop("store", real_store)
    services = Services(wrapped, runtime, checkpoint=scheduler, **kw)
    cid = services.conversations.create_conversation(owner).id
    return services, runtime, scheduler, cid


# -- problem B: external handoff versus closure --------------------------------------------------


def test_closure_waits_for_a_paused_invoker_and_start_precedes_the_closure(
    store: SqliteStore, owner: UserId
) -> None:
    """The check-then-act race of revision 2: the invoker pauses after the authorization check and
    before the external handoff, and a closure is requested meanwhile."""
    services, runtime, scheduler, cid = fixture(store, owner)
    runtime.await_gate.arm()
    held = scheduler.hold("gate_held")
    handle = start_run(services, owner, cid)
    assert held.wait_reached()
    run_id = handle.run_id

    reached = threading.Event()
    scheduler.hooks["closure_waiting_for_gate"] = lambda _run: reached.set()
    closer, _ = in_thread(
        lambda: services.coordinator.settler.close_and_verify(run_id, ClosureReason.DEADLINE)
    )
    assert reached.wait(5)  # the closer has reached the handoff gate ...
    gate = services.coordinator.controls.control_for(run_id).handoff_gate
    assert gate.locked()  # ... which the paused invoker still holds, so it cannot pass
    assert store.get_run(run_id).closed_at is None  # no closure has been committed
    assert runtime.calls_of("start") == []  # and nothing has reached the runtime

    held.release()
    assert runtime.await_gate.wait_entered()  # the handoff completed before any closure
    closer.join(5)
    assert not closer.is_alive()
    run = store.get_run(run_id)
    assert run.closed_at is not None and run.handoff is Handoff.STARTED
    assert run.handoff_outcome is HandoffOutcome.ACCEPTED
    ops = operations(runtime)
    assert ops.index("start") < ops.index("stop")  # stop only after the handoff and the closure
    assert len(runtime.calls_of("start")) == 1

    runtime.await_gate.release()  # the late result arrives after closure
    outcome = handle.wait(5)
    assert outcome.assistant_message is None  # the closed attempt can never publish
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL


def test_closure_first_means_start_is_never_called_and_no_external_action_occurs(
    store: SqliteStore, owner: UserId
) -> None:
    services, runtime, scheduler, cid = fixture(store, owner)
    before_gate = scheduler.hold("before_gate")  # authorized (T3), not yet at the handoff
    handle = start_run(services, owner, cid)
    assert before_gate.wait_reached()
    run_id = handle.run_id

    result = services.coordinator.settler.close_and_verify(run_id, ClosureReason.SHUTDOWN)
    # handoff NONE with a closed fence is a durable proof of non-invocation (B1)
    assert result.run.status is RunStatus.FAILED
    assert result.run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert result.run.handoff is Handoff.NONE

    before_gate.release()  # the paused invoker resumes and must NOT start the runtime
    outcome = handle.wait(5)
    assert outcome.run.failure_code == "interrupted_before_dispatch"
    assert operations(runtime) == ["prepare"]  # no start, no stop, no probe
    assert [m.content for m in store.get_history(owner, cid).messages] == ["q"]


def test_stop_cannot_overlap_a_start_in_progress(store: SqliteStore, owner: UserId) -> None:
    services, runtime, scheduler, cid = fixture(store, owner)
    runtime.start_gate.arm()
    runtime.await_gate.arm()
    handle = start_run(services, owner, cid)
    assert runtime.start_gate.wait_entered()  # the handoff is in progress, holding the gate
    run_id = handle.run_id
    reached = threading.Event()
    scheduler.hooks["closure_waiting_for_gate"] = lambda _run: reached.set()
    closer, _ = in_thread(
        lambda: services.coordinator.settler.close_and_verify(run_id, ClosureReason.SHUTDOWN)
    )
    assert reached.wait(5)  # the closer is at the gate, which the in-progress start still holds
    assert services.coordinator.controls.control_for(run_id).handoff_gate.locked()
    assert store.get_run(run_id).closed_at is None
    assert runtime.calls_of("stop") == []  # stop is not sent while start is in progress
    runtime.start_gate.release()
    assert runtime.await_gate.wait_entered()
    closer.join(5)
    ops = operations(runtime)
    assert ops.index("start") < ops.index("stop")
    runtime.await_gate.release()
    assert handle.wait(5).assistant_message is None


def test_the_attempt_is_never_started_twice(store: SqliteStore, owner: UserId) -> None:
    services, runtime, _, cid = fixture(store, owner)
    sid = SubmissionId(new_uuid())
    first = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=sid, content="q"
    )
    for _ in range(3):  # retransmission, reconcile and a replacement coordinator never invoke
        services.coordinator.submit(
            owner=owner, conversation_id=cid, submission_id=sid, content="q"
        )
        services.coordinator.reconcile()
    Services(store, runtime, boot_id="another-boot").coordinator.startup()
    assert len(runtime.calls_of("start")) == 1
    assert first.run.status is RunStatus.SUCCEEDED
    # The handoff marker itself moves once: a second T3b is refused.
    assert store.mark_handoff_started(first.run.id, services.boot_id).result.value in (
        "wrong_source",
        "already_started",
    )


# -- problem A: publication versus closure -------------------------------------------------------


def test_closure_wins_over_output_in_hand_and_the_output_is_discarded(
    store: SqliteStore, owner: UserId
) -> None:
    services, _, scheduler, cid = fixture(store, owner)
    before_publish = scheduler.hold("before_publish")
    handle = start_run(services, owner, cid)
    assert before_publish.wait_reached()  # the runtime has delivered; the output is only in memory
    run_id = handle.run_id

    closed = services.coordinator.settler.close_and_verify(run_id, ClosureReason.DEADLINE)
    assert closed.run.closed_at is not None  # closure committed before publication
    before_publish.release()
    outcome = handle.wait(5)
    assert outcome.assistant_message is None
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "deadline_exceeded"
    # The bound instance's own delivery proves the attempt ended (B3); the output is dropped.
    assert outcome.run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert outcome.run.completion_observed is CompletionObserved.YES
    assert [m.role for m in store.get_history(owner, cid).messages] == [MessageRole.USER]


def test_publication_wins_and_a_closure_waiting_in_the_gate_cannot_undo_it(
    store: SqliteStore, owner: UserId
) -> None:
    services, runtime, scheduler, cid = fixture(store, owner)
    before_publish = scheduler.hold("before_publish")
    handle = start_run(services, owner, cid)
    assert before_publish.wait_reached()
    run_id = handle.run_id

    in_gate = scheduler.hold("closure_holding_gate")
    closer, _ = in_thread(
        lambda: services.coordinator.settler.close_and_verify(run_id, ClosureReason.DEADLINE)
    )
    assert in_gate.wait_reached()  # the closer holds the gate; the fence is still open
    before_publish.release()
    outcome = handle.wait(5)  # publication commits while the closure is mid-flight
    assert outcome.run.status is RunStatus.SUCCEEDED and outcome.assistant_message is not None
    in_gate.release()
    closer.join(5)
    assert store.get_run(run_id).status is RunStatus.SUCCEEDED  # closure could not undo it
    assert runtime.calls_of("stop") == []  # and stop was never sent
    messages = store.get_history(owner, cid).messages
    assert [m.content for m in messages] == ["q", "scripted reply"]
    assert messages[1].id == outcome.assistant_message.id


def test_late_result_after_closure_settles_on_evidence_and_is_never_published(
    store: SqliteStore, owner: UserId
) -> None:
    settings = replace(FAST, deadline_seconds=0.15)
    services, runtime, _, cid = fixture(store, owner, settings=settings)
    runtime.ignore_deadline = True  # a runtime that does not honour the attempt deadline
    runtime.await_gate.arm()
    handle = start_run(services, owner, cid)
    # The watchdog closes the attempt; stop is not evidence; the probe cannot tell: quarantine.
    deadline = time.monotonic() + 5
    while store.get_run(handle.run_id).status is not RunStatus.INDETERMINATE:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    quarantined = store.get_run(handle.run_id)
    assert quarantined.closure_reason is ClosureReason.DEADLINE
    assert runtime.calls_of("stop") and runtime.calls_of("probe")

    runtime.await_gate.release()  # the hung attempt finally delivers
    outcome = handle.wait(5)
    assert outcome.assistant_message is None
    assert outcome.run.status is RunStatus.FAILED  # T7 on the bound instance's delivery (B3)
    assert outcome.run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert outcome.run.failure_code == "deadline_exceeded"
    assert outcome.run.completion_observed is CompletionObserved.YES
    follow = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="next"
    )
    assert follow.assistant_message is not None  # the slot was released with the settlement


# -- uncertain invocation ------------------------------------------------------------------------


def test_unknown_but_durable_handoff_marker_lets_the_confirmed_owner_proceed_once(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("mark_handoff_started", Fault("unknown_durable"))
    services, runtime, _, cid = fixture(store, owner, store=faulty)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 1


def test_unknown_and_not_durable_handoff_marker_never_calls_start(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("mark_handoff_started", Fault("unknown_lost"))
    services, runtime, _, cid = fixture(store, owner, store=faulty)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert runtime.calls_of("start") == []  # not claimed invoked, not invoked
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.handoff is Handoff.NONE
    assert outcome.run.termination_basis is EvidenceBasis.NEVER_DISPATCHED


def test_unreadable_store_after_an_unknown_marker_leaves_the_run_for_reconcile_without_starting(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("mark_handoff_started", Fault("unknown_lost"))
    faulty.script("get_run", Fault("fail"))
    services, runtime, _, cid = fixture(store, owner, store=faulty)
    with pytest.raises(Exception, match="storage"):
        services.coordinator.submit(
            owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
        )
    assert runtime.calls_of("start") == []
    stuck = store.get_history(owner, cid).runs[0]
    assert stuck.status is RunStatus.IN_FLIGHT and stuck.handoff is Handoff.NONE
    report = services.coordinator.reconcile()  # later, with a readable store
    assert report.settled == 1
    assert store.get_history(owner, cid).runs[0].termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert runtime.calls_of("start") == []  # reconcile never invokes


@pytest.mark.parametrize("how", ["unknown_ack", "start_raises"])
def test_uncertain_start_is_recorded_unknown_and_never_claimed_uninvoked(
    store: SqliteStore, owner: UserId, how: str
) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    if how == "unknown_ack":
        runtime.start_ack = StartAck.UNKNOWN
    else:
        runtime.start_raises = RuntimeError("connection reset after send")
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    runtime.await_gate.arm()
    handle = start_run(services, owner, cid)
    assert runtime.await_gate.wait_entered()
    run = store.get_run(handle.run_id)
    assert run.handoff is Handoff.STARTED and run.handoff_outcome is HandoffOutcome.UNKNOWN
    closed = services.coordinator.settler.close_and_verify(run.id, ClosureReason.DEADLINE)
    # Non-invocation and adapter-never-reached are refused; only B3/B4 (B5 needs late-delivery
    # exclusion, which an external binding does not have) could settle this: quarantine.
    assert closed.run.status is RunStatus.INDETERMINATE
    settler = services.coordinator.settler
    runtime.probe_script.append(
        ProbeResult(ProbeKind.CONFIRMED_ENDED, EvidenceBasis.EXECUTION_TERMINATED_VERIFIED)
    )
    still = settler.reverify(store.get_run(run.id), ClosureReason.ORPHAN_RECONCILE)
    assert still.status is RunStatus.INDETERMINATE  # B5 refused after an UNKNOWN external handoff
    runtime.probe_script.append(
        ProbeResult(ProbeKind.CONFIRMED_ENDED, EvidenceBasis.PROCESS_EXIT_VERIFIED)
    )
    settled = settler.reverify(store.get_run(run.id), ClosureReason.ORPHAN_RECONCILE)
    assert settled.status is RunStatus.FAILED  # B4 is admissible after an UNKNOWN handoff
    assert settled.termination_basis is EvidenceBasis.PROCESS_EXIT_VERIFIED
    runtime.await_gate.release()
    handle.wait(5)


def test_a_lost_handoff_outcome_write_is_conservative(store: SqliteStore, owner: UserId) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("record_handoff_outcome", Fault("fail"))
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    services, runtime, _, cid = fixture(store, owner, runtime=runtime, store=faulty)
    runtime.await_gate.arm()
    handle = start_run(services, owner, cid)
    assert runtime.await_gate.wait_entered()
    run = store.get_run(handle.run_id)
    assert run.handoff is Handoff.STARTED and run.handoff_outcome is None  # unrecorded = UNKNOWN
    closed = services.coordinator.settler.close_and_verify(run.id, ClosureReason.DEADLINE)
    assert closed.run.status is RunStatus.INDETERMINATE  # nothing is claimed
    runtime.await_gate.release()
    assert handle.wait(5).run.status is RunStatus.FAILED  # the bound instance's delivery: B3


def test_a_handoff_the_adapter_refuses_settles_on_adapter_never_reached(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime()
    runtime.start_ack = StartAck.NOT_STARTED
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.termination_basis is EvidenceBasis.ADAPTER_NEVER_REACHED
    assert outcome.run.failure_code == "runtime_unavailable"
    assert runtime.calls_of("stop") == [] and runtime.calls_of("probe") == []  # nothing to stop


def test_a_bare_exception_from_await_is_possibly_active_not_a_failure(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.await_raises = RuntimeError("secret detail: /home/user/model.bin")
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.INDETERMINATE  # probe could not tell: no release
    assert "secret" not in (outcome.run.failure_message or "")
    assert outcome.assistant_message is None


# -- identity mismatches (F1) --------------------------------------------------------------------


def test_output_from_another_instance_is_rejected_and_is_not_evidence(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.delivered_instance_ref = "some-other-instance"
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    original = runtime.instance_ref
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.assistant_message is None
    run = outcome.run
    assert run.status is RunStatus.INDETERMINATE  # the mismatching delivery proved nothing
    assert run.closure_reason is ClosureReason.INSTANCE_MISMATCH
    assert run.termination_basis is None
    # Control addressed only the PERSISTED binding, never "whichever instance answered".
    assert {c.instance_ref for c in runtime.calls if c.operation in ("stop", "probe")} == {original}


def test_control_never_reaches_a_replacement_instance(store: SqliteStore, owner: UserId) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    runtime.await_gate.arm()
    handle = start_run(services, owner, cid)
    assert runtime.await_gate.wait_entered()
    original = runtime.instance_ref
    replacement = runtime.replace_instance()  # the runtime was replaced mid-attempt
    closed = services.coordinator.settler.close_and_verify(
        handle.run_id, ClosureReason.CONNECTION_LOST
    )
    assert closed.run.status is RunStatus.INDETERMINATE  # INSTANCE_MISMATCH is not termination
    stop_probe = [c for c in runtime.calls if c.operation in ("stop", "probe")]
    assert stop_probe and {c.instance_ref for c in stop_probe} == {original}
    assert replacement not in {c.instance_ref for c in runtime.calls}
    # The replacement instance's own work is unaffected, but the slot stays quarantined.
    runtime.await_gate.release()
    handle.wait(5)


def test_model_mismatch_from_the_verified_instance_is_evidence_and_settles(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.delivered_model_label = "a-different-model"
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "model_identity_mismatch"
    assert outcome.run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert outcome.assistant_message is None


def test_a_known_terminal_failure_from_another_instance_is_possibly_active(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.result = lambda _: Failed(
        "boom", "x", Knowledge.ENDED, instance_ref="not-the-bound-one"
    )
    services, runtime, _, cid = fixture(store, owner, runtime=runtime)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.INDETERMINATE
    assert outcome.run.termination_basis is None


# -- slot ownership under load -------------------------------------------------------------------


def test_a_pending_run_waiting_for_capacity_holds_no_slot_and_proceeds_on_release(
    store: SqliteStore, owner: UserId
) -> None:
    services, runtime, scheduler, first_cid = fixture(store, owner)
    second_cid = services.conversations.create_conversation(owner).id
    runtime.await_gate.arm()
    first = start_run(services, owner, first_cid, "one")
    assert runtime.await_gate.wait_entered()
    at_slot = threading.Event()
    scheduler.hooks["waiting_for_slot"] = lambda _run: at_slot.set()
    second = start_run(services, owner, second_cid, "two")
    assert at_slot.wait(5)  # the second worker has tried the slot and found it busy
    waiting = store.get_run(second.run_id)
    assert waiting.status is RunStatus.PENDING and waiting.slot_id is None  # admission only
    assert store.get_run(first.run_id).slot_id == services.coordinator._settings.slot_id
    runtime.await_gate.release()
    assert first.wait(5).run.status is RunStatus.SUCCEEDED
    assert second.wait(5).run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 2


def test_waiting_for_the_slot_is_bounded_and_ends_never_dispatched(
    store: SqliteStore, owner: UserId
) -> None:
    settings = replace(FAST, slot_wait_seconds=0.1)
    services, runtime, _, first_cid = fixture(store, owner, settings=settings)
    second_cid = services.conversations.create_conversation(owner).id
    runtime.await_gate.arm()
    first = start_run(services, owner, first_cid)
    assert runtime.await_gate.wait_entered()
    second = start_run(services, owner, second_cid).wait(5)
    assert second.run.failure_code == "runtime_busy"
    assert second.run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert len(runtime.calls_of("start")) == 1  # the second attempt never reached the runtime
    runtime.await_gate.release()
    first.wait(5)


# -- authorization uncertainty and the hung-handoff case (U-2) -------------------------------


def test_an_authorization_that_may_not_have_committed_never_invokes_and_is_left_for_reconcile(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("authorize_dispatch", Fault("unknown_lost"))
    services, runtime, _, cid = fixture(store, owner, store=faulty)
    with pytest.raises(StorageOutcomeUnknown):
        services.coordinator.submit(
            owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
        )
    assert operations(runtime) == ["prepare"]  # no start: the authorization was not confirmed
    assert store.get_history(owner, cid).runs[0].status is RunStatus.PENDING
    report = services.coordinator.reconcile()  # a stranded pending run is provably never dispatched
    assert report.pending_settled == 1
    run = store.get_history(owner, cid).runs[0]
    assert (
        run.status is RunStatus.FAILED and run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    )
    assert operations(runtime) == ["prepare"]


def test_an_authorization_that_committed_but_was_unconfirmed_proceeds_once_after_a_read(
    store: SqliteStore, owner: UserId
) -> None:
    faulty = FaultyExecutionStore(store)
    faulty.script("authorize_dispatch", Fault("unknown_durable"))
    services, runtime, _, cid = fixture(store, owner, store=faulty)
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert len(runtime.calls_of("start")) == 1


def test_a_hung_handoff_is_not_claimed_safe_the_closure_is_not_committed(
    store: SqliteStore, owner: UserId
) -> None:
    """U-2: while ``start`` has not returned, a closer that cannot take the gate commits nothing."""
    settings = replace(FAST, closure_gate_wait_seconds=0.2)
    services, runtime, _, cid = fixture(store, owner, settings=settings)
    runtime.start_gate.arm()
    handle = start_run(services, owner, cid)
    assert runtime.start_gate.wait_entered()
    result = services.coordinator.settler.close_and_verify(handle.run_id, ClosureReason.SHUTDOWN)
    assert result.gate_stuck  # nothing is asserted about a handoff that has not ended
    run = store.get_run(handle.run_id)
    assert run.closed_at is None and run.status is RunStatus.IN_FLIGHT  # fence still open
    assert runtime.calls_of("stop") == [] and runtime.calls_of("probe") == []
    runtime.start_gate.release()  # the handoff finally returns; the attempt proceeds normally
    assert handle.wait(5).run.status is RunStatus.SUCCEEDED
