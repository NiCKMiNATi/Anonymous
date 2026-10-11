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
from enum import StrEnum
from typing import Protocol

from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.configuration import BindingOrigin
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    HandoffOutcome,
)
from anonymous.domain.ids import ConversationId, MessageId, RunId, SubmissionId, UserId
from anonymous.domain.models import Conversation, Message, ModelRun, RunStatus
from anonymous.domain.provenance import ExecutionProvenance


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


class WriteResult(StrEnum):
    """Outcome of a conditional write on the run record (the arbiter, design §4.1)."""

    APPLIED = "applied"
    WRONG_SOURCE = "wrong_source"  # the run is not in this transition's source state
    FENCE_CLOSED = "fence_closed"  # T3b after closure: start must not be called
    ALREADY_STARTED = "already_started"
    ALREADY_CLOSED = "already_closed"
    PUBLISHED = "published"  # publication won; the run is succeeded
    SETTLED = "settled"  # the run is already failed; the stored result stands
    ALREADY_INDETERMINATE = "already_indeterminate"
    STALE_VERSION = "stale_version"
    SLOT_BUSY = "slot_busy"
    LEGACY_BLOCKED = "legacy_blocked"
    NO_ADMISSIBLE_BASIS = "no_admissible_basis"


@dataclass(frozen=True, slots=True)
class Transition:
    result: WriteResult
    run: ModelRun  # the stored state after the call (after the write when ``APPLIED``)
    holder_status: RunStatus | None = None  # SLOT_BUSY: status of the run owning the slot


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    result: WriteResult
    run: ModelRun
    published: PublishedResponse | None = None  # APPLIED, or PUBLISHED with the original message


@dataclass(frozen=True, slots=True)
class DispatchRecord:
    """Everything T3 records durably before any external call."""

    binding: ExecutionBinding
    provenance: ExecutionProvenance
    configuration_digest: str
    slot_id: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class ConfigurationBinding:
    conversation_id: ConversationId
    seq: int
    configuration_digest: str
    origin: BindingOrigin
    baseline_evidence: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LegacyBlocker:
    run_id: RunId
    conversation_id: ConversationId
    status: RunStatus
    runtime_label: str | None  # descriptive only; never evidence


@dataclass(frozen=True, slots=True)
class GenerationState:
    legacy_blockers: tuple[LegacyBlocker, ...]
    quarantined_runs: tuple[RunId, ...]  # 0B runs holding the slot while indeterminate


class ConversationStore(Protocol):
    def create_conversation(
        self, owner: UserId, title: str | None, configuration_digest: str | None = None
    ) -> Conversation: ...

    def list_conversations(self, owner: UserId) -> tuple[Conversation, ...]: ...

    def get_history(self, owner: UserId, conversation_id: ConversationId) -> ConversationHistory:
        """Raise ``ConversationNotFound`` if absent or not owned. Never returns a fabricated
        empty history when reading fails (raises ``StorageFailure`` instead)."""
        ...


