"""InProcessRuntime — adapts a blocking, in-process ``SynchronousModel`` to ``RuntimePort``.

The runtime exists only inside the owning process: no external transport, broker, queue or
launcher. That is exactly what makes two things true (and only for this adapter):

* when ``await_result`` has returned or raised, the call has ended (the adapter owns the stack),
  so a delivery is positive evidence for the *bound* instance;
* the binding is recorded with ``lifetime_scope = owning_process``, so a later boot that holds the
  exclusive instance guard knows the owning process, and every worker in it, is gone (design
  §4.8). That judgment is made by the control router, never by this adapter's label.
"""

from __future__ import annotations

import threading
from enum import Enum

from anonymous.application.ports.model import (
    AdapterDescriptor,
    Completed,
    Failed,
    Knowledge,
    ModelExecutionError,
    ModelRequest,
    PreparedBinding,
    PrepareFailed,
    ProbeKind,
    ProbeResult,
    StartAck,
    StopAck,
    SynchronousModel,
)
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import EvidenceBasis, LifetimeScope
from anonymous.domain.ids import new_uuid
from anonymous.domain.provenance import ComponentIdentity

BINDING_FORMAT = "inprocess/1"
ADAPTER_ID = "inprocess-runtime"
ADAPTER_VERSION = "1"


class _State(Enum):
    STARTED = "started"
    RUNNING = "running"
    ENDED = "ended"
    TOMBSTONED = "tombstoned"


class InProcessRuntime:
    def __init__(self, model: SynchronousModel, *, max_input_chars: int | None = None) -> None:
        self._model = model
        self._max_input_chars = max_input_chars
        self._instance_ref = f"inproc-{new_uuid()}"
        self._lock = threading.Lock()
        self._attempts: dict[str, _State] = {}
        self._requests: dict[str, ModelRequest] = {}

    @property
    def instance_ref(self) -> str:
        return self._instance_ref

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            binding_formats=frozenset({BINDING_FORMAT}),
            max_input_chars=self._max_input_chars,
        )

    def prepare(self, attempt_id: str) -> PreparedBinding | PrepareFailed:
        identity = self._model.identity
        binding = ExecutionBinding(
            format=BINDING_FORMAT,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            instance_ref=self._instance_ref,
            lifetime_scope=LifetimeScope.OWNING_PROCESS,
            declared_bases=frozenset(
                {
                    EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
                    EvidenceBasis.PROCESS_EXIT_VERIFIED,
                    EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
                }
            ),
            late_delivery_excluded=True,  # no transport exists between caller and runtime
            model_label=identity.model_id,
            runtime_label=identity.runtime_id,
        )
        return PreparedBinding(
            binding=binding,
            model_artifact=ComponentIdentity.label_only(identity.model_id),
            runtime_build=ComponentIdentity.label_only(identity.runtime_id),
            adapter=ComponentIdentity.label_only(f"{ADAPTER_ID} {ADAPTER_VERSION}"),
        )

    def start(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        request: ModelRequest,
        handoff_deadline_seconds: float,
    ) -> StartAck:
        with self._lock:
            if binding.instance_ref != self._instance_ref:
                return StartAck.NOT_STARTED
            if self._attempts.get(attempt_id) is _State.TOMBSTONED:
                return StartAck.NOT_STARTED
            if attempt_id in self._attempts:
                return StartAck.NOT_STARTED  # an attempt starts at most once
            self._attempts[attempt_id] = _State.STARTED
            self._requests[attempt_id] = request
            return StartAck.ACCEPTED

    def await_result(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> Completed | Failed:
        with self._lock:
            if (
                binding.instance_ref != self._instance_ref
                or self._attempts.get(attempt_id) is not _State.STARTED
            ):
                return Failed(
                    "not_started", "The attempt was not started.", Knowledge.NEVER_REACHED
                )
            self._attempts[attempt_id] = _State.RUNNING
            request = self._requests.pop(attempt_id)
        try:
            # A blocking call into code we own; when it unwinds, the attempt has ended.
            output = self._model.generate(request)
        except ModelExecutionError as error:
            self._finish(attempt_id)
            return Failed(error.code, error.public_message, Knowledge.ENDED, self._instance_ref)
        except Exception:
            self._finish(attempt_id)
            return Failed(
                "runtime_error", "The model runtime failed.", Knowledge.ENDED, self._instance_ref
            )
        self._finish(attempt_id)
        return Completed(
            content=output.content,
            instance_ref=self._instance_ref,
            model_label=output.identity.model_id,
        )

    def _finish(self, attempt_id: str) -> None:
        with self._lock:
            self._attempts[attempt_id] = _State.ENDED

    def stop(self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float) -> StopAck:
        with self._lock:
            if binding.instance_ref != self._instance_ref:
                return StopAck.INSTANCE_MISMATCH
            state = self._attempts.get(attempt_id)
            if state is None or state is _State.STARTED:
                self._attempts[attempt_id] = _State.TOMBSTONED
                self._requests.pop(attempt_id, None)
                return StopAck.ACCEPTED
            if state is _State.RUNNING:
                return StopAck.REFUSED  # a blocking in-process call cannot be interrupted
            return StopAck.ACCEPTED

    def probe(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> ProbeResult:
        with self._lock:
            if binding.instance_ref != self._instance_ref:
                return ProbeResult(ProbeKind.INSTANCE_MISMATCH)
            state = self._attempts.get(attempt_id)
        if state is _State.RUNNING or state is _State.STARTED:
            return ProbeResult(ProbeKind.STILL_ACTIVE)
        if state in (_State.ENDED, _State.TOMBSTONED):
            return ProbeResult(
                ProbeKind.CONFIRMED_ENDED, EvidenceBasis.EXECUTION_TERMINATED_VERIFIED
            )
        return ProbeResult(ProbeKind.UNKNOWN, reason="attempt unknown to this instance")


__all__ = ["ADAPTER_ID", "BINDING_FORMAT", "InProcessRuntime"]
