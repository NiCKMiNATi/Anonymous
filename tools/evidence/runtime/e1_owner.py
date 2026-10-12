#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Owner process for E1 (the process the harness will SIGKILL).

Starts one stand-in, persists the record a successor would have (atomic write), prints
RECORDED, then idles holding the watchdog pipe. Standard library only; loopback only."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--record", required=True)
ap.add_argument("--marker", required=True)
ap.add_argument("--nonce", required=True)
ap.add_argument("--tag", required=True)
ap.add_argument("--child-new-session", type=int, default=1)
ap.add_argument("--watchdog", type=int, default=0)
ap.add_argument("--wrapper", type=int, default=0)
ap.add_argument("--max-life", type=float, default=60.0)
a, rest = ap.parse_known_args()
a.standin_args = rest

proc, record, wd = e1_lib.spawn_instance(
    a.marker, a.tag, a.nonce, a.standin_args, new_session=bool(a.child_new_session),
    watchdog=bool(a.watchdog), wrapper=bool(a.wrapper))
record["owner"] = e1_lib.identity(os.getpid())
tmp = a.record + ".tmp"
with open(tmp, "w") as f:
    json.dump(record, f)
os.replace(tmp, a.record)
print("RECORDED", flush=True)
t0 = time.monotonic()
while time.monotonic() - t0 < a.max_life:  # backstop: never idle forever
    time.sleep(0.2)
os._exit(4)
