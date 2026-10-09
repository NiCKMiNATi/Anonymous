"""Encoding of absolute instants for storage and the wire (shared by adapters and the API).

Fixed-width UTC text with microseconds and a literal ``Z``. This is an implementation-local
encoding (LD-01 stays open); it is deliberately unambiguous and independent of any client
timezone. Naive datetimes are rejected so a local-time value can never be stored by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime

_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def encode_instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("instants must be timezone-aware")
    return value.astimezone(UTC).strftime(_FORMAT)


def decode_instant(text: str) -> datetime:
    return datetime.strptime(text, _FORMAT).replace(tzinfo=UTC)
