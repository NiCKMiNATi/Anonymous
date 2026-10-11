"""A populated Slice 0A dataset with SEVERAL unresolved executions, opened by 0B-1 (design §5.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anonymous.adapters.model.fake import FakeModelAdapter
from anonymous.api.app import create_app
from anonymous.composition import build_application
from anonymous.config import Settings
from anonymous.domain.errors import ConversationBusy, LegacyUnresolvedBlock
from anonymous.domain.ids import RunId, new_uuid
from anonymous.domain.models import RunStatus
from tests.conftest import FAST
from tests.doubles import ManualClock, RecordingModel
from tests.persistence.test_migration_0002 import LEGACY_TABLES, populated


def raw_snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    conn = sqlite3.connect(path)
    try:
        return {t: [tuple(r) for r in conn.execute(q).fetchall()] for t, q in LEGACY_TABLES.items()}
    finally:
        conn.close()


def unresolved_rows(snapshot: dict[str, list[tuple[object, ...]]]) -> list[tuple[object, ...]]:
    return [r for r in snapshot["model_runs"] if r[3] in ("in_flight", "indeterminate")]


@pytest.fixture
def legacy(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    path = tmp_path / "legacy.sqlite3"
    runs = populated(path)
    return path, runs


@pytest.mark.parametrize("model", [RecordingModel("x"), None], ids=["test-model", "fake-adapter"])
def test_unresolved_legacy_runs_block_all_dispatch_and_nothing_resolves_them(
    legacy: tuple[Path, dict[str, str]], model: RecordingModel | None
) -> None:
    path, runs = legacy
    # ``None`` runs the shipped FakeModelAdapter, whose label equals the legacy rows' runtime_id:
    # a matching label is not evidence, so nothing is resolved.
    app = build_application(Settings(db_path=path), model=model, execution_settings=FAST)
    try:
        report = app.startup_report
        assert report.legacy_blockers == 4 and report.pending_settled == 1
        state = app.store.generation_state()
        assert len(state.legacy_blockers) == 4 and state.quarantined_runs == ()
        assert {b.runtime_label for b in state.legacy_blockers} == {"fake-in-process-runtime-1"}
        refusals: list[type[Exception]] = []
        for conversation in app.conversations.list_conversations(app.owner):
            history = app.conversations.open_conversation(app.owner, conversation.id)
            assert history.messages  # reading works everywhere
            with pytest.raises((LegacyUnresolvedBlock, ConversationBusy)) as refused:
                app.conversations.send_message(app.owner, conversation.id, new_uuid(), "no")
            refusals.append(type(refused.value))
        # The four unresolved conversations are busy; every OTHER conversation is blocked
        # globally because a legacy execution could still be active somewhere.
        assert refusals.count(ConversationBusy) == 4
        assert refusals.count(LegacyUnresolvedBlock) == 3
        assert app.execution.reconcile().legacy_blockers == 4  # nothing to resolve them with
        assert len(app.store.list_unresolved_runs()) == 4
        # None of them was assigned the single slot, and no binding or fence was invented.
        conn = sqlite3.connect(path)
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM model_runs WHERE slot_id IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM model_runs WHERE record_epoch='legacy_0a'"
                    " AND (binding_format IS NOT NULL OR closed_at IS NOT NULL"
                    " OR handoff IS NOT NULL)"
                ).fetchone()[0]
                == 0
            )
        finally:
            conn.close()
    finally:
        assert app.shutdown()
    # Every legacy unresolved row is byte-for-byte what 0A left, after startup and shutdown.
    rows = {r[0]: r for r in raw_snapshot(path)["model_runs"]}
    for name in ("in_flight_a", "in_flight_b", "indeterminate_a", "indeterminate_b"):
        assert rows[runs[name]][3] in ("in_flight", "indeterminate")
    pending = rows[runs["pending"]]
    assert pending[3] == "failed" and pending[6] == "interrupted_before_dispatch"


def test_repeated_restarts_change_nothing_and_the_block_persists(
    legacy: tuple[Path, dict[str, str]],
) -> None:
    path, _ = legacy
    states = []
    for _ in range(3):
        app = build_application(
            Settings(db_path=path), model=RecordingModel(), execution_settings=FAST
        )
        try:
            states.append(
                (raw_snapshot(path)["model_runs"], app.store.generation_state().legacy_blockers)
            )
        finally:
            assert app.shutdown()
    assert states[0] == states[1] == states[2]
    assert len(states[0][1]) == 4


def test_http_reports_the_block_and_refuses_with_a_specific_reason(
    legacy: tuple[Path, dict[str, str]],
) -> None:
    path, runs = legacy
    app = create_app(Settings(db_path=path), model=RecordingModel(), clock=ManualClock())
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        health = client.get("/api/v1/health").json()
        assert health["generation"] == {
            "state": "blocked",
            "reason": "generation_blocked_legacy_unresolved",
            "legacy_unresolved_runs": 4,
            "quarantined_runs": 0,
        }
        conversations = client.get("/api/v1/conversations").json()["conversations"]
        target = next(c for c in conversations if c["title"] == "pending")
        refused = client.post(
            f"/api/v1/conversations/{target['id']}/messages",
            json={"submission_id": new_uuid(), "content": "hello"},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "generation_blocked_legacy_unresolved"
        detail = client.get(f"/api/v1/conversations/{target['id']}").json()
        assert [m["content"] for m in detail["messages"]] == [
            "hello"
        ]  # history readable, unchanged
        assert detail["runs"][0]["status"] == "failed"
    assert RunId(runs["in_flight_a"])


def test_a_dataset_with_only_resolved_legacy_runs_is_not_blocked(tmp_path: Path) -> None:
    from tests.persistence.test_migration_0002 import add_conversation, add_turn, legacy_db

    path = tmp_path / "clean-legacy.sqlite3"
    conn = legacy_db(path)
    add_turn(conn, add_conversation(conn, "ok"), "succeeded")
    add_turn(conn, add_conversation(conn, "bad"), "failed")
    conn.commit()
    conn.close()
    app = build_application(
        Settings(db_path=path), model=FakeModelAdapter(), execution_settings=FAST
    )
    try:
        assert app.startup_report.legacy_blockers == 0
        target = app.conversations.list_conversations(app.owner)[0]
        outcome = app.conversations.send_message(app.owner, target.id, new_uuid(), "go")
        assert outcome.run.status is RunStatus.SUCCEEDED
    finally:
        assert app.shutdown()


def test_the_default_dataset_is_a_new_file_so_legacy_data_is_never_executed_against() -> None:
    assert Settings().db_path.name == "anonymous-0b1-dev.sqlite3"
