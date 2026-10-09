"""Persistence ports (ADR-0004, C08).

Purpose-specific contracts, deliberately *not* a universal repository: each use case sees only the
guarantees it needs. Adapters report evidence sufficient to tell apart:

* confirmed  — the method returned;
* failed     — ``StorageFailure`` (known not committed);
* unknown    — ``StorageOutcomeUnknown`` (error while committing; may be durable).

Every method that touches user data is scoped to an owner (FR-14); another owner's data behaves
as not found.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from anonymous.domain.ids import ConversationId, MessageId, RunId, SubmissionId, UserId
from anonymous.domain.models import Conversation, Message, ModelRun


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current absolute instant as a timezone-aware UTC datetime."""
        ...


@dataclass(frozen=True, slots=True)
class ConversationHistory:
    conversation: Conversation
    messages: tuple[Message, ...]  # authoritative order (by position)
    runs: tuple[ModelRun, ...]  # every attempt, oldest first, including failed ones


@dataclass(frozen=True, slots=True)
class SubmissionOutcome:
    """Current authoritative state of one accepted submission."""

    user_message: Message
    run: ModelRun
    assistant_message: Message | None
    replayed: bool  # True when this call resolved an already accepted submission


@dataclass(frozen=True, slots=True)
class PublishedResponse:
    message: Message
    run: ModelRun  # the run as settled (``succeeded``) by the same atomic publication


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    settled_failed: int  # pending runs that provably never dispatched
    marked_indeterminate: int  # in-flight runs whose outcome cannot be established


class ConversationStore(Protocol):
    def create_conversation(self, owner: UserId, title: str | None) -> Conversation: ...

    def list_conversations(self, owner: UserId) -> tuple[Conversation, ...]: ...

    def get_history(self, owner: UserId, conversation_id: ConversationId) -> ConversationHistory:
        """Raise ``ConversationNotFound`` if absent or not owned. Never returns a fabricated
        empty history when reading fails (raises ``StorageFailure`` instead)."""
        ...


class ExecutionStore(Protocol):
    def admit_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
        content_sha256: str,
    ) -> SubmissionOutcome:
        """Atomically (CB-02): resolve replay/conflict, check ownership and admission, then commit
        the user message, a ``pending`` run and the submission association.

        Raises ``ConversationNotFound``, ``ConversationBusy`` or ``IdempotencyConflict``.
        """
        ...

    def record_dispatch(self, run_id: RunId, model_id: str, runtime_id: str) -> ModelRun:
        """``pending -> in_flight`` with identities recorded before invocation."""
        ...

    def publish_response(self, run_id: RunId, content: str) -> PublishedResponse:
        """Atomically (CB-04) commit the assistant message and mark the run ``succeeded``."""
        ...

    def settle_failed(self, run_id: RunId, code: str, message: str) -> ModelRun:
        """Settle a ``pending`` or ``in_flight`` run as ``failed``; commits no assistant message."""
        ...

    def recover_unsettled_runs(self) -> RecoveryReport:
        """Startup disposition. Never dispatches work and never marks anything successful."""
        ...


class HistorySource(Protocol):
    """Read-only access for the Context Builder (C06)."""

    def read_messages_through(
        self, conversation_id: ConversationId, last_message_id: MessageId
    ) -> tuple[Message, ...]:
        """Committed messages from the start of the conversation up to and including
        ``last_message_id``, in authoritative order."""
        ...
