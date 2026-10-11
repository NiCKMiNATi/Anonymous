"""ScriptedRuntime — a deterministic, controllable ``RuntimePort`` for the 0B-1 tests.

It is an in-process stand-in with **no** external transport, broker, queue or launcher. Every
behavior the lifecycle must survive is scripted: the handoff acknowledgment, blocking inside
``start`` or ``await_result`` until a test releases a gate, which instance delivers, probe and stop
answers, instance replacement, and the lifetime scope recorded in the binding. It records every
call so tests can assert exactly what reached the "runtime" (for example zero ``start`` calls).

Nothing here is evidence about any real runtime.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from anonymous.application.ports.model import (
    AdapterDescriptor,
    Completed,
    Failed,
    Knowledge,
    ModelRequest,
    PreparedBinding,
    PrepareFailed,
    ProbeKind,
    ProbeResult,
    StartAck,
    StopAck,
)
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import EvidenceBasis, LifetimeScope
from anonymous.domain.ids import new_uuid
from anonymous.domain.provenance import ComponentIdentity

ADAPTER_ID = "scripted-runtime"
ADAPTER_VERSION = "1"
FORMAT_IN_PROCESS = "scripted/1"
FORMAT_EXTERNAL = "scripted-external/1"


class Gate:
    """A latch a test uses to hold the runtime at a precise point and observe that it arrived."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self._released = threading.Event()
        self.enabled = False

    def arm(self) -> Gate:
        self.enabled = True
        return self

    def hold(self, timeout: float | None = None) -> bool:
        """Called by the runtime. Returns False if the wait timed out (``timeout`` given)."""
        if not self.enabled:
            return True
        self.entered.set()
        return self._released.wait(timeout)

    def release(self) -> None:
        self._released.set()

    def wait_entered(self, timeout: float = 5.0) -> bool:
        return self.entered.wait(timeout)


@dataclass(slots=True)
class Call:
    operation: str
    attempt_id: str
    instance_ref: str | None


ResultFactory = Callable[[ModelRequest], "Completed | Failed"]


