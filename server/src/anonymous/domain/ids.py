"""Stable identities.

Identities are opaque UUIDs. Their meaning never derives from names, models, devices, order or
time (INV-001, INV-002, INV-008, INV-009). The canonical string form (lowercase, hyphenated) is an
implementation-local encoding, not an architectural mandate.
"""

from __future__ import annotations

import uuid
from typing import NewType

UserId = NewType("UserId", str)
ConversationId = NewType("ConversationId", str)
MessageId = NewType("MessageId", str)
RunId = NewType("RunId", str)
SubmissionId = NewType("SubmissionId", str)


def new_uuid() -> str:
    return str(uuid.uuid4())


def parse_uuid(value: str) -> str | None:
    """Return the canonical form of ``value`` if it is a UUID, otherwise ``None``.

    Only the canonical hyphenated representation is accepted so that one identity has exactly one
    spelling (``uuid.UUID`` alone would also accept braces, urn: prefixes and bare hex).
    """
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None
