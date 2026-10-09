"""Local-development request guards and response hardening (pure ASGI).

NOT AUTHENTICATION. Slice 0A has no device/session authority (ADR-0005/0009 are not implemented).
These guards only reduce accidental or cross-site exposure of the unauthenticated loopback API:

* ``Host`` must be a loopback name — blocks DNS-rebinding pages from reading the API;
* a present ``Origin`` must be this server's own origin or an explicitly allowed dev origin —
  blocks cross-site requests from other web pages;
* responses are marked uncacheable and get conservative browser headers (private content must not
  sit in shared caches).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        b"default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    ),
)


# ``host[:port]`` where host is a bracketed IP literal or a name without ``:``/brackets. Anything
# else (trailing junk after ``]``, a non-numeric port, userinfo) is not a loopback Host.
_HOST_HEADER = re.compile(r"^(?P<host>\[[0-9A-Fa-f:.]+\]|[^:\[\]@/\s]+)(?::\d{1,5})?$")


def _host_without_port(value: str) -> str:
    match = _HOST_HEADER.match(value)
    return match.group("host") if match else value


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *_SECURITY_HEADERS],
        }
    )
    await send({"type": "http.response.body", "body": body})


class LocalOnlyGuard:
    def __init__(
        self, app: ASGIApp, *, allowed_hosts: Iterable[str], allowed_origins: Iterable[str]
    ) -> None:
        self._app = app
        self._hosts = frozenset(h.lower() for h in allowed_hosts)
        self._origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        host = headers.get(b"host", b"").decode("latin-1")
        if _host_without_port(host).lower() not in self._hosts:
            await _reject(send, 400, "invalid_host", "This host name is not accepted.")
            return
        origin = headers.get(b"origin")
        if origin is not None and origin.decode("latin-1") not in self._origins:
            await _reject(send, 403, "forbidden_origin", "This origin is not accepted.")
            return

        async def send_hardened(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message["headers"]}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in existing]
                message = {**message, "headers": [*message["headers"], *extra]}
            await send(message)

        await self._app(scope, receive, send_hardened)
