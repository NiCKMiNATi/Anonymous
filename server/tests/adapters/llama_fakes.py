"""Fakes for the dev-only external llama adapter tests: synthetic data, loopback only.

No real runtime, model or network beyond an ephemeral 127.0.0.1 listener is involved.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from anonymous.adapters.model.llama_launch_record import (
    ArtifactIdentity,
    LaunchRecord,
    write_record,
)
from anonymous.adapters.model.process_identity import ProcessIdentity

KEY = "synthetic-per-launch-key-0123456789abcdef"
FAKE_PID = 4242
FAKE_START = (1_700_000_000, 123_456)
NONCE = "0123456789abcdef0123456789abcdef"


@dataclass(slots=True)
class SeenRequest:
    method: str
    path: str
    authorization: str | None
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class FakeLlamaServer:
    """Answers ``POST /v1/chat/completions`` with a scripted reply and records every request."""

    def __init__(
        self,
        *,
        reply: str = "synthetic reply",
        finish_reason: str | None = "stop",
        status: int = 200,
        raw_body: bytes | None = None,
        delay: float = 0.0,
        drop: bool = False,
        require_key: str | None = KEY,
        framing: str = "length",
    ) -> None:
        self.reply = reply
        self.finish_reason = finish_reason
        self.status = status
        self.raw_body = raw_body
        self.delay = delay
        self.drop = drop
        self.require_key = require_key
        # "length" | "short" (Content-Length overstated, EOF early) | "chunked" |
        # "chunked_truncated" | "close_delimited" | "both" (Content-Length and chunked) |
        # "dup_same" | "dup_conflict" (two Content-Length headers) | "invalid_length"
        self.framing = framing
        self.requests: list[SeenRequest] = []
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        assert self._httpd is not None
        return int(self._httpd.server_address[1])

    def start(self) -> FakeLlamaServer:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # silence stderr
                return

            def _seen(self, body: bytes) -> None:
                outer.requests.append(
                    SeenRequest(self.command, self.path, self.headers.get("Authorization"), body)
                )

            def do_GET(self) -> None:
                self._seen(b"")
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                self._seen(body)
                if outer.delay:
                    time.sleep(outer.delay)
                if outer.drop:
                    self.close_connection = True
                    return
                if outer.require_key is not None and (
                    self.headers.get("Authorization") != f"Bearer {outer.require_key}"
                ):
                    self._reply(401, b'{"error":"invalid api key"}')
                    return
                if outer.raw_body is not None:
                    self._reply(outer.status, outer.raw_body)
                    return
                payload = {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": outer.reply},
                            "finish_reason": outer.finish_reason,
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
                self._reply(outer.status, json.dumps(payload).encode())

            def _reply(self, status: int, body: bytes) -> None:
                framing = outer.framing if status == 200 else "length"
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if framing in ("dup_same", "dup_conflict", "invalid_length"):
                    # The complete body is delivered; only the declared length is ambiguous.
                    declared = {
                        "dup_same": [str(len(body)), str(len(body))],
                        "dup_conflict": [str(len(body)), str(len(body) + 7)],
                        "invalid_length": [f"{len(body)}abc"],
                    }[framing]
                    for value in declared:
                        self.send_header("Content-Length", value)
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True
                    return
                if framing in ("length", "short"):
                    extra = 500 if framing == "short" else 0
                    self.send_header("Content-Length", str(len(body) + extra))
                    self.end_headers()
                    self.wfile.write(body)
                    if framing == "short":
                        self.close_connection = True
                    return
                if framing == "close_delimited":
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    self.close_connection = True
                    return
                # chunked variants
                self.send_header("Transfer-Encoding", "chunked")
                if framing == "both":
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                half = len(body) // 2
                for part in (body[:half], body[half:]):
                    self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                if framing != "chunked_truncated":
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    self.close_connection = True

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()


@dataclass(slots=True)
class FakeInspector:
    """Process facts under test control. ``listener`` defaults to the recorded process."""

    identities: dict[int, ProcessIdentity | None] = field(default_factory=dict)
    listener: tuple[tuple[int, str], ...] | None = None
    port: int = 0

    def identity_of(self, pid: int) -> ProcessIdentity | None:
        return self.identities.get(pid)

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        if self.listener is not None:
            return self.listener
        return ((FAKE_PID, f"127.0.0.1:{port}"),)


def write_launch(
    directory: Path,
    server: FakeLlamaServer,
    *,
    model: ArtifactIdentity | None = None,
    runtime: ArtifactIdentity | None = None,
    nonce: str = NONCE,
) -> tuple[Path, LaunchRecord, FakeInspector]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    key_file = directory / f"key-{nonce}"
    key_file.write_text(KEY, encoding="ascii")
    key_file.chmod(0o600)
    record = LaunchRecord(
        nonce=nonce,
        pid=FAKE_PID,
        start=FAKE_START,
        host="127.0.0.1",
        port=server.port,
        key_file=key_file,
        model=model or ArtifactIdentity("Qwen3-4B-Q4_K_M", "a" * 64, "asserted"),
        runtime=runtime or ArtifactIdentity("llama.cpp-b11440", "b" * 64, "asserted"),
        created_utc=1_700_000_000.0,
    )
    path = directory / "launch.json"
    write_record(path, record)
    inspector = FakeInspector(identities={FAKE_PID: ProcessIdentity(FAKE_PID, FAKE_START)})
    return path, record, inspector
