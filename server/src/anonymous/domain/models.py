"""Core domain objects for the slice: Conversation, Message, ModelRun.

These are immutable records of what Anonymous has committed. Presentation shapes live in the API
layer. Nothing here knows about SQLite, HTTP or any model runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from anonymous.domain.errors import InvalidMessage, InvalidTitle
from anonymous.domain.ids import ConversationId, MessageId, RunId, UserId

MAX_MESSAGE_CHARS = 32_000
"""Placeholder input bound. The real budget depends on the runtime and is a later design gate."""

MAX_TITLE_CHARS = 200


class MessageRole(StrEnum):
    # DM §9 lists further possible authors; the V0 slice needs only these two and this is not a
    # fixed enum for the domain.
    USER = "user"
    ASSISTANT = "assistant"


class RunStatus(StrEnum):
    PENDING = "pending"  # accepted, user message committed, not yet dispatched
    IN_FLIGHT = "in_flight"  # dispatch association durable; invocation may have happened
    SUCCEEDED = "succeeded"  # assistant response committed with this run
    FAILED = "failed"  # settled without a response
    INDETERMINATE = "indeterminate"  # outcome cannot be established; keeps admission closed


UNSETTLED_STATUSES = frozenset({RunStatus.PENDING, RunStatus.IN_FLIGHT, RunStatus.INDETERMINATE})
TERMINAL_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED})

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.IN_FLIGHT, RunStatus.FAILED}),
    RunStatus.IN_FLIGHT: frozenset(
        {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.INDETERMINATE}
    ),
    RunStatus.INDETERMINATE: frozenset(),  # resolution is deferred (see ExecPlan)
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class Conversation:
    id: ConversationId
    owner_id: UserId
    title: str | None  # presentation metadata, not identity
    created_at: datetime  # absolute instant (UTC)


@dataclass(frozen=True, slots=True)
class Message:
    id: MessageId
    conversation_id: ConversationId
    position: int  # server-authoritative order within the conversation; NOT derived from time
    role: MessageRole
    content: str
    committed_at: datetime  # absolute instant of commitment; never an ordering authority
    produced_by_run_id: RunId | None  # set for assistant messages only


@dataclass(frozen=True, slots=True)
class ModelRun:
    id: RunId
    conversation_id: ConversationId
    triggering_message_id: MessageId
    status: RunStatus
    model_id: str | None  # recorded at dispatch, before invocation
    runtime_id: str | None
    failure_code: str | None
    failure_message: str | None  # sanitized; never message content
    requested_at: datetime  # execution timing, distinct from message commit instants
    dispatched_at: datetime | None
    settled_at: datetime | None


def validate_message_content(content: object) -> str:
    """Return ``content`` unchanged if it is an acceptable user message, else raise.

    Committed text is preserved exactly as submitted (no trimming); only content that is empty or
    whitespace-only is refused.
    """
    if not isinstance(content, str):
        raise InvalidMessage("Message content must be text.")
    if not content.strip():
        raise InvalidMessage("Message must not be empty.")
    if len(content) > MAX_MESSAGE_CHARS:
        raise InvalidMessage(f"Message is longer than {MAX_MESSAGE_CHARS} characters.")
    return content


def validate_title(title: object) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str):
        raise InvalidTitle("Title must be text.")
    stripped = title.strip()
    if not stripped:
        return None
    if len(stripped) > MAX_TITLE_CHARS:
        raise InvalidTitle(f"Title is longer than {MAX_TITLE_CHARS} characters.")
    return stripped
