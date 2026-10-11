"""Independent reconciliation, quarantine, T7 and control routing (LD-04 §5, §6, §9)."""

from __future__ import annotations

import hashlib
import threading
import time

import pytest

from anonymous.adapters.model.inprocess import InProcessRuntime
from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.control import BindingControlRouter
from anonymous.application.ports.model import ProbeKind, ProbeResult, StopAck
from anonymous.domain.errors import RuntimeQuarantined
from anonymous.domain.evidence import EvidenceBasis, HandoffOutcome, LifetimeScope
from anonymous.domain.ids import ConversationId, RunId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import RunStatus
from tests.conftest import Services
from tests.dispatching import binding, dispatch
from tests.doubles import RecordingModel

B = EvidenceBasis


def admit(store: SqliteStore, owner: UserId, cid: ConversationId, text: str = "q") -> RunId:
    return store.admit_submission(
        owner=owner,
        conversation_id=cid,
        submission_id=SubmissionId(new_uuid()),
        content=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    ).run.id


def orphan(
    store: SqliteStore,
    owner: UserId,
    *,
    boot: str = "boot-1",
    scope: LifetimeScope = LifetimeScope.OWNING_PROCESS,
    outcome: HandoffOutcome | None = HandoffOutcome.ACCEPTED,
    late: bool = True,
    slot: str = "local-runtime-0",
) -> tuple[ConversationId, RunId]:
    """A run left ``in_flight`` by a process that no longer exists."""
    cid = store.create_conversation(owner, None).id
    run_id = admit(store, owner, cid)
    dispatch(store, run_id, boot=boot, scope=scope, late_excluded=late, outcome=outcome, slot=slot)
    return cid, run_id


def runtime_for(scope: LifetimeScope) -> ScriptedRuntime:
    # A fresh runtime object has a fresh instance identity: it is not the one the orphan used.
    return ScriptedRuntime(scope=scope)


# -- restart and reconciliation ------------------------------------------------------------------


