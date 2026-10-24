"""Settlement guards for an EXTERNAL binding that declares no B3/B4/B5 basis (ADR-0015).

Every B3-shaped path ends in ``RunSettler.apply_evidence``: a late delivery after closure, a
terminal failure, a rejected completion, a lost publication race, and a probe result. For an
external binding that declares nothing none of them may settle; the run closes and, if it cannot be
shown to have ended, quarantines. Owning-process and fully declared bindings behave as before.
"""

from __future__ import annotations

import ast
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

import anonymous
from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.model import (
    Completed,
    Failed,
    Knowledge,
    PreparedBinding,
    PrepareFailed,
    ProbeKind,
    ProbeResult,
    StartAck,
)
from anonymous.application.ports.persistence import WriteResult
from anonymous.application.worker import ExecutionHandle
from anonymous.domain.errors import RuntimeQuarantined
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    LifetimeScope,
    basis_permitted_for_binding,
)
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import ModelRun, RunStatus
from tests.conftest import FAST, Services
from tests.doubles import Scheduler
from tests.unit.test_architecture_boundaries import calls_of


class DeclaringScripted(ScriptedRuntime):
    """A scripted runtime whose binding declares exactly ``declared`` (default: nothing)."""

    declared: frozenset[EvidenceBasis] = frozenset()

    def prepare(self, attempt_id: str) -> PreparedBinding | PrepareFailed:
        prepared = super().prepare(attempt_id)
        if isinstance(prepared, PrepareFailed):
            return prepared
        return replace(prepared, binding=replace(prepared.binding, declared_bases=self.declared))


def external(declared: frozenset[EvidenceBasis] = frozenset()) -> DeclaringScripted:
    runtime = DeclaringScripted(scope=LifetimeScope.EXTERNAL)
    runtime.declared = declared
    return runtime


def rig(store: SqliteStore, owner: UserId, runtime: ScriptedRuntime, **kw):  # type: ignore[no-untyped-def]
    scheduler = Scheduler()
    services = Services(store, runtime, checkpoint=scheduler, **kw)
    cid = services.conversations.create_conversation(owner).id
    return services, scheduler, cid


def begin(services: Services, owner: UserId, cid: ConversationId) -> ExecutionHandle:
    return services.coordinator.begin_submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )


def submit(services: Services, owner: UserId, cid: ConversationId) -> ModelRun:
    # Bounded: a run that never finishes fails the test instead of hanging it.
    return begin(services, owner, cid).wait(10).run


def assert_unsettled_quarantine(
    store: SqliteStore, services: Services, owner: UserId, run: ModelRun
) -> None:
    assert run.status is RunStatus.INDETERMINATE and run.termination_basis is None
    other = services.conversations.create_conversation(owner).id
    with pytest.raises(RuntimeQuarantined):
        submit(services, owner, other)
    assert store.get_run(run.id).status is RunStatus.INDETERMINATE


# -- the empty declaration is storable and truthfully read back ----------------------------------


def test_an_empty_declaration_round_trips_through_dispatch(
    store: SqliteStore, owner: UserId
) -> None:
    services, _, cid = rig(store, owner, external())
    run = submit(services, owner, cid)
    assert run.status is RunStatus.SUCCEEDED  # T4 needs no declaration
    assert run.binding is not None and run.binding.declared_bases == frozenset()
    assert run.binding.lifetime_scope is LifetimeScope.EXTERNAL


# -- terminal failure, rejected completions --------------------------------------------------------


