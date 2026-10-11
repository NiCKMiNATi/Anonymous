from __future__ import annotations

import pytest

from anonymous.domain.errors import InvalidMessage, InvalidTitle
from anonymous.domain.ids import new_uuid, parse_uuid
from anonymous.domain.models import (
    MAX_MESSAGE_CHARS,
    RunStatus,
    can_transition,
    validate_message_content,
    validate_title,
)


@pytest.mark.parametrize("bad", ["", "   ", "\n\t "])
def test_empty_or_whitespace_message_is_rejected(bad: str) -> None:
    with pytest.raises(InvalidMessage):
        validate_message_content(bad)


def test_non_text_and_oversized_messages_are_rejected() -> None:
    with pytest.raises(InvalidMessage):
        validate_message_content(None)
    with pytest.raises(InvalidMessage):
        validate_message_content("x" * (MAX_MESSAGE_CHARS + 1))
    assert validate_message_content("x" * MAX_MESSAGE_CHARS)


def test_accepted_message_is_preserved_exactly() -> None:
    text = "  hello\n  world  "
    assert validate_message_content(text) == text  # no trimming of committed source text


def test_title_validation() -> None:
    assert validate_title(None) is None
    assert validate_title("   ") is None
    assert validate_title("  My chat ") == "My chat"
    with pytest.raises(InvalidTitle):
        validate_title("x" * 500)


def test_uuid_parsing_accepts_only_canonical_form() -> None:
    value = new_uuid()
    assert parse_uuid(value) == value
    for bad in [
        "",
        "abc",
        value.upper(),
        value.replace("-", ""),
        f"{{{value}}}",
        f"urn:uuid:{value}",
    ]:
        assert parse_uuid(bad) is None


def test_run_transitions() -> None:
    assert can_transition(RunStatus.PENDING, RunStatus.IN_FLIGHT)
    assert can_transition(RunStatus.PENDING, RunStatus.FAILED)
    assert can_transition(RunStatus.IN_FLIGHT, RunStatus.SUCCEEDED)
    assert can_transition(RunStatus.IN_FLIGHT, RunStatus.INDETERMINATE)
    assert not can_transition(RunStatus.PENDING, RunStatus.SUCCEEDED)  # never skips dispatch
    for terminal in (RunStatus.SUCCEEDED, RunStatus.FAILED):
        for target in RunStatus:
            assert not can_transition(terminal, target)
    # T7: an indeterminate run may only be settled failed (on evidence); never resumed or succeeded.
    assert can_transition(RunStatus.INDETERMINATE, RunStatus.FAILED)
    for target in (RunStatus.PENDING, RunStatus.IN_FLIGHT, RunStatus.SUCCEEDED):
        assert not can_transition(RunStatus.INDETERMINATE, target)
