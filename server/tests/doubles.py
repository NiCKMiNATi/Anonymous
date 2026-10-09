"""Test doubles shared across the backend suite."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from anonymous.application.ports.model import (
    ModelExecutionError,
    ModelIdentity,
    ModelOutput,
    ModelRequest,
)
from anonymous.domain.errors import StorageFailure, StorageOutcomeUnknown
from anonymous.domain.ids import RunId
from anonymous.domain.models import ModelRun

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


class FaultyExecutionStore:
    """Delegates to a real store but injects failures at chosen checkpoints."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.fail_admit: Exception | None = None
        self.fail_dispatch: Exception | None = None
        self.fail_publish: Exception | None = None
        self.fail_settle: Exception | None = None

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def admit_submission(self, **kwargs: object) -> object:
        if self.fail_admit:
            raise self.fail_admit
        return self._inner.admit_submission(**kwargs)  # type: ignore[attr-defined]

    def record_dispatch(self, run_id: RunId, model_id: str, runtime_id: str) -> ModelRun:
        if self.fail_dispatch:
            raise self.fail_dispatch
        return self._inner.record_dispatch(run_id, model_id, runtime_id)  # type: ignore[attr-defined, no-any-return]

    def publish_response(self, run_id: RunId, content: str) -> object:
        if self.fail_publish:
            raise self.fail_publish
        return self._inner.publish_response(run_id, content)  # type: ignore[attr-defined]

    def settle_failed(self, run_id: RunId, code: str, message: str) -> ModelRun:
        if self.fail_settle:
            raise self.fail_settle
        return self._inner.settle_failed(run_id, code, message)  # type: ignore[attr-defined, no-any-return]


STORAGE_FAILURE = StorageFailure("injected storage failure")
STORAGE_UNKNOWN = StorageOutcomeUnknown("injected unknown outcome")