def test_a_failure_reported_as_ended_does_not_settle_an_undeclared_external_binding(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = external()
    runtime.result = lambda request: Failed("boom", "x", Knowledge.ENDED, runtime.instance_ref)
    services, _, cid = rig(store, owner, runtime)
    assert_unsettled_quarantine(store, services, owner, submit(services, owner, cid))


@pytest.mark.parametrize("kind", ["truncated", "empty", "model_mismatch"])
def test_a_rejected_completion_does_not_settle_an_undeclared_external_binding(
    store: SqliteStore, owner: UserId, kind: str
) -> None:
    runtime = external()
    if kind == "truncated":
        runtime.result = lambda r: Completed("cut", runtime.instance_ref, runtime.model_id, False)
    elif kind == "empty":
        runtime.result = lambda r: Completed("  ", runtime.instance_ref, runtime.model_id)
    else:
        runtime.delivered_model_label = "some-other-model"
    services, _, cid = rig(store, owner, runtime)
    assert_unsettled_quarantine(store, services, owner, submit(services, owner, cid))


# -- late delivery and the publication race -------------------------------------------------------


def test_a_late_delivery_cannot_release_an_undeclared_external_quarantine(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = external()
    runtime.ignore_deadline = True
    runtime.await_gate.arm()
    services, _, cid = rig(store, owner, runtime, settings=replace(FAST, deadline_seconds=0.15))
    handle = begin(services, owner, cid)
    try:
        deadline = time.monotonic() + 5
        while store.get_run(handle.run_id).status is not RunStatus.INDETERMINATE:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        runtime.await_gate.release()  # never leave a non-daemon worker blocked on a failure
    outcome = handle.wait(5)  # the hung attempt finally delivers, from the bound instance
    assert outcome.assistant_message is None
    assert_unsettled_quarantine(store, services, owner, store.get_run(handle.run_id))


def test_a_lost_publication_race_does_not_manufacture_b3_for_an_undeclared_external_binding(
    store: SqliteStore, owner: UserId
) -> None:
    services, scheduler, cid = rig(store, owner, external())
    before_publish = scheduler.hold("before_publish")
    handle = begin(services, owner, cid)
    assert before_publish.wait_reached()  # delivered; the output is only in memory
    services.coordinator.settler.close_and_verify(handle.run_id, ClosureReason.DEADLINE)
    before_publish.release()
    outcome = handle.wait(5)
    assert outcome.assistant_message is None  # closure won; the output is discarded
    assert_unsettled_quarantine(store, services, owner, store.get_run(handle.run_id))


# -- probe results ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "basis", [EvidenceBasis.PROCESS_EXIT_VERIFIED, EvidenceBasis.EXECUTION_TERMINATED_VERIFIED]
)
def test_an_undeclared_probe_result_never_settles_even_if_the_router_let_it_through(
    store: SqliteStore, owner: UserId, basis: EvidenceBasis
) -> None:
    runtime = external()
    runtime.await_gate.arm()
    runtime.ignore_deadline = True
    services, _, cid = rig(store, owner, runtime)
    handle = begin(services, owner, cid)
    try:
        assert runtime.await_gate.wait_entered()

        class CredulousRouter:
            def stop(self, *args: object) -> None:
                return None

            def probe(self, *args: object) -> ProbeResult:
                return ProbeResult(ProbeKind.CONFIRMED_ENDED, basis)

        services.coordinator.settler._router = CredulousRouter()
        closed = services.coordinator.settler.close_and_verify(
            handle.run_id, ClosureReason.DEADLINE
        )
        assert closed.run.status is RunStatus.INDETERMINATE
        assert closed.run.termination_basis is None
    finally:
        runtime.await_gate.release()  # never leave a non-daemon worker blocked on a failure
    handle.wait(5)


# -- the choke point itself: bounded, no threads ------------------------------------------------


def _quarantined(
    store: SqliteStore, owner: UserId, runtime: ScriptedRuntime
) -> tuple[Services, ModelRun]:
    runtime.result = lambda request: Failed("runtime_error", "", Knowledge.POSSIBLY_ACTIVE)
    services, _, cid = rig(store, owner, runtime)
    run = submit(services, owner, cid)
    assert run.status is RunStatus.INDETERMINATE
    return services, run


@pytest.mark.parametrize(
    "basis",
    [
        EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
        EvidenceBasis.PROCESS_EXIT_VERIFIED,
        EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
    ],
)
def test_apply_evidence_cannot_release_an_undeclared_external_quarantine(
    store: SqliteStore, owner: UserId, basis: EvidenceBasis
) -> None:
    services, run = _quarantined(store, owner, external())
    settler = services.coordinator.settler
    result = settler.apply_evidence(
        run.id,
        basis=basis,
        code="deadline_exceeded",
        completion=CompletionObserved.YES,
        reason=ClosureReason.DEADLINE,
    )
    assert result is None
    still = store.get_run(run.id)
    assert still.status is RunStatus.INDETERMINATE and still.termination_basis is None


def test_the_same_evidence_does_release_a_quarantine_when_the_binding_declared_it(
    store: SqliteStore, owner: UserId
) -> None:
    """The contrast that keeps the test above from being vacuous."""
    services, run = _quarantined(store, owner, external(declared_all()))
    result = services.coordinator.settler.apply_evidence(
        run.id,
        basis=EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
        code="deadline_exceeded",
        completion=CompletionObserved.YES,
        reason=ClosureReason.DEADLINE,
    )
    assert result is not None
    assert store.get_run(run.id).status is RunStatus.FAILED


# -- handoff marker versus handoff outcome (T3b versus T3c) ---------------------------------------


@pytest.mark.parametrize(
    ("ack", "recorded"),
    [(StartAck.ACCEPTED, HandoffOutcome.ACCEPTED), (StartAck.UNKNOWN, HandoffOutcome.UNKNOWN)],
)
def test_publication_needs_the_started_marker_not_an_accepted_outcome(
    store: SqliteStore, owner: UserId, ack: StartAck, recorded: HandoffOutcome
) -> None:
    runtime = external()
    runtime.start_ack = ack
    services, _, cid = rig(store, owner, runtime)
    outcome = begin(services, owner, cid).wait(10)
    run = store.get_run(outcome.run.id)
    assert run.status is RunStatus.SUCCEEDED and outcome.assistant_message is not None
    assert run.handoff is Handoff.STARTED  # T3b: durable before start was called
    assert run.handoff_outcome is recorded  # T3c: what start answered, UNKNOWN stays UNKNOWN
    assert outcome.assistant_message.produced_by_run_id == run.id


# -- what is unchanged -----------------------------------------------------------------------------


def declared_all() -> frozenset[EvidenceBasis]:
    return frozenset(
        {
            EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
            EvidenceBasis.PROCESS_EXIT_VERIFIED,
            EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
        }
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda: external(declared_all()),  # a scripted external binding that declares B3
        lambda: _owning_process_declaring_nothing(),  # owning-process bindings are not touched
    ],
)
def test_a_terminal_failure_still_settles_when_the_binding_may_claim_it(
    store: SqliteStore, owner: UserId, build: Callable[[], ScriptedRuntime]
) -> None:
    runtime = build()
    runtime.result = lambda request: Failed("boom", "x", Knowledge.ENDED, runtime.instance_ref)
    services, _, cid = rig(store, owner, runtime)
    run = submit(services, owner, cid)
    assert run.status is RunStatus.FAILED
    assert run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert run.completion_observed is CompletionObserved.NO


