#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

E3 pilot READER: a passive requester independent of the Owner, so that the Owner's death is not also
the requester's death. It sends exactly ONE generation request (a single connection through
e2b_harness.http_call: no retry, no reconnect, no second request), then waits until the response
arrives or its absolute deadline passes. It never closes the connection on purpose and never
cancels. Its outcome is an observation of one in-flight attempt: it does not qualify cancellation,
disconnect or late-delivery exclusion, and a client completion is not evidence that the server is
idle.

stdin: line 1 = JSON {port, key, body (string), deadline_s}; then a line "GO". The key lives only in
this process's memory. stdout: JSON metadata lines (SENT, DONE); never response text.
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import e2b_harness as H  # noqa: E402
import e2b_lib as E  # noqa: E402


def emit(**kw):
    print(json.dumps(kw), flush=True)


def main():
    cfg = json.loads(sys.stdin.readline())
    if sys.stdin.readline().strip() != "GO":
        return 2
    up0 = time.clock_gettime(time.CLOCK_UPTIME_RAW)
    emit(e="SENT", up=up0)
    r = H.http_call(cfg["port"], "POST", "/v1/chat/completions", cfg["body"].encode(), cfg["key"], cfg["deadline_s"])
    up1 = time.clock_gettime(time.CLOCK_UPTIME_RAW)
    j = H.jbody(r) or {}
    ch = (j.get("choices") or [{}])[0]
    content = (ch.get("message") or {}).get("content") or ""
    usage = j.get("usage") or {}
    emit(e="DONE", up=up1, status=r["status"], elapsed=r["elapsed"], timed_out=r["timed_out"], error=r["error"],
         overflow=r["overflow"], finish_reason=ch.get("finish_reason"), prompt_tokens=usage.get("prompt_tokens"),
         completion_tokens=usage.get("completion_tokens"), content_len=len(content),
         content_sha256=E.sha256_bytes(content.encode()) if content else None, body_bytes=len(r["body"]),
         client_completed=r["status"] == 200 and ch.get("finish_reason") is not None and not r["timed_out"] and r["error"] is None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
