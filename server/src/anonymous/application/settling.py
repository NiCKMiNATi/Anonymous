"""RunSettler — closure, stop, verification and settlement (LD-04 §4.4 SP-9…SP-12, §9).

Used by the run's own worker, its deadline watchdog, shutdown, and reconcile. All of them go
through the same code, so the invariants live in one place:

* a closure of an open fence is committed only while holding the run's handoff gate (G-1, A-4);
* stop is attempted only *after* closure is durable, and only if the durable handoff state says
  the runtime may have been called (never for ``NONE``/``NOT_CALLED``/``NOT_STARTED``);
* stop acknowledgments are not evidence; only a verified probe, a delivery from the bound
  instance, or the durable handoff record can settle a run;
* control always addresses the **persisted** binding.
"""

from __future__ import annotations

import logging
import time

from anonymous.application.failures import code_for_reason, public_message
from anonymous.application.ports.model import (
    Completed,
    ControlRouter,
    Failed,
    Knowledge,
    ProbeKind,
)
from anonymous.application.ports.persistence import ExecutionStore, Transition, WriteResult
from anonymous.application.supervisor import (
    Checkpoint,
    ControlRegistry,
    ExecutionSettings,
)
from anonymous.domain.errors import StorageOutcomeUnknown
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    admissible_bases,
    basis_permitted_for_binding,
)
from anonymous.domain.ids import RunId
from anonymous.domain.models import ModelRun, RunStatus

logger = logging.getLogger("anonymous.settling")

_MAX_VERSION_RETRIES = 5


class SettlementOutcome:
    """What a settle attempt achieved; ``run`` is always the freshly stored state."""

    __slots__ = ("gate_stuck", "run")

    def __init__(self, run: ModelRun, gate_stuck: bool = False) -> None:
        self.run = run
        self.gate_stuck = gate_stuck


