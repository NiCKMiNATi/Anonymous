"""Truncated replies through the real HTTP -> coordinator -> SQLite path (ADR-0016).

A fake loopback llama server answers with the exact finish ``length``; nothing else is faked.
Synthetic data only: no runtime, model or inference.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anonymous.adapters.model.llama_http import LlamaHttpRuntime
from anonymous.api.app import create_app
from anonymous.config import Settings
from anonymous.domain.errors import RetryNotEligible
from tests.adapters.llama_fakes import FakeLlamaServer, write_launch
from tests.api.conftest import BASE_URL, open_client
from tests.doubles import ManualClock
from tests.persistence.test_migration_0002 import add_conversation, add_turn, legacy_db

CUT = "The three colors are red, orange and"


@pytest.fixture
def server() -> Iterator[FakeLlamaServer]:
    fake = FakeLlamaServer(reply=CUT, finish_reason="length").start()
    try:
        yield fake
    finally:
        fake.stop()


@contextmanager
def open_llama(db_path: Path, server: FakeLlamaServer, tmp_path: Path) -> Iterator[TestClient]:
    path, _, inspector = write_launch(tmp_path / "launch", server)
    runtime = LlamaHttpRuntime(path, max_tokens=64, max_input_chars=1400, inspector=inspector)
    app = create_app(Settings(db_path=db_path, port=8000), runtime=runtime, clock=ManualClock())
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


def new_conversation(client: TestClient) -> str:
    return str(client.post("/api/v1/conversations", json={"title": None}).json()["id"])


def send(client: TestClient, cid: str, content: str, sid: str | None = None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"submission_id": sid or str(uuid.uuid4()), "content": content},
    )


def test_a_truncated_reply_is_labelled_in_the_submission_result_and_the_history(
    db_path: Path, server: FakeLlamaServer, tmp_path: Path
) -> None:
    with open_llama(db_path, server, tmp_path) as client:
        cid = new_conversation(client)
        response = send(client, cid, "name three colors")
        assert response.status_code == 201
        body = response.json()
        assert body["run"]["status"] == "succeeded"  # a run success; the message carries the label
        assert body["user_message"]["completeness"] is None
        assert body["assistant_message"]["completeness"] == "truncated"
        assert body["assistant_message"]["content"] == CUT  # the text is untouched
        assert body["run"]["termination_basis"] == "runtime_reported_terminal"  # T4's usual stamp

        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["completeness"] for m in detail["messages"]] == [None, "truncated"]
        assert detail["messages"][1]["content"] == CUT
        health = client.get("/api/v1/health").json()
        assert health["generation"]["state"] == "open"
        assert health["generation"]["quarantined_runs"] == 0


def test_a_normal_reply_is_complete_and_a_second_message_still_works(
    db_path: Path, server: FakeLlamaServer, tmp_path: Path
) -> None:
    with open_llama(db_path, server, tmp_path) as client:
        cid = new_conversation(client)
        send(client, cid, "first")
        server.finish_reason, server.reply = "stop", "a full answer."
        second = send(client, cid, "second")
        assert second.status_code == 201
        assert second.json()["assistant_message"]["completeness"] == "complete"
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["completeness"] for m in detail["messages"]] == [
            None,
            "truncated",
            None,
            "complete",
        ]


def test_replaying_a_submission_returns_the_same_truncated_message(
    db_path: Path, server: FakeLlamaServer, tmp_path: Path
) -> None:
    with open_llama(db_path, server, tmp_path) as client:
        cid = new_conversation(client)
        sid = str(uuid.uuid4())
        first = send(client, cid, "name three colors", sid)
        server.finish_reason, server.reply = "stop", "different now"  # a re-run would differ
        replay = send(client, cid, "name three colors", sid)
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["assistant_message"] == first.json()["assistant_message"]
    assert replay.json()["assistant_message"]["completeness"] == "truncated"
    assert len(server.requests) == 1  # the model was not called again


def test_the_label_survives_an_application_restart_and_a_replay_after_it(
    db_path: Path, server: FakeLlamaServer, tmp_path: Path
) -> None:
    sid = str(uuid.uuid4())
    with open_llama(db_path, server, tmp_path) as client:
        cid = new_conversation(client)
        first = send(client, cid, "name three colors", sid).json()
    # The application is gone (guard released); a new process opens the same database.
    with open_llama(db_path, server, tmp_path) as client:
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["completeness"] for m in detail["messages"]] == [None, "truncated"]
        assert detail["messages"][1] == first["assistant_message"]
        replay = send(client, cid, "name three colors", sid)
        assert replay.status_code == 200
        assert replay.json()["assistant_message"]["completeness"] == "truncated"
        health = client.get("/api/v1/health").json()
        assert health["generation"]["state"] == "open"
        server.finish_reason, server.reply = "stop", "after the restart"
        assert send(client, cid, "and then").status_code == 201  # the slot is free


def test_a_truncated_success_is_not_retryable_and_changes_nothing(
    db_path: Path, server: FakeLlamaServer, tmp_path: Path
) -> None:
    with open_llama(db_path, server, tmp_path) as client:
        cid = new_conversation(client)
        body = send(client, cid, "name three colors").json()
        retry = client.post(
            f"/api/v1/conversations/{cid}/retry",
            json={"retry_id": str(uuid.uuid4()), "message_id": body["user_message"]["id"]},
        )
        assert retry.status_code == 409
        assert retry.json()["error"]["code"] == RetryNotEligible.code
        detail = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["completeness"] for m in detail["messages"]] == [None, "truncated"]
        assert len(server.requests) == 1


def test_the_default_fake_model_replies_are_complete(db_path: Path) -> None:
    with open_client(db_path) as client:
        cid = new_conversation(client)
        body = send(client, cid, "hello").json()
        assert body["assistant_message"]["completeness"] == "complete"
        assert body["user_message"]["completeness"] is None


def test_legacy_assistant_messages_stay_unclassified_after_migration(db_path: Path) -> None:
    conn = legacy_db(db_path)
    legacy_cid = add_conversation(conn, "old")
    add_turn(conn, legacy_cid, "succeeded")
    conn.commit()
    conn.close()
    with open_client(db_path) as client:  # opening migrates 0001 -> 0003; nothing is backfilled
        detail = client.get(f"/api/v1/conversations/{legacy_cid}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
        assert [m["completeness"] for m in detail["messages"]] == [None, None]
        assert client.get("/api/v1/health").json()["schema_version"] == 3
