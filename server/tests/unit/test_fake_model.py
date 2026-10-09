from __future__ import annotations

import pytest

from anonymous.adapters.model.fake import FAIL_TRIGGER, FakeModelAdapter
from anonymous.application.ports.model import ContextMessage, ModelExecutionError, ModelRequest
from anonymous.domain.models import MessageRole


def request(*pairs: tuple[MessageRole, str]) -> ModelRequest:
    return ModelRequest(messages=tuple(ContextMessage(r, c) for r, c in pairs))


def test_reply_is_deterministic_and_reports_identity() -> None:
    model = FakeModelAdapter()
    req = request((MessageRole.USER, "hello"))
    first, second = model.generate(req), model.generate(req)
    assert first == second
    assert first.content == "Fake reply to: hello (context messages: 1)"
    assert first.identity == model.identity
    assert model.identity.model_id != model.identity.runtime_id  # distinct concepts


def test_reply_depends_on_constructed_view() -> None:
    model = FakeModelAdapter()
    one = model.generate(request((MessageRole.USER, "hi")))
    two = model.generate(
        request(
            (MessageRole.USER, "earlier"),
            (MessageRole.ASSISTANT, "answer"),
            (MessageRole.USER, "hi"),
        )
    )
    assert one.content != two.content
    assert "context messages: 3" in two.content


def test_failure_trigger_raises_structured_error() -> None:
    with pytest.raises(ModelExecutionError) as caught:
        FakeModelAdapter().generate(request((MessageRole.USER, f"please {FAIL_TRIGGER}")))
    assert caught.value.code == "fake_failure"
    assert "please" not in caught.value.public_message  # never echoes message content


def test_no_user_message_is_an_error() -> None:
    with pytest.raises(ModelExecutionError):
        FakeModelAdapter().generate(request((MessageRole.ASSISTANT, "x")))
