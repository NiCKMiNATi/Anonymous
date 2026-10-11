"""HTTP surface for explicit retry and the generation state."""

from __future__ import annotations

from pathlib import Path

from tests.api.conftest import open_client
from tests.doubles import RecordingModel, failing_model

BASE = "/api/v1"


def failed_send(client, text: str = "please answer"):  # type: ignore[no-untyped-def]
    cid = client.post(f"{BASE}/conversations", json={}).json()["id"]
    result = client.post(
        f"{BASE}/conversations/{cid}/messages",
        json={"submission_id": "11111111-1111-4111-8111-111111111111", "content": text},
    ).json()
    assert result["run"]["status"] == "failed"
    return cid, result


def test_retry_creates_a_new_run_on_the_same_message_and_replays_idempotently(
    db_path: Path,
) -> None:
    with open_client(db_path, model=failing_model()) as client:
        cid, first = failed_send(client)
        message_id = first["user_message"]["id"]
    with open_client(db_path, model=RecordingModel("second try")) as client:
        body = {"retry_id": "22222222-2222-4222-8222-222222222222", "message_id": message_id}
        created = client.post(f"{BASE}/conversations/{cid}/retry", json=body)
        assert created.status_code == 201
        data = created.json()
        assert (
            data["run"]["kind"] == "retry" and data["run"]["retry_of_run_id"] == first["run"]["id"]
        )
        assert data["assistant_message"]["content"] == "second try"
        assert data["run"]["termination_basis"] == "runtime_reported_terminal"
        replay = client.post(f"{BASE}/conversations/{cid}/retry", json=body)
        assert replay.status_code == 200 and replay.json()["run"]["id"] == data["run"]["id"]
        detail = client.get(f"{BASE}/conversations/{cid}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]  # no duplicate
        assert [r["status"] for r in detail["runs"]] == ["failed", "succeeded"]


def test_ineligible_and_malformed_retries_are_refused_without_side_effects(db_path: Path) -> None:
    with open_client(db_path, model=RecordingModel("fine")) as client:
        cid = client.post(f"{BASE}/conversations", json={}).json()["id"]
        sent = client.post(
            f"{BASE}/conversations/{cid}/messages",
            json={"submission_id": "33333333-3333-4333-8333-333333333333", "content": "q"},
        ).json()
        body = {
            "retry_id": "44444444-4444-4444-8444-444444444444",
            "message_id": sent["user_message"]["id"],
        }
        refused = client.post(f"{BASE}/conversations/{cid}/retry", json=body)
        assert (
            refused.status_code == 409 and refused.json()["error"]["code"] == "retry_not_eligible"
        )
        bad = client.post(f"{BASE}/conversations/{cid}/retry", json={**body, "retry_id": "nope"})
        assert bad.status_code == 400
        assert len(client.get(f"{BASE}/conversations/{cid}").json()["runs"]) == 1


def test_health_reports_an_open_generation_state(db_path: Path) -> None:
    with open_client(db_path) as client:
        health = client.get(f"{BASE}/health").json()
        assert health["generation"]["state"] == "open"
        assert health["schema_version"] == 2
