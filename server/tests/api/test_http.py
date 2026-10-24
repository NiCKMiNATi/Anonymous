"""Integration tests through the real HTTP -> application -> SQLite path (fake model by default)."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from anonymous.application.ports.model import ModelRequest
from tests.api.conftest import open_client
from tests.doubles import RecordingModel

INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def new_conversation(client: TestClient, title: str | None = None) -> str:
    response = client.post("/api/v1/conversations", json={"title": title})
    assert response.status_code == 201
    return str(response.json()["id"])


def send(client: TestClient, cid: str, content: str, sid: str | None = None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"submission_id": sid or str(uuid.uuid4()), "content": content},
    )


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def test_health_reports_readiness_and_the_missing_security_layer(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["storage"] == "ok" and body["schema_version"] == 3
    assert "no authentication" in body["security"]


def test_hello_round_trip_with_the_fake_model(client: TestClient) -> None:
    cid = new_conversation(client, "First chat")
    response = send(client, cid, "hello")
    assert response.status_code == 201
    body = response.json()
    assert body["replayed"] is False
    assert body["user_message"]["content"] == "hello" and body["user_message"]["position"] == 1
    assert body["assistant_message"]["content"] == "Fake reply to: hello (context messages: 1)"
    assert body["assistant_message"]["position"] == 2
    assert body["assistant_message"]["produced_by_run_id"] == body["run"]["id"]
    assert body["run"]["status"] == "succeeded"
    assert body["run"]["model_id"] == "fake-echo-1"
    assert body["run"]["runtime_id"] == "fake-in-process-runtime-1"
    for message in (body["user_message"], body["assistant_message"]):
        assert INSTANT.match(message["committed_at"])  # absolute UTC instant

    detail = client.get(f"/api/v1/conversations/{cid}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["conversation"]["title"] == "First chat"
    assert detail["runs"][0]["id"] == body["run"]["id"]
    assert [c["id"] for c in client.get("/api/v1/conversations").json()["conversations"]] == [cid]


def test_data_survives_a_server_restart(db_path: Path) -> None:
    with open_client(db_path) as first:
        cid = new_conversation(first, "Persistent")
        sent = send(first, cid, "hello").json()
        before = first.get(f"/api/v1/conversations/{cid}").json()

    with open_client(db_path) as second:  # new app, new connections, same file
        after = second.get(f"/api/v1/conversations/{cid}").json()
        assert after == before
        assert after["messages"][0]["committed_at"] == sent["user_message"]["committed_at"]
        assert after["messages"][1]["produced_by_run_id"] == sent["run"]["id"]
        assert [c["id"] for c in second.get("/api/v1/conversations").json()["conversations"]] == [
            cid
        ]
        # and the conversation continues normally after the restart
        assert send(second, cid, "again").status_code == 201
        assert len(second.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 4


def test_retransmitted_submission_returns_200_and_the_original_outcome(
    client: TestClient,
) -> None:
    cid = new_conversation(client)
    sid = str(uuid.uuid4())
    first = send(client, cid, "hello", sid)
    second = send(client, cid, "hello", sid)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["replayed"] is True
    assert second.json()["user_message"] == first.json()["user_message"]
    assert second.json()["assistant_message"] == first.json()["assistant_message"]
    assert len(client.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 2


def test_submission_id_reuse_with_different_content_conflicts(client: TestClient) -> None:
    cid = new_conversation(client)
    sid = str(uuid.uuid4())
    send(client, cid, "hello", sid)
    response = send(client, cid, "something else", sid)
    assert response.status_code == 409 and error_code(response) == "idempotency_conflict"
    assert len(client.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 2


def test_fake_generation_failure_keeps_user_message_and_creates_no_assistant_message(
    client: TestClient,
) -> None:
    cid = new_conversation(client)
    response = send(client, cid, "please [fake:fail]")
    assert response.status_code == 201  # the submission was accepted and committed
    body = response.json()
    assert body["assistant_message"] is None
    assert body["run"]["status"] == "failed" and body["run"]["failure_code"] == "fake_failure"
    detail = client.get(f"/api/v1/conversations/{cid}").json()
    assert [m["role"] for m in detail["messages"]] == ["user"]
    assert detail["runs"][0]["status"] == "failed"
    assert send(client, cid, "all good now").json()["run"]["status"] == "succeeded"


def test_validation_and_identifier_errors(client: TestClient) -> None:
    cid = new_conversation(client)
    assert send(client, cid, "").status_code == 422
    assert error_code(send(client, cid, "   ")) == "invalid_message"
    assert error_code(send(client, cid, "x" * 40_000)) == "invalid_message"
    bad_id = send(client, "not-a-uuid", "hi")
    assert bad_id.status_code == 400 and error_code(bad_id) == "invalid_identifier"
    assert client.get("/api/v1/conversations/not-a-uuid").status_code == 400
    assert client.get("/api/v1/conversations/%2e%2e%2fetc").status_code in (400, 404)
    missing = client.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert missing.status_code == 404 and error_code(missing) == "conversation_not_found"
    assert send(client, str(uuid.uuid4()), "hi").status_code == 404
    bad_sid = client.post(
        f"/api/v1/conversations/{cid}/messages", json={"submission_id": "x", "content": "hi"}
    )
    assert bad_sid.status_code == 400
    malformed = client.post(f"/api/v1/conversations/{cid}/messages", json={"content": "hi"})
    assert malformed.status_code == 422 and error_code(malformed) == "invalid_request"
    extra = client.post("/api/v1/conversations", json={"title": "x", "owner": "someone-else"})
    assert extra.status_code == 422  # clients cannot choose an owner
    assert len(client.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 0


def test_validation_errors_do_not_echo_submitted_content(client: TestClient) -> None:
    cid = new_conversation(client)
    secret = "TOP-SECRET-PAYLOAD"
    response = client.post(
        f"/api/v1/conversations/{cid}/messages", json={"submission_id": 5, "content": secret}
    )
    assert response.status_code == 422 and secret not in response.text


def test_busy_conversation_returns_409_and_appends_nothing(db_path: Path) -> None:
    entered, release = threading.Event(), threading.Event()

    def block(_: ModelRequest) -> None:
        entered.set()
        release.wait(10)

    with open_client(db_path, model=RecordingModel("slow", on_generate=block)) as client:
        cid = new_conversation(client)
        results: list[int] = []
        worker = threading.Thread(
            target=lambda: results.append(send(client, cid, "first").status_code)
        )
        worker.start()
        try:
            assert entered.wait(10)
            busy = send(client, cid, "second")
            assert busy.status_code == 409 and error_code(busy) == "conversation_busy"
            during = client.get(f"/api/v1/conversations/{cid}").json()  # reads continue
            assert [m["content"] for m in during["messages"]] == ["first"]
            assert during["runs"][0]["status"] == "in_flight"
        finally:
            release.set()
            worker.join(10)
        assert results == [201]
        final = client.get(f"/api/v1/conversations/{cid}").json()
        assert [m["content"] for m in final["messages"]] == ["first", "slow"]


def test_unexpected_server_error_is_sanitized(db_path: Path) -> None:
    class Exploding(RecordingModel):
        def generate(self, request: ModelRequest):  # type: ignore[no-untyped-def]
            raise MemoryError("internal detail /secret/path")

    # MemoryError is an Exception subclass; the coordinator contains it as a runtime failure.
    with open_client(db_path, model=Exploding()) as client:
        cid = new_conversation(client)
        response = send(client, cid, "hi")
        assert (
            response.status_code == 201
            and response.json()["run"]["failure_code"] == "runtime_error"
        )
        assert "secret" not in response.text


def test_storage_unavailable_returns_503_with_guidance(client: TestClient, db_path: Path) -> None:
    import sqlite3

    cid = new_conversation(client)
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE submissions")
    conn.commit()
    conn.close()
    response = send(client, cid, "hi")
    assert response.status_code == 503 and error_code(response) == "storage_unavailable"
    assert "sqlite" not in response.text.lower()
    assert "same submission id" in response.json()["error"]["message"]


# -- local-only guards and response hardening ----------------------------------------------------


def test_foreign_host_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400 and error_code(response) == "invalid_host"
    for ok in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
        assert client.get("/api/v1/health", headers={"Host": ok}).status_code == 200


def test_foreign_origin_is_rejected_and_known_origins_are_allowed(client: TestClient) -> None:
    bad = client.post("/api/v1/conversations", json={}, headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403 and error_code(bad) == "forbidden_origin"
    assert client.get("/api/v1/conversations").json()["conversations"] == []  # nothing created
    for origin in ("http://127.0.0.1:8000", "http://localhost:5173"):
        assert client.get("/api/v1/health", headers={"Origin": origin}).status_code == 200


SAME_ORIGIN_FORMS = ("http://127.0.0.1:{p}", "http://localhost:{p}", "http://[::1]:{p}")


def test_every_supported_loopback_form_is_an_accepted_same_origin(client: TestClient) -> None:
    for form in SAME_ORIGIN_FORMS:
        response = client.post(
            "/api/v1/conversations", json={}, headers={"Origin": form.format(p=8000)}
        )
        assert response.status_code == 201, form


def test_ipv6_loopback_origin_is_accepted_when_served_on_ipv6(db_path: Path) -> None:
    from anonymous.api.app import create_app
    from anonymous.config import Settings

    settings = Settings(db_path=db_path, host="::1", port=8765)
    with TestClient(create_app(settings), base_url="http://[::1]:8765") as c:
        for form in SAME_ORIGIN_FORMS:
            ok = c.post("/api/v1/conversations", json={}, headers={"Origin": form.format(p=8765)})
            assert ok.status_code == 201, form
        # The configured port is part of the origin: the default port is no longer this server.
        wrong = c.post("/api/v1/conversations", json={}, headers={"Origin": "http://[::1]:8000"})
        assert wrong.status_code == 403 and error_code(wrong) == "forbidden_origin"


def test_dev_client_origins_include_ipv6_loopback(client: TestClient) -> None:
    for origin in ("http://127.0.0.1:5173", "http://localhost:5173", "http://[::1]:5173"):
        assert client.get("/api/v1/health", headers={"Origin": origin}).status_code == 200


def test_unrelated_origins_stay_rejected(client: TestClient) -> None:
    hostile = (
        "null",
        "https://evil.example",
        "http://evil.example:8000",
        "http://127.0.0.1:9999",  # other port on a loopback name
        "http://[::1]:9999",
        "http://[::2]:8000",  # a different IPv6 address
        "http://[::ffff:127.0.0.1]:8000",  # mapped form is not an accepted spelling
        "https://127.0.0.1:8000",  # wrong scheme
        "https://[::1]:8000",
        "http://::1:8000",  # unbracketed IPv6 is not a valid origin
        "http://127.0.0.1.evil.example:8000",  # look-alike prefix
        "http://localhost.evil.example:8000",
        "http://[::1].evil.example:8000",
        "http://127.0.0.1:8000/",  # an Origin has no path
        "http://127.0.0.1:8000, http://evil.example",
        "",
    )
    for origin in hostile:
        response = client.post("/api/v1/conversations", json={}, headers={"Origin": origin})
        assert response.status_code == 403 and error_code(response) == "forbidden_origin", origin
    assert client.get("/api/v1/conversations").json()["conversations"] == []  # nothing created


def test_host_header_is_parsed_strictly(client: TestClient) -> None:
    accepted = ("127.0.0.1", "localhost", "[::1]", "127.0.0.1:8000", "localhost:5173", "[::1]:8000")
    for host in accepted:
        assert client.get("/api/v1/health", headers={"Host": host}).status_code == 200, host
    rejected = (
        "attacker.example",
        "[::1].attacker.example:8000",  # not an IPv6 literal followed by a port
        "[::1]x",
        "[::2]:8000",
        "::1",  # unbracketed
        "127.0.0.1:port",
        "127.0.0.1:8000@attacker.example",
        "localhost.attacker.example",
        "127.0.0.1 attacker.example",
    )
    for host in rejected:
        response = client.get("/api/v1/health", headers={"Host": host})
        assert response.status_code == 400 and error_code(response) == "invalid_host", host


def test_responses_are_uncacheable_and_hardened(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "access-control-allow-origin" not in response.headers  # no CORS


def test_built_client_is_served_from_the_same_origin(db_path: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Anonymous</title>")
    with open_client(db_path, client_dist=dist) as client:
        page = client.get("/")
        assert page.status_code == 200 and "Anonymous" in page.text
        assert client.get("/api/v1/health").status_code == 200  # API routes win over static
        assert "no-store" in page.headers["cache-control"]
