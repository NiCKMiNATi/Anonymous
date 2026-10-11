"""Runtime configuration from environment variables. Development defaults only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_PORT = 8000
DEFAULT_DEV_CLIENT_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://[::1]:5173",
)
# URL authority forms of the loopback names above. An IPv6 literal is bracketed in a Host header
# and in an Origin (RFC 3986/6454), unlike the bare ``::1`` accepted by the CLI.
_LOOPBACK_AUTHORITIES = ("127.0.0.1", "localhost", "[::1]")


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path = Path(".anonymous-data/anonymous-0b1-dev.sqlite3")
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    client_dist: Path | None = None
    fake_delay_seconds: float = 0.0
    extra_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_DEV_CLIENT_ORIGINS
    )

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        dist = os.environ.get("ANONYMOUS_CLIENT_DIST")
        return cls(
            db_path=Path(os.environ.get("ANONYMOUS_DB_PATH", str(defaults.db_path))),
            host=os.environ.get("ANONYMOUS_HOST", defaults.host),
            port=int(os.environ.get("ANONYMOUS_PORT", defaults.port)),
            client_dist=Path(dist) if dist else None,
            fake_delay_seconds=float(os.environ.get("ANONYMOUS_FAKE_DELAY_SECONDS", "0")),
        )

    def allowed_hosts(self) -> tuple[str, ...]:
        """Host header values (without port) accepted. Loopback names only (DNS-rebinding guard)."""
        return _LOOPBACK_AUTHORITIES

    def allowed_origins(self) -> frozenset[str]:
        """Exact origins accepted: this server's own loopback origins plus the dev client origins.

        Same-origin forms mirror ``allowed_hosts`` (including bracketed IPv6) on the configured
        port, so a page served from any supported loopback address can make its own requests.
        Nothing is matched by wildcard or prefix.
        """
        same_origin = {f"http://{authority}:{self.port}" for authority in _LOOPBACK_AUTHORITIES}
        return frozenset(same_origin | set(self.extra_allowed_origins))
