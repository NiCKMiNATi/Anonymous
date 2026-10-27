"""Read-only dataset probe for the owner wrappers: run-status counts, never content.

Usage: ``python -I dataset_state.py PATH``. Prints one line, ``STATE key=value ...``.

STATE is ``absent`` (no file), ``open``, ``unsettled`` (a run is pending or in flight, normal while
a reply is being generated; after a crash the application reconciles it at its next start),
``blocked`` (a run is indeterminate: the application refuses new generation for the whole dataset,
the history stays readable), ``busy`` (the file is locked) or ``unreadable``. The connection is
opened ``mode=ro``: it creates no file, runs no migration and writes nothing. The ``blocked`` rule
mirrors the store's quarantine query; legacy-epoch blockers are not checked here (the application's
health endpoint reports them).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

_COUNTS = "SELECT status, COUNT(*) FROM model_runs WHERE record_epoch = '0b' GROUP BY status"


def probe(path: Path) -> str:
    if not path.exists():
        return "absent"
    if not path.is_file() or path.is_symlink():
        return "unreadable"
    try:
        connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return "unreadable"
    try:
        connection.execute("PRAGMA query_only = ON")
        counts = dict(connection.execute(_COUNTS).fetchall())
    except sqlite3.OperationalError as error:
        text = str(error).lower()
        return "busy" if "locked" in text or "busy" in text else "unreadable"
    except sqlite3.Error:
        return "unreadable"
    finally:
        connection.close()
    runs = sum(counts.values())
    indeterminate = counts.get("indeterminate", 0)
    unsettled = counts.get("pending", 0) + counts.get("in_flight", 0)
    state = "blocked" if indeterminate else ("unsettled" if unsettled else "open")
    return f"{state} runs={runs} indeterminate={indeterminate} unsettled={unsettled}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: dataset_state.py PATH", file=sys.stderr)
        return 2
    print(probe(Path(argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
