"""The dev-only external llama.cpp adapter against a fake loopback HTTP server (ADR-0015).

Synthetic data only. Every scenario runs through the real coordinator, worker, settler and SQLite
store; only the runtime process is faked. What is pinned here:

* a complete, attributable, accepted response publishes through T4 and frees the slot (an exact
  ``length`` finish publishes the same way, visibly truncated, ADR-0016);
* a rejected, ambiguous or failed response never settles through B3/B4/B5: it quarantines;
* the binding says ``external`` with no declared bases, and nothing sensitive reaches records/logs;
* only ``POST /v1/chat/completions`` is ever requested.
"""

from __future__ import annotations

import ast
import http.client
import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from anonymous.adapters.model import llama_http
from anonymous.adapters.model.llama_http import BINDING_FORMAT, CHAT_PATH, LlamaHttpRuntime
from anonymous.adapters.model.llama_launch_record import ArtifactIdentity
from anonymous.adapters.model.process_identity import ProcessIdentity
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.model import (
    Completed,
    ContextMessage,
    Failed,
    Knowledge,
    ModelRequest,
    PreparedBinding,
    PrepareFailed,
    ProbeKind,
    StartAck,
    StopAck,
)
from anonymous.application.supervisor import ExecutionSettings
from anonymous.domain.errors import RuntimeQuarantined
from anonymous.domain.evidence import (
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    LifetimeScope,
)
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import Completeness, Message, MessageRole, ModelRun, RunStatus
from anonymous.domain.provenance import Verification
from tests.adapters.llama_fakes import (
    FAKE_PID,
    FAKE_START,
    KEY,
    FakeInspector,
    FakeLlamaServer,
    write_launch,
)
from tests.conftest import FAST, Services

PROMPT = "synthetic prompt about nothing private"
MAX_TOKENS = 77


@pytest.fixture
def server() -> Iterator[FakeLlamaServer]:
    fake = FakeLlamaServer().start()
    try:
        yield fake
    finally:
        fake.stop()


class Rig:
    def __init__(
        self,
        store: SqliteStore,
        owner: UserId,
        tmp_path: Path,
        server: FakeLlamaServer,
        *,
        settings: ExecutionSettings = FAST,
        max_input_chars: int = 1400,
    ) -> None:
        self.owner = owner
        self.server = server
        self.record_path, self.record, self.inspector = write_launch(tmp_path / "launch", server)
        self.runtime = LlamaHttpRuntime(
            self.record_path,
            max_tokens=MAX_TOKENS,
            max_input_chars=max_input_chars,
            inspector=self.inspector,
        )
        self.services = Services(store, self.runtime, settings=settings)
        self.cid = self.services.conversations.create_conversation(owner).id

    def send(
        self, text: str = PROMPT, cid: ConversationId | None = None
    ) -> tuple[ModelRun, Message | None]:
        outcome = self.services.coordinator.submit(
            owner=self.owner,
            conversation_id=cid or self.cid,
            submission_id=SubmissionId(new_uuid()),
            content=text,
        )
        return outcome.run, outcome.assistant_message


@pytest.fixture
def rig(store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer) -> Rig:
    return Rig(store, owner, tmp_path, server)


# -- normal success ----------------------------------------------------------------------------


def test_a_complete_attributable_response_publishes_through_t4_and_frees_the_slot(
    rig: Rig, store: SqliteStore
) -> None:
    run, message = rig.send()
    assert run.status is RunStatus.SUCCEEDED
    assert message is not None and message.content == rig.server.reply
    assert message.produced_by_run_id == run.id
    # Truthful binding: an external process, with no runtime-asserted evidence declared.
    binding = run.binding
    assert binding is not None
    assert binding.lifetime_scope is LifetimeScope.EXTERNAL
    assert binding.declared_bases == frozenset()
    assert binding.late_delivery_excluded is False
    assert binding.format == BINDING_FORMAT and binding.instance_ref == rig.record.instance_ref
    # T3b made the marker STARTED before start; the adapter's UNKNOWN is the recorded outcome (T3c).
    assert run.handoff is Handoff.STARTED and run.handoff_outcome is HandoffOutcome.UNKNOWN
    # T4 stamps its fixed basis; for this binding it means attributed delivery only (ADR-0015).
    assert run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    # History persisted, and the slot is free for the next send.
    history = store.get_history(rig.owner, rig.cid).messages
    assert [m.role for m in history] == [MessageRole.USER, MessageRole.ASSISTANT]
    again, second = rig.send("second synthetic prompt")
    assert again.status is RunStatus.SUCCEEDED and second is not None


