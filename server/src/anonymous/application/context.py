"""Context Builder (C06): the transient model view of a conversation (INV-015).

Two builders exist, one per shipped configuration (ADR-0014, ADR-0017). Neither mutates, deletes
or persists anything, and neither contributes anything but role and content to the view.

* ``ContextBuilder`` (``whole-history@1``): the committed prefix through the triggering user
  message, whole, roles and order preserved. It is the Slice 0A behavior pinned by the golden
  replay and is unchanged; nothing is ever omitted, and an over-capacity prefix is refused by the
  worker's capacity check.
* ``BoundedRecentContextBuilder`` (``bounded-recent-history@1``): a contiguous suffix of that
  prefix that fits the runtime's declared character limit.
"""

from __future__ import annotations

from dataclasses import dataclass

from anonymous.application.ports.model import ContextMessage, ModelRequest
from anonymous.application.ports.persistence import HistorySource
from anonymous.domain.models import Completeness, Message
from anonymous.domain.provenance import ContextSelection


@dataclass(frozen=True, slots=True)
class ContextView:
    """A built request and, for a bounded builder, what it selected. ``selection`` is ``None``
    for a whole-history view (unrecorded, not "nothing omitted")."""

    request: ModelRequest
    selection: ContextSelection | None = None


def _request(messages: tuple[Message, ...]) -> ModelRequest:
    return ModelRequest(
        messages=tuple(ContextMessage(role=m.role, content=m.content) for m in messages)
    )


class ContextBuilder:
    def __init__(self, source: HistorySource) -> None:
        self._source = source

    def build(self, triggering_message: Message) -> ModelRequest:
        prefix = self._source.read_messages_through(
            triggering_message.conversation_id, triggering_message.id
        )
        return _request(prefix)

    def build_view(self, triggering_message: Message, limit_chars: int | None) -> ContextView:
        """The whole history; ``limit_chars`` is not used (the worker's capacity check refuses)."""
        return ContextView(self.build(triggering_message))


def select_recent(prefix: tuple[Message, ...], limit_chars: int | None) -> tuple[Message, ...]:
    """The contiguous suffix of ``prefix`` (which ends with the triggering message) whose
    characters fit ``limit_chars``. A pure function of its arguments.

    The triggering message is always selected, even if it alone exceeds the limit: the worker's
    capacity check then refuses before dispatch, so it is never silently dropped or cut. Older
    messages are added one at a time, newest first, and selection stops at the first one that does
    not fit; a smaller message beyond it is never reached.
    """
    if not prefix:
        raise ValueError("the history must contain the triggering message")
    if limit_chars is None:
        return prefix
    first = len(prefix) - 1
    total = len(prefix[first].content)
    while first > 0 and total + len(prefix[first - 1].content) <= limit_chars:
        first -= 1
        total += len(prefix[first].content)
    return prefix[first:]


class BoundedRecentContextBuilder:
    def __init__(self, source: HistorySource) -> None:
        self._source = source

    def build(self, triggering_message: Message) -> ModelRequest:
        """Unlimited input: identical to the whole-history view (the golden replay uses this)."""
        return self.build_view(triggering_message, None).request

    def build_view(self, triggering_message: Message, limit_chars: int | None) -> ContextView:
        prefix = self._source.read_messages_through(
            triggering_message.conversation_id, triggering_message.id
        )
        selected = select_recent(prefix, limit_chars)
        first = selected[0]
        return ContextView(
            request=_request(selected),
            selection=ContextSelection(
                first_message_id=first.id,
                first_position=first.position,
                selected_count=len(selected),
                omitted_count=len(prefix) - len(selected),
                selected_chars=sum(len(m.content) for m in selected),
                limit_chars=limit_chars,
                truncated_included_count=sum(
                    1 for m in selected if m.completeness is Completeness.TRUNCATED
                ),
            ),
        )