class ExecutionStore(Protocol):
    """Every method is one short transaction; none is held across any external call."""

    def find_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content_sha256: str,
    ) -> SubmissionOutcome | None:
        """Resolve an already accepted submission (replay) or ``None``; ``IdempotencyConflict``
        if the id was used for something else."""
        ...

    def admit_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
        content_sha256: str,
        executable_digests: frozenset[str] | None = None,
    ) -> SubmissionOutcome:
        """T1 (CB-02): replay/conflict, ownership, admission, generation blocks; then commit the
        user message, a ``pending`` run and the submission association atomically."""
        ...

    def admit_retry(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        retry_id: str,
        message_id: MessageId,
        executable_digests: frozenset[str] | None = None,
    ) -> SubmissionOutcome:
        """T1 for an explicit retry on the same saved user message (design §8.2)."""
        ...

    def get_run(self, run_id: RunId) -> ModelRun: ...

    def get_outcome(self, run_id: RunId) -> tuple[ModelRun, Message, Message | None]:
        """The run, its triggering user message and its assistant message, if any."""
        ...

    def settle_pending(self, run_id: RunId, code: str, message: str) -> Transition:
        """T2: ``pending`` → ``failed`` (never dispatched)."""
        ...

    def authorize_dispatch(self, run_id: RunId, record: DispatchRecord) -> Transition:
        """T3: ``pending`` → ``in_flight``: binding, provenance, configuration, slot, boot id."""
        ...

    def mark_handoff_started(self, run_id: RunId, boot_id: str) -> Transition:
        """T3b: ``handoff NONE → STARTED`` while the fence is open. ``FENCE_CLOSED`` ⇒ do not
        call ``start``."""
        ...

    def record_handoff_outcome(self, run_id: RunId, outcome: HandoffOutcome) -> Transition:
        """T3c (best effort; if lost the outcome stays unrecorded, treated as UNKNOWN)."""
        ...

    def publish_response(self, run_id: RunId, content: str) -> PublishOutcome:
        """T4: assistant message + ``succeeded`` atomically; needs an open fence and a started
        handoff. An already published run returns ``PUBLISHED`` with the original message."""
        ...

    def close_run(
        self, run_id: RunId, reason: ClosureReason, expected_version: int | None = None
    ) -> Transition:
        """T5c: close the fence of an ``in_flight`` run; ``PUBLISHED`` if publication won."""
        ...

    def settle_in_flight(
        self,
        run_id: RunId,
        *,
        basis: EvidenceBasis,
        code: str,
        message: str,
        completion: CompletionObserved,
        reason: ClosureReason,
        expected_version: int | None = None,
    ) -> Transition:
        """T5: ``in_flight`` → ``failed`` (closing the fence in the same write if open)."""
        ...

    def mark_indeterminate(self, run_id: RunId, expected_version: int) -> Transition:
        """T6: closed ``in_flight`` → ``indeterminate`` (quarantine)."""
        ...

    def settle_indeterminate(
        self,
        run_id: RunId,
        *,
        basis: EvidenceBasis,
        code: str,
        message: str,
        completion: CompletionObserved,
        expected_version: int,
    ) -> Transition:
        """T7: ``indeterminate`` → ``failed`` on an admissible basis; idempotent."""
        ...

    def recover_pending_runs(self) -> int:
        """Startup: settle every ``pending`` run T2/B1. Never touches ``in_flight`` runs."""
        ...

    def list_pending_runs(self) -> tuple[ModelRun, ...]:
        """Every ``pending`` run (accepted, never dispatched)."""
        ...

    def list_unresolved_runs(self) -> tuple[ModelRun, ...]:
        """Every run in ``in_flight`` or ``indeterminate`` (any epoch)."""
        ...

    def generation_state(self) -> GenerationState: ...

    # -- configuration ------------------------------------------------------------------------

    def register_configuration(self, digest: str, canonical: str) -> bool:
        """Insert if absent. ``False`` if a different manifest is stored under the digest."""
        ...

    def get_configuration_manifest(self, digest: str) -> str | None: ...

    def get_current_binding(
        self, conversation_id: ConversationId
    ) -> ConfigurationBinding | None: ...

    def bind_legacy_conversations(self, digest: str, evidence: str) -> int:
        """Append a ``legacy_baseline`` binding to every pre-0B conversation without one."""
        ...

    def adopt_configuration(
        self, owner: UserId, conversation_id: ConversationId, adoption_id: str, digest: str
    ) -> ConfigurationBinding: ...


class HistorySource(Protocol):
    """Read-only access for the Context Builder (C06)."""

    def read_messages_through(
        self, conversation_id: ConversationId, last_message_id: MessageId
    ) -> tuple[Message, ...]:
        """Committed messages from the start of the conversation up to and including
        ``last_message_id``, in authoritative order."""
        ...
