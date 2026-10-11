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
from anonymous.application.supervisor import (
    Checkpoint,
    ControlRegistry,
    ExecutionSettings,
    no_checkpoint,
)
from anonymous.domain.errors import StorageFailure, StorageOutcomeUnknown
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
        checkpoint: Checkpoint = no_checkpoint,
    ) -> None:
        self._checkpoint = checkpoint
        self._store = store
        self._settler = settler
        self._controls = controls
        self._settings = settings
        self._last = float("-inf")
        self._lock = threading.Lock()

    def startup(self) -> ReconcileReport:
        """Settle abandoned ``pending`` runs (T2/B1), then reconcile orphans. The same orphan rule
        as at any other time: a run with a live worker or an admission in progress is not one."""
        return self.reconcile()

    def reconcile(self) -> ReconcileReport:
        examined = settled = unresolved = live = legacy = 0
        # A ``pending`` run with no live worker was never dispatched (its worker died or could not
        # confirm its authorization): provably B1, and it must not hold its conversation forever.
        stranded = self._settle_abandoned_pending()
        for run in self._store.list_unresolved_runs():
            if run.record_epoch is RecordEpoch.LEGACY_0A:
                legacy += 1
                continue  # no admissible basis exists for a binding-less run (design §5.5)
            if self._controls.has_live_worker(run.id):
                live += 1
                continue
            examined += 1
            try:
                after = self._settler.reverify(run, ClosureReason.ORPHAN_RECONCILE)
            except (StorageFailure, StorageOutcomeUnknown) as error:
                # One run's storage fault must not stop the others (or startup). Nothing was
                # concluded for this run: it stays as stored, so generation stays blocked by it.
                logger.warning(
                    "reconcile could not resolve run=%s type=%s", run.id, type(error).__name__
                )
                unresolved += 1
                continue
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

    def _settle_abandoned_pending(self) -> int:
        """A ``pending`` run is abandoned only if no worker is live for it AND no admission is
        between its commit and its live mark. The admission gate makes those two facts one:
        holding it, a pending run without a live mark cannot be a live admission."""
        settled = 0
        self._checkpoint("orphan_scan_waiting", "")  # about to enter the admission gate
        with self._controls.admission_gate:
            self._checkpoint("orphan_scan_entered", "")
            for pending in self._store.list_pending_runs():
                if self._controls.has_live_worker(pending.id):
                    continue
                outcome = self._store.settle_pending(
                    pending.id,
                    "interrupted_before_dispatch",
                    public_message("interrupted_before_dispatch"),
                )
                settled += outcome.result is WriteResult.APPLIED
        self._checkpoint("orphan_scan_done", "")
        return settled

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
