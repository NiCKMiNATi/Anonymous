from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Wall-clock instants as timezone-aware UTC. Not monotonic; never used for ordering."""

    def now(self) -> datetime:
        return datetime.now(UTC)
