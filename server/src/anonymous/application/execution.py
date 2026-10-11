"""Execution coordinator (C05): admission, supervised attempts, retry, reconcile, shutdown.

LD-04 revision 3.1 (design: docs/design/ld-04-execution-lifecycle.md). Durable checkpoints, in
order, for one attempt (each a short transaction; none open across an external call):

  T1  user message + ``pending`` run committed            — nothing else happens before this
  T3  dispatch *authorized*: binding, provenance, configuration, slot, boot id
  T3b handoff marker durable (open fence required)        — ``start`` may be called only after this
      ``start``  (bounded handoff, under the handoff gate; at most once per attempt)
  T3c handoff outcome recorded (best effort)
      ``await_result`` (no gate, no transaction)
  T4  assistant message + ``succeeded`` atomically        — only with an open fence
  or  closure (T5c) → stop → verification → T5 / T6 → later T7, each only on admissible evidence

A response is reported only from what the store confirmed. Execution belongs to a supervised
worker thread independent of the HTTP request; a disconnected client changes nothing.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable

from anonymous.application.configuration import ConfigurationCatalog
from anonymous.application.failures import public_message
from anonymous.application.ports.model import ControlRouter, RuntimePort
from anonymous.application.ports.persistence import ExecutionStore, HistorySource, SubmissionOutcome
from anonymous.application.reconcile import Reconciler, ReconcileReport
from anonymous.application.settling import RunSettler
from anonymous.application.supervisor import (
    Checkpoint,
    ControlRegistry,
    ExecutionSettings,
    Reservation,
    SpawnFailed,
    SpawnRefused,
    ThreadRegistry,
    no_checkpoint,
)
from anonymous.application.worker import ExecutionHandle, RunWorker
from anonymous.domain.errors import AnonymousError, GenerationBlocked
from anonymous.domain.evidence import ClosureReason
from anonymous.domain.ids import ConversationId, MessageId, SubmissionId, UserId
from anonymous.domain.models import validate_message_content
from anonymous.domain.provenance import ComponentIdentity

logger = logging.getLogger("anonymous.execution")


class ExecutionCoordinator:
    def __init__(
        self,
        *,
        store: ExecutionStore,
        history: HistorySource,
        runtime: RuntimePort,
        router: ControlRouter,
        catalog: ConfigurationCatalog,
        settings: ExecutionSettings | None = None,
        boot_id: str,
        checkpoint: Checkpoint = no_checkpoint,
        app_build: ComponentIdentity | None = None,
    ) -> None:
        self._store = store
        self._history = history
        self._runtime = runtime
        self._catalog = catalog
        self._settings = settings or ExecutionSettings()
        self._boot_id = boot_id
        self._checkpoint = checkpoint
        self._app_build = app_build or ComponentIdentity.label_only("anonymous-server")
        self.controls = ControlRegistry()
        self.threads = ThreadRegistry(lambda point: checkpoint(point, ""))
        self.settler = RunSettler(store, router, self._settings, self.controls, checkpoint)
        self.reconciler = Reconciler(store, self.settler, self.controls, self._settings, checkpoint)

    # -- lifecycle -----------------------------------------------------------------------------

    def startup(self) -> ReconcileReport:
        return self.reconciler.startup()

    def reconcile(self) -> ReconcileReport:
        reservation = self._reserve("reconcile")  # shutdown waits for an in-progress reconcile
        try:
            return self.reconciler.reconcile()
        finally:
            reservation.release()

    def shutdown(self, timeout_seconds: float | None = None) -> bool:
        """Stop admitting, close every active attempt, join the workers.

        Returns ``True`` only if every reservation has ended: every worker and watchdog that was
        started, every worker that was reserved but not yet started, and every admission or
        reconcile in progress. If it returns ``False`` something may still execute (a hung
        runtime, or a thread whose start is unconfirmed): the caller must NOT release process
        ownership; the process must exit, which releases the guard and ends the worker with it.
        """
        self.threads.begin_shutdown()
        live = self.controls.live_runs()
        for run_id in live:
            self.controls.control_for(run_id).closure_intent.set()
        for run_id in live:
            try:
                self.settler.close_and_verify(run_id, ClosureReason.SHUTDOWN)
            except Exception as error:
                logger.error("shutdown closure failed run=%s type=%s", run_id, type(error).__name__)
        bound = (
            timeout_seconds if timeout_seconds is not None else self._settings.shutdown_join_seconds
        )
        return self.threads.join_all(bound)

    # -- submissions -----------------------------------------------------------------------------

    def submit(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
    ) -> SubmissionOutcome:
        return self.begin_submit(
            owner=owner,
            conversation_id=conversation_id,
            submission_id=submission_id,
            content=content,
        ).wait()

    def begin_submit(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
    ) -> ExecutionHandle:
        """Admit (T1) and start the supervised worker; returns without waiting for the run."""
        content = validate_message_content(content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        replay = self._store.find_submission(
            owner=owner,
            conversation_id=conversation_id,
            submission_id=submission_id,
            content_sha256=digest,
        )
        if replay is not None:
            return self._finished(replay)  # resolves the original outcome; never starts work
        return self._admit_and_start(
            lambda: self._store.admit_submission(
                owner=owner,
                conversation_id=conversation_id,
                submission_id=submission_id,
                content=content,
                content_sha256=digest,
                executable_digests=self._catalog.executable_digests(),
            )
        )

    def retry(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        retry_id: str,
        message_id: MessageId,
    ) -> SubmissionOutcome:
        return self.begin_retry(
            owner=owner,
            conversation_id=conversation_id,
            retry_id=retry_id,
            message_id=message_id,
        ).wait()

    def begin_retry(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        retry_id: str,
        message_id: MessageId,
    ) -> ExecutionHandle:
        """Explicit retry: a new run on the SAME saved user message; never a new message."""
        return self._admit_and_start(
            lambda: self._store.admit_retry(
                owner=owner,
                conversation_id=conversation_id,
                retry_id=retry_id,
                message_id=message_id,
                executable_digests=self._catalog.executable_digests(),
            )
        )

    # -- internals ---------------------------------------------------------------------------

    def _reserve(self, name: str) -> Reservation:
        try:
            return self.threads.reserve(name)
        except SpawnRefused:
            raise GenerationBlocked("The server is shutting down; nothing was accepted.") from None

    @staticmethod
    def _finished(outcome: SubmissionOutcome) -> ExecutionHandle:
        handle = ExecutionHandle(outcome.run.id)
        handle.complete(outcome)
        return handle

    def _admit_and_start(self, admit: Callable[[], SubmissionOutcome]) -> ExecutionHandle:
        """The single path for submissions and retries (design: remediation of review finding 2).

        1. reserve — counts this request toward shutdown quiescence before anything is committed;
        2. under the admission gate: commit the pending run, then mark it live (one atomic step as
           far as orphan detection is concerned);
        3. start the worker on the reservation.
        """
        reservation = self._reserve("admission")
        try:
            self.reconciler.maybe_reconcile()
            with self.controls.admission_gate:
                self._checkpoint("admission_gate_held", "")
                admitted = admit()
                if not admitted.replayed:
                    self.controls.mark_worker_live(admitted.run.id)
                self._checkpoint("admission_committed", admitted.run.id)
        except BaseException:
            reservation.release()  # nothing was started; an unknown commit leaves an orphan row
            raise
        if admitted.replayed:
            reservation.release()
            return self._finished(admitted)
        return self._start_worker(admitted, reservation)

    def _start_worker(
        self, admitted: SubmissionOutcome, reservation: Reservation
    ) -> ExecutionHandle:
        run_id = admitted.run.id
        handle = ExecutionHandle(run_id)
        worker = RunWorker(
            admitted=admitted,
            handle=handle,
            store=self._store,
            history=self._history,
            runtime=self._runtime,
            catalog=self._catalog,
            settler=self.settler,
            controls=self.controls,
            settings=self._settings,
            boot_id=self._boot_id,
            checkpoint=self._checkpoint,
            app_build=self._app_build,
            spawn_watchdog=reservation.spawn_child,
            is_accepting=lambda: self.threads.accepting,
        )
        try:
            reservation.start(worker, f"anonymous-run-{run_id}")
        except SpawnFailed:
            # Established: the worker never ran, so the run was never dispatched (B1). The
            # reservation is still held while the run is settled; only then is it released.
            logger.error("worker thread could not be started run=%s", run_id)
            try:
                self._store.settle_pending(
                    run_id,
                    "interrupted_before_dispatch",
                    public_message("interrupted_before_dispatch"),
                )
                run, user, assistant = self._store.get_outcome(run_id)
                handle.complete(
                    SubmissionOutcome(
                        user_message=user, run=run, assistant_message=assistant, replayed=False
                    )
                )
            except AnonymousError as error:
                handle.fail(error)
            finally:
                self.controls.mark_worker_done(run_id)
                reservation.release()
        return handle
