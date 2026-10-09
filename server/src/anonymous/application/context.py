"""Context Builder (C06) — minimal for this slice.

Builds the transient model view from the committed prefix of a conversation through the
triggering user message: whole history, roles and order preserved, nothing from other
conversations, no Memory. There is no budget yet (LD-06), so nothing is omitted. The view is
never persisted as authoritative data (INV-015).
"""

from __future__ import annotations

from anonymous.application.ports.model import ContextMessage, ModelRequest
from anonymous.application.ports.persistence import HistorySource
from anonymous.domain.models import Message


class ContextBuilder:
    def __init__(self, source: HistorySource) -> None:
        self._source = source

    def build(self, triggering_message: Message) -> ModelRequest:
        prefix = self._source.read_messages_through(
            triggering_message.conversation_id, triggering_message.id
        )
        return ModelRequest(
            messages=tuple(ContextMessage(role=m.role, content=m.content) for m in prefix)
        )
