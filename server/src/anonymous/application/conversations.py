"""Conversation application service (C04): create/list/open/send.

Parses and validates identifiers at the application boundary, then routes to the persistence
contract or to the execution coordinator. C04 calls C05; C05 never calls back.
"""

from __future__ import annotations

from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.persistence import (
    ConversationHistory,
    ConversationStore,
    SubmissionOutcome,
)
from anonymous.domain.errors import InvalidIdentifier
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, parse_uuid
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


class ConversationService:
    def __init__(self, store: ConversationStore, execution: ExecutionCoordinator) -> None:
        self._store = store
        self._execution = execution

    def create_conversation(self, owner: UserId, title: str | None = None) -> Conversation:
        return self._store.create_conversation(owner, validate_title(title))

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
