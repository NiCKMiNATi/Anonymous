"""Concurrent HTTP submissions (maintained successor of the Slice 0A review probe R2/R3).

Eight real client threads, released together by a barrier, send the same submission id over the
real HTTP -> application -> SQLite path: exactly one wins admission and one run is created; the
others get the original outcome (identical content) or a conflict (different content).
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.api.conftest import open_client
from tests.doubles import RecordingModel


@pytest.mark.parametrize("conflicting", [False, True], ids=["identical", "conflicting"])
def test_concurrent_identical_or_conflicting_submissions_create_one_run(
    db_path: Path, conflicting: bool
) -> None:
    model = RecordingModel("answer")
    with open_client(db_path, model=model) as client:
        cid = client.post("/api/v1/conversations", json={}).json()["id"]
        submission_id = str(uuid.uuid4())
        barrier = threading.Barrier(8)

        def send(index: int):  # type: ignore[no-untyped-def]
            barrier.wait(10)
            return client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={
                    "submission_id": submission_id,
                    "content": f"input-{index}" if conflicting else "same input",
                },
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(send, range(8)))
        statuses = sorted(r.status_code for r in responses)
        assert statuses == ([201] + [409] * 7 if conflicting else [200] * 7 + [201])
        history = client.get(f"/api/v1/conversations/{cid}").json()
        assert len(history["messages"]) == 2 and len(history["runs"]) == 1
        assert [m["position"] for m in history["messages"]] == [1, 2]
        assert len(model.requests) == 1  # one invocation for eight requests