@dataclass(slots=True)
class ScriptedRuntime:
    model_id: str = "scripted-model"
    runtime_id: str = "scripted-runtime"
    scope: LifetimeScope = LifetimeScope.OWNING_PROCESS
    late_delivery_excluded: bool | None = None  # default: True only for owning_process
    max_input_chars: int | None = None
    # -- behavior knobs (mutable) ------------------------------------------------------------
    prepare_failure: PrepareFailed | None = None
    start_ack: StartAck = StartAck.ACCEPTED
    start_raises: Exception | None = None
    start_gate: Gate = field(default_factory=Gate)
    await_gate: Gate = field(default_factory=Gate)
    stop_gate: Gate = field(default_factory=Gate)
    probe_gate: Gate = field(default_factory=Gate)
    ignore_deadline: bool = False  # a runtime that does not honour await_result's deadline
    delivered_instance_ref: str | None = None  # override the delivering instance (mismatch)
    delivered_model_label: str | None = None
    result: ResultFactory | None = None
    await_raises: Exception | None = None
    execute_when_unknown: bool = True  # an UNKNOWN handoff still reaches the runtime
    stop_ack: StopAck = StopAck.ACCEPTED
    probe_script: deque[ProbeResult] = field(default_factory=deque)
    probe_default: ProbeResult = field(
        default_factory=lambda: ProbeResult(ProbeKind.UNKNOWN, reason="scripted")
    )
    # -- state -------------------------------------------------------------------------------
    instance_ref: str = field(default_factory=lambda: f"scripted-{new_uuid()}")
    calls: list[Call] = field(default_factory=list)
    reply: str = "scripted reply"
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _tombstones: set[str] = field(default_factory=set)
    _accepted: dict[str, ModelRequest] = field(default_factory=dict)

    # -- test helpers ------------------------------------------------------------------------

    def calls_of(self, operation: str) -> list[Call]:
        with self._lock:
            return [c for c in self.calls if c.operation == operation]

    def replace_instance(self) -> str:
        """Simulate a runtime replacement: a new instance identity, old bindings now stale."""
        self.instance_ref = f"scripted-{new_uuid()}"
        return self.instance_ref

    def _record(self, operation: str, attempt_id: str, instance_ref: str | None) -> None:
        with self._lock:
            self.calls.append(Call(operation, attempt_id, instance_ref))

    # -- RuntimePort -------------------------------------------------------------------------

    def _format(self) -> str:
        return FORMAT_IN_PROCESS if self.scope is LifetimeScope.OWNING_PROCESS else FORMAT_EXTERNAL

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            binding_formats=frozenset({FORMAT_IN_PROCESS, FORMAT_EXTERNAL}),
            max_input_chars=self.max_input_chars,
        )

    def prepare(self, attempt_id: str) -> PreparedBinding | PrepareFailed:
        self._record("prepare", attempt_id, None)
        if self.prepare_failure is not None:
            return self.prepare_failure
        late = (
            self.late_delivery_excluded
            if self.late_delivery_excluded is not None
            else self.scope is LifetimeScope.OWNING_PROCESS
        )
        binding = ExecutionBinding(
            format=self._format(),
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            instance_ref=self.instance_ref,
            lifetime_scope=self.scope,
            declared_bases=frozenset(
                {
                    EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
                    EvidenceBasis.PROCESS_EXIT_VERIFIED,
                    EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
                }
            ),
            late_delivery_excluded=late,
            model_label=self.model_id,
            runtime_label=self.runtime_id,
        )
        return PreparedBinding(
            binding=binding,
            model_artifact=ComponentIdentity.label_only(self.model_id),
            runtime_build=ComponentIdentity.label_only(self.runtime_id),
            adapter=ComponentIdentity.label_only(f"{ADAPTER_ID} {ADAPTER_VERSION}"),
        )

    def start(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        request: ModelRequest,
        handoff_deadline_seconds: float,
    ) -> StartAck:
        self._record("start", attempt_id, binding.instance_ref)
        self.start_gate.hold()
        if self.start_raises is not None:
            raise self.start_raises
        with self._lock:
            if binding.instance_ref != self.instance_ref or attempt_id in self._tombstones:
                return StartAck.NOT_STARTED
            ack = self.start_ack
            if ack is StartAck.ACCEPTED or (ack is StartAck.UNKNOWN and self.execute_when_unknown):
                self._accepted[attempt_id] = request
            return ack

    def await_result(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> Completed | Failed:
        self._record("await_result", attempt_id, binding.instance_ref)
        timeout = None if self.ignore_deadline else deadline_seconds
        if not self.await_gate.hold(timeout):
            return Failed(
                "deadline", "The attempt did not finish in time.", Knowledge.POSSIBLY_ACTIVE
            )
        if self.await_raises is not None:
            raise self.await_raises
        with self._lock:
            request = self._accepted.pop(attempt_id, None)
        if request is None:
            return Failed("not_started", "The attempt was not started.", Knowledge.NEVER_REACHED)
        delivering = self.delivered_instance_ref or binding.instance_ref
        if self.result is not None:
            outcome = self.result(request)
            if isinstance(outcome, Completed):
                return Completed(outcome.content, delivering, outcome.model_label, outcome.complete)
            return outcome
        return Completed(
            content=self.reply,
            instance_ref=delivering,
            model_label=self.delivered_model_label or self.model_id,
        )

    def stop(self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float) -> StopAck:
        self._record("stop", attempt_id, binding.instance_ref)
        self.stop_gate.hold()
        with self._lock:
            if binding.instance_ref != self.instance_ref:
                return StopAck.INSTANCE_MISMATCH
            if attempt_id not in self._accepted:
                self._tombstones.add(attempt_id)
            return self.stop_ack

    def probe(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> ProbeResult:
        self._record("probe", attempt_id, binding.instance_ref)
        self.probe_gate.hold()
        with self._lock:
            if binding.instance_ref != self.instance_ref:
                return ProbeResult(ProbeKind.INSTANCE_MISMATCH)
            if self.probe_script:
                return self.probe_script.popleft()
            return self.probe_default
