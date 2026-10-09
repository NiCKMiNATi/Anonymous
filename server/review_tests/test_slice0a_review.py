"""REVIEW ONLY: real SQLite/HTTP fault and concurrency probes, opt-in via explicit path.
No application source is changed. All data is synthetic and temporary.
"""

import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import UTC, datetime

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from anonymous.adapters.persistence.sqlite import store as store_module
from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.api.app import create_app
from anonymous.application.context import ContextBuilder
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import ModelIdentity, ModelOutput
from anonymous.config import Settings
from anonymous.domain.errors import ConversationBusy, StorageOutcomeUnknown
from anonymous.domain.ids import SubmissionId, new_uuid


class Clock:
    def now(self):
        return datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


class Model:
    identity = ModelIdentity("review-model", "review-runtime")

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def generate(self, request):
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic failure")
        return ModelOutput("synthetic answer", self.identity)


@pytest.fixture
def system(tmp_path):
    path = tmp_path / "review.sqlite3"
    migrate(path)
    store = SqliteStore(path, Clock())
    owner = store.ensure_dev_owner()
    cid = store.create_conversation(owner, "review").id
    return path, store, owner, cid


def submit(store, model, owner, cid, sid, content="synthetic input"):
    return ExecutionCoordinator(store, ContextBuilder(store), model).submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(sid), content=content
    )


@pytest.mark.parametrize("conflict", [False, True])
def test_concurrent_identical_or_conflicting_http_submissions(tmp_path, conflict):
    model = Model()
    with TestClient(
        create_app(Settings(db_path=tmp_path / "http.db"), model=model),
        base_url="http://127.0.0.1:8000",
    ) as client:
        cid = client.post("/api/v1/conversations", json={}).json()["id"]
        sid = new_uuid()
        barrier = threading.Barrier(8)

        def send(i):
            barrier.wait(10)
            return client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"submission_id": sid, "content": f"input-{i}" if conflict else "same input"},
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(send, range(8)))
        statuses = sorted(r.status_code for r in responses)
        assert statuses == ([201] + [409] * 7 if conflict else [200] * 7 + [201])
        history = client.get(f"/api/v1/conversations/{cid}").json()
        assert len(history["messages"]) == 2 and len(history["runs"]) == 1
        assert [m["position"] for m in history["messages"]] == [1, 2]
        assert model.calls == 1


class CommitFault:
    """Wrap a REAL connection; fail immediately before or after its actual COMMIT."""

    def __init__(self, inner, counter, target, after):
        self.inner, self.counter, self.target, self.after = inner, counter, target, after

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def execute(self, sql, *args):
        if sql == "COMMIT":
            self.counter[0] += 1
            if self.counter[0] == self.target:
                if self.after:
                    self.inner.execute(sql, *args)
                raise sqlite3.OperationalError("synthetic commit acknowledgment failure")
        return self.inner.execute(sql, *args)


@pytest.mark.parametrize(
    "stage,target", [("admission", 1), ("dispatch", 2), ("publication", 3), ("settlement", 3)]
)
@pytest.mark.parametrize("after", [False, True], ids=["before-real-commit", "after-real-commit"])
def test_unknown_commit_durable_facts_replay_and_restart(system, monkeypatch, stage, target, after):
    path, store, owner, cid = system
    model, sid = Model(fail=stage == "settlement"), new_uuid()
    counter = [0]
    with monkeypatch.context() as patch:
        patch.setattr(
            store_module, "connect", lambda p: CommitFault(connect(p), counter, target, after)
        )
        with pytest.raises(StorageOutcomeUnknown):
            submit(store, model, owner, cid, sid)
    history = store.get_history(owner, cid)
    if stage == "admission" and not after:
        assert history.messages == () and history.runs == () and model.calls == 0
        retry = submit(store, model, owner, cid, sid)
        assert not retry.replayed and retry.run.status == "succeeded" and model.calls == 1
        return
    expected = {
        ("admission", True): "pending",
        ("dispatch", False): "pending",
        ("dispatch", True): "in_flight",
        ("publication", False): "in_flight",
        ("publication", True): "succeeded",
        ("settlement", False): "in_flight",
        ("settlement", True): "failed",
    }[(stage, after)]
    assert history.runs[0].status == expected
    calls = model.calls
    replay = submit(store, model, owner, cid, sid)
    assert replay.replayed and replay.run.status == expected and model.calls == calls
    assert len(history.messages) == (2 if expected == "succeeded" else 1)
    reopened = SqliteStore(path, Clock())
    reopened.recover_unsettled_runs()
    final = reopened.get_history(owner, cid)
    assert final.messages == history.messages
    restart_status = {"pending": "failed", "in_flight": "indeterminate"}.get(expected, expected)
    assert final.runs[0].status == restart_status
    replay = submit(reopened, model, owner, cid, sid)
    assert replay.replayed and replay.run.status == restart_status and model.calls == calls
    if restart_status == "indeterminate":
        with pytest.raises(ConversationBusy):
            submit(reopened, model, owner, cid, new_uuid())


