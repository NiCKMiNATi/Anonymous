#!/usr/bin/env python3
"""EVIDENCE TOOL / NON-PRODUCTION. Synthetic data only; no network.

Measures, for the Slice 0A SQLite development adapter, the elapsed time between the moment the
commit instant is sampled from the clock (inside the write transaction) and the moment the
database confirms the durable COMMIT. This is the size of the gap between the stored message
instant and the physical commit; it is an observation on one host, not a guarantee or tolerance.

Run from ``server/`` so the ``anonymous`` package is importable and nothing is written to the repo:

    uv run python ../tools/evidence/sqlite/measure_commit_instant_gap.py --iterations 300

The database lives in a temporary directory that is removed afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

from anonymous.adapters.persistence.sqlite import store as store_module
from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.domain.ids import SubmissionId, new_uuid


class Probe:
    """Real clock whose reads are timestamped on a monotonic counter."""

    def __init__(self) -> None:
        self.sampled_ns: int | None = None

    def now(self):  # type: ignore[no-untyped-def]
        from datetime import UTC, datetime

        self.sampled_ns = time.perf_counter_ns()
        return datetime.now(UTC)


class TimedConnection:
    def __init__(self, inner: sqlite3.Connection, probe: Probe, gaps: list[float]) -> None:
        self._inner = inner
        self._probe = probe
        self._gaps = gaps

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def execute(self, sql: str, *args: object) -> object:
        result = self._inner.execute(sql, *args)
        if sql.strip().upper() == "COMMIT" and self._probe.sampled_ns is not None:
            self._gaps.append((time.perf_counter_ns() - self._probe.sampled_ns) / 1e6)
            self._probe.sampled_ns = None
        return result


def summarize(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {
        "n": float(len(ordered)),
        "min_ms": ordered[0],
        "median_ms": statistics.median(ordered),
        "p95_ms": pick(0.95),
        "p99_ms": pick(0.99),
        "max_ms": ordered[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=300)
    args = parser.parse_args()

    probe = Probe()
    gaps: dict[str, list[float]] = {"admission": [], "dispatch": [], "publication": []}
    with tempfile.TemporaryDirectory(prefix="anonymous-commit-gap-") as tmp:
        path = Path(tmp) / "gap.sqlite3"
        migrate(path)
        store = SqliteStore(path, probe)
        owner = store.ensure_dev_owner()
        cid = store.create_conversation(owner, None).id
        real_connect = connect
        current = {"gaps": gaps["admission"]}
        store_module.connect = lambda p: TimedConnection(  # type: ignore[attr-defined]
            real_connect(p), probe, current["gaps"]
        )
        for _ in range(args.iterations):
            current["gaps"] = gaps["admission"]
            text = "synthetic"
            outcome = store.admit_submission(
                owner=owner,
                conversation_id=cid,
                submission_id=SubmissionId(new_uuid()),
                content=text,
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            )
            current["gaps"] = gaps["dispatch"]
            store.record_dispatch(outcome.run.id, "m", "r")
            current["gaps"] = gaps["publication"]
            store.publish_response(outcome.run.id, "answer")

    print(f"host: {platform.platform()} / python {platform.python_version()} / sqlite {sqlite3.sqlite_version}")
    print("journal_mode=WAL synchronous=FULL; sample = clock read inside the write transaction")
    for name, values in gaps.items():
        stats = summarize(values)
        print(
            f"{name:12s} n={int(stats['n'])} min={stats['min_ms']:.3f} median={stats['median_ms']:.3f}"
            f" p95={stats['p95_ms']:.3f} p99={stats['p99_ms']:.3f} max={stats['max_ms']:.3f} (ms,"
            " sample -> COMMIT returned)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
