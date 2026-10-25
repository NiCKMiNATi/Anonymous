"""Context-selection metadata through the real HTTP -> coordinator -> SQLite path (ADR-0017).

Scripted and fake-loopback runtimes with synthetic text only: no real model, no inference.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anonymous.adapters.clock import SystemClock
from anonymous.adapters.model.llama_http import LlamaHttpRuntime
from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.api.app import create_app
from anonymous.application.configuration import baseline_manifest
from anonymous.application.ports.model import Completed
from anonymous.config import Settings
from tests.adapters.llama_fakes import FakeLlamaServer, write_launch
from tests.api.conftest import BASE_URL
from tests.doubles import ManualClock

U1, A1, U2 = "u" * 10, "a" * 10, "v" * 5


def scripted(limit: int | None) -> ScriptedRuntime:
    runtime = ScriptedRuntime(max_input_chars=limit, reply=A1)
    runtime.result = lambda _request: Completed(runtime.reply, "", runtime.model_id)
    return runtime


def open_with(db_path: Path, runtime: ScriptedRuntime) -> TestClient:
    app = create_app(Settings(db_path=db_path, port=8000), runtime=runtime, clock=ManualClock())
    return TestClient(app, base_url=BASE_URL)


def new_conversation(client: TestClient) -> str:
    return str(client.post("/api/v1/conversations", json={"title": None}).json()["id"])


def send(client: TestClient, cid: str, content: str, sid: str | None = None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"submission_id": sid or str(uuid.uuid4()), "content": content},
    )


def test_a_run_reports_its_context_selection_and_the_history_stays_complete(
    db_path: Path,
) -> None:
    runtime = scripted(1000)
    with open_with(db_path, runtime) as client:
        cid = new_conversation(client)
        send(client, cid, U1)
        runtime.max_input_chars = 15
        body = send(client, cid, U2).json()
        context = body["run"]["context"]
        assert context["omitted_count"] == 1 and context["selected_count"] == 2
        assert context["limit_chars"] == 15 and context["measure"] == "characters"
        assert set(context) == {
            "first_message_id",
            "first_position",
            "selected_count",
            "omitted_count",
            "selected_chars",
            "limit_chars",
            "measure",
            "truncated_included_count",
        }
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["content"] for m in detail["messages"]] == [U1, A1, U2, A1]  # nothing omitted
        by_id = {r["id"]: r for r in detail["runs"]}
        assert by_id[body["run"]["id"]]["context"] == context
        assert by_id[body["assistant_message"]["produced_by_run_id"]]["context"] == context
        first_run = detail["runs"][0]
        assert first_run["context"]["omitted_count"] == 0  # recorded: nothing omitted


def test_the_metadata_survives_restart_replay_and_refetch(db_path: Path) -> None:
    sid = str(uuid.uuid4())
    runtime = scripted(1000)
    with open_with(db_path, runtime) as client:
        cid = new_conversation(client)
        send(client, cid, U1)
        runtime.max_input_chars = 15
        first = send(client, cid, U2, sid).json()
    runtime = scripted(15)  # a restarted application
    with open_with(db_path, runtime) as client:
        replay = send(client, cid, U2, sid)
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["run"]["context"] == first["run"]["context"]
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert detail["runs"][1]["context"] == first["run"]["context"]
        assert runtime.calls_of("start") == []  # the replay ran nothing


def test_an_oversized_latest_message_is_refused_with_the_fixed_message(db_path: Path) -> None:
    runtime = scripted(10)
    with open_with(db_path, runtime) as client:
        cid = new_conversation(client)
        body = send(client, cid, "z" * 11).json()
        run = body["run"]
        assert run["status"] == "failed" and run["failure_code"] == "message_exceeds_capacity"
        assert run["failure_message"] == (
            "This message is longer than the model can accept; nothing was sent."
        )
        assert run["context"] is None  # never dispatched, so nothing was recorded
        assert body["user_message"]["content"] == "z" * 11
        assert runtime.calls == []
        assert client.get("/api/v1/health").json()["generation"]["quarantined_runs"] == 0


def test_whole_history_conversations_and_older_rows_report_no_selection(db_path: Path) -> None:
    runtime = scripted(1000)
    with open_with(db_path, runtime) as client:  # registers both configurations
        bounded = new_conversation(client)
        send(client, bounded, U1)
    store = SqliteStore(db_path, SystemClock())
    old = store.create_conversation(store.ensure_dev_owner(), None, baseline_manifest().digest)
    conn = sqlite3.connect(db_path)
    stored = conn.execute("SELECT provenance_json FROM model_runs").fetchone()[0]
    conn.close()
    assert "context_selection" in stored
    with open_with(db_path, runtime) as client:
        body = send(client, old.id, U1).json()
        assert body["run"]["status"] == "succeeded"
        assert body["run"]["context"] is None  # whole-history: unrecorded, not "nothing omitted"
        detail = client.get(f"/api/v1/conversations/{old.id}").json()
        assert [r["context"] for r in detail["runs"]] == [None]


# -- truncated replies inside the window --------------------------------------------------------

CUT = "The three colors are red, orange and"


@pytest.fixture
def llama() -> Iterator[FakeLlamaServer]:
    fake = FakeLlamaServer(reply=CUT, finish_reason="length").start()
    try:
        yield fake
    finally:
        fake.stop()


def test_a_truncated_reply_in_the_window_is_sent_verbatim_and_counted(
    db_path: Path, llama: FakeLlamaServer, tmp_path: Path
) -> None:
    path, _, inspector = write_launch(tmp_path / "launch", llama)
    runtime = LlamaHttpRuntime(path, max_tokens=64, max_input_chars=1400, inspector=inspector)
    app = create_app(Settings(db_path=db_path, port=8000), runtime=runtime, clock=ManualClock())
    with TestClient(app, base_url=BASE_URL) as client:
        cid = new_conversation(client)
        first = send(client, cid, "name three colors").json()
        assert first["assistant_message"]["completeness"] == "truncated"
        llama.finish_reason, llama.reply = "stop", "ok"
        second = send(client, cid, "go on").json()
    sent = llama.requests[-1].json()["messages"]
    assert [m["content"] for m in sent] == ["name three colors", CUT, "go on"]  # verbatim, unmarked
    assert second["run"]["context"]["truncated_included_count"] == 1
    assert second["run"]["context"]["omitted_count"] == 0
    assert first["run"]["context"]["truncated_included_count"] == 0


def test_an_over_budget_conversation_keeps_working_without_quarantine(
    db_path: Path, llama: FakeLlamaServer, tmp_path: Path
) -> None:
    path, _, inspector = write_launch(tmp_path / "launch", llama)
    runtime = LlamaHttpRuntime(path, max_tokens=64, max_input_chars=100, inspector=inspector)
    app = create_app(Settings(db_path=db_path, port=8000), runtime=runtime, clock=ManualClock())
    with TestClient(app, base_url=BASE_URL) as client:
        cid = new_conversation(client)
        omitted = []
        for turn in range(4):
            body = send(client, cid, f"question number {turn} " + "q" * 20).json()
            assert body["run"]["status"] == "succeeded"
            omitted.append(body["run"]["context"]["omitted_count"])
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        health = client.get("/api/v1/health").json()
    assert omitted[0] == 0 and omitted[-1] > 0  # the window slid, the request never exceeded 100
    sizes = [sum(len(m["content"]) for m in r.json()["messages"]) for r in llama.requests]
    assert max(sizes) <= 100
    assert len(detail["messages"]) == 8  # every message retained
    assert health["generation"]["state"] == "open"