class RunSettler:
    def __init__(
        self,
        store: ExecutionStore,
        router: ControlRouter,
        settings: ExecutionSettings,
        controls: ControlRegistry,
        checkpoint: Checkpoint,
    ) -> None:
        self._store = store
        self._router = router
        self._settings = settings
        self._controls = controls
        self._checkpoint = checkpoint

    # -- evidence application (T5 / T7) ----------------------------------------------------------

    def apply_evidence(
        self,
        run_id: RunId,
        *,
        basis: EvidenceBasis,
        code: str,
        completion: CompletionObserved,
        reason: ClosureReason,
        adapter_message: str | None = None,
    ) -> Transition | None:
        """Settle on ``basis`` with T5 (``in_flight``) or T7 (``indeterminate``), re-reading and
        retrying on a stale version. Repeated or concurrent calls are idempotent.

        A commit whose outcome is unknown is resolved by reading the run again: if the write landed
        the run is terminal and nothing more is done; if it did not, the same evidence is applied
        again (same source predicate, same ``expected_version``), so it can land at most once. The
        retries are bounded; a run that still cannot be resolved stays as it is (conservative)."""
        message = public_message(code, adapter_message)
        unknown = 0
        for _ in range(_MAX_VERSION_RETRIES):
            run = self._store.get_run(run_id)
            if run.binding is not None and not basis_permitted_for_binding(
                basis, scope=run.binding.lifetime_scope, declared=run.binding.declared_bases
            ):
                # Every B3-shaped path ends here (a rejected or late delivery, a terminal failure,
                # a lost publication race, a probe result). An undeclared claim settles nothing:
                # the run stays closed and, if unresolved, quarantined. The store enforces the
                # same rule inside its settlement transaction (defence in depth, ADR-0015).
                logger.warning("evidence not declared for this binding run=%s (ignored)", run_id)
                return None
            try:
                if run.status is RunStatus.IN_FLIGHT:
                    result = self._store.settle_in_flight(
                        run_id,
                        basis=basis,
                        code=code,
                        message=message,
                        completion=completion,
                        reason=reason,
                        expected_version=run.state_version,
                    )
                elif run.status is RunStatus.INDETERMINATE:
                    result = self._store.settle_indeterminate(
                        run_id,
                        basis=basis,
                        code=code,
                        message=message,
                        completion=completion,
                        expected_version=run.state_version,
                    )
                else:
                    return None
            except StorageOutcomeUnknown:
                unknown += 1
                if unknown >= self._settings.republish_attempts:
                    raise
                continue
            if result.result in (WriteResult.STALE_VERSION, WriteResult.ALREADY_INDETERMINATE):
                continue
            return result
        return None

    # -- closure and verification (SP-9 … SP-11) -----------------------------------------------

    def close_and_verify(self, run_id: RunId, reason: ClosureReason) -> SettlementOutcome:
        control = self._controls.control_for(run_id)
        with control.settle_lock:
            run = self._store.get_run(run_id)
            if run.status is RunStatus.IN_FLIGHT and run.closed_at is None:
                if not self._close_under_gate(run, reason):
                    # U-2: the handoff section did not end; nothing is claimed.
                    return SettlementOutcome(self._store.get_run(run_id), gate_stuck=True)
                run = self._store.get_run(run_id)
            return SettlementOutcome(self._verify_and_settle(run, reason))

    def reverify(self, run: ModelRun, reason: ClosureReason) -> ModelRun:
        """Reconcile an orphan or an ``indeterminate`` run: close if still open, then verify."""
        return self.close_and_verify(run.id, reason).run

    def _close_under_gate(self, run: ModelRun, reason: ClosureReason) -> bool:
        control = self._controls.control_for(run.id)
        self._checkpoint("closure_waiting_for_gate", run.id)  # about to contend for the gate
        if not control.handoff_gate.acquire(timeout=self._settings.closure_gate_wait_seconds):
            logger.error("handoff gate stuck run=%s; closure not committed", run.id)
            return False
        try:
            self._checkpoint("closure_holding_gate", run.id)
            self._store.close_run(run.id, reason)
        finally:
            control.handoff_gate.release()
        return True

    def _verify_and_settle(self, run: ModelRun, reason: ClosureReason) -> ModelRun:
        if run.status not in (RunStatus.IN_FLIGHT, RunStatus.INDETERMINATE):
            return run
        if run.record_epoch.value != "0b" or run.binding is None or run.handoff is None:
            return run  # binding-less (legacy) runs have no admissible basis in 0B-1
        closure_reason = run.closure_reason or reason
        code = code_for_reason(closure_reason)
        # Durable proof that the runtime was never called: no external action at all.
        if run.handoff is Handoff.NONE or run.handoff_outcome is HandoffOutcome.NOT_CALLED:
            return self._settle(
                run,
                EvidenceBasis.NEVER_DISPATCHED,
                "interrupted_before_dispatch",
                CompletionObserved.NO,
                closure_reason,
            )
        if run.handoff_outcome is HandoffOutcome.NOT_STARTED:
            return self._settle(
                run,
                EvidenceBasis.ADAPTER_NEVER_REACHED,
                "runtime_unavailable",
                CompletionObserved.NO,
                closure_reason,
            )
        binding = run.binding
        allowed = admissible_bases(
            epoch=run.record_epoch,
            handoff=run.handoff,
            outcome=run.handoff_outcome,
            late_delivery_excluded=run.binding_late_delivery_excluded(),
        )
        allowed = frozenset(
            basis
            for basis in allowed
            if basis_permitted_for_binding(
                basis, scope=binding.lifetime_scope, declared=binding.declared_bases
            )
        )  # an undeclared runtime-asserting basis is never accepted (ADR-0015)
        deadline = self._settings.control_deadline_seconds
        # Stop is an instruction, never evidence. It follows durable closure (SP-10).
        self._router.stop(run.id, binding, run.execution_boot_id, deadline)
        for attempt in range(self._settings.probe_attempts):
            result = self._router.probe(run.id, binding, run.execution_boot_id, deadline)
            if (
                result.kind is ProbeKind.CONFIRMED_ENDED
                and result.basis is not None
                and result.basis in allowed
            ):
                return self._settle(
                    run, result.basis, code, CompletionObserved.UNKNOWN, closure_reason
                )
            if attempt + 1 < self._settings.probe_attempts:
                time.sleep(self._settings.probe_interval_seconds)
        fresh = self._store.get_run(run.id)
        if fresh.status is RunStatus.IN_FLIGHT and fresh.closed_at is not None:
            self._store.mark_indeterminate(fresh.id, fresh.state_version)
        return self._store.get_run(run.id)

    def _settle(
        self,
        run: ModelRun,
        basis: EvidenceBasis,
        code: str,
        completion: CompletionObserved,
        reason: ClosureReason,
    ) -> ModelRun:
        self.apply_evidence(run.id, basis=basis, code=code, completion=completion, reason=reason)
        return self._store.get_run(run.id)

    # -- late delivery (SP-12 / §4.5) ---------------------------------------------------------

    def late_delivery(self, run_id: RunId, delivery: Completed | Failed) -> None:
        """The worker's ``await_result`` returned after the attempt was closed or settled.

        The content is discarded (never stored, logged or published). A delivery by the verified
        bound instance is B3 evidence that the attempt ended; anything else is a fault only.
        """
        run = self._store.get_run(run_id)
        if run.status not in (RunStatus.IN_FLIGHT, RunStatus.INDETERMINATE) or run.binding is None:
            logger.warning("late delivery after settlement run=%s (ignored)", run_id)
            return
        verified = delivery.instance_ref == run.binding.instance_ref
        if isinstance(delivery, Failed):
            verified = verified and delivery.knowledge is Knowledge.ENDED
        if not verified:
            logger.error("delivery not attributable to the bound instance run=%s", run_id)
            return
        completion = (
            CompletionObserved.YES if isinstance(delivery, Completed) else CompletionObserved.NO
        )
        reason = run.closure_reason or ClosureReason.SUPERVISOR_FAULT
        self.apply_evidence(
            run_id,
            basis=EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
            code=code_for_reason(reason),
            completion=completion,
            reason=reason,
        )
