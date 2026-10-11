"""Test doubles shared across the backend suite."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import baseline_manifest
from anonymous.application.ports.model import (
    ModelExecutionError,
    ModelIdentity,
    ModelOutput,
    ModelRequest,
)
from anonymous.domain.errors import StorageFailure, StorageOutcomeUnknown
from anonymous.domain.ids import UserId
from anonymous.domain.models import Conversation

START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class ManualClock:
    """Auto-advancing by ``step`` per call (0 = frozen). Can be forced to arbitrary values."""

    def __init__(self, start: datetime = START, step: timedelta = timedelta(seconds=1)) -> None:
        self.current = start
        self.step = step
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            value = self.current
            self.current = value + self.step
            return value


class SequenceClock:
    """Returns the given instants in order (then repeats the last)."""

    def __init__(self, values: Sequence[datetime]) -> None:
        self._values = list(values)
        self._index = 0

    def now(self) -> datetime:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


class RecordingModel:
    """A ``ModelPort`` double that records requests and can run a hook or fail."""

    def __init__(
        self,
        reply: str = "test reply",
        *,
        on_generate: Callable[[ModelRequest], None] | None = None,
        error: Exception | None = None,
        identity: ModelIdentity | None = None,
        output_identity: ModelIdentity | None = None,
    ) -> None:
        self._identity = identity or ModelIdentity("test-model-1", "test-runtime-1")
        self._output_identity = output_identity or self._identity
        self.reply = reply
        self.on_generate = on_generate
        self.error = error
        self.requests: list[ModelRequest] = []

    @property
    def identity(self) -> ModelIdentity:
        return self._identity

    def generate(self, request: ModelRequest) -> ModelOutput:
        self.requests.append(request)
        if self.on_generate is not None:
            self.on_generate(request)
        if self.error is not None:
            raise self.error
        return ModelOutput(content=self.reply, identity=self._output_identity)


def failing_model() -> RecordingModel:
    return RecordingModel(error=ModelExecutionError("boom_code", "Simulated runtime failure."))


@dataclass(slots=True)
class Fault:
    """One scripted fault for one operation. ``kind``:

    * ``pass``            — forward unchanged (skips one call in the script);
    * ``fail``            — raise ``StorageFailure``; the store is not called (known not saved);
    * ``unknown_lost``    — raise ``StorageOutcomeUnknown`` without calling the store;
    * ``unknown_durable`` — call the store (the write commits), then raise the unknown outcome;
    * ``before`` / ``after`` — run ``hook`` before / after the real call (scheduling probe);
    * ``raise``           — raise ``error``.
    """

    kind: str
    hook: Callable[[], None] | None = None
    error: Exception | None = None


_LEGACY_ATTRIBUTES = {
    "fail_admit": ("admit_submission", "admit_retry"),
    "fail_dispatch": ("authorize_dispatch",),
    "fail_publish": ("publish_response",),
    "fail_settle": ("settle_pending", "settle_in_flight", "settle_indeterminate"),
}


class FaultyExecutionStore:
    """Delegates to a real store but injects failures at chosen operations.

    ``fail_*`` attributes make every call of the mapped operations raise; ``script(op, *faults)``
    queues faults consumed one per call (then calls pass through).
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.fail_admit: Exception | None = None
        self.fail_dispatch: Exception | None = None
        self.fail_publish: Exception | None = None
        self.fail_settle: Exception | None = None
        self._scripts: dict[str, deque[Fault]] = {}
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def script(self, operation: str, *faults: Fault) -> None:
        with self._lock:
            self._scripts.setdefault(operation, deque()).extend(faults)

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            for attribute, operations in _LEGACY_ATTRIBUTES.items():
                error = getattr(self, attribute)
                if error is not None and name in operations:
                    raise error
            with self._lock:
                queue = self._scripts.get(name)
                fault = queue.popleft() if queue else None
            if fault is None:
                return target(*args, **kwargs)
            if fault.kind == "pass":
                return target(*args, **kwargs)
            if fault.kind == "fail":
                raise StorageFailure("injected storage failure")
            if fault.kind == "unknown_lost":
                raise StorageOutcomeUnknown("injected unknown outcome")
            if fault.kind == "unknown_durable":
                target(*args, **kwargs)
                raise StorageOutcomeUnknown("injected unknown outcome")
            if fault.kind == "raise":
                assert fault.error is not None
                raise fault.error
            if fault.kind == "before":
                assert fault.hook is not None
                fault.hook()
                return target(*args, **kwargs)
            if fault.kind == "after":
                result = target(*args, **kwargs)
                assert fault.hook is not None
                fault.hook()
                return result
            raise AssertionError(f"unknown fault kind {fault.kind}")

        return call


class BoundStore(SqliteStore):
    """A store whose ``create_conversation`` binds the shipped default configuration, like the
    application service does, so lower-level tests need not repeat the digest."""

    def create_conversation(
        self, owner: UserId, title: str | None, configuration_digest: str | None = None
    ) -> Conversation:
        return super().create_conversation(
            owner, title, configuration_digest or baseline_manifest().digest
        )


STORAGE_FAILURE = StorageFailure("injected storage failure")
STORAGE_UNKNOWN = StorageOutcomeUnknown("injected unknown outcome")


class Scheduler:
    """Controlled scheduling: named checkpoints in the coordinator can be held and released.

    Usage: ``point = scheduler.hold("after_t3b")``; the supervised thread blocks when it reaches
    that point; the test calls ``point.wait_reached()``, does something, then ``point.release()``.
    ``events`` records every checkpoint passed, in order, for ordering assertions.
    """

    class Point:
        def __init__(self) -> None:
            self.reached = threading.Event()
            self._release = threading.Event()

        def wait_reached(self, timeout: float = 5.0) -> bool:
            return self.reached.wait(timeout)

        def release(self) -> None:
            self._release.set()

    def __init__(self) -> None:
        self._points: dict[str, Scheduler.Point] = {}
        self._lock = threading.Lock()
        self.events: list[str] = []
        self.hooks: dict[str, Callable[[str], None]] = {}

    def hold(self, name: str) -> Scheduler.Point:
        point = Scheduler.Point()
        with self._lock:
            self._points[name] = point
        return point

    def __call__(self, name: str, run_id: str) -> None:
        with self._lock:
            self.events.append(name)
            point = self._points.pop(name, None)
        hook = self.hooks.get(name)
        if hook is not None:
            hook(run_id)
        if point is not None:
            point.reached.set()
            assert point._release.wait(10), f"checkpoint {name} was never released"