def test_the_request_is_one_bounded_non_streaming_chat_completion_with_the_whole_history(
    rig: Rig,
) -> None:
    rig.send("first synthetic prompt")
    rig.send("second synthetic prompt")
    first, second = rig.server.requests
    assert (first.method, first.path) == ("POST", CHAT_PATH)
    assert first.authorization == f"Bearer {KEY}"
    body = second.json()
    assert body["stream"] is False and body["max_tokens"] == MAX_TOKENS
    assert body["cache_prompt"] is False
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][-1]["content"] == "second synthetic prompt"
    assert set(body) == {"messages", "max_tokens", "stream", "cache_prompt", "temperature"}


def test_provenance_separates_asserted_pins_from_verified_identity(
    rig: Rig, store: SqliteStore
) -> None:
    run, _ = rig.send()
    provenance = store.get_run(run.id).provenance
    assert provenance is not None
    # A pin copied from configuration is a claim, never a check (ADR-0015 point 10).
    assert provenance.model_artifact.digest == "sha256:" + "a" * 64
    assert provenance.model_artifact.verification is Verification.ASSERTED
    assert provenance.runtime_build.verification is Verification.ASSERTED
    assert provenance.adapter.verification is Verification.UNSPECIFIED


def test_a_label_only_artifact_carries_no_digest(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    path, _, inspector = write_launch(
        tmp_path / "launch",
        server,
        model=ArtifactIdentity("Qwen3-4B-Q4_K_M", None, "unspecified"),
    )
    runtime = LlamaHttpRuntime(path, max_tokens=8, max_input_chars=100, inspector=inspector)
    prepared = runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    assert prepared.model_artifact.digest is None
    assert prepared.model_artifact.verification is Verification.UNSPECIFIED


# -- ADR-0016: an exact "length" delivery publishes as a visibly truncated message -----------------


def length_body(content: str = "The three colors are red, orange and") -> bytes:
    payload = {"choices": [{"message": {"content": content}, "finish_reason": "length"}]}
    return json.dumps(payload).encode()


def test_a_stop_response_is_published_as_complete(rig: Rig) -> None:
    run, message = rig.send()
    assert run.status is RunStatus.SUCCEEDED and message is not None
    assert message.completeness is Completeness.COMPLETE


def test_a_length_response_publishes_through_t4_as_truncated_without_new_claims(
    rig: Rig, store: SqliteStore
) -> None:
    rig.server.reply, rig.server.finish_reason = "The three colors are red, orange and", "length"
    run, message = rig.send()
    assert run.status is RunStatus.SUCCEEDED and message is not None
    assert message.content == "The three colors are red, orange and"  # the text is untouched
    assert message.completeness is Completeness.TRUNCATED
    assert message.produced_by_run_id == run.id
    # Exactly what any accepted delivery claims (ADR-0015 point 1): nothing about the process,
    # natural completion, idleness or B3, and the binding is still external with no declared bases.
    assert run.termination_basis is EvidenceBasis.RUNTIME_REPORTED_TERMINAL
    assert run.completion_observed is CompletionObserved.YES
    binding = run.binding
    assert binding is not None
    assert binding.lifetime_scope is LifetimeScope.EXTERNAL
    assert binding.declared_bases == frozenset() and binding.late_delivery_excluded is False
    assert run.handoff is Handoff.STARTED and run.handoff_outcome is HandoffOutcome.UNKNOWN
    # Persisted, and no quarantine: the slot is free for every conversation, including this one.
    assert store.get_run(run.id).status is RunStatus.SUCCEEDED
    assert store.generation_state().quarantined_runs == ()
    other = rig.services.conversations.create_conversation(rig.owner).id
    rig.server.finish_reason = "stop"
    again, reply = rig.send("a normal follow-up")
    elsewhere, second = rig.send("another conversation", other)
    assert again.status is RunStatus.SUCCEEDED and reply is not None
    assert reply.completeness is Completeness.COMPLETE
    assert elsewhere.status is RunStatus.SUCCEEDED and second is not None
    history = store.get_history(rig.owner, rig.cid).messages
    assert [m.completeness for m in history] == [
        None,
        Completeness.TRUNCATED,
        None,
        Completeness.COMPLETE,
    ]


def test_a_truncated_reply_goes_back_to_the_model_verbatim_and_unmarked(rig: Rig) -> None:
    rig.server.reply, rig.server.finish_reason = "red, orange and", "length"
    rig.send("name colors")
    rig.server.finish_reason = "stop"
    rig.send("go on")
    body = rig.server.requests[1].json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][1] == {"role": "assistant", "content": "red, orange and"}
    assert all(set(m) == {"role", "content"} for m in body["messages"])  # no marker field
    assert "cut off" not in json.dumps(body) and "truncat" not in json.dumps(body)