def _owning_process_declaring_nothing() -> ScriptedRuntime:
    runtime = DeclaringScripted(scope=LifetimeScope.OWNING_PROCESS)
    runtime.declared = frozenset()
    return runtime


def test_the_guard_does_not_touch_non_runtime_bases(store: SqliteStore, owner: UserId) -> None:
    """B1/B2 are facts of Anonymous's own handoff record: an undeclared external binding still
    settles a refused handoff (nothing was sent) and an over-capacity input (never dispatched)."""
    runtime = external()
    runtime.max_input_chars = 3
    services, _, cid = rig(store, owner, runtime)
    run = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="qqqq"
    ).run
    assert run.status is RunStatus.FAILED
    assert run.termination_basis is EvidenceBasis.NEVER_DISPATCHED


# -- structural: every B3-shaped settlement reaches the guard --------------------------------------


def _enclosing_functions(path: Path, attribute: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attribute
            ):
                found.add(function.name)
    return found


def test_the_store_settles_evidence_only_through_the_guarded_choke_point() -> None:
    root = Path(anonymous.__file__).parent
    for write in ("settle_in_flight", "settle_indeterminate"):
        assert calls_of(write, "_store") == ["application/settling.py"]
        assert _enclosing_functions(root / "application" / "settling.py", write) == {
            "apply_evidence"
        }
    # Its callers: the settler's own verification and late delivery, and the worker's terminal
    # failures. Adding another caller must be a deliberate, reviewed change.
    assert calls_of("apply_evidence") == ["application/settling.py", "application/worker.py"]
    assert _enclosing_functions(root / "application" / "settling.py", "apply_evidence") == {
        "_settle",
        "late_delivery",
    }
    assert _enclosing_functions(root / "application" / "worker.py", "apply_evidence") == {
        "_settle_known"
    }


# -- the store enforces the same rule itself (direct calls cannot bypass the settler) ---------

RUNTIME_ASSERTING = [
    EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
    EvidenceBasis.PROCESS_EXIT_VERIFIED,
    EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
]


