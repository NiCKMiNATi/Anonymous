"""Real-process test: start the server, write through HTTP, stop it (orderly and SIGKILL),
restart on the same database and confirm the data is intact (acceptance A8)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import httpx2 as httpx
import pytest

pytestmark = pytest.mark.process


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def running_server(
    db_path: Path, port: int, *, kill: bool, delay: float = 0.0
) -> Iterator[httpx.Client]:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "anonymous",
            "--port",
            str(port),
            "--db-path",
            str(db_path),
            "--fake-delay-seconds",
            str(delay),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if client.get("/api/v1/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if process.poll() is not None:
                output = process.stdout.read().decode() if process.stdout else ""
                raise AssertionError(f"server exited early: {output}")
            if time.monotonic() > deadline:
                raise AssertionError("server did not become ready")
            time.sleep(0.1)
        yield client
    finally:
        client.close()
        if process.poll() is None:
            process.send_signal(signal.SIGKILL if kill else signal.SIGINT)
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()


@pytest.mark.parametrize("kill", [False, True], ids=["orderly-stop", "sigkill"])
def test_conversation_survives_server_restart(tmp_path: Path, kill: bool) -> None:
    db_path = tmp_path / "restart.sqlite3"
    port = free_port()
    with running_server(db_path, port, kill=kill) as client:
        cid = client.post("/api/v1/conversations", json={"title": "Restart me"}).json()["id"]
        sent = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": str(uuid.uuid4()), "content": "hello"},
        ).json()
        before = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["role"] for m in before["messages"]] == ["user", "assistant"]

    # The first server process is gone. Start a new one on the same data.
    with running_server(db_path, free_port(), kill=False) as client:
        after = client.get(f"/api/v1/conversations/{cid}").json()
        assert after == before
        assert after["messages"][0]["committed_at"] == sent["user_message"]["committed_at"]
        assert after["messages"][1]["produced_by_run_id"] == after["runs"][0]["id"]
        followup = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": str(uuid.uuid4()), "content": "still here?"},
        )
        assert followup.status_code == 201
        assert len(client.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 4


def test_sigkill_during_generation_is_settled_on_restart_and_replays_without_a_second_run(
    tmp_path: Path,
) -> None:
    """Maintained successor of the Slice 0A review probe "real process SIGKILL during inference":
    the in-process runtime dies with the process, the next owner of the exclusive guard is the
    evidence (B4), and nothing is invoked again."""
    db_path, submission_id = tmp_path / "crash.sqlite3", str(uuid.uuid4())
    with running_server(db_path, free_port(), kill=True, delay=30) as client:
        cid = client.post("/api/v1/conversations", json={}).json()["id"]
        posted = threading.Thread(
            target=lambda: _post_ignoring_connection_loss(str(client.base_url), cid, submission_id),
            daemon=True,
        )
        posted.start()
        # ``in_flight`` only means the dispatch was *authorized*. B4 is admissible only once the
        # invocation began, so wait for the durable proof of it (the handoff marker, T3b, and the
        # runtime's acceptance, T3c) before killing. A crash earlier than that is a different
        # case (B1, never dispatched) with its own test: ``test_ownership_and_crash.py``
        # ``[before_gate]``.
        deadline = time.monotonic() + 20
        while True:
            before = client.get(f"/api/v1/conversations/{cid}").json()
            started = before["runs"] and before["runs"][0]["status"] == "in_flight"
            if started and durable_handoff(db_path) == ("STARTED", "ACCEPTED"):
                break
            assert time.monotonic() < deadline, "the invocation never began"
            time.sleep(0.02)
        assert durable_handoff(db_path) == ("STARTED", "ACCEPTED")  # still true at the kill
    posted.join(20)  # the server was SIGKILLed on leaving the block above

    with running_server(db_path, free_port(), kill=False) as client:
        after = client.get(f"/api/v1/conversations/{cid}").json()
        assert after["messages"] == before["messages"]  # the user message is intact
        run = after["runs"][0]
        assert run["status"] == "failed" and run["id"] == before["runs"][0]["id"]
        assert run["termination_basis"] == "process_exit_verified"  # B4: the handoff had begun
        assert durable_handoff(db_path) == ("STARTED", "ACCEPTED")  # and was never repeated
        replay = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": submission_id, "content": "crash input"},
        )
        assert replay.status_code == 200 and replay.json()["run"]["id"] == run["id"]
        assert len(client.get(f"/api/v1/conversations/{cid}").json()["runs"]) == 1
        followup = client.post(  # the conversation and the slot are free again
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": str(uuid.uuid4()), "content": "next"},
        )
        assert followup.status_code == 201


def test_a_durable_pending_run_is_settled_at_startup_without_inference(tmp_path: Path) -> None:
    """Maintained successor of the Slice 0A review probe "startup settles a durable pending run":
    a process died after admission and before any dispatch, so the next process proves B1."""
    import hashlib

    from anonymous.composition import build_application
    from anonymous.config import Settings
    from anonymous.domain.ids import SubmissionId

    db_path, submission_id = tmp_path / "pending.sqlite3", str(uuid.uuid4())
    app = build_application(Settings(db_path=db_path))
    cid = app.conversations.create_conversation(app.owner).id
    accepted = app.store.admit_submission(
        owner=app.owner,
        conversation_id=cid,
        submission_id=SubmissionId(submission_id),
        content="pending input",
        content_sha256=hashlib.sha256(b"pending input").hexdigest(),
    )  # committed; no worker ever existed for it
    assert app.shutdown()

    with running_server(db_path, free_port(), kill=False) as client:
        replay = client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": submission_id, "content": "pending input"},
        ).json()
        assert replay["replayed"] and replay["user_message"]["id"] == accepted.user_message.id
        assert replay["run"]["status"] == "failed"
        assert replay["run"]["failure_code"] == "interrupted_before_dispatch"
        assert replay["run"]["termination_basis"] == "never_dispatched"
        assert replay["assistant_message"] is None  # nothing was generated


def durable_handoff(db_path: Path) -> tuple[str | None, str | None] | None:
    """The run's durable handoff state, read from the database by the test (a second reader)."""
    import sqlite3

    conn = sqlite3.connect(db_path, timeout=5)
    try:
        row = conn.execute("SELECT handoff, handoff_outcome FROM model_runs LIMIT 1").fetchone()
    finally:
        conn.close()
    return None if row is None else (row[0], row[1])


def _post_ignoring_connection_loss(base_url: str, cid: str, submission_id: str) -> None:
    # A client of its own: the server's death resets this connection at once, instead of the
    # request waiting out a read timeout on a connection pool the test also closes.
    with suppress(httpx.TransportError), httpx.Client(base_url=base_url, timeout=60) as own:
        own.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"submission_id": submission_id, "content": "crash input"},
        )


def test_second_server_on_the_same_database_refuses_to_start(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.sqlite3"
    with running_server(db_path, free_port(), kill=False):
        second = subprocess.run(
            [
                sys.executable,
                "-m",
                "anonymous",
                "--port",
                str(free_port()),
                "--db-path",
                str(db_path),
            ],
            capture_output=True,
            timeout=30,
        )
        assert second.returncode != 0
        assert b"Another Anonymous server" in second.stderr + second.stdout


def test_non_loopback_bind_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "anonymous",
            "--host",
            "0.0.0.0",
            "--db-path",
            str(tmp_path / "x.db"),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert b"loopback" in result.stderr
    assert not (tmp_path / "x.db").exists()  # refused before touching storage
