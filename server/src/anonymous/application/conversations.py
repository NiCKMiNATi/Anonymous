"""Conversation application service (C04): create/list/open/send.

Parses and validates identifiers at the application boundary, then routes to the persistence
contract or to the execution coordinator. C04 calls C05; C05 never calls back.
"""

from __future__ import annotations

from anonymous.application.configuration import ConfigurationCatalog, ConfigurationService
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.persistence import (
    ConfigurationBinding,
    ConversationHistory,
    ConversationStore,
    SubmissionOutcome,
)
from anonymous.domain.errors import InvalidIdentifier
from anonymous.domain.ids import ConversationId, MessageId, SubmissionId, UserId, parse_uuid
from anonymous.domain.models import Conversation, validate_title


def parse_conversation_id(raw: str) -> ConversationId:
    parsed = parse_uuid(raw)
    if parsed is None:
        raise InvalidIdentifier("Conversation id is not a valid identifier.")
    return ConversationId(parsed)


def parse_submission_id(raw: str) -> SubmissionId:
    parsed = parse_uuid(raw)
    if parsed is None:
        raise InvalidIdentifier("Submission id is not a valid identifier.")
    return SubmissionId(parsed)


def parse_message_id(raw: str) -> MessageId:
    parsed = parse_uuid(raw)
    if parsed is None:
        raise InvalidIdentifier("Message id is not a valid identifier.")
    return MessageId(parsed)


class ConversationService:
    def __init__(
        self,
        store: ConversationStore,
        execution: ExecutionCoordinator,
        catalog: ConfigurationCatalog,
        configuration: ConfigurationService,
    ) -> None:
        self._store = store
        self._execution = execution
        self._catalog = catalog
        self._configuration = configuration

    def create_conversation(self, owner: UserId, title: str | None = None) -> Conversation:
        # A new conversation is bound to the build's default configuration, atomically with its
        # creation. An upgrade changes the default for NEW conversations only.
        return self._store.create_conversation(
            owner, validate_title(title), self._catalog.default_digest
        )

    def list_conversations(self, owner: UserId) -> tuple[Conversation, ...]:
        return self._store.list_conversations(owner)

    def open_conversation(self, owner: UserId, raw_conversation_id: str) -> ConversationHistory:
        return self._store.get_history(owner, parse_conversation_id(raw_conversation_id))

    def send_message(
        self, owner: UserId, raw_conversation_id: str, raw_submission_id: str, content: str
    ) -> SubmissionOutcome:
        return self._execution.submit(
            owner=owner,
            conversation_id=parse_conversation_id(raw_conversation_id),
            submission_id=parse_submission_id(raw_submission_id),
            content=content,
        )

    def retry_generation(
        self, owner: UserId, raw_conversation_id: str, retry_id: str, raw_message_id: str
    ) -> SubmissionOutcome:
        """Explicit retry: a new run on the same saved user message (never a new message)."""
        if parse_uuid(retry_id) is None:
            raise InvalidIdentifier("Retry id is not a valid identifier.")
        return self._execution.retry(
            owner=owner,
            conversation_id=parse_conversation_id(raw_conversation_id),
            retry_id=retry_id,
            message_id=parse_message_id(raw_message_id),
        )

    def adopt_configuration(
        self,
        owner: UserId,
        raw_conversation_id: str,
        adoption_id: str,
        digest: str,
    ) -> ConfigurationBinding:
        """Explicit adoption of a changed configuration (application-level only in 0B-1)."""
        if parse_uuid(adoption_id) is None:
            raise InvalidIdentifier("Adoption id is not a valid identifier.")
        result: ConfigurationBinding = self._configuration.adopt(
            owner, parse_conversation_id(raw_conversation_id), adoption_id, digest
        )
        return result
