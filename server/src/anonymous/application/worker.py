"""RunWorker — the supervisor of one attempt (LD-04 §4.4 SP-1…SP-12).

One worker per run, in a supervised thread independent of any HTTP request. It is the *only*
party that may call ``start`` for its run: it holds the single-use invocation right (the T3
winner), calls ``start`` at most once, only after T3b is durable and only while holding the
handoff gate. Everything else (deadline watchdog, shutdown, reconcile) closes and settles through
:class:`RunSettler`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from anonymous.application.configuration import ConfigurationCatalog
from anonymous.application.failures import public_message
from anonymous.application.ports.model import (
    Completed,
    Failed,
    Knowledge,
    ModelRequest,
    PreparedBinding,
    PrepareFailed,
    RuntimePort,
    StartAck,
)
from anonymous.application.ports.persistence import (
    DispatchRecord,
    ExecutionStore,
    HistorySource,
    SubmissionOutcome,
    Transition,
    WriteResult,
)
from anonymous.application.settling import RunSettler
from anonymous.application.supervisor import (
    Checkpoint,
    ControlRegistry,
    ExecutionSettings,
    RunControl,
)
from anonymous.domain.errors import AnonymousError, StorageFailure, StorageOutcomeUnknown
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
)
from anonymous.domain.ids import RunId
from anonymous.domain.models import Completeness, ModelRun, RunStatus
from anonymous.domain.provenance import (
    ComponentIdentity,
    ContextSelection,
    ExecutionProvenance,
    Verification,
)

logger = logging.getLogger("anonymous.worker")


class ExecutionHandle:
    """Lets a caller wait for a run's worker without owning it (the worker outlives the caller)."""

    def __init__(self, run_id: RunId) -> None:
        self.run_id = run_id
        self._done = threading.Event()
        self._outcome: SubmissionOutcome | None = None
        self._error: BaseException | None = None

    def complete(self, outcome: SubmissionOutcome) -> None:
        self._outcome = outcome
        self._done.set()

    def fail(self, error: BaseException) -> None:
        self._error = error
        self._done.set()

    def wait(self, timeout: float | None = None) -> SubmissionOutcome:
        if not self._done.wait(timeout):
            raise TimeoutError("the run has not finished")
        if self._error is not None:
            raise self._error
        assert self._outcome is not None
        return self._outcome

    @property
    def done(self) -> bool:
        return self._done.is_set()


