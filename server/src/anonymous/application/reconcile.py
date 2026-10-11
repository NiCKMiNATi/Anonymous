"""Independent reconciliation (LD-04 §5.3, §9 S5/S6).

Runs at startup, before a send/retry touches a conversation that has an unresolved run with no live
supervisor, or on an explicit command. It acts on the *owner run's row*: it needs no capacity and
never acquires the slot it is trying to recover. It never invokes a model and never settles
without an admissible basis. Legacy (pre-0B) blockers are counted and reported, never touched.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from anonymous.application.failures import public_message
from anonymous.application.ports.persistence import ExecutionStore, WriteResult
from anonymous.application.settling import RunSettler
from anonymous.application.supervisor import ControlRegistry, ExecutionSettings
from anonymous.domain.evidence import ClosureReason, RecordEpoch
from anonymous.domain.models import RunStatus

logger = logging.getLogger("anonymous.reconcile")


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    pending_settled: int = 0
    examined: int = 0
    settled: int = 0
    still_unresolved: int = 0
    skipped_live: int = 0
    legacy_blockers: int = 0


class Reconciler:
    def __init__(
        self,
        store: ExecutionStore,
        settler: RunSettler,
        controls: ControlRegistry,
        settings: ExecutionSettings,
    ) -> None:
        self._store = store
        self._settler = settler
        self._controls = controls
        self._settings = settings
        self._last = float("-inf")
        self._lock = threading.Lock()

    def startup(self) -> ReconcileReport:
        """Settle never-dispatched ``pending`` runs (T2/B1), then reconcile orphans."""
        pending = self._store.recover_pending_runs()
        report = self.reconcile()
        return ReconcileReport(
            pending_settled=pending + report.pending_settled,
            examined=report.examined,
            settled=report.settled,
            still_unresolved=report.still_unresolved,
            skipped_live=report.skipped_live,
            legacy_blockers=report.legacy_blockers,
        )

    def reconcile(self) -> ReconcileReport:
        examined = settled = unresolved = live = legacy = 0
        # A ``pending`` run with no live worker was never dispatched (its worker died or could not
        # confirm its authorization): provably B1, and it must not hold its conversation forever.
        stranded = 0
        for pending in self._store.list_pending_runs():
            if self._controls.has_live_worker(pending.id):
                continue
            outcome = self._store.settle_pending(
                pending.id,
                "interrupted_before_dispatch",
                public_message("interrupted_before_dispatch"),
            )
            stranded += outcome.result is WriteResult.APPLIED
        for run in self._store.list_unresolved_runs():
            if run.record_epoch is RecordEpoch.LEGACY_0A:
                legacy += 1
                continue  # no admissible basis exists for a binding-less run (design §5.5)
            if self._controls.has_live_worker(run.id):
                live += 1
                continue
            examined += 1
            after = self._settler.reverify(run, ClosureReason.ORPHAN_RECONCILE)
            if after.status in (RunStatus.FAILED, RunStatus.SUCCEEDED):
                settled += 1
            else:
                unresolved += 1
        if legacy or unresolved:
            logger.warning(
                "reconcile: unresolved=%d legacy_blockers=%d (generation stays blocked)",
                unresolved,
                legacy,
            )
        return ReconcileReport(
            pending_settled=stranded,
            examined=examined,
            settled=settled,
            still_unresolved=unresolved,
            skipped_live=live,
            legacy_blockers=legacy,
        )

    def maybe_reconcile(self) -> None:
        """Trigger (b): a request that touches unresolved work. Rate-limited; no polling loop."""
        with self._lock:
            now = time.monotonic()
            if now - self._last < self._settings.reconcile_min_interval_seconds:
                return
            self._last = now
        state = self._store.generation_state()
        if (
            state.quarantined_runs
            or self._store.list_pending_runs()
            or any(
                not self._controls.has_live_worker(r.id)
                for r in self._store.list_unresolved_runs()
                if r.record_epoch is RecordEpoch.CURRENT
            )
        ):
            self.reconcile()