FRAMING_FAULTS = [
    "short",
    "chunked_truncated",
    "close_delimited",
    "both",
    "dup_same",
    "dup_conflict",
    "invalid_length",
]


@pytest.mark.parametrize("framing", FRAMING_FAULTS)
def test_a_length_finish_with_a_framing_fault_is_not_a_truncated_publication(
    rig: Rig, framing: str
) -> None:
    rig.server.raw_body = length_body()  # a complete, valid length completion in the body ...
    rig.server.framing = framing  # ... delivered with broken or ambiguous framing
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_complete_chunked_length_response_is_published_as_truncated(rig: Rig) -> None:
    rig.server.raw_body = length_body()
    rig.server.framing = "chunked"
    run, message = rig.send()
    assert run.status is RunStatus.SUCCEEDED and message is not None
    assert message.completeness is Completeness.TRUNCATED


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_a_length_body_in_an_http_error_is_not_published(rig: Rig, status: int) -> None:
    rig.server.status, rig.server.raw_body = status, length_body()
    run, message = rig.send()
    assert_quarantined(rig, run, message)


@pytest.mark.parametrize("fault", ["drop", "wrong_key"])
def test_a_length_finish_with_a_dropped_or_refused_request_is_not_published(
    rig: Rig, fault: str
) -> None:
    rig.server.finish_reason, rig.server.reply = "length", "cut off mid"
    if fault == "drop":
        rig.server.drop = True
    else:
        rig.server.require_key = "some-other-instances-key"
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_length_finish_after_the_deadline_is_not_published_and_cannot_release_the_slot(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    server.delay, server.finish_reason, server.reply = 1.0, "length", "cut off mid"
    rig = Rig(store, owner, tmp_path, server, settings=replace(FAST, deadline_seconds=0.3))
    run, message = rig.send()
    assert_quarantined(rig, run, message)
    threading.Event().wait(1.2)  # the late length delivery arrives after closure
    assert store.get_run(run.id).status is RunStatus.INDETERMINATE
    assert store.get_history(owner, rig.cid).messages[-1].role is MessageRole.USER


@pytest.mark.parametrize("change", ["process", "listener"])
def test_a_length_finish_is_not_published_if_identity_changed_during_the_request(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer, change: str
) -> None:
    server.delay, server.finish_reason, server.reply = 1.0, "length", "cut off mid"
    rig = Rig(store, owner, tmp_path, server)

    def swap() -> None:
        if change == "process":
            rig.inspector.identities[FAKE_PID] = ProcessIdentity(FAKE_PID, (FAKE_START[0] + 1, 0))
        else:
            rig.inspector.listener = ((FAKE_PID + 1, f"127.0.0.1:{rig.record.port}"),)

    timer = threading.Timer(0.5, swap)
    timer.start()
    run, message = rig.send()
    timer.join()
    assert_quarantined(rig, run, message)


def test_a_length_finish_from_an_unverifiable_runtime_is_never_requested(rig: Rig) -> None:
    rig.server.finish_reason = "length"
    rig.inspector.listener = ((FAKE_PID + 1, f"127.0.0.1:{rig.record.port}"),)
    run, message = rig.send()
    assert message is None and run.status is RunStatus.FAILED
    assert rig.server.requests == []  # nothing was sent, so there is nothing to label


def test_the_parsed_delivery_carries_exactly_the_two_distinct_flags(rig: Rig) -> None:
    """The adapter's contract: stop is complete, exactly length is limit_reached, else neither."""
    seen: dict[str | None, tuple[bool, bool]] = {}
    for finish in ("stop", "length", None, "", "content_filter", "Length"):
        rig.server.finish_reason, rig.server.reply = finish, "some text"
        prepared = rig.runtime.prepare(f"a-{finish}")
        assert isinstance(prepared, PreparedBinding)
        attempt = f"a-{finish}"
        assert rig.runtime.start(attempt, prepared.binding, _request(), 2.0) is StartAck.UNKNOWN
        result = rig.runtime.await_result(attempt, prepared.binding, 2.0)
        assert isinstance(result, Completed)
        seen[finish] = (result.complete, result.limit_reached)
    assert seen == {
        "stop": (True, False),
        "length": (False, True),
        None: (False, False),
        "": (False, False),
        "content_filter": (False, False),
        "Length": (False, False),
    }


# -- rejected and ambiguous responses never settle through B3/B4/B5 ------------------------------


def assert_quarantined(rig: Rig, run: ModelRun, message: object) -> None:
    assert message is None
    assert run.status is RunStatus.INDETERMINATE
    assert run.termination_basis is None  # no basis was manufactured
    other = rig.services.conversations.create_conversation(rig.owner).id
    with pytest.raises(RuntimeQuarantined):  # the slot is held for every conversation
        rig.send("next", other)


@pytest.mark.parametrize(
    ("reply", "finish"),
    [
        ("", "stop"),
        ("   ", "stop"),
        ("", "length"),  # ADR-0016: an output-limit delivery with no content is still rejected
        ("  \n ", "length"),
        ("odd", "content_filter"),
        ("odd", "tool_calls"),
        ("x", None),
        ("x", ""),
        ("x", "Length"),  # only the exact finish reasons count
        ("x", "LENGTH"),
        ("x", "length "),
        ("x", "stop "),
    ],
)
def test_rejected_responses_quarantine_instead_of_settling(
    rig: Rig, reply: str, finish: str | None
) -> None:
    rig.server.reply, rig.server.finish_reason = reply, finish
    run, message = rig.send()
    assert_quarantined(rig, run, message)


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 503])
def test_http_errors_alone_do_not_establish_that_generation_ended(rig: Rig, status: int) -> None:
    rig.server.status, rig.server.raw_body = status, b'{"error":"synthetic"}'
    run, message = rig.send()
    assert_quarantined(rig, run, message)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"{}",
        b'{"choices":[]}',
        b'{"choices":[{"message":{"content":5}}]}',
        b"x" * 300_000,
    ],
)
def test_malformed_or_oversized_bodies_quarantine(rig: Rig, raw: bytes) -> None:
    rig.server.raw_body = raw
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_dropped_connection_quarantines(rig: Rig) -> None:
    rig.server.drop = True
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_wrong_key_is_rejected_by_the_runtime_and_quarantines(rig: Rig) -> None:
    rig.server.require_key = "some-other-instances-key"
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_deadline_quarantines_and_a_late_response_cannot_release_it(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    server.delay = 1.0
    rig = Rig(store, owner, tmp_path, server, settings=replace(FAST, deadline_seconds=0.3))
    run, message = rig.send()
    assert_quarantined(rig, run, message)
    # Let the runtime's late answer arrive after the quarantine; the run must stay unresolved.
    threading.Event().wait(1.2)
    assert store.get_run(run.id).status is RunStatus.INDETERMINATE


def test_the_process_changing_during_the_request_is_not_an_attributable_response(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    server.delay = 1.0
    rig = Rig(store, owner, tmp_path, server)
    swap = threading.Timer(
        0.5,
        lambda: rig.inspector.identities.__setitem__(
            FAKE_PID, ProcessIdentity(FAKE_PID, (FAKE_START[0] + 1, 0))
        ),
    )
    swap.start()
    run, message = rig.send()
    swap.join()
    assert_quarantined(rig, run, message)


# -- nothing sent: these are provably not dispatched and do not quarantine -------------------------


def test_connection_refused_before_any_byte_is_adapter_never_reached(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    rig = Rig(store, owner, tmp_path, server)
    server.stop()  # the recorded port no longer accepts connections
    run, message = rig.send()
    assert message is None and run.status is RunStatus.FAILED
    assert run.termination_basis is EvidenceBasis.ADAPTER_NEVER_REACHED
    run2, _ = rig.send("again")  # not quarantined: nothing was sent
    assert run2.status is RunStatus.FAILED


def _mismatch(rig: Rig) -> None:
    rig.inspector.identities[FAKE_PID] = ProcessIdentity(FAKE_PID, (1, 1))


def _gone(rig: Rig) -> None:
    rig.inspector.identities[FAKE_PID] = None


def _other_listener(rig: Rig) -> None:
    rig.inspector.listener = ((FAKE_PID + 1, f"127.0.0.1:{rig.record.port}"),)


def _wildcard_listener(rig: Rig) -> None:
    rig.inspector.listener = ((FAKE_PID, f"*:{rig.record.port}"),)


def _two_listeners(rig: Rig) -> None:
    port = rig.record.port
    rig.inspector.listener = ((FAKE_PID, f"127.0.0.1:{port}"), (FAKE_PID + 1, f"*:{port}"))


def _missing_record(rig: Rig) -> None:
    rig.record_path.unlink()


def _public_record(rig: Rig) -> None:
    rig.record_path.chmod(0o644)


@pytest.mark.parametrize(
    "break_it",
    [
        _mismatch,
        _gone,
        _other_listener,
        _wildcard_listener,
        _two_listeners,
        _missing_record,
        _public_record,
    ],
)
def test_an_unverifiable_runtime_is_never_dispatched_to(rig: Rig, break_it) -> None:  # type: ignore[no-untyped-def]
    break_it(rig)
    run, message = rig.send()
    assert message is None and run.status is RunStatus.FAILED
    assert run.failure_code == "binding_unavailable"
    assert run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert rig.server.requests == []


def test_over_capacity_input_is_refused_before_dispatch(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    rig = Rig(store, owner, tmp_path, server, max_input_chars=20)
    run, message = rig.send("x" * 21)
    assert message is None and run.failure_code == "context_exceeds_capacity"
    assert run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    assert server.requests == []


# -- adapter contract ---------------------------------------------------------------------------


def _request() -> ModelRequest:
    return ModelRequest((ContextMessage(MessageRole.USER, PROMPT),))


def test_stop_is_unsupported_and_probe_never_confirms_an_end(rig: Rig) -> None:
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    assert rig.runtime.stop("a", prepared.binding, 1.0) is StopAck.UNSUPPORTED
    result = rig.runtime.probe("a", prepared.binding, 1.0)
    assert result.kind is ProbeKind.UNKNOWN and result.basis is None


def test_a_replacement_instance_is_never_sent_an_attempt_and_is_not_probed_as_the_bound_one(
    rig: Rig, tmp_path: Path
) -> None:
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    write_launch(tmp_path / "launch", rig.server, nonce="f" * 32)  # a new launch replaces it
    assert rig.runtime.start("a", prepared.binding, _request(), 1.0) is StartAck.NOT_STARTED
    assert rig.server.requests == []
    assert rig.runtime.probe("a", prepared.binding, 1.0).kind is ProbeKind.INSTANCE_MISMATCH


def test_an_attempt_starts_at_most_once(rig: Rig) -> None:
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    # HTTP has no acknowledgment before the response: the handoff is UNKNOWN, never ACCEPTED.
    assert rig.runtime.start("a", prepared.binding, _request(), 1.0) is StartAck.UNKNOWN
    assert rig.runtime.start("a", prepared.binding, _request(), 1.0) is StartAck.NOT_STARTED
    result = rig.runtime.await_result("a", prepared.binding, 5.0)
    assert result.__class__.__name__ == "Completed"
    again = rig.runtime.await_result("a", prepared.binding, 5.0)
    assert again.__class__.__name__ == "Failed"
    assert len(rig.server.requests) == 1


def test_prepare_failure_carries_no_detail(rig: Rig) -> None:
    rig.record_path.unlink()
    result = rig.runtime.prepare("a")
    assert isinstance(result, PrepareFailed)
    assert str(rig.record_path) not in result.public_message


# -- privacy ------------------------------------------------------------------------------------


def _all_text(db_path: Path) -> str:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute("SELECT * FROM model_runs").fetchall()
    finally:
        connection.close()
    return json.dumps(rows, default=str)


def test_only_the_chat_endpoint_is_ever_requested(rig: Rig) -> None:
    rig.send()
    rig.server.status, rig.server.raw_body = 500, b"{}"
    rig.send("again")
    assert {(r.method, r.path) for r in rig.server.requests} == {("POST", CHAT_PATH)}


def test_no_key_path_or_endpoint_leaks_into_records_or_logs(
    rig: Rig, db_path: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.send(PROMPT)  # success
    rig.server.reply = "SECRET-MODEL-OUTPUT"
    rig.server.finish_reason = "length"
    rig.send("second synthetic prompt")  # rejected, quarantines
    rig.record_path.unlink()
    rig.services.coordinator.reconcile()  # exercises the control path with an unreadable record
    text = caplog.text
    for forbidden in (
        KEY,
        "Bearer",
        str(tmp_path),
        PROMPT,
        "SECRET-MODEL-OUTPUT",
        "synthetic reply",
    ):
        assert forbidden not in text, forbidden
    stored = _all_text(db_path)
    for forbidden in (KEY, str(tmp_path), "/props", "/v1/models", rig.record.key_file.name):
        assert forbidden not in stored, forbidden
    assert "127.0.0.1" not in stored


def test_the_adapter_names_no_other_endpoint() -> None:
    tree = ast.parse(Path(llama_http.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    strings = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    assert [s for s in strings if s.startswith("/")] == [CHAT_PATH]
    for forbidden in ("props", "slots", "health", "models"):
        assert not [s for s in strings if forbidden in s.lower()], forbidden


# -- F3: endpoint attribution at dispatch and before a response is accepted -----------------------


class SwitchingInspector(FakeInspector):
    """The recorded process stays alive with the same start; only the listener changes."""

    def __init__(self, base: FakeInspector) -> None:
        super().__init__(identities=base.identities, listener=base.listener)
        self.calls = 0
        self.switch_after = 1  # the first listener query (prepare) is genuine

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        self.calls += 1
        if self.calls > self.switch_after:
            return ((FAKE_PID + 7, f"127.0.0.1:{port}"),)  # another process now holds the port
        return super().listeners(port)


def test_a_listener_replaced_after_prepare_is_never_sent_the_prompt_or_the_key(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer
) -> None:
    rig = Rig(store, owner, tmp_path, server)
    switching = SwitchingInspector(rig.inspector)
    rig.runtime._inspector = switching  # prepare sees the genuine listener, dispatch does not
    run, message = rig.send()
    assert message is None and run.status is RunStatus.FAILED
    assert run.termination_basis is EvidenceBasis.ADAPTER_NEVER_REACHED  # nothing was written
    assert rig.server.requests == []  # neither the prompt nor the bearer key reached anyone
    assert switching.identities[FAKE_PID] == ProcessIdentity(FAKE_PID, FAKE_START)  # still alive


@pytest.mark.parametrize("replacement", [((FAKE_PID + 7, "127.0.0.1:{port}"),), ()])
def test_start_checks_the_listener_itself_not_only_prepare(
    rig: Rig, replacement: tuple[tuple[int, str], ...]
) -> None:
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    rig.inspector.listener = tuple(
        (pid, name.format(port=rig.record.port)) for pid, name in replacement
    )
    assert rig.runtime.start("a", prepared.binding, _request(), 1.0) is StartAck.NOT_STARTED
    assert rig.server.requests == []


@pytest.mark.parametrize("later", ["replaced", "vanished", "shared"])
def test_a_response_is_not_accepted_if_the_endpoint_changed_while_it_was_in_flight(
    store: SqliteStore, owner: UserId, tmp_path: Path, server: FakeLlamaServer, later: str
) -> None:
    server.delay = 1.0
    rig = Rig(store, owner, tmp_path, server)
    port = rig.record.port
    after = {
        "replaced": ((FAKE_PID + 7, f"127.0.0.1:{port}"),),
        "vanished": (),
        "shared": ((FAKE_PID, f"127.0.0.1:{port}"), (FAKE_PID + 7, f"127.0.0.1:{port}")),
    }[later]
    flip = threading.Timer(0.5, lambda: setattr(rig.inspector, "listener", after))
    flip.start()
    run, message = rig.send()
    flip.join()
    assert len(server.requests) == 1  # it was unknowable at dispatch; the answer is not accepted
    assert rig.inspector.identities[FAKE_PID] == ProcessIdentity(FAKE_PID, FAKE_START)
    assert_quarantined(rig, run, message)


def test_a_server_that_knows_the_bearer_key_is_not_thereby_the_recorded_process(
    rig: Rig,
) -> None:
    """The key authenticates the client to the runtime; it never attributes a response."""
    rig.inspector.listener = ((FAKE_PID + 7, f"127.0.0.1:{rig.record.port}"),)
    run, message = rig.send()  # the fake server would happily answer with the right key
    assert message is None and run.status is RunStatus.FAILED
    assert rig.server.requests == []


# -- F5: HTTP framing --------------------------------------------------------------------------


def test_an_overstated_content_length_with_valid_completion_json_never_reaches_t4(
    rig: Rig,
) -> None:
    rig.server.framing = "short"  # Content-Length exceeds what is sent; the prefix is valid JSON
    run, message = rig.send()
    assert len(rig.server.requests) == 1
    assert_quarantined(rig, run, message)


@pytest.mark.parametrize(
    "framing",
    ["chunked_truncated", "close_delimited", "both", "dup_same", "dup_conflict", "invalid_length"],
)
def test_incomplete_or_ambiguous_framing_is_not_a_completion(rig: Rig, framing: str) -> None:
    rig.server.framing = framing
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_a_complete_chunked_response_is_accepted(rig: Rig) -> None:
    rig.server.framing = "chunked"
    run, message = rig.send()
    assert run.status is RunStatus.SUCCEEDED
    assert message is not None and message.content == rig.server.reply


# -- F6: an ambiguous write stays ambiguous ----------------------------------------------------


def test_a_partial_write_is_unknown_at_start_and_possibly_active_afterwards(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_pipe(self: http.client.HTTPConnection, *args: object, **kwargs: object) -> None:
        raise BrokenPipeError("synthetic partial write")

    monkeypatch.setattr(http.client.HTTPConnection, "request", broken_pipe)
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    assert rig.runtime.start("a", prepared.binding, _request(), 1.0) is StartAck.UNKNOWN
    result = rig.runtime.await_result("a", prepared.binding, 1.0)
    assert isinstance(result, Failed)
    assert result.knowledge is Knowledge.POSSIBLY_ACTIVE  # never NEVER_REACHED


def test_a_partial_write_quarantines_end_to_end(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_pipe(self: http.client.HTTPConnection, *args: object, **kwargs: object) -> None:
        raise BrokenPipeError("synthetic partial write")

    monkeypatch.setattr(http.client.HTTPConnection, "request", broken_pipe)
    run, message = rig.send()
    assert_quarantined(rig, run, message)


def test_never_started_is_still_never_reached(rig: Rig) -> None:
    prepared = rig.runtime.prepare("a")
    assert isinstance(prepared, PreparedBinding)
    result = rig.runtime.await_result("never-started", prepared.binding, 1.0)
    assert isinstance(result, Failed) and result.knowledge is Knowledge.NEVER_REACHED
