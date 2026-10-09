"""Domain and application error vocabulary.

Each error carries a stable machine ``code`` and a message that is safe to show to a client: it
never contains message content, credentials or filesystem paths.
"""

from __future__ import annotations


class AnonymousError(Exception):
    code = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)
        self.public_message = message or "An internal error occurred."


class InvalidIdentifier(AnonymousError):
    code = "invalid_identifier"


class InvalidMessage(AnonymousError):
    code = "invalid_message"


class InvalidTitle(AnonymousError):
    code = "invalid_title"


class ConversationNotFound(AnonymousError):
    code = "conversation_not_found"


class ConversationBusy(AnonymousError):
    """A generation is pending, in flight or unresolved; a new send is refused, not queued."""

    code = "conversation_busy"


class IdempotencyConflict(AnonymousError):
    """A submission id was reused with a different meaning (content or target conversation)."""

    code = "idempotency_conflict"


class StorageFailure(AnonymousError):
    """A persistence operation failed and is known NOT to have been committed."""

    code = "storage_unavailable"


class StorageOutcomeUnknown(AnonymousError):
    """A failure occurred while committing; the operation may or may not be durable."""

    code = "storage_outcome_unknown"


class RunStateConflict(AnonymousError):
    """A run was not in the state an operation required (e.g. already settled)."""

    code = "run_state_conflict"
