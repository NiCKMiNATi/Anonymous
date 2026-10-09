"""Real-process test: start the server, write through HTTP, stop it (orderly and SIGKILL),
restart on the same database and confirm the data is intact (acceptance A8)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2 as httpx
import pytest

pytestmark = pytest.mark.process


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def running_server(db_path: Path, port: int, *, kill: bool) -> Iterator[httpx.Client]:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "anonymous", "--port", str(port), "--db-path", str(db_path)],
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