def _direct_settle_indeterminate(
    store: SqliteStore, run: ModelRun, basis: EvidenceBasis
) -> WriteResult:
    return store.settle_indeterminate(
        run.id,
        basis=basis,
        code="deadline_exceeded",
        message="synthetic",
        completion=CompletionObserved.UNKNOWN,
        expected_version=store.get_run(run.id).state_version,
    ).result


@pytest.mark.parametrize("basis", RUNTIME_ASSERTING)
def test_a_direct_store_call_cannot_settle_an_undeclared_external_quarantine(
    store: SqliteStore, owner: UserId, basis: EvidenceBasis
) -> None:
    _, run = _quarantined(store, owner, external())
    # B3, B4 and B5 are all admissible for this handoff state; only the binding forbids them.
    assert store.get_run(run.id).handoff_outcome is HandoffOutcome.ACCEPTED
    assert _direct_settle_indeterminate(store, run, basis) is WriteResult.NO_ADMISSIBLE_BASIS
    still = store.get_run(run.id)
    assert still.status is RunStatus.INDETERMINATE and still.termination_basis is None


@pytest.mark.parametrize("basis", RUNTIME_ASSERTING)
def test_a_direct_store_call_cannot_settle_an_undeclared_external_run_in_flight(
    store: SqliteStore, owner: UserId, basis: EvidenceBasis
) -> None:
    runtime = external()
    runtime.await_gate.arm()
    runtime.ignore_deadline = True
    services, _, cid = rig(store, owner, runtime)
    handle = begin(services, owner, cid)
    try:
        assert runtime.await_gate.wait_entered()
        store.close_run(handle.run_id, ClosureReason.DEADLINE)  # closed fence, still in_flight
        result = store.settle_in_flight(
            handle.run_id,
            basis=basis,
            code="deadline_exceeded",
            message="synthetic",
            completion=CompletionObserved.UNKNOWN,
            reason=ClosureReason.DEADLINE,
        )
        assert result.result is WriteResult.NO_ADMISSIBLE_BASIS
        assert store.get_run(handle.run_id).status is RunStatus.IN_FLIGHT
    finally:
        runtime.await_gate.release()  # never leave a non-daemon worker blocked on a failure
    handle.wait(10)


@pytest.mark.parametrize("basis", RUNTIME_ASSERTING)
def test_the_store_still_settles_when_the_external_binding_declared_the_basis(
    store: SqliteStore, owner: UserId, basis: EvidenceBasis
) -> None:
    """The contrast: the same direct call is applied when the adapter declared the basis."""
    _, run = _quarantined(store, owner, external(declared_all()))
    # B5 needs an ACCEPTED outcome or late-delivery exclusion; this run's outcome is ACCEPTED.
    assert _direct_settle_indeterminate(store, run, basis) is WriteResult.APPLIED
    assert store.get_run(run.id).status is RunStatus.FAILED


def test_the_store_leaves_owning_process_bindings_unchanged(
    store: SqliteStore, owner: UserId
) -> None:
    _, run = _quarantined(store, owner, _owning_process_declaring_nothing())
    result = _direct_settle_indeterminate(store, run, EvidenceBasis.RUNTIME_REPORTED_TERMINAL)
    assert result is WriteResult.APPLIED  # existing behavior: the rule is scoped to EXTERNAL


def test_the_store_does_not_touch_non_runtime_bases(store: SqliteStore, owner: UserId) -> None:
    """B2 (the adapter provably never reached the runtime) settles an undeclared external run."""
    runtime = external()
    runtime.start_ack = StartAck.NOT_STARTED
    services, _, cid = rig(store, owner, runtime)
    run = submit(services, owner, cid)
    assert run.status is RunStatus.FAILED
    assert run.termination_basis is EvidenceBasis.ADAPTER_NEVER_REACHED


def test_the_pure_rule_is_scoped_to_external_runtime_asserting_bases() -> None:
    none = frozenset[EvidenceBasis]()
    for basis in EvidenceBasis:
        asserting = basis in RUNTIME_ASSERTING
        assert basis_permitted_for_binding(basis, scope=LifetimeScope.EXTERNAL, declared=none) is (
            not asserting
        )
        owning = LifetimeScope.OWNING_PROCESS
        assert basis_permitted_for_binding(basis, scope=owning, declared=none)
        assert basis_permitted_for_binding(
            basis, scope=LifetimeScope.EXTERNAL, declared=frozenset({basis})
        )