def test_an_owning_process_orphan_is_settled_by_the_guard_after_restart(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = orphan(store, owner, boot="boot-1")
    runtime = runtime_for(LifetimeScope.OWNING_PROCESS)
    services = Services(store, runtime, boot_id="boot-2")
    report = services.coordinator.startup()
    assert (report.settled, report.still_unresolved) == (1, 0)
    run = store.get_run(run_id)
    assert run.status is RunStatus.FAILED and run.termination_basis is B.PROCESS_EXIT_VERIFIED
    assert run.failure_code == "interrupted_server_restart"
    assert runtime.calls_of("start") == []  # reconcile never invokes anything
    assert services.conversations.open_conversation(owner, cid).messages  # history intact


def test_without_the_guard_a_restart_alone_is_not_evidence(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = orphan(store, owner, boot="boot-1")
    services = Services(
        store, runtime_for(LifetimeScope.OWNING_PROCESS), boot_id="boot-2", guard_held=False
    )
    report = services.coordinator.startup()
    assert report.still_unresolved == 1
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE


def test_restart_with_an_external_runtime_keeps_the_slot_quarantined_across_restarts(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    for boot in ("boot-2", "boot-3"):  # restart twice: still no evidence
        services = Services(store, runtime_for(LifetimeScope.EXTERNAL), boot_id=boot)
        assert services.coordinator.startup().still_unresolved == 1
        assert store.get_run(run_id).status is RunStatus.INDETERMINATE
    other = store.create_conversation(owner, None).id
    with pytest.raises(RuntimeQuarantined):  # all new generation is blocked, in every conversation
        services.conversations.send_message(owner, other, new_uuid(), "hi")
    assert store.get_history(owner, cid).messages  # reading is unaffected
    assert store.generation_state().quarantined_runs == (run_id,)


def test_reconcile_by_another_actor_needs_no_slot_and_releases_it_with_t7(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    first = Services(store, runtime_for(LifetimeScope.EXTERNAL), boot_id="boot-2")
    assert first.coordinator.startup().still_unresolved == 1
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE  # holds the slot (quarantine)

    # A different actor (another request/boot) obtains admissible evidence for the PERSISTED
    # binding. It does not acquire the slot it is recovering.
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.instance_ref = "instance-1"  # the instance recorded in the persisted binding
    runtime.probe_script.append(ProbeResult(ProbeKind.CONFIRMED_ENDED, B.PROCESS_EXIT_VERIFIED))
    second = Services(store, runtime, boot_id="boot-3")
    report = second.coordinator.reconcile()
    assert report.settled == 1
    run = store.get_run(run_id)
    assert run.status is RunStatus.FAILED and run.termination_basis is B.PROCESS_EXIT_VERIFIED
    assert store.generation_state().quarantined_runs == ()
    outcome = second.conversations.send_message(owner, cid, new_uuid(), "again")  # slot is free
    assert outcome.assistant_message is not None


def test_concurrent_reconcilers_settle_once_and_release_idempotently(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    Services(store, runtime_for(LifetimeScope.EXTERNAL), boot_id="boot-2").coordinator.startup()
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE
    version = store.get_run(run_id).state_version

    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.instance_ref = "instance-1"
    runtime.probe_default = ProbeResult(ProbeKind.CONFIRMED_ENDED, B.PROCESS_EXIT_VERIFIED)
    actors = [Services(store, runtime, boot_id=f"boot-{i}") for i in range(4)]
    barrier = threading.Barrier(len(actors))
    reports: list[object] = []

    def reconcile(service: Services) -> None:
        barrier.wait(5)
        reports.append(service.coordinator.reconcile())

    threads = [threading.Thread(target=reconcile, args=(a,)) for a in actors]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    run = store.get_run(run_id)
    assert run.status is RunStatus.FAILED
    assert run.state_version == version + 1  # exactly one settlement write
    again = actors[0].coordinator.reconcile()  # repeated T7 is a no-op
    assert again.examined == 0 and store.get_run(run_id).state_version == version + 1
    assert store.generation_state().quarantined_runs == ()
    assert actors[0].conversations.send_message(owner, cid, new_uuid(), "ok").assistant_message


def test_an_unsupported_binding_stays_unresolved_and_nothing_else_is_touched(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = orphan(store, owner, scope=LifetimeScope.EXTERNAL, late=False)
    model = RecordingModel()
    services = Services(store, model, boot_id="boot-2")  # an in-process adapter: no handler
    assert services.coordinator.startup().still_unresolved == 1
    assert store.get_run(run_id).status is RunStatus.INDETERMINATE
    assert model.requests == []


def test_a_request_touching_unresolved_work_triggers_reconcile_without_a_polling_loop(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = orphan(store, owner, boot="boot-1")
    services = Services(store, runtime_for(LifetimeScope.OWNING_PROCESS), boot_id="boot-2")
    # No startup() call: the next send itself reconciles first, then is admitted.
    outcome = services.conversations.send_message(owner, cid, new_uuid(), "continue")
    assert store.get_run(run_id).status is RunStatus.FAILED
    assert outcome.assistant_message is not None


# -- control routing (F4) ------------------------------------------------------------------------


def router_for(
    runtime: ScriptedRuntime, *, held: bool = True, boot: str = "now"
) -> BindingControlRouter:
    return BindingControlRouter([runtime], current_boot_id=boot, guard_held=lambda: held)


def test_control_is_bounded_and_a_timeout_is_never_evidence() -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    runtime.probe_gate.arm()
    runtime.stop_gate.arm()
    bound = binding(
        instance=runtime.instance_ref, scope=LifetimeScope.EXTERNAL, late_excluded=False
    )
    router = router_for(runtime)
    started = time.monotonic()
    probe = router.probe("a", bound, "boot-1", 0.1)
    stop = router.stop("a", bound, "boot-1", 0.1)
    assert time.monotonic() - started < 2.0  # bounded, although the runtime never answered
    assert probe.kind is ProbeKind.UNKNOWN and stop is StopAck.TIMEOUT
    runtime.probe_gate.release()
    runtime.stop_gate.release()


def test_control_is_callable_while_generation_is_blocked(store: SqliteStore, owner: UserId) -> None:
    services = Services(store, ScriptedRuntime(scope=LifetimeScope.EXTERNAL))
    runtime = services.runtime
    assert isinstance(runtime, ScriptedRuntime)
    runtime.await_gate.arm()
    cid = services.conversations.create_conversation(owner).id
    handle = services.coordinator.begin_submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert runtime.await_gate.wait_entered()  # generation is blocked
    run = store.get_run(handle.run_id)
    assert run.binding is not None
    runtime.probe_script.append(ProbeResult(ProbeKind.STILL_ACTIVE))
    started = time.monotonic()
    result = services.router.probe(run.id, run.binding, run.execution_boot_id, 1.0)
    assert result.kind is ProbeKind.STILL_ACTIVE and time.monotonic() - started < 1.0
    runtime.await_gate.release()
    handle.wait(5)


def test_a_basis_the_binding_did_not_declare_is_discarded() -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    bound = binding(instance=runtime.instance_ref, scope=LifetimeScope.EXTERNAL)
    undeclared = (
        bound.__class__(
            **{**bound.__dict__, "declared_bases": frozenset({B.RUNTIME_REPORTED_TERMINAL})}
        )
        if hasattr(bound, "__dict__")
        else bound
    )
    from dataclasses import replace

    undeclared = replace(bound, declared_bases=frozenset({B.RUNTIME_REPORTED_TERMINAL}))
    runtime.probe_script.append(ProbeResult(ProbeKind.CONFIRMED_ENDED, B.PROCESS_EXIT_VERIFIED))
    assert router_for(runtime).probe("a", undeclared, "boot-1", 1.0).kind is ProbeKind.UNKNOWN


@pytest.mark.parametrize(
    ("scope", "owner_boot", "held", "expected"),
    [
        (LifetimeScope.OWNING_PROCESS, "earlier", True, ProbeKind.CONFIRMED_ENDED),
        (LifetimeScope.OWNING_PROCESS, "earlier", False, ProbeKind.INSTANCE_MISMATCH),
        (LifetimeScope.OWNING_PROCESS, "now", True, ProbeKind.INSTANCE_MISMATCH),
        (LifetimeScope.OWNING_PROCESS, None, True, ProbeKind.INSTANCE_MISMATCH),
        (LifetimeScope.EXTERNAL, "earlier", True, ProbeKind.INSTANCE_MISMATCH),
    ],
)
def test_the_guard_is_evidence_only_for_an_owning_process_binding_of_an_earlier_boot(
    scope: LifetimeScope, owner_boot: str | None, held: bool, expected: ProbeKind
) -> None:
    runtime = ScriptedRuntime(scope=scope)  # a different instance than the one in the binding
    bound = binding(instance="old-instance", scope=scope)
    result = router_for(runtime, held=held, boot="now").probe("a", bound, owner_boot, 1.0)
    assert result.kind is expected
    if expected is ProbeKind.CONFIRMED_ENDED:
        assert result.basis is B.PROCESS_EXIT_VERIFIED


def test_a_replacement_adapter_is_never_probed_for_a_foreign_binding() -> None:
    runtime = ScriptedRuntime(scope=LifetimeScope.EXTERNAL)
    foreign = binding(instance="someone-elses", scope=LifetimeScope.EXTERNAL)
    result = router_for(runtime).probe("a", foreign, "boot-1", 1.0)
    assert result.kind is ProbeKind.INSTANCE_MISMATCH  # the handler verified the instance itself
    assert runtime.calls_of("probe")[0].instance_ref == "someone-elses"


def test_in_process_adapter_reports_its_own_attempts_only() -> None:
    model = RecordingModel("r")
    runtime = InProcessRuntime(model)
    prepared = runtime.prepare("attempt-1")
    assert not hasattr(prepared, "code")
    bound = prepared.binding
    assert runtime.probe("attempt-1", bound, 1.0).kind is ProbeKind.UNKNOWN  # never seen
    stale = binding(instance="inproc-someone-else", scope=LifetimeScope.OWNING_PROCESS)
    assert runtime.probe("attempt-1", stale, 1.0).kind is ProbeKind.INSTANCE_MISMATCH
    assert runtime.stop("attempt-1", stale, 1.0) is StopAck.INSTANCE_MISMATCH
