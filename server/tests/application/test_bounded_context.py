"""Bounded recent-history context through the real coordinator, worker and SQLite (ADR-0017).

Scripted and in-process runtimes with synthetic text only: no real model, no inference.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import (
    ConfigurationCatalog,
    baseline_manifest,
    bounded_recent_manifest,
    default_configuration_digest,
    shipped_configurations,
)
from anonymous.application.context import BoundedRecentContextBuilder
from anonymous.application.ports.model import Completed, PrepareFailed
from anonymous.composition import build_application
from anonymous.config import Settings
from anonymous.domain.errors import StorageFailure
from anonymous.domain.ids import ConversationId, UserId, new_uuid
from anonymous.domain.models import ModelRun, RunStatus
from anonymous.domain.provenance import ContextSelection
from tests.conftest import Services
from tests.doubles import ManualClock, RecordingModel

E0 = baseline_manifest()
BOUNDED = bounded_recent_manifest()
U1, A1, U2 = "u" * 10, "a" * 10, "v" * 5


def bounded_catalog() -> ConfigurationCatalog:
    """What the composition root ships: both configurations, the bounded one the default."""
    return ConfigurationCatalog(shipped_configurations(), default_digest=BOUNDED.digest)


class Rig:
    """A scripted runtime that records the exact request it was given for each run."""

    def __init__(self, store: SqliteStore, owner: UserId, *, limit: int | None, reply: str = A1):
        self.store, self.owner = store, owner
        self.seen: list[list[tuple[str, str]]] = []
        self.runtime = ScriptedRuntime(max_input_chars=limit, reply=reply)
        self.runtime.result = self._result
        self.services = Services(store, self.runtime, catalog=bounded_catalog())
        self.cid = self.services.conversations.create_conversation(owner).id

    def _result(self, request):  # type: ignore[no-untyped-def]
        self.seen.append([(m.role.value, m.content) for m in request.messages])
        return Completed(self.runtime.reply, "", self.runtime.model_id)

    def send(self, text: str, *, cid: ConversationId | None = None, sid: str | None = None):  # type: ignore[no-untyped-def]
        return self.services.conversations.send_message(
            self.owner, cid or self.cid, sid or new_uuid(), text
        )


def selection_of(run: ModelRun) -> ContextSelection:
    assert run.provenance is not None and run.provenance.context_selection is not None
    return run.provenance.context_selection


def stored_provenance(store: SqliteStore, run: ModelRun) -> str | None:
    row = store.get_run(run.id)
    return row.provenance.to_json() if row.provenance is not None else None


# -- window selection, end to end ---------------------------------------------------------------


@pytest.mark.parametrize(("limit", "omitted"), [(25, 0), (24, 1)])
def test_exact_boundary_fits_and_one_character_over_drops_the_earliest(
    store: SqliteStore, owner: UserId, limit: int, omitted: int
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)  # reply A1
    rig.runtime.max_input_chars = limit
    second = rig.send(U2)
    assert second.run.status is RunStatus.SUCCEEDED
    selection = selection_of(second.run)
    assert (selection.omitted_count, selection.limit_chars) == (omitted, limit)
    expected = [("user", U1), ("assistant", A1), ("user", U2)][omitted:]
    assert rig.seen[-1] == expected  # order and roles preserved, nothing cut or reworded
    assert selection.selected_chars == sum(len(c) for _, c in expected)
    assert selection.selected_count == len(expected)


def test_the_window_is_a_contiguous_suffix_that_stops_at_the_first_misfit(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000, reply="x" * 50)
    rig.send("hi")  # u1 (2 chars); reply: 50 chars
    rig.runtime.max_input_chars = 30
    run = rig.send("yo").run  # u2 (2 chars)
    assert rig.seen[-1] == [
        ("user", "yo")
    ]  # the 50-character reply does not fit; u1 is not reached
    selection = selection_of(run)
    assert (selection.first_position, selection.omitted_count) == (3, 2)


def test_the_latest_message_is_always_in_the_view_when_it_fits(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    rig.runtime.max_input_chars = len(U2)  # exactly the latest message
    run = rig.send(U2).run
    assert run.status is RunStatus.SUCCEEDED
    assert rig.seen[-1] == [("user", U2)]
    assert selection_of(run).selected_count == 1


# -- the oversized trigger ----------------------------------------------------------------------


def test_an_oversized_latest_message_is_refused_before_dispatch_without_quarantine(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=10)
    rig.send("short")
    before = rig.runtime.calls.copy()
    outcome = rig.send("z" * 11)
    run = outcome.run
    assert run.status is RunStatus.FAILED
    assert run.failure_code == "message_exceeds_capacity"
    assert (
        run.failure_message == "This message is longer than the model can accept; nothing was sent."
    )
    assert outcome.user_message.content == "z" * 11  # saved, not cut, not deleted
    assert outcome.assistant_message is None
    assert run.dispatched_at is None and run.provenance is None
    assert rig.runtime.calls == before  # no prepare, start or await: never dispatched
    state = store.generation_state()
    assert state.quarantined_runs == () and state.legacy_blockers == ()
    follow_up = rig.send("ok")  # the conversation is still usable
    assert follow_up.run.status is RunStatus.SUCCEEDED
    assert rig.seen[-1] == [("user", "ok")]  # the oversized message ends the window


def test_a_whole_history_conversation_keeps_the_old_refusal_and_code(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000)
    cid = ConversationId(store.create_conversation(owner, None, E0.digest).id)
    rig.send(U1, cid=cid)
    rig.runtime.max_input_chars = 24
    refused = rig.send(U2, cid=cid)  # whole history is 25 characters
    assert refused.run.failure_code == "context_exceeds_capacity"
    assert refused.run.provenance is None


# -- history is never changed -------------------------------------------------------------------


def test_the_full_history_stays_in_sqlite_and_nothing_is_rewritten(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    rig.runtime.max_input_chars = len(U2)
    rig.send(U2)
    rig.send("w" * (len(U2) + 1))  # refused: over the limit
    history = store.get_history(owner, rig.cid)
    assert [m.content for m in history.messages] == [U1, A1, U2, A1, "w" * (len(U2) + 1)]
    assert [m.position for m in history.messages] == [1, 2, 3, 4, 5]
    assert len(history.runs) == 3


def test_computing_a_selection_alone_has_no_side_effects(store: SqliteStore, owner: UserId) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    outcome = rig.send(U2)
    before = store.get_history(owner, rig.cid)
    builder = BoundedRecentContextBuilder(store)
    first = builder.build_view(outcome.user_message, 12)
    assert builder.build_view(outcome.user_message, 12) == first  # deterministic
    assert store.get_history(owner, rig.cid) == before


# -- configuration choice -----------------------------------------------------------------------


def test_new_conversations_bind_the_bounded_configuration_and_old_ones_keep_theirs(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=None)
    old = ConversationId(store.create_conversation(owner, None, E0.digest).id)
    assert store.get_current_binding(rig.cid).configuration_digest == BOUNDED.digest  # type: ignore[union-attr]
    new_run = rig.send("hi").run
    old_run = rig.send("hi", cid=old).run
    assert new_run.configuration_digest == BOUNDED.digest
    assert new_run.provenance is not None
    assert new_run.provenance.context_configuration.label == "bounded-recent-history@1"
    assert old_run.configuration_digest == E0.digest  # never silently rebound
    assert old_run.provenance is not None
    assert old_run.provenance.context_configuration.label == "whole-history@1"
    assert old_run.provenance.context_selection is None  # unrecorded, not "nothing omitted"
    assert store.get_current_binding(old).configuration_digest == E0.digest  # type: ignore[union-attr]


def test_the_application_default_is_the_bounded_configuration(tmp_path: Path) -> None:
    app = build_application(Settings(db_path=tmp_path / "d.sqlite3"), clock=ManualClock())
    try:
        assert app.catalog.default_digest == default_configuration_digest() == BOUNDED.digest
        conversation = app.conversations.create_conversation(app.owner)
        binding = app.store.get_current_binding(ConversationId(conversation.id))
        assert binding is not None and binding.configuration_digest == BOUNDED.digest
        assert E0.digest in app.catalog.executable_digests()  # old conversations still run
    finally:
        app.shutdown()


def test_a_fake_runtime_without_a_limit_sees_the_whole_history_unchanged(
    store: SqliteStore, owner: UserId
) -> None:
    model = RecordingModel("reply")
    services = Services(store, model, catalog=bounded_catalog())
    bounded = services.conversations.create_conversation(owner).id
    whole = ConversationId(store.create_conversation(owner, None, E0.digest).id)
    for cid in (bounded, whole):
        for text in ("one", "two", "three"):
            services.conversations.send_message(owner, cid, new_uuid(), text * 400)
    half = len(model.requests) // 2
    assert model.requests[:half] == model.requests[half:]  # identical views, identical lengths
    assert len(model.requests[half - 1].messages) == 5
    last = store.get_history(owner, bounded).runs[-1]
    selection = selection_of(last)
    assert (selection.omitted_count, selection.limit_chars) == (0, None)


# -- provenance ---------------------------------------------------------------------------------


def test_the_selection_is_recorded_at_dispatch_and_is_immutable(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    rig.runtime.max_input_chars = 15
    run = rig.send(U2).run
    selection = selection_of(run)
    assert selection.to_dict() == {
        "first_message_id": store.get_history(owner, rig.cid).messages[1].id,
        "first_position": 2,
        "selected_count": 2,
        "omitted_count": 1,
        "selected_chars": 15,
        "limit_chars": 15,
        "measure": "characters",
        "truncated_included_count": 0,
    }
    assert selection_of(store.get_run(run.id)) == selection  # read back from SQLite
    assert U1 not in (run.provenance.to_json() if run.provenance else "")  # ids and counts only
    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(
            "UPDATE model_runs SET provenance_json = '{}', state_version = state_version + 1"
            " WHERE id = ?",
            (run.id,),
        )
    conn.close()
    assert selection_of(store.get_run(run.id)) == selection


def test_the_selection_is_reproducible_from_history_and_the_trigger(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    rig.runtime.max_input_chars = 20
    outcome = rig.send(U2)
    recomputed = BoundedRecentContextBuilder(store).build_view(outcome.user_message, 20).selection
    assert recomputed == selection_of(outcome.run)


# -- retry and replay ---------------------------------------------------------------------------


def test_a_retry_records_its_own_identical_selection_and_a_replay_adds_nothing(
    store: SqliteStore, owner: UserId
) -> None:
    rig = Rig(store, owner, limit=1000)
    rig.send(U1)
    rig.runtime.max_input_chars = 15
    rig.runtime.prepare_failure = PrepareFailed("runtime_unavailable", "down")
    failed = rig.send(U2)
    assert failed.run.status is RunStatus.FAILED and failed.run.provenance is None
    rig.runtime.prepare_failure = None
    retried = rig.services.conversations.retry_generation(
        owner, rig.cid, new_uuid(), failed.user_message.id
    )
    assert retried.run.status is RunStatus.SUCCEEDED and retried.run.kind.value == "retry"
    selection = selection_of(retried.run)
    assert selection.omitted_count == 1
    assert rig.seen[-1] == [("assistant", A1), ("user", U2)]

    sid = new_uuid()
    first = rig.send("next", sid=sid)
    calls = len(rig.runtime.calls)
    replay = rig.send("next", sid=sid)
    assert replay.replayed and len(rig.runtime.calls) == calls  # nothing was re-run
    assert selection_of(replay.run) == selection_of(first.run)


def test_a_storage_failure_while_reading_history_refuses_before_dispatch(
    store: SqliteStore, owner: UserId, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(store, owner, limit=1000)

    def broken(*_: object) -> tuple[()]:
        raise StorageFailure("injected")

    monkeypatch.setattr(store, "read_messages_through", broken)
    run = rig.send("x").run
    assert run.failure_code == "context_unavailable" and run.provenance is None
    assert rig.runtime.calls_of("start") == []