class RunWorker:
    def __init__(
        self,
        *,
        admitted: SubmissionOutcome,
        handle: ExecutionHandle,
        store: ExecutionStore,
        history: HistorySource,
        runtime: RuntimePort,
        catalog: ConfigurationCatalog,
        settler: RunSettler,
        controls: ControlRegistry,
        settings: ExecutionSettings,
        boot_id: str,
        checkpoint: Checkpoint,
        app_build: ComponentIdentity,
        spawn_watchdog: Callable[[str, Callable[[], None]], object],
        is_accepting: Callable[[], bool],
    ) -> None:
        self._admitted = admitted
        self._handle = handle
        self._store = store
        self._history = history
        self._runtime = runtime
        self._catalog = catalog
        self._settler = settler
        self._controls = controls
        self._settings = settings
        self._boot = boot_id
        self._checkpoint = checkpoint
        self._app_build = app_build
        self._spawn_watchdog = spawn_watchdog
        self._is_accepting = is_accepting
        self._run = admitted.run
        self._control: RunControl = controls.control_for(admitted.run.id)

    # -- thread entry --------------------------------------------------------------------------

    def __call__(self) -> None:
        run_id = self._run.id
        # The run was marked live at admission, atomically with its commit (admission gate).
        try:
            self._handle.complete(self._execute())
        except BaseException as error:  # delivered to the waiting caller, never swallowed
            self._handle.fail(error)
        finally:
            self._controls.mark_worker_done(run_id)

    # -- the attempt -----------------------------------------------------------------------------

    def _outcome(self) -> SubmissionOutcome:
        run, user, assistant = self._store.get_outcome(self._run.id)
        return SubmissionOutcome(
            user_message=user, run=run, assistant_message=assistant, replayed=False
        )

    def _settle_pending(self, code: str) -> SubmissionOutcome:
        logger.warning("generation not dispatched run=%s code=%s", self._run.id, code)
        self._store.settle_pending(self._run.id, code, public_message(code))
        return self._outcome()

    def _execute(self) -> SubmissionOutcome:
        run = self._run
        # -- before any external call: failures here are provably never-dispatched (B1) ---------
        try:
            binding_row = self._store.get_current_binding(run.conversation_id)
            digest = binding_row.configuration_digest if binding_row else None
            if digest is None or not self._catalog.is_executable(digest):
                return self._settle_pending("configuration_unavailable")
            builder = self._catalog.builder(digest, self._history)
            assert builder is not None
            limit = self._runtime.describe().max_input_chars
            view = builder.build_view(self._admitted.user_message, limit)
            request = view.request
        except StorageFailure:
            return self._settle_pending("context_unavailable")
        # The final guard for every configuration (ADR-0017): nothing is ever cut to fit. A bounded
        # view always contains the triggering message, so only that message alone can exceed it.
        if limit is not None and sum(len(m.content) for m in request.messages) > limit:
            return self._settle_pending(
                "context_exceeds_capacity" if view.selection is None else "message_exceeds_capacity"
            )
        prepared = self._runtime.prepare(run.id)
        if isinstance(prepared, PrepareFailed):
            return self._settle_pending("binding_unavailable")
        manifest = self._catalog.manifest(digest)
        assert manifest is not None
        provenance = self._provenance(
            prepared,
            manifest.context.id,
            manifest.context.version,
            manifest.context_digest,
            view.selection,
        )

        authorized = self._authorize(
            DispatchRecord(
                binding=prepared.binding,
                provenance=provenance,
                configuration_digest=digest,
                slot_id=self._settings.slot_id,
                boot_id=self._boot,
            )
        )
        if authorized is None:
            return self._outcome()
        # -- from here the runtime may be called: every failure is possibly-active ---------------
        try:
            return self._invoke_and_finish(prepared, request)
        except (StorageFailure, StorageOutcomeUnknown):
            raise  # nothing durable was changed by this failure; reconcile resolves the run
        except AnonymousError:
            raise
        except Exception as error:
            logger.error("supervisor fault run=%s type=%s", run.id, type(error).__name__)
            self._settler.close_and_verify(run.id, ClosureReason.SUPERVISOR_FAULT)
            return self._outcome()

    def _provenance(
        self,
        prepared: PreparedBinding,
        context_id: str,
        context_version: int,
        context_digest: str,
        selection: ContextSelection | None,
    ) -> ExecutionProvenance:
        return ExecutionProvenance(
            application_build=self._app_build,
            adapter=prepared.adapter,
            model_artifact=prepared.model_artifact,
            runtime_build=prepared.runtime_build,
            context_configuration=ComponentIdentity(
                label=f"{context_id}@{context_version}",
                digest=context_digest,
                verification=Verification.VERIFIED,
            ),
            behavior_configuration=ComponentIdentity.none(),
            context_selection=selection,
        )

    # -- T3 --------------------------------------------------------------------------------------

    def _authorize(self, record: DispatchRecord) -> Transition | None:
        """Win the invocation right (T3) or settle the pending run. ``None`` ⇒ do not invoke."""
        run_id = self._run.id
        deadline = time.monotonic() + self._settings.slot_wait_seconds
        while True:
            if self._control.closure_intent.is_set() or not self._is_accepting():
                self._settle_pending_quiet("interrupted_before_dispatch")
                return None
            try:
                transition = self._store.authorize_dispatch(run_id, record)
            except StorageFailure:
                # Known NOT committed: the runtime was never called (B1).
                self._settle_pending_quiet("dispatch_not_recorded")
                return None
            except StorageOutcomeUnknown:
                # Not confirmed: never invoke on an unconfirmed authorization. A read decides.
                current = self._store.get_run(run_id)
                if (
                    current.status is RunStatus.IN_FLIGHT
                    and current.execution_boot_id == self._boot
                ):
                    return Transition(WriteResult.APPLIED, current)
                raise
            if transition.result is WriteResult.APPLIED:
                return transition
            if transition.result is WriteResult.SLOT_BUSY:
                if transition.holder_status is RunStatus.INDETERMINATE:
                    self._settle_pending_quiet("runtime_quarantined")
                    return None
                if time.monotonic() >= deadline:
                    self._settle_pending_quiet("runtime_busy")
                    return None
                self._checkpoint("waiting_for_slot", run_id)
                time.sleep(self._settings.slot_poll_seconds)
                continue
            if transition.result is WriteResult.LEGACY_BLOCKED:
                self._settle_pending_quiet("generation_blocked_legacy_unresolved")
                return None
            return None  # WRONG_SOURCE: someone else already resolved the run

    def _settle_pending_quiet(self, code: str) -> None:
        logger.warning("generation not dispatched run=%s code=%s", self._run.id, code)
        self._store.settle_pending(self._run.id, code, public_message(code))

    # -- SP-3 … SP-8 -----------------------------------------------------------------------------

    def _invoke_and_finish(
        self, prepared: PreparedBinding, request: ModelRequest
    ) -> SubmissionOutcome:
        run_id = self._run.id
        binding = prepared.binding
        ack = self._handoff(prepared, request)
        if ack is None:
            # The fence closed before T3b (closure won) or another party owns the run.
            self._settler.close_and_verify(run_id, ClosureReason.ORPHAN_RECONCILE)
            return self._outcome()
        if ack is StartAck.NOT_STARTED:
            self._settler.close_and_verify(run_id, ClosureReason.RUNTIME_FAILURE)
            return self._outcome()

        stop_watchdog = threading.Event()
        self._start_watchdog(stop_watchdog)
        try:
            self._checkpoint("before_await", run_id)
            try:
                delivery = self._runtime.await_result(
                    run_id, binding, self._settings.deadline_seconds
                )
            except Exception as error:
                logger.error("await raised run=%s type=%s", run_id, type(error).__name__)
                delivery = Failed("runtime_error", "", Knowledge.POSSIBLY_ACTIVE)
        finally:
            stop_watchdog.set()
        self._checkpoint("after_await", run_id)
        return self._handle_delivery(binding.instance_ref, binding.model_label, delivery)

    def _handoff(self, prepared: PreparedBinding, request: ModelRequest) -> StartAck | None:
        """SP-3…SP-6 under the handoff gate. ``None`` ⇒ ``start`` was not and will not be called."""
        run_id = self._run.id
        binding = prepared.binding
        gate = self._control.handoff_gate
        self._checkpoint("before_gate", run_id)
        if not gate.acquire(timeout=self._settings.closure_gate_wait_seconds):
            logger.error("handoff gate unavailable run=%s", run_id)
            return None
        try:
            self._checkpoint("gate_held", run_id)
            skip = self._control.closure_intent.is_set()
            try:
                marker = self._store.mark_handoff_started(run_id, self._boot)
            except StorageOutcomeUnknown:
                current = self._store.get_run(run_id)  # may raise: then start is not called
                if current.handoff is not Handoff.STARTED or current.closed_at is not None:
                    return None
                marker = Transition(WriteResult.APPLIED, current)
            if marker.result is not WriteResult.APPLIED:
                return None  # FENCE_CLOSED / ALREADY_STARTED / WRONG_SOURCE: never call start
            self._checkpoint("after_t3b", run_id)
            if skip:
                self._record_outcome(HandoffOutcome.NOT_CALLED)
                return None
            try:
                ack = self._runtime.start(
                    run_id, binding, request, self._settings.handoff_deadline_seconds
                )
            except Exception as error:
                logger.error("start raised run=%s type=%s", run_id, type(error).__name__)
                ack = StartAck.UNKNOWN
            self._checkpoint("after_start", run_id)
            self._record_outcome(
                {
                    StartAck.ACCEPTED: HandoffOutcome.ACCEPTED,
                    StartAck.NOT_STARTED: HandoffOutcome.NOT_STARTED,
                    StartAck.UNKNOWN: HandoffOutcome.UNKNOWN,
                }[ack]
            )
            self._checkpoint("after_outcome", run_id)
            return ack
        finally:
            gate.release()

    def _record_outcome(self, outcome: HandoffOutcome) -> None:
        try:
            self._store.record_handoff_outcome(self._run.id, outcome)
        except AnonymousError:
            # Best effort (T3c): an unrecorded outcome is treated as UNKNOWN, which is conservative.
            logger.warning("handoff outcome not recorded run=%s", self._run.id)

    def _start_watchdog(self, stop: threading.Event) -> None:
        run_id = self._run.id

        def watch() -> None:
            if stop.wait(self._settings.deadline_seconds + 0.05):
                return
            try:
                self._settler.close_and_verify(run_id, ClosureReason.DEADLINE)
            except Exception as error:
                logger.error("watchdog failed run=%s type=%s", run_id, type(error).__name__)

        self._spawn_watchdog(f"anonymous-watchdog-{run_id}", watch)

    # -- delivery handling (SP-8) ------------------------------------------------------------------

    def _handle_delivery(
        self, bound_instance: str, bound_model: str, delivery: Completed | Failed
    ) -> SubmissionOutcome:
        run_id = self._run.id
        run = self._store.get_run(run_id)
        if run.status is not RunStatus.IN_FLIGHT or run.closed_at is not None:
            self._settler.late_delivery(run_id, delivery)  # discard; B3 only if verified
            return self._outcome()

        if isinstance(delivery, Failed):
            attributable = delivery.instance_ref == bound_instance
            if delivery.knowledge is Knowledge.ENDED and attributable:
                self._settle_known(delivery.code, delivery.public_message, CompletionObserved.NO)
            elif delivery.code == "deadline":
                self._settler.close_and_verify(run_id, ClosureReason.DEADLINE)
            else:
                self._settler.close_and_verify(run_id, ClosureReason.CONNECTION_LOST)
            return self._outcome()

        # Completed: first the delivering *instance*, then the reported *model*.
        if delivery.instance_ref != bound_instance:
            logger.error("delivery from a different instance run=%s (rejected)", run_id)
            self._settler.close_and_verify(run_id, ClosureReason.INSTANCE_MISMATCH)
            return self._outcome()
        if delivery.model_label != bound_model:
            self._settle_known("model_identity_mismatch", "", CompletionObserved.YES)
            return self._outcome()
        if not delivery.complete and not delivery.limit_reached:
            # An incomplete result of unknown kind: rejected exactly as before (LD-04 P4).
            self._settle_known("output_truncated", "", CompletionObserved.YES)
            return self._outcome()
        if not delivery.content.strip():
            self._settle_known("empty_output", "", CompletionObserved.YES)
            return self._outcome()
        # ADR-0016: a complete, attributable, non-empty delivery whose adapter marked it as cut off
        # at the output limit publishes through T4 like any accepted delivery, labelled truncated.
        # T4 still claims accepted response delivery only (ADR-0015 point 1).
        return self._publish(
            delivery.content,
            Completeness.TRUNCATED if delivery.limit_reached else Completeness.COMPLETE,
        )

    def _settle_known(
        self, code: str, adapter_message: str, completion: CompletionObserved
    ) -> None:
        """The bound instance delivered a terminal outcome: B3, fence closed in the same write."""
        logger.warning("generation failed run=%s code=%s", self._run.id, code)
        transition = self._settler.apply_evidence(
            self._run.id,
            basis=EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
            code=code,
            completion=completion,
            reason=ClosureReason.RUNTIME_FAILURE,
            adapter_message=adapter_message,
        )
        if transition is None or transition.result is WriteResult.NO_ADMISSIBLE_BASIS:
            self._settler.close_and_verify(self._run.id, ClosureReason.RUNTIME_FAILURE)

    # -- T4 and the uncertain-publication cases (design §7) ------------------------------------

    def _publish(self, content: str, completeness: Completeness) -> SubmissionOutcome:
        run_id = self._run.id
        self._checkpoint("before_publish", run_id)
        unreadable = False
        for _ in range(self._settings.republish_attempts):
            try:
                outcome = self._store.publish_response(run_id, content, completeness)
            except StorageOutcomeUnknown:
                # Case A/B/C: resolve by reading, never by calling the model again.
                try:
                    current = self._store.get_run(run_id)
                except AnonymousError:
                    unreadable = True  # Case C: undetermined — change nothing
                    break
                if current.status is RunStatus.SUCCEEDED:
                    return self._outcome()  # Case A: committed; preserve the original result
                if current.status is not RunStatus.IN_FLIGHT or current.closed_at is not None:
                    self._discard_publication()
                    return self._outcome()
                continue  # still open with no message: re-publish (idempotent)
            except StorageFailure:
                continue  # known not committed: bounded re-publication
            if outcome.result in (WriteResult.APPLIED, WriteResult.PUBLISHED):
                return self._outcome()
            # ALREADY_CLOSED / SETTLED / WRONG_SOURCE: closure or settlement won; discard.
            logger.warning("publication refused run=%s result=%s", run_id, outcome.result.value)
            self._discard_publication()
            return self._outcome()
        if unreadable:
            raise StorageOutcomeUnknown(
                "The database could not confirm whether the response was saved."
            )
        # Known failed publication after bounded attempts: B3 (the bound instance delivered),
        # closure + settlement in one write; the output is discarded. A fresh answer needs an
        # explicit retry.
        self._settle_known("response_not_saved", "", CompletionObserved.YES)
        return self._outcome()

    def _discard_publication(self) -> None:
        """Closure or settlement won: the provisional output is dropped (never stored or logged).

        It came from the verified bound instance, so it is still B3 evidence if unresolved."""
        run = self._store.get_run(self._run.id)
        instance = run.binding.instance_ref if run.binding else ""
        self._settler.late_delivery(self._run.id, Completed("", instance, ""))


def run_summary(run: ModelRun) -> str:  # content-free diagnostic helper
    return f"{run.id} {run.status.value}"
