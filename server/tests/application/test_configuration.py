"""Conversation configuration pinning, provenance, adoption and the Slice 0A golden baseline."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import (
    GOLDEN_FILE_SHA256,
    ConfigurationCatalog,
    ConfigurationService,
    ShippedConfiguration,
    baseline_manifest,
    golden_document,
    golden_replay,
    load_golden_bytes,
    shipped_configurations,
    view_digest,
)
from anonymous.application.context import ContextBuilder
from anonymous.application.ports.model import (
    ModelExecutionError,
    ModelIdentity,
    ModelOutput,
    ModelRequest,
)
from anonymous.composition import build_application
from anonymous.config import Settings
from anonymous.domain.configuration import (
    BindingOrigin,
    ContextConstruction,
    EffectiveConfiguration,
)
from anonymous.domain.errors import (
    ConfigurationUnavailable,
    ConfigurationUnbound,
    ConversationBusy,
    IdempotencyConflict,
)
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.provenance import Verification
from tests.conftest import Services
from tests.doubles import BoundStore, ManualClock, RecordingModel
from tests.persistence.test_migration_0002 import add_conversation, add_turn, legacy_db

E0 = baseline_manifest()
E2 = EffectiveConfiguration(ContextConstruction("whole-history", 2))  # a later build's default


def catalog(
    *configs: EffectiveConfiguration, default: EffectiveConfiguration | None = None
) -> ConfigurationCatalog:
    shipped = [ShippedConfiguration(c, ContextBuilder, golden_checked=(c is E0)) for c in configs]
    return ConfigurationCatalog(shipped, (default or configs[0]).digest)


def prepare(store: SqliteStore, cat: ConfigurationCatalog) -> ConfigurationService:
    service = ConfigurationService(store, cat)
    service.startup()
    return service


# -- pinning across an upgrade -------------------------------------------------------------------


def test_an_upgrade_changes_the_default_for_new_conversations_but_never_rebinds_old_ones(
    store: SqliteStore, owner: UserId
) -> None:
    old_build = catalog(E0)
    prepare(store, old_build)
    old = Services(store, RecordingModel("one"), catalog=old_build)
    cid = old.conversations.create_conversation(owner).id
    before = old.conversations.send_message(owner, cid, new_uuid(), "hello")
    assert before.run.configuration_digest == E0.digest

    upgraded = catalog(E2, E0, default=E2)  # the new build ships a new default and still runs E0
    prepare(store, upgraded)
    new = Services(store, RecordingModel("two"), catalog=upgraded)
    fresh = new.conversations.create_conversation(owner).id
    assert store.get_current_binding(ConversationId(cid)).configuration_digest == E0.digest  # type: ignore[union-attr]
    assert store.get_current_binding(fresh).configuration_digest == E2.digest  # type: ignore[union-attr]
    after = new.conversations.send_message(owner, cid, new_uuid(), "again")
    assert after.run.configuration_digest == E0.digest  # still the pinned configuration
    assert (
        new.conversations.send_message(owner, fresh, new_uuid(), "x").run.configuration_digest
        == E2.digest
    )
    assert before.run.configuration_digest == E0.digest  # historical provenance not relabeled


def test_each_run_records_label_identity_and_verification_for_every_component(
    store: SqliteStore, owner: UserId
) -> None:
    cat = catalog(E0)
    prepare(store, cat)
    services = Services(store, RecordingModel("r"), catalog=cat)
    cid = services.conversations.create_conversation(owner).id
    run = services.conversations.send_message(owner, cid, new_uuid(), "q").run
    p = run.provenance
    assert p is not None
    assert p.context_configuration.digest == E0.context_digest
    assert p.context_configuration.verification is Verification.VERIFIED
    assert p.context_configuration.label == "whole-history@1"
    assert p.behavior_configuration.explicit_none  # recorded explicitly, not omitted
    assert p.model_artifact.verification is Verification.UNSPECIFIED  # a label is not an identity
    assert p.model_artifact.digest is None and p.model_artifact.label == "test-model-1"
    assert run.binding is not None and run.binding.instance_ref.startswith("inproc-")


# -- explicit adoption ---------------------------------------------------------------------------


def test_adoption_is_explicit_idempotent_reversible_and_affects_only_later_runs(
    store: SqliteStore, owner: UserId
) -> None:
    cat = catalog(E2, E0, default=E2)
    prepare(store, cat)
    services = Services(store, RecordingModel("r"), catalog=cat)
    cid = services.conversations.create_conversation(owner, "x").id
    store.register_configuration(E0.digest, E0.canonical())
    first = services.conversations.send_message(owner, cid, new_uuid(), "one")
    assert first.run.configuration_digest == E2.digest

    adoption_id = new_uuid()
    binding = services.conversations.adopt_configuration(owner, cid, adoption_id, E0.digest)
    assert binding.origin is BindingOrigin.ADOPTION and binding.seq == 2
    assert services.conversations.adopt_configuration(owner, cid, adoption_id, E0.digest) == binding
    with pytest.raises(IdempotencyConflict):
        services.conversations.adopt_configuration(owner, cid, adoption_id, E2.digest)
    second = services.conversations.send_message(owner, cid, new_uuid(), "two")
    assert second.run.configuration_digest == E0.digest
    assert store.get_history(owner, cid).runs[0].configuration_digest == E2.digest  # not rewritten
    services.conversations.adopt_configuration(owner, cid, new_uuid(), E2.digest)  # reversible
    assert store.get_current_binding(ConversationId(cid)).seq == 3  # type: ignore[union-attr]


def test_adoption_is_refused_while_a_run_is_unsettled(store: SqliteStore, owner: UserId) -> None:
    cat = catalog(E2, E0, default=E2)
    prepare(store, cat)
    runtime = ScriptedRuntime()
    runtime.await_gate.arm()
    services = Services(store, runtime, catalog=cat)
    cid = services.conversations.create_conversation(owner).id
    handle = services.coordinator.begin_submit(
        owner=owner,
        conversation_id=ConversationId(cid),
        submission_id=SubmissionId(new_uuid()),
        content="q",
    )
    assert runtime.await_gate.wait_entered()
    with pytest.raises(ConversationBusy):
        services.conversations.adopt_configuration(owner, cid, new_uuid(), E0.digest)
    runtime.await_gate.release()
    handle.wait(5)


# -- an unavailable pinned configuration is visibly blocked, never substituted -------------------


def test_an_unavailable_pinned_configuration_blocks_generation_but_not_reading(
    store: SqliteStore, owner: UserId
) -> None:
    first_build = catalog(E0)
    prepare(store, first_build)
    old = Services(store, RecordingModel("r"), catalog=first_build)
    cid = old.conversations.create_conversation(owner).id
    old.conversations.send_message(owner, cid, new_uuid(), "kept")

    later = catalog(E2)  # a build that can no longer execute E0
    prepare(store, later)
    model = RecordingModel("never")
    services = Services(store, model, catalog=later)
    with pytest.raises(ConfigurationUnavailable):
        services.conversations.send_message(owner, cid, new_uuid(), "blocked")
    assert model.requests == []  # nothing was substituted and nothing was sent
    history = services.conversations.open_conversation(owner, cid)  # reading still works
    assert [m.content for m in history.messages] == ["kept", "r"]  # no message was appended
    # The way out is explicit adoption of an available configuration.
    services.conversations.adopt_configuration(owner, cid, new_uuid(), E2.digest)
    ok = services.conversations.send_message(owner, cid, new_uuid(), "now")
    assert ok.run.configuration_digest == E2.digest
    assert history.runs[0].configuration_digest == E0.digest


def test_a_tampered_stored_manifest_is_unavailable(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    import sqlite3

    cat = catalog(E0)
    prepare(store, cat)
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TRIGGER effective_configurations_are_immutable")
    conn.execute("UPDATE effective_configurations SET manifest = '{}'")
    conn.commit()
    conn.close()
    fresh = catalog(E0)
    ConfigurationService(store, fresh).startup()
    assert not fresh.is_executable(E0.digest)  # failed verification: blocked, not trusted


# -- legacy Slice 0A conversations ---------------------------------------------------------------


def legacy_settings(tmp_path: Path) -> tuple[Settings, Path]:
    path = tmp_path / "legacy.sqlite3"
    conn = legacy_db(path)
    add_turn(conn, add_conversation(conn, "kept"), "succeeded", text="old question")
    add_turn(conn, add_conversation(conn, "failed"), "failed", text="old failed")
    conn.commit()
    conn.close()
    return Settings(db_path=path), path


def test_legacy_conversations_are_bound_at_startup_only_after_the_baseline_reproduces_0a(
    tmp_path: Path,
) -> None:
    settings, _ = legacy_settings(tmp_path)
    app = build_application(settings, model=RecordingModel("hello again"))
    try:
        assert app.startup_report.legacy_blockers == 0
        owner = app.owner
        conversations = app.conversations.list_conversations(owner)
        assert len(conversations) == 2
        for conversation in conversations:
            binding = app.store.get_current_binding(conversation.id)
            assert binding is not None and binding.origin is BindingOrigin.LEGACY_BASELINE
            assert binding.configuration_digest == E0.digest
            assert binding.baseline_evidence == GOLDEN_FILE_SHA256  # the evidence is recorded
        target = next(c for c in conversations if c.title == "kept")
        history = app.conversations.open_conversation(owner, target.id)
        assert history.runs[0].provenance is None  # historical provenance stays unrecorded
        assert history.runs[0].configuration_digest is None  # nothing fabricated for old runs
        outcome = app.conversations.send_message(owner, target.id, new_uuid(), "continue")
        assert outcome.assistant_message is not None
        assert outcome.run.configuration_digest == E0.digest
        assert [m.content for m in app.conversations.open_conversation(owner, target.id).messages][
            :2
        ] == [
            "old question",
            "reply",
        ]
    finally:
        assert app.shutdown()


class ReversedBuilder(ContextBuilder):
    """An implementation that does NOT reproduce Slice 0A (message order reversed)."""

    def build(self, triggering_message):  # type: ignore[no-untyped-def]
        request = super().build(triggering_message)
        return ModelRequest(messages=tuple(reversed(request.messages)))


def test_if_equivalence_cannot_be_shown_legacy_conversations_stay_unbound_and_need_adoption(
    tmp_path: Path,
) -> None:
    settings, _ = legacy_settings(tmp_path)
    broken = ConfigurationCatalog(
        [
            ShippedConfiguration(E0, ReversedBuilder, golden_checked=True),
            ShippedConfiguration(E2, ContextBuilder),
        ],
        default_digest=E0.digest,
    )
    app = build_application(settings, model=RecordingModel("r"), catalog=broken)
    try:
        assert not broken.is_executable(E0.digest)  # failed the golden replay: not executable
        owner = app.owner
        conversations = app.conversations.list_conversations(owner)
        assert all(app.store.get_current_binding(c.id) is None for c in conversations)  # not bound
        target = next(c for c in conversations if c.title == "kept")
        with pytest.raises(ConfigurationUnbound):
            app.conversations.send_message(owner, target.id, new_uuid(), "blocked")
        assert app.conversations.open_conversation(owner, target.id).messages  # still readable
        # Explicit adoption of an available configuration is the only way forward.
        app.conversations.adopt_configuration(owner, target.id, new_uuid(), E2.digest)
        ok = app.conversations.send_message(owner, target.id, new_uuid(), "now")
        assert ok.run.configuration_digest == E2.digest
        # And a NEW conversation is bound to the default, which is unavailable: visibly blocked.
        fresh = app.conversations.create_conversation(owner)
        with pytest.raises(ConfigurationUnavailable):
            app.conversations.send_message(owner, fresh.id, new_uuid(), "blocked")
    finally:
        assert app.shutdown()


# -- the golden baseline -------------------------------------------------------------------------


EVIDENCE = (
    Path(__file__).resolve().parents[3] / "docs" / "evidence" / "ld-04-slice-0a-context-golden.json"
)


def test_the_packaged_fixture_is_byte_identical_to_the_evidence_record_and_pinned() -> None:
    packaged = load_golden_bytes()
    assert hashlib.sha256(packaged).hexdigest() == GOLDEN_FILE_SHA256
    assert packaged == EVIDENCE.read_bytes()  # one reference, two locations, same bytes


def test_the_shipped_builder_reproduces_every_slice_0a_view_byte_for_byte() -> None:
    assert golden_replay(ContextBuilder) == []
    assert shipped_configurations()[0].golden_checked


def test_a_builder_that_differs_from_0a_is_detected() -> None:
    problems = golden_replay(ReversedBuilder)
    assert problems and any(p.startswith("FX-02") for p in problems)


def test_a_tampered_fixture_file_is_rejected_before_use() -> None:
    data = bytearray(load_golden_bytes())
    data[100] ^= 0x01
    assert golden_replay(ContextBuilder, bytes(data)) == [
        "golden fixture file digest does not match the pinned digest"
    ]


class Scripted:
    """A synchronous model returning scripted replies; ``None`` scripts a model failure."""

    identity = ModelIdentity("golden-stub-model", "golden-stub-runtime")

    def __init__(self) -> None:
        self.script: list[str | None] = []
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelOutput:
        self.requests.append(request)
        reply = self.script.pop(0)
        if reply is None:
            raise ModelExecutionError("stub_failure", "scripted failure")
        return ModelOutput(reply, self.identity)


def views(model: Scripted) -> list[list[dict[str, str]]]:
    return [
        [{"role": m.role.value, "content": m.content} for m in r.messages] for r in model.requests
    ]


def test_every_fixture_replays_through_the_real_store_and_coordinator(
    tmp_path: Path,
) -> None:
    """End to end, including FX-07 (two interleaved conversations) and the order-versus-time case:
    the views the runtime actually receives equal the ones the real 0A code produced."""
    document = golden_document()
    for fixture in document["fixtures"]:
        db = tmp_path / f"{fixture['id']}.sqlite3"
        from anonymous.adapters.persistence.sqlite.migrations import migrate

        migrate(db)
        backwards = fixture["id"] == "FX-06"
        clock = ManualClock(
            datetime(2026, 1, 1, tzinfo=UTC), step=timedelta(seconds=-1 if backwards else 1)
        )
        store = BoundStore(db, clock)
        cat = ConfigurationCatalog(shipped_configurations())
        ConfigurationService(store, cat).startup()
        owner = store.ensure_dev_owner()
        model = Scripted()
        services = Services(store, model, catalog=cat)
        if fixture["id"] == "FX-07":
            c1 = services.conversations.create_conversation(owner).id
            c2 = services.conversations.create_conversation(owner).id
            for cid, text, reply in [
                (c1, "A1", "a1"),
                (c2, "B1", "b1"),
                (c1, "A2", "a2"),
                (c2, "B2", "b2"),
            ]:
                model.script.append(reply)
                services.conversations.send_message(owner, cid, new_uuid(), text)
            expected = [e["view"] for e in fixture["dispatched_views_in_call_order"]]
        else:
            cid = services.conversations.create_conversation(owner).id
            history = fixture["history_after"]
            for index, message in enumerate(history):
                if message["role"] != "user":
                    continue
                answered = index + 1 < len(history) and history[index + 1]["role"] == "assistant"
                model.script.append(history[index + 1]["content"] if answered else None)
                services.conversations.send_message(owner, cid, new_uuid(), message["content"])
            expected = [d["view"] for d in fixture["dispatched_views"]]
            stored = store.get_history(owner, cid)
            assert [(m.position, m.role.value, m.content) for m in stored.messages] == [
                (h["position"], h["role"], h["content"]) for h in history
            ]
        assert views(model) == expected, fixture["id"]
        assert [view_digest(v) for v in views(model)] == [view_digest(v) for v in expected]
    assert json.loads(load_golden_bytes())["facts"]["model_request_fields"] == ["messages"]
