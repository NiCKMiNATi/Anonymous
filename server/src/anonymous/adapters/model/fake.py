"""FakeModelAdapter — a deterministic stand-in for a real runtime behind ``ModelPort``.

The reply is a pure function of the constructed view, so tests and manual runs are repeatable.
The adapter knows nothing about conversations, persistence or HTTP; swapping it for a real
runtime adapter must not require changes outside composition.

Development conveniences (adapter behavior, not application behavior):

* a user message containing ``[fake:fail]`` makes this adapter fail, to exercise the failure path;
* ``delay_seconds`` simulates latency so loading states can be observed.
"""

from __future__ import annotations

import time

from anonymous.application.ports.model import (
    ModelExecutionError,
    ModelIdentity,
    ModelOutput,
    ModelRequest,
)
from anonymous.domain.models import MessageRole

FAIL_TRIGGER = "[fake:fail]"

FAKE_IDENTITY = ModelIdentity(model_id="fake-echo-1", runtime_id="fake-in-process-runtime-1")


class FakeModelAdapter:
    def __init__(self, delay_seconds: float = 0.0) -> None:
        self._delay_seconds = delay_seconds

    @property
    def identity(self) -> ModelIdentity:
        return FAKE_IDENTITY

    def generate(self, request: ModelRequest) -> ModelOutput:
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role is MessageRole.USER), None
        )
        if last_user is None:
            raise ModelExecutionError("fake_no_user_message", "The request had no user message.")
        if FAIL_TRIGGER in last_user:
            raise ModelExecutionError("fake_failure", "The fake model was asked to fail.")
        return ModelOutput(
            content=f"Fake reply to: {last_user} (context messages: {len(request.messages)})",
            identity=self.identity,
        )