@pytest.mark.parametrize("table", ["messages", "model_runs", "submissions"])
def test_each_admission_statement_failure_rolls_back_all_facts(system, table):
    path, store, owner, cid = system
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"CREATE TRIGGER review_failure BEFORE INSERT ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'review'); END"
        )
    from anonymous.domain.errors import StorageFailure

    model = Model()
    with pytest.raises(StorageFailure):
        submit(store, model, owner, cid, new_uuid())
    history = store.get_history(owner, cid)
    assert history.messages == () and history.runs == () and model.calls == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM submissions").fetchone()[0] == 0


def test_publication_second_statement_failure_preserves_user_and_settles_failure(system):
    path, store, owner, cid = system
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER review_failure BEFORE UPDATE ON model_runs "
            "WHEN NEW.status='succeeded' BEGIN SELECT RAISE(ABORT, 'review'); END"
        )
    model = Model()
    result = submit(store, model, owner, cid, new_uuid())
    assert result.run.status == "failed" and result.run.failure_code == "response_not_saved"
    assert result.assistant_message is None and model.calls == 1
    assert len(store.get_history(owner, cid).messages) == 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def process_server(path, delay=0):
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "anonymous",
            "--port",
            str(port),
            "--db-path",
            str(path),
            "--fake-delay-seconds",
            str(delay),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15)
    try:
        for _ in range(200):
            try:
                if client.get("/api/v1/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            assert process.poll() is None
            time.sleep(0.05)
        else:
            raise AssertionError("server not ready")
        yield process, client
    finally:
        client.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_real_process_sigkill_during_inference_and_replay(tmp_path):
    path, sid = tmp_path / "crash.db", new_uuid()
    with process_server(path, delay=10) as (process, client):
        cid = client.post("/api/v1/conversations", json={}).json()["id"]

        def send():
            with suppress(httpx.TransportError):
                client.post(
                    f"/api/v1/conversations/{cid}/messages",
                    json={"submission_id": sid, "content": "crash input"},
                )

        worker = threading.Thread(target=send)
        worker.start()
        for _ in range(100):
            before = client.get(f"/api/v1/conversations/{cid}").json()
            if before["runs"] and before["runs"][0]["status"] == "in_flight":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("never dispatched")
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        worker.join(10)
        assert not worker.is_alive()
    with process_server(path) as (_, client):
        after = client.get(f"/api/v1/conversations/{cid}").json()
        assert after["messages"] == before["messages"]
        assert after["runs"][0]["status"] == "indeterminate"
        replay = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": sid, "content": "crash input"},
        )
        assert replay.status_code == 200 and replay.json()["run"]["status"] == "indeterminate"
        assert (
            client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"submission_id": new_uuid(), "content": "new"},
            ).status_code
            == 409
        )


def test_real_process_startup_settles_durable_pending_without_inference(system):
    path, store, owner, cid = system
    import hashlib

    sid = SubmissionId(new_uuid())
    accepted = store.admit_submission(
        owner=owner,
        conversation_id=cid,
        submission_id=sid,
        content="pending input",
        content_sha256=hashlib.sha256(b"pending input").hexdigest(),
    )
    with process_server(path) as (_, client):
        result = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": sid, "content": "pending input"},
        ).json()
        assert result["replayed"] and result["user_message"]["id"] == accepted.user_message.id
        assert result["run"]["status"] == "failed"
        assert result["run"]["failure_code"] == "interrupted_before_dispatch"
        assert result["assistant_message"] is None


def test_ipv6_same_origin_is_allowed(tmp_path):
    with TestClient(
        create_app(Settings(db_path=tmp_path / "ipv6.db", host="::1")), base_url="http://[::1]:8000"
    ) as client:
        response = client.post(
            "/api/v1/conversations", json={}, headers={"Origin": "http://[::1]:8000"}
        )
        assert response.status_code == 201, response.text


def test_delayed_commit_characterizes_timestamp_approximation(system, monkeypatch):
    """Observation, NOT an assertion of full FR-15 compliance.

    Advance a synthetic wall clock by a minute inside the real COMMIT wrapper.
    The row retains the earlier transaction timestamp, not the later commit instant.
    """
    from datetime import timedelta

    path, _, owner, cid = system

    class MutableClock:
        current = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

        def now(self):
            return self.current

    clock = MutableClock()
    store = SqliteStore(path, clock)
    observations = []

    class DelayedCommit:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, *args):
            if sql == "COMMIT":
                clock.current += timedelta(minutes=1)
                observations.append(clock.current)
            return self.inner.execute(sql, *args)

    with monkeypatch.context() as patch:
        patch.setattr(store_module, "connect", lambda p: DelayedCommit(connect(p)))
        outcome = submit(store, Model(), owner, cid, new_uuid())
    assert outcome.user_message.committed_at == observations[0] - timedelta(minutes=1)
    assert outcome.assistant_message.committed_at == observations[2] - timedelta(minutes=1)
    assert [m.position for m in store.get_history(owner, cid).messages] == [1, 2]
