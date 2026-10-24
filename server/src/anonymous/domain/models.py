"""Core domain objects for the slice: Conversation, Message, ModelRun.

These are immutable records of what Anonymous has committed. Presentation shapes live in the API
layer. Nothing here knows about SQLite, HTTP or any model runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.errors import InvalidMessage, InvalidTitle
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    RecordEpoch,
    RunKind,
)
from anonymous.domain.ids import ConversationId, MessageId, RunId, UserId
from anonymous.domain.provenance import ExecutionProvenance

MAX_MESSAGE_CHARS = 32_000
"""Placeholder input bound. The real budget depends on the runtime and is a later design gate."""

MAX_TITLE_CHARS = 200


class MessageRole(StrEnum):
    # DM §9 lists further possible authors; the V0 slice needs only these two and this is not a
    # fixed enum for the domain.
    USER = "user"
    ASSISTANT = "assistant"


class Completeness(StrEnum):
    """Whether an assistant answer ended naturally (ADR-0016). ``None`` on a message means
    unclassified: every user message and every assistant message that predates the field."""

    COMPLETE = "complete"
    TRUNCATED = "truncated"  # cut off at the model's output limit; delivered completely


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
    # T7: only with an admissible termination basis (domain.evidence); never to succeeded.
    RunStatus.INDETERMINATE: frozenset({RunStatus.FAILED}),
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
    completeness: Completeness | None = None  # assistant messages only; None = unclassified


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
    # -- LD-04 (migration 0002); defaults describe a legacy / not-yet-dispatched run ------------
    record_epoch: RecordEpoch = RecordEpoch.CURRENT
    state_version: int = 0
    kind: RunKind = RunKind.INITIAL
    retry_of_run_id: RunId | None = None
    closed_at: datetime | None = None
    closure_reason: ClosureReason | None = None
    handoff: Handoff | None = None
    handoff_outcome: HandoffOutcome | None = None
    execution_boot_id: str | None = None
    slot_id: str | None = None
    binding: ExecutionBinding | None = None
    configuration_digest: str | None = None
    provenance: ExecutionProvenance | None = None
    termination_basis: EvidenceBasis | None = None
    completion_observed: CompletionObserved | None = None

    def binding_late_delivery_excluded(self) -> bool:
        return self.binding is not None and self.binding.late_delivery_excluded


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
