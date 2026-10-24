"""LlamaHttpRuntime — dev-only RuntimePort for an independently launched local llama.cpp server.

ADR-0015 (Proposed). This adapter does NOT own the runtime process: the dev launcher started it,
and it can outlive Anonymous (E3: it survives its owner and finishes the request it accepted). The
binding therefore says what is true and claims nothing it cannot show:

* ``lifetime_scope = EXTERNAL`` (never ``owning_process``);
* ``declared_bases`` is empty: no B3, B4 or B5 is claimed, so the router discards any such probe
  result and ``RunSettler.apply_evidence`` refuses such settlements for this binding;
* ``late_delivery_excluded = False``.

What it does do:

* one HTTP request per attempt, ``POST /v1/chat/completions``, non-streaming, to the exact loopback
  address and port of the launch record. No other endpoint is ever requested (not ``/health``,
  ``/slots``, ``/props`` or ``/v1/models``: the last two expose the model's absolute path);
* before anything is sent, the recorded (pid, start) must be live AND be the sole listener on the
  exact address; a prompt or the key is never sent to a listener that fails this check. A response
  is delivered as ``Completed`` only if the framing is complete and unambiguous, it is HTTP 200 and
  well formed, and the same two facts hold again afterwards. The per-launch bearer key only keeps
  other local clients away from the runtime: possessing it proves nothing about the identity of the
  server that answered, and it is never used as attribution. Remaining race: a listener swapped
  between a check and its use (see ADR-0015);
* every other outcome is ``POSSIBLY_ACTIVE`` (never ``ENDED``): an HTTP 4xx/5xx alone does not show
  that generation ended, so it closes the attempt and quarantines the dev dataset;
* ``stop`` is ``UNSUPPORTED`` and ``probe`` is never ``CONFIRMED_ENDED``.

Request and response bodies, the key and every path are held in memory only: nothing here logs or
persists them.
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anonymous.adapters.model.llama_launch_record import (
    ArtifactIdentity,
    LaunchRecord,
    LaunchRecordError,
    read_key,
    read_record,
)
from anonymous.adapters.model.process_identity import (
    IdentityInspector,
    IdentityUnavailable,
    ProcessIdentity,
    default_inspector,
)
from anonymous.application.ports.model import (
    AdapterDescriptor,
    Completed,
    Failed,
    Knowledge,
    ModelRequest,
    PreparedBinding,
    PrepareFailed,
    ProbeKind,
    ProbeResult,
    StartAck,
    StopAck,
)
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import LifetimeScope
from anonymous.domain.provenance import ComponentIdentity, Verification

logger = logging.getLogger("anonymous.llama_dev")

ADAPTER_ID = "llama-dev-http"
ADAPTER_VERSION = "1"
BINDING_FORMAT = "llama-dev-http/1"
CHAT_PATH = "/v1/chat/completions"  # the only path this adapter ever requests
MAX_RESPONSE_BYTES = 262_144
_TEMPERATURE = 0.7


@dataclass(slots=True)
class _Pending:
    connection: http.client.HTTPConnection
    record: LaunchRecord
    identity: ProcessIdentity
    instance_ref: str


class _Ambiguous:
    """A request write failed part-way: bytes may have reached the runtime (not NEVER_REACHED)."""


_AMBIGUOUS = _Ambiguous()


class _NotVerified(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _component(artifact: ArtifactIdentity) -> ComponentIdentity:
    if artifact.sha256 is None:
        return ComponentIdentity.label_only(artifact.label)
    return ComponentIdentity(
        label=artifact.label,
        digest=f"sha256:{artifact.sha256}",
        verification=Verification(artifact.verification),
    )


def _failed(code: str, instance_ref: str | None = None) -> Failed:
    # Never ``ENDED``: nothing here can show that the runtime stopped working on the request.
    return Failed(code, "The model runtime failed.", Knowledge.POSSIBLY_ACTIVE, instance_ref)


class LlamaHttpRuntime:
    def __init__(
        self,
        record_path: Path,
        *,
        max_tokens: int,
        max_input_chars: int,
        inspector: IdentityInspector | None = None,
    ) -> None:
        self._record_path = Path(record_path)
        self._max_tokens = max_tokens
        self._max_input_chars = max_input_chars
        self._inspector = inspector
        self._lock = threading.Lock()
        # None: consumed, or nothing was ever written. _AMBIGUOUS: a write may have occurred.
        self._attempts: dict[str, _Pending | _Ambiguous | None] = {}

    # -- identity ---------------------------------------------------------------------------

    def _inspect(self) -> IdentityInspector:
        if self._inspector is None:
            self._inspector = default_inspector()
        return self._inspector

    def _live_record(self, *, check_listener: bool) -> tuple[LaunchRecord, ProcessIdentity]:
        """The current launch record, with its process verified live by (pid, start)."""
        record = read_record(self._record_path)
        inspector = self._inspect()
        live = inspector.identity_of(record.pid)
        if live is None or live.start != record.start:
            raise _NotVerified("process_identity_mismatch")
        if check_listener:
            want = f"{record.host}:{record.port}"
            sockets = inspector.listeners(record.port)
            if len(sockets) != 1 or sockets[0] != (record.pid, want):
                raise _NotVerified("listener_not_the_recorded_process")
        return record, live

    def _endpoint_is_recorded_process(
        self, record: LaunchRecord, identity: ProcessIdentity
    ) -> bool:
        """The recorded process is live with the same start AND is the sole listener on the exact
        address. Raises ``IdentityUnavailable`` when this cannot be established."""
        inspector = self._inspect()
        if inspector.identity_of(record.pid) != identity:
            return False
        want = ((record.pid, f"{record.host}:{record.port}"),)
        return inspector.listeners(record.port) == want

    # -- RuntimePort ------------------------------------------------------------------------

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            binding_formats=frozenset({BINDING_FORMAT}),
            max_input_chars=self._max_input_chars,
        )

    def prepare(self, attempt_id: str) -> PreparedBinding | PrepareFailed:
        try:
            record, _ = self._live_record(check_listener=True)
        except (LaunchRecordError, _NotVerified, IdentityUnavailable) as error:
            logger.warning(
                "llama-dev prepare refused reason=%s", getattr(error, "code", "unavailable")
            )
            return PrepareFailed("binding_unavailable", "The model runtime could not be prepared.")
        binding = ExecutionBinding(
            format=BINDING_FORMAT,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            instance_ref=record.instance_ref,
            lifetime_scope=LifetimeScope.EXTERNAL,
            declared_bases=frozenset(),
            late_delivery_excluded=False,
            model_label=record.model.label,
            runtime_label=record.runtime.label,
        )
        return PreparedBinding(
            binding=binding,
            model_artifact=_component(record.model),
            runtime_build=_component(record.runtime),
            adapter=ComponentIdentity.label_only(f"{ADAPTER_ID} {ADAPTER_VERSION}"),
        )

    def start(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        request: ModelRequest,
        handoff_deadline_seconds: float,
    ) -> StartAck:
        """Connect and write the complete request; the response is read in ``await_result``.

        HTTP has no acknowledgment before the response, so ``ACCEPTED`` is never claimed: once the
        request is written the handoff is ``UNKNOWN`` (it may be executing). Before anything is
        written, every failure is ``NOT_STARTED`` (nothing was sent)."""
        with self._lock:
            if attempt_id in self._attempts:
                return StartAck.NOT_STARTED  # an attempt starts at most once
            self._attempts[attempt_id] = None
        if binding.adapter_id != ADAPTER_ID or binding.format != BINDING_FORMAT:
            return StartAck.NOT_STARTED
        try:
            # Immediately before dispatch, not only in prepare: a slot wait can separate the two.
            record, live = self._live_record(check_listener=True)
            if record.instance_ref != binding.instance_ref:
                return StartAck.NOT_STARTED  # a replacement instance is never sent this attempt
            key = read_key(record)
        except (LaunchRecordError, _NotVerified, IdentityUnavailable):
            return StartAck.NOT_STARTED
        body = json.dumps(
            {
                "messages": [
                    {"role": m.role.value, "content": m.content} for m in request.messages
                ],
                "max_tokens": self._max_tokens,
                "stream": False,
                "cache_prompt": False,
                "temperature": _TEMPERATURE,
            }
        ).encode("utf-8")
        connection = http.client.HTTPConnection(
            record.host, record.port, timeout=handoff_deadline_seconds
        )
        try:
            connection.connect()
        except OSError:
            connection.close()
            return StartAck.NOT_STARTED  # nothing was written
        try:
            connection.request(
                "POST",
                CHAT_PATH,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                    "Connection": "close",
                },
            )
        except (OSError, http.client.HTTPException):
            connection.close()
            with self._lock:
                self._attempts[attempt_id] = _AMBIGUOUS  # part of the request may have been written
            return StartAck.UNKNOWN
        with self._lock:
            self._attempts[attempt_id] = _Pending(connection, record, live, binding.instance_ref)
        return StartAck.UNKNOWN

    def await_result(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> Completed | Failed:
        with self._lock:
            pending = self._attempts.get(attempt_id)
            self._attempts[attempt_id] = None
        if isinstance(pending, _Ambiguous):
            return _failed("runtime_error")  # a write may have happened: possibly active
        if pending is None or pending.instance_ref != binding.instance_ref:
            return Failed(
                "not_started", "The attempt was not started.", Knowledge.NEVER_REACHED, None
            )
        connection = pending.connection
        try:
            if connection.sock is not None:
                connection.sock.settimeout(deadline_seconds)
            response = connection.getresponse()
            status = response.status
            raw = _read_body(response) if status == 200 else None
        except TimeoutError:
            return _failed("deadline")
        except (OSError, http.client.HTTPException):  # includes IncompleteRead
            return _failed("runtime_error")
        finally:
            connection.close()
        # HTTP 4xx/5xx alone does not show that generation ended: possibly active (ADR-0015).
        if raw is None:
            return _failed("runtime_error")
        parsed = _parse_chat_response(raw)
        if parsed is None:
            return _failed("runtime_error")
        content, finished = parsed
        # Attribution: before the response is accepted, the same process must still be live and
        # still be the sole listener on the exact address. The bearer key is not evidence.
        try:
            attributable = self._endpoint_is_recorded_process(pending.record, pending.identity)
        except IdentityUnavailable:
            return _failed("runtime_error")
        if not attributable:
            return _failed("runtime_error")
        return Completed(
            content=content,
            instance_ref=binding.instance_ref,
            model_label=binding.model_label,
            complete=finished,
        )

    def stop(self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float) -> StopAck:
        # Anonymous neither owns nor can interrupt this runtime, and a stop is no evidence anyway.
        return StopAck.UNSUPPORTED

    def probe(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> ProbeResult:
        try:
            record = read_record(self._record_path)
        except LaunchRecordError:
            return ProbeResult(ProbeKind.UNKNOWN, reason="launch record unavailable")
        if record.instance_ref != binding.instance_ref:
            return ProbeResult(ProbeKind.INSTANCE_MISMATCH)
        # No verified signal that an attempt ended exists for this adapter (ADR-0015).
        return ProbeResult(ProbeKind.UNKNOWN, reason="no verifiable end signal")


def _read_body(response: http.client.HTTPResponse) -> bytes | None:
    """The complete response body, or ``None`` if it is oversized, incomplete or ambiguously framed.

    ``HTTPResponse.read(n)`` returns a short body at EOF without raising when the declared
    Content-Length is not met, so completeness is checked here. Supported framing: a valid single
    Content-Length, or chunked transfer coding (which raises ``IncompleteRead`` on truncation).
    Rejected as ambiguous: a close-delimited body, an invalid or repeated Content-Length (even if
    the repeats are identical), and Content-Length together with chunked coding.

    ``http.client`` parses only the *first* Content-Length header into ``response.length``, so the
    repetition is detected here from the raw header list."""
    lengths = response.headers.get_all("Content-Length") or []
    if len(lengths) > 1:
        return None
    declared = response.length  # remaining bytes declared by Content-Length, before any read
    if response.chunked:
        if lengths:
            return None
    elif declared is None or declared > MAX_RESPONSE_BYTES:
        return None
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(65_536, MAX_RESPONSE_BYTES + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            return None
        parts.append(chunk)
    if not response.chunked and total != declared:
        return None  # premature EOF before the declared length: not a complete delivery
    return b"".join(parts)


def _parse_chat_response(raw: bytes) -> tuple[str, bool] | None:
    """``(content, finished_naturally)`` from a chat completion body, or ``None`` if malformed."""
    try:
        body: Any = json.loads(raw)
        choice = body["choices"][0]
        content = choice["message"]["content"]
        finish = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    if content is None:
        content = ""
    if not isinstance(content, str) or (finish is not None and not isinstance(finish, str)):
        return None
    return content, finish == "stop"


__all__ = ["ADAPTER_ID", "BINDING_FORMAT", "CHAT_PATH", "LlamaHttpRuntime"]
