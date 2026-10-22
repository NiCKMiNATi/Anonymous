#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

E3 pilot SUCCESSOR: a fresh process that receives ONE input, the path of the durable execution
record. It identifies the surviving runtime from the record and the kernel only (E1 identity, process
group, tag scan, lsof listener inventory, kqueue exit watch), classifies it over time without ever
returning PROVEN_TERMINATED while the recorded identity is live, and at the end of the observation
window terminates it by verified (pid, start) through the signal ledger. It makes no HTTP request,
opens no socket, reads no API key, fixture or model (the Driver also starts it under a kernel
network-and-read denial), and has no waitpid: exit evidence is the kernel's NOTE_EXIT notification
(when it could be registered) plus the non-parent conjunction. It is the record's writer after the
Owner is dead; writes are serialised with the Driver's by the locked store.

This module and e3_lib contain no socket code; a test asserts that statically and the sandbox
enforces it dynamically.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e3_lib as T  # noqa: E402


def emit(**kw):
    try:
        print(json.dumps(kw, default=str), flush=True)
    except (BrokenPipeError, ValueError, OSError):
        pass


def main(record_path):
    record_path = os.path.abspath(record_path)
    run_id = os.path.basename(record_path)[: -len(".json")]
    root = os.path.dirname(os.path.dirname(record_path))
    run_dir = os.path.join(root, "runs", run_id)
    records = T.LockedRecords(root)
    rec = records.read(run_id)
    e3 = rec.get("e3") or {}
    pid, start = rec.get("pid"), rec.get("start")
    if not (rec.get("state") == "BOUND" and e3.get("scope") == T.SCOPE and pid and start and rec.get("binding_verified")
            and e3.get("t0_up") is not None and isinstance(e3.get("bounds"), dict)):
        emit(e="REFUSED", why="record is not a bound E3 record with a durable pre-kill section")
        return 2
    b, t0 = e3["bounds"], e3["t0_up"]
    port, tag = rec["port"], rec["tag"]
    lt = b.get("lock_timeout_s", T.BOUNDS["lock_timeout_s"])
    records.lock_timeout_s = lt  # every shared lock wait of the Successor is bounded as well
    ledger = T.SignalLedger(run_dir, lock_timeout_s=lt)
    proc = T.IdentityProc(pid, start)
    watch, exit_event, exit_up = None, None, None
    alive_at_first = proc.poll() is None  # the Successor's very first look at the recorded identity
    if alive_at_first:  # register only for the verified identity, then re-verify it
        watch = L.ExitWatch(pid)
        if not watch.registered or proc.poll() is not None:
            if watch.registered and proc.poll() is not None:
                exit_event, exit_up = T.EXIT_NO_NOTIFICATION, T.uptime()  # seen alive, gone before the watch could report
            watch.close()
            watch = None
    emit(e="START", t_rel=T.uptime() - t0, watch=bool(watch))
    classifications = []

    def sample():
        verdict, why, obs = T.classify_os(rec)
        i = obs["identity_at_pid"]
        gone = (not L.same_identity(pid, start, i)) or i["status"] == "zombie"
        c = {"t_rel": round(T.uptime() - t0, 3), "verdict": verdict, "identity_gone": gone, "why": why[:2]}
        classifications.append(c)
        emit(e="CLASSIFY", **c)
        return verdict

    def note_exit(ev):
        nonlocal exit_event, exit_up
        if ev is not None and exit_event is None:
            exit_event, exit_up = T.EXIT_OBSERVED, T.uptime()

    times = [t0 + o for o in b["classify_offsets_s"]]
    nxt = 0
    self_exit = False
    while True:
        fresh = records.read(run_id)
        if fresh["state"] in ("EXIT_VERIFIED", "QUARANTINED"):
            emit(e="ALREADY_RESOLVED", state=fresh["state"])
            return 0
        rec = fresh  # always classify and verify against the newest record (the Driver may add descendants)
        deadline = (fresh.get("e3") or {}).get("window_deadline_up", t0 + b["orphan_max_s"])
        now = T.uptime()
        next_t = times[nxt] if nxt < len(times) else (times[-1] + (nxt - len(times) + 1) * b["classify_period_s"])
        if now >= next_t:
            nxt += 1
            if sample() == L.TERMINATED:
                self_exit = True
                break
        if now >= deadline:
            break
        wait = max(0.01, min(next_t, deadline) - T.uptime())
        if watch:
            ev = watch.wait(min(wait, 0.5))
            if ev is not None:
                note_exit(ev)
                if sample() == L.TERMINATED:
                    self_exit = True
                    break
        else:
            time.sleep(min(wait, 0.2))
    signals = []
    if not self_exit and proc.poll() is None:
        def wait_gone(limit):
            end = time.monotonic() + limit
            while time.monotonic() < end:
                if watch:
                    note_exit(watch.wait(0.2))
                else:
                    time.sleep(0.2)
                if proc.poll() is not None:
                    return True
            return proc.poll() is not None

        signals.append(ledger.send("successor", pid, start, signal.SIGTERM, "window_end"))
        if not wait_gone(b["successor_term_s"]):
            signals.append(ledger.send("successor", pid, start, signal.SIGKILL, "term_grace_expired"))
            wait_gone(b["successor_kill_s"])
    rec = records.read(run_id)
    for d in rec.get("descendants", []):  # a descendant is never expected; any recorded one is killed by identity
        signals.append(ledger.send("successor", d["pid"], d["start"], signal.SIGKILL, "recorded_descendant"))
    v = T.verify_nonparent(rec, port, tag, b["verify_s"])
    if exit_event is None:  # no notification was received: which fact is it?
        exit_event = T.EXIT_NO_NOTIFICATION if alive_at_first else T.EXIT_UNOBSERVED
    sent = [s for s in signals if s["sent"]]
    # who can have caused the exit: the ledger shows every DELIVERED experiment signal (also the Driver's
    # monitor and backstop). A stop that kills or quarantines is known to this process only through the record: the
    # Driver publishes ``e3.killing_stop`` for any such stop (also the non-quarantining immediate ones, S1 and S7,
    # which never set the owner-review flag) and the sticky owner-review flag marks a quarantine; with either one a
    # missing delivery is undetermined, not a self-exit
    attr = T.exit_attribution(ledger.entries(), pid, start, T.record_stop_state(rec))
    gone = v["checks"].get("identity_gone") is True
    terminated_by = T.termination_label(attr, gone)  # one rule for the record, the raw report and the committed view
    written = T.write_final(records, rec, v["verified"], v["checks"], "successor", exit_event,
                            extra={"terminated_by": terminated_by, "exit_cause": attr["cause"], "exit_by": attr["by"],
                                   "successor_signals": [{"sig": s["sig"], "sent": s["sent"], "why": s["why"]} for s in signals]})
    emit(e="FINAL", verified=v["verified"], checks=v["checks"], classify_os=v["classify_os"], record_written=written,
         exit_event=exit_event, self_exit=terminated_by == "self_exit", terminated_by=terminated_by, exit_cause=attr,
         signals=signals, t_rel=round(T.uptime() - t0, 3),
         exit_t_rel=None if exit_up is None else round(exit_up - t0, 3), classifications=classifications)
    return 0 if (v["verified"] and written is True) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1]))
    except SystemExit:
        raise
    except BaseException as exc:  # the Driver's backstop handles whatever this leaves unresolved
        emit(e="ERROR", what=type(exc).__name__)
        sys.exit(3)
