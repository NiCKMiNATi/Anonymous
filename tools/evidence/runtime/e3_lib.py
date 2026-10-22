#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

Slice 0B-2 E3 pilot support: bounds, the trigger state machine, the single-use authorization, the
signal ledger (every signal to an experiment process goes through it), serialised record writers, the
OS-only successor classifier, non-parent exit verification and the verdict rows. Standard library
only. Reads (never modifies) the E1/E2-B libraries.

Protocol: docs/evidence/v0-0b2-e3-pilot-protocol.md. This file has no socket code: the Successor
imports it and must be unable to open one (it also runs under a kernel network denial).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e2b_lib as E  # noqa: E402

SCOPE = "e3-pilot-v1"
VARIANT = "V1"
PROTOCOL_DOC = os.path.join(E.REPO, "docs", "evidence", "v0-0b2-e3-pilot-protocol.md")
PINS_FILE = os.path.join(HERE, "e3_pins.json")
APPROVED = "APPROVED_BY_OWNER"

# --------------------------------------------------------------------------------------------
# bounds (uptime-clock seconds unless stated). Production uses these values unchanged; tests pass a
# smaller copy to run_pilot(). The protocol (section 5) is the specification.

BOUNDS = {
    "arm_delay_s": 1.5,            # request must have been in flight this long before a kill
    "poll_interval_s": 0.1,        # /slots polling period before the kill
    "consecutive_polls": 3,        # consecutive is_processing polls required
    "stale_s": 0.2,                # kill must follow the last qualifying poll within this
    "prekill_abort_s": 20.0,       # request sent -> trigger or abort
    "idle_after_reader_s": 10.0,   # orphan observation ends this long after the reader completed ...
    "orphan_max_s": 60.0,          # ... or this long after the owner kill, whichever is earlier
    "backstop_s": 75.0,            # driver backstop deadline after the owner kill
    "successor_term_s": 3.0, "successor_kill_s": 3.0, "verify_s": 4.0, "backstop_verify_s": 10.0,
    "min_margin_s": 5.0,           # scheduling margin the 75 s backstop must keep after the Successor's longest path
    "lock_timeout_s": 2.0,         # every record or signal-ledger lock wait is bounded by this (never an unbounded flock)
    "owner_dead_s": 5.0,           # owner must be gone this long after SIGKILL
    "owner_shutdown_s": 40.0,      # allowance for a normal pre-kill shutdown through the owner
    "lifetime_s": 300.0,           # monitor-enforced (S11), whole lifetime from the spawn
    "reader_deadline_s": 90.0,     # absolute request deadline inside the reader
    "classify_offsets_s": (0.25, 1.0, 2.0, 5.0, 10.0), "classify_period_s": 10.0,
}
LIMS_NOTE = "S1-S13 thresholds are E2-B's (e2b_lib.LIMITS) unchanged except the lifetime ceiling"


def stop_limits(bounds=BOUNDS):
    return dict(E.LIMITS, lifetime_s=bounds["lifetime_s"])


def worst_case_lifetime(b=BOUNDS, readiness_s=E.LIMITS["readiness_s"], bind_s=5.0):
    """Longest spawn-to-final-record time the bounds allow; must not exceed the lifetime ceiling."""
    head = readiness_s + bind_s + b["prekill_abort_s"]
    return max(head + b["owner_shutdown_s"], head + b["backstop_s"] + b["backstop_verify_s"])


def successor_worst_case_s(b=BOUNDS):
    """Longest the Successor can take, from t0: the longest observation window, its SIGTERM grace, its
    SIGKILL wait and its whole non-parent verification (it then writes the record)."""
    return b["orphan_max_s"] + b["successor_term_s"] + b["successor_kill_s"] + b["verify_s"]


def check_bounds(b=BOUNDS, readiness_s=E.LIMITS["readiness_s"]):
    """Internal consistency of the bounds; returns a list of problems (empty = consistent)."""
    p = []
    if worst_case_lifetime(b, readiness_s) > b["lifetime_s"]:
        p.append("worst-case lifetime exceeds the lifetime ceiling")
    if b["backstop_s"] - successor_worst_case_s(b) < b["min_margin_s"]:
        p.append("backstop leaves less than the minimum margin after the successor's longest window plus TERM, KILL and verification")
    if b["reader_deadline_s"] < b["prekill_abort_s"] + b["orphan_max_s"]:
        p.append("reader deadline shorter than pre-kill plus orphan window")
    if b["stale_s"] > 0.5 or b["consecutive_polls"] < 3:
        p.append("trigger weaker than the protocol minimum")
    if not (0 < b["lock_timeout_s"] <= 5.0):
        p.append("lock timeout must be positive and at most 5 s")
    return p


def uptime():
    return time.clock_gettime(time.CLOCK_UPTIME_RAW)


class LockTimeout(TimeoutError):
    """A shared lock was not acquired within its bound. The caller proceeds without the lock's effect
    (a failed annotation, a refused signal); it never waits further."""


def flock_bounded(fd, timeout_s, step=0.005):
    """Exclusive ``flock`` that gives up after ``timeout_s`` seconds (non-blocking attempts; the
    holder's death releases the lock, a live stalled holder cannot hold the caller past the bound)."""
    end = time.monotonic() + max(0.0, timeout_s)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= end:
                raise LockTimeout(f"lock not acquired within {timeout_s} s")
            time.sleep(step)


# --------------------------------------------------------------------------------------------
# pins and the fixture G


def load_pins(path=PINS_FILE):
    with open(path) as f:
        return json.load(f)


def pins_ready(pins):
    """Fixture G must be pinned by length and full SHA-256 AND approved by the owner."""
    g = (pins or {}).get("fixture_g") or {}
    if g.get("state") != APPROVED:
        return False, f"fixture G is not owner-approved (state {g.get('state')!r})"
    if not (isinstance(g.get("bytes"), int) and isinstance(g.get("sha256"), str) and len(g["sha256"]) == 64):
        return False, "fixture G is not pinned by length and full SHA-256"
    if g.get("max_tokens") != 384:
        return False, "fixture G must carry max_tokens 384"
    return True, "ok"


def load_fixture_g(fx_dir, pins):
    """Read the external canonical-JSON fixture G; exact length, full SHA-256, canonical form and the
    structural limits (non-streaming, max_tokens 384, chat messages). Messages name no content."""
    g = pins["fixture_g"]
    try:
        with open(os.path.join(fx_dir, "G.json"), "rb") as f:
            raw = f.read()
    except OSError:
        raise E.FixtureError("G: unreadable")
    if len(raw) != g["bytes"] or E.sha256_bytes(raw) != g["sha256"]:
        raise E.FixtureError("G: length or sha256 mismatch")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise E.FixtureError("G: not json")
    if E.canon(obj) != raw:
        raise E.FixtureError("G: not canonical")
    if obj.get("max_tokens") != g["max_tokens"] or obj.get("stream") is not False or not obj.get("messages"):
        raise E.FixtureError("G: structure does not match the pinned limits")
    return obj


# --------------------------------------------------------------------------------------------
# authorization: separate file, separate scope, implementation-bound, single use


IMPLEMENTATION_FILES = ("e3_harness.py", "e3_lib.py", "e3_owner.py", "e3_reader.py", "e3_successor.py",
                        "e2b_harness.py", "e2b_lib.py", "e1_lib.py", "e2b_pins.json", "e3_pins.json")


def implementation_hashes(directory=HERE):
    out = {}
    for name in IMPLEMENTATION_FILES:
        try:
            out[name] = E.sha256_file(os.path.join(directory, name))
        except OSError:
            out[name] = None
    return out


def auth_path(root):
    return os.path.join(root, "AUTHORIZATION-E3.json")


def marker_path(root, authorization_id):
    safe = "".join(c for c in str(authorization_id) if c.isalnum() or c in "-_")
    return os.path.join(root, "CONSUMED-" + safe)


def _reject_constant(name):
    raise ValueError("non-finite JSON constant " + name)


def valid_expiry(value, start):
    """A real number (never a bool), finite, and strictly later than the execution start. NaN, the
    infinities (also from an overflowing literal such as 1e999) and integers too large for a float are
    refused: none of them is an effective expiry."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and float(value) > start
    except OverflowError:
        return False


def check_authorization(root, protocol_doc=PROTOCOL_DOC, pins=None, impl=None, now=None):
    """Return (ok, why, authorization). Refuses: a missing or foreign file, any scope but the E3 pilot,
    a base file, more than one lifetime, any hash mismatch (protocol, every implementation file,
    fixture G), expiry, and a consumed authorization."""
    try:
        with open(auth_path(root)) as f:
            a = json.load(f, parse_constant=_reject_constant)
        doc_hash = E.sha256_file(protocol_doc)
    except (OSError, ValueError):  # includes NaN / Infinity literals, which json would otherwise accept
        return False, "E3 authorization or protocol document unreadable", None
    if not isinstance(a, dict):
        return False, "E3 authorization is not an object", None
    if a.get("scope") != SCOPE:
        return False, f"scope must be {SCOPE!r}", None
    if a.get("variant") != VARIANT or type(a.get("lifetimes")) is not int or a["lifetimes"] != 1:  # a bool or a float is not the integer 1
        return False, "only variant V1 with exactly one lifetime (the integer 1) is authorized", None
    if not a.get("authorization_id") or not isinstance(a["authorization_id"], str):
        return False, "authorization_id missing", None
    if a.get("protocol_sha256") != doc_hash:
        return False, "authorization does not match the current E3 protocol document hash", None
    want = impl if impl is not None else implementation_hashes()
    have = a.get("implementation_sha256")
    if not isinstance(have, dict) or set(have) != set(IMPLEMENTATION_FILES):
        return False, "authorization must bind exactly the implementation files", None
    bad = sorted(n for n in IMPLEMENTATION_FILES if not want.get(n) or have.get(n) != want[n])
    if bad:
        return False, "implementation identity differs from the authorization: " + ",".join(bad), None
    if pins is not None:
        if a.get("fixture_g_sha256") != (pins.get("fixture_g") or {}).get("sha256"):
            return False, "fixture G hash differs from the authorization", None
    start = time.time() if now is None else now
    if not valid_expiry(a.get("expires_epoch"), start):
        return False, "authorization expiry is missing, not a finite number, or not later than the execution start", None
    if os.path.exists(marker_path(root, a["authorization_id"])):
        return False, "authorization already consumed (single use)", None
    return True, "ok", a


def consume_authorization(root, a, run_id):
    """Exclusive create of the consumption marker; a second attempt fails. Called immediately before
    the first process that can spawn the runtime is started."""
    path = marker_path(root, a["authorization_id"])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, json.dumps({"run_id": run_id, "utc": time.time(), "scope": SCOPE}).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


# --------------------------------------------------------------------------------------------
# trigger state machine (pure)

def slots_processing(slots):
    """(ok, processing) from a decoded ``/slots`` body. ``ok`` only for a non-empty list of objects
    (anything else is a malformed response: no evidence either way). ``processing`` is True only when a
    slot carries the literal JSON boolean ``true``; a truthy string, a number, ``null`` or a missing
    field never counts as active generation."""
    if not isinstance(slots, list) or not slots or not all(isinstance(s, dict) for s in slots):
        return False, None
    return True, any(s.get("is_processing") is True for s in slots)


WAIT, FIRE, MISSED, TIMEOUT, STOP = "WAIT", "FIRE", "MISSED", "TIMEOUT", "STOP"


class Trigger:
    """'Observable active generation'. FIRE only when the request has been in flight for the arming
    delay, N consecutive successful polls reported ``is_processing`` true, the reader has not
    completed and no stop is active. Token counts never take part (diagnostic only)."""

    def __init__(self, b=BOUNDS):
        self.b, self.sent_up, self.consec = b, None, 0
        self.last_qualifying_up, self.reader_done_up = None, None

    def request_sent(self, up):
        self.sent_up = up

    def reader_completed(self, up):
        self.reader_done_up = up

    def poll(self, up, ok, processing):
        if ok and processing is True:
            self.consec += 1
            self.last_qualifying_up = up
        else:
            self.consec = 0

    def decide(self, now, stop_active=False):
        if stop_active:
            return STOP
        if self.reader_done_up is not None:
            return MISSED
        if self.sent_up is None:
            return WAIT
        if now - self.sent_up > self.b["prekill_abort_s"]:
            return TIMEOUT
        if now - self.sent_up >= self.b["arm_delay_s"] and self.consec >= self.b["consecutive_polls"]:
            return FIRE
        return WAIT

    def fresh(self, now):
        return self.last_qualifying_up is not None and now - self.last_qualifying_up <= self.b["stale_s"]


def window_deadline(t0, reader_done_up, stop_up, b=BOUNDS):
    """End of the orphan observation window: the earliest of owner kill + orphan_max, reader
    completion + idle, and a stop. Client completion is not server idleness; this only bounds the
    observation."""
    cands = [t0 + b["orphan_max_s"]]
    if reader_done_up is not None:
        cands.append(reader_done_up + b["idle_after_reader_s"])
    if stop_up is not None:
        cands.append(stop_up)
    return max(t0, min(cands))


# --------------------------------------------------------------------------------------------
# signal ledger: the one place an experiment process is signalled


class SignalLedger:
    """Serialises and records every signal to an experiment process (runtime, owner). Under an
    exclusive file lock it (1) refuses any signal after a SIGKILL to the same (pid, start), (2)
    allows at most one SIGTERM per identity, (3) re-verifies the kernel identity immediately before
    the signal, (4) runs an optional ``precheck`` as the very last step before ``kill(2)`` and (5)
    appends who sent what, with the time of the actual attempt. A successor and a backstop therefore
    cannot both signal one identity more than the ledger allows, and a reused pid (different start
    time) is never signalled. The residual window between the identity check and kill(2) is not
    removable on this OS and is documented in the protocol.

    The lock wait is bounded (``lock_timeout_s`` or the per-call ``timeout_s``): a holder that stalls
    cannot hold a caller past the bound. A caller that times out sends nothing and the result says
    ``ledger_lock_timeout`` (it cannot be appended to the ledger, which needs the lock)."""

    UNRECORDED_KEEP = 200  # bound on the in-memory list of refusals that could not be appended to the ledger

    def __init__(self, run_dir, lock_timeout_s=None):
        self.path = os.path.join(run_dir, "signals.jsonl")
        self.lock = os.path.join(run_dir, "signals.lock")
        self.lock_timeout_s = BOUNDS["lock_timeout_s"] if lock_timeout_s is None else lock_timeout_s
        # Attempts refused because the ledger lock was not obtained cannot be appended to the ledger (that needs
        # the lock). They are kept here, in this process only, without pids, so that the report can count them:
        # the ledger file alone is a record of the attempts that obtained the lock.
        self.unrecorded = []
        self.unrecorded_total = 0

    @contextlib.contextmanager
    def _locked(self, timeout_s=None):
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            flock_bounded(fd, self.lock_timeout_s if timeout_s is None else timeout_s)
            yield
        finally:
            os.close(fd)

    def entries(self):
        try:
            with open(self.path) as f:
                return [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []

    def send(self, who, pid, start, sig, reason="", precheck=None, timeout_s=None):
        """``precheck`` (optional) is called inside the critical section, after every ledger and identity
        check and immediately before ``kill(2)``; it returns None to proceed or a reason string to refuse
        (an exception also refuses: fail closed). The refusal is recorded as ``precheck:<reason>``."""
        start = list(start)
        try:
            with self._locked(timeout_s):
                return self._send_locked(who, pid, start, sig, reason, precheck)
        except LockTimeout:
            self.unrecorded_total += 1
            if len(self.unrecorded) < self.UNRECORDED_KEEP:
                self.unrecorded.append({"who": who, "sig": int(sig), "why": "ledger_lock_timeout"})
            return {"pid": pid, "sig": int(sig), "sent": False, "why": "ledger_lock_timeout", "recorded": False}

    def _send_locked(self, who, pid, start, sig, reason, precheck):
        prior = [e for e in self.entries() if e["pid"] == pid and e["start"] == start]
        res = {"pid": pid, "sig": int(sig), "sent": False, "why": None}
        if any(e["sig"] == int(signal.SIGKILL) and e["sent"] for e in prior):
            res["why"] = "already_killed"
        elif sig == signal.SIGTERM and any(e["sig"] == int(signal.SIGTERM) and e["sent"] for e in prior):
            res["why"] = "term_already_sent"
        else:
            ident = L.identity(pid)
            if not L.same_identity(pid, start, ident):
                res["why"] = "identity_mismatch_or_gone"
            elif ident["status"] == "zombie":
                res["why"] = "already_exited"
            else:
                refusal = None
                if precheck is not None:
                    try:
                        refusal = precheck()
                    except Exception as exc:
                        refusal = "error:" + type(exc).__name__
                if refusal:
                    res["why"] = "precheck:" + str(refusal)
                else:
                    res["attempt_up"], res["attempt_wall"] = uptime(), time.time()  # the actual attempt, taken inside the lock
                    try:
                        os.kill(pid, sig)
                        res["sent"] = True
                    except ProcessLookupError:
                        res["why"] = "gone"
        up, wall = res.get("attempt_up", uptime()), res.get("attempt_wall", time.time())
        with open(self.path, "a") as f:
            f.write(json.dumps(dict(res, who=who, start=start, reason=reason, up=up, wall=wall)) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return res

    def kill_fn(self, who, reason=""):
        """Adapter with the E2-B ``kill_fn(targets, sig)`` shape. Targets must carry (pid, start)."""
        def fn(targets, sig=signal.SIGKILL):
            return {t["pid"]: self.send(who, t["pid"], t["start"], sig, reason)["sent"] for t in targets}
        return fn


# --------------------------------------------------------------------------------------------
# serialised record writers


class LockedRecords(E.Records):
    """E2-B record store whose writers (owner, driver monitor, successor, backstop) are serialised by
    a bounded cross-process lock and always start from the on-disk record: a stale in-memory copy can neither
    lose an update nor un-set owner_review_required (the in-memory flag is also kept)."""

    def __init__(self, root, lock_timeout_s=None):
        super().__init__(root)
        self.lock_timeout_s = BOUNDS["lock_timeout_s"] if lock_timeout_s is None else lock_timeout_s

    def _lock_file(self, run_id):
        d = os.path.join(os.path.dirname(self.dir), "locks")
        os.makedirs(d, mode=0o700, exist_ok=True)
        return os.path.join(d, run_id + ".lock")

    @contextlib.contextmanager
    def _xlock(self, run_id):
        """Cross-process writer lock, bounded: a stalled holder makes the write fail with LockTimeout
        after ``lock_timeout_s`` instead of blocking the caller (the Driver's safety path above all)."""
        fd = os.open(self._lock_file(run_id), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            flock_bounded(fd, self.lock_timeout_s)
            yield
        finally:
            os.close(fd)

    def _refresh(self, rec):
        disk = self.read(rec["run_id"])
        keep = {k: rec[k] for k in E.OWNER_FLAGS if rec.get(k)}
        rec.clear()
        rec.update(disk)
        rec.update(keep)

    def create(self, rec):
        with self._xlock(rec["run_id"]):
            return super().create(rec)

    def advance(self, rec, state, **fields):
        with self._xlock(rec["run_id"]):
            self._refresh(rec)
            if rec["state"] == "QUARANTINED" and state == "EXIT_VERIFIED" and fields.get("cleared_by") != "recover":
                raise ValueError("a quarantine is sticky: only the owner-directed recover tool clears it")
            return super().advance(rec, state, **fields)

    def annotate(self, rec, **fields):
        with self._xlock(rec["run_id"]):
            self._refresh(rec)
            return super().annotate(rec, **fields)


# --------------------------------------------------------------------------------------------
# liveness of a process we do not parent


class IdentityProc:
    """Popen-shaped view of a process known only by its kernel identity. ``poll()`` is None while the
    exact (pid, start) is live and not a zombie. There is no exit status (no waitpid)."""

    returncode = None

    def __init__(self, pid, start):
        self.pid, self.start = pid, list(start)

    def poll(self):
        i = L.identity(self.pid)
        return None if (L.same_identity(self.pid, self.start, i) and i["status"] != "zombie") else 0


# --------------------------------------------------------------------------------------------
# owner-directed recovery (E3-specific kill step; the E2-B recover() would enumerate through an
# unverified root pid)


def root_is_live(root_pid, root_start):
    i = L.identity(root_pid)
    return L.same_identity(root_pid, root_start, i) and i["status"] != "zombie"


def recovery_targets(rec, descendants_of=None):
    """What an owner-directed recovery may signal. Fresh descendants are discovered ONLY through a root
    whose recorded (pid, start) is verified live both before and after the enumeration; if the root
    identity does not match (exited, zombie, or its pid reused by an unrelated process) nothing is
    discovered, and only the previously recorded descendants are considered, each of which is still
    verified individually by (pid, start) at signal time. Never by process group."""
    pid, start = rec["pid"], list(rec["start"])
    recorded = [{"pid": d["pid"], "start": list(d["start"]), "role": "recorded_descendant"} for d in rec.get("descendants", [])]
    targets, fresh = [], []
    verified = root_is_live(pid, start)
    if verified:
        found = (descendants_of or L.descendants)(pid)
        if root_is_live(pid, start):  # the same process before and after: the list is really its tree
            have = {(d["pid"], tuple(d["start"])) for d in recorded}
            fresh = [{"pid": i["pid"], "start": list(i["start"]), "role": "fresh_descendant"} for i in found
                     if (i["pid"], tuple(i["start"])) not in have]
        else:
            verified = False
        targets.append({"pid": pid, "start": start, "role": "root"})
    return {"targets": targets + recorded + fresh, "root_verified": verified,
            "recorded_descendants": len(recorded), "fresh_descendants": len(fresh)}


def recover_locked(records, run_id, boottime, kill=False, confirm=None, sleep=time.sleep, kill_fn=None):
    """E2-B recovery rules with an E3 kill step. The caller holds the run lock. Read-only unless ``kill``
    and ``confirm == run_id``. A record without a recorded identity (INTENT) is handled by E2-B as is
    (it signals only tagged processes whose argv equals the intent, each by (pid, start)); every
    record with an identity is killed here through ``recovery_targets``, after which E2-B classifies
    and, only on PROVEN_TERMINATED without an owner-review flag, clears. A quarantine whose identity
    cannot be established therefore stays a quarantine."""
    kill_fn = kill_fn or E.kill_identified
    rec = records.read(run_id)
    if rec["state"] == "INTENT" or not (rec.get("pid") and rec.get("start")):
        return E._recover_locked(records, run_id, boottime, kill, confirm, sleep, kill_fn)
    plan = killed = None
    if (kill and confirm == run_id and rec["state"] != "EXIT_VERIFIED"
            and (not rec.get("boottime") or rec["boottime"] == boottime)
            and (rec.get("owner_review_required") or L.classify(rec)[0] == L.ALIVE)):
        plan = recovery_targets(rec)
        killed = kill_fn(plan["targets"])
        sleep(0.5)
    rep = E._recover_locked(records, run_id, boottime, False, None, sleep, kill_fn)
    if plan is not None:
        rep.setdefault("actions", []).insert(0, {"killed": killed, "root_verified": plan["root_verified"],
                                                 "recorded_descendants": plan["recorded_descendants"],
                                                 "fresh_descendants": plan["fresh_descendants"]})
        if rep.get("verdict") == "QUARANTINE_OWNER_REVIEW":
            rep["process_state_after"] = L.classify(records.read(run_id))[0]
    return rep


# --------------------------------------------------------------------------------------------
# OS-only classification (no socket, no probe) and non-parent exit verification


def classify_os(record):
    """E1 classifier minus the application probe: kernel identity, recorded descendants, process
    group, instance tag and the listener inventory (lsof reads kernel tables; it opens no
    connection). PROVEN_TERMINATED needs the same full conjunction as E1; nothing here can return
    it while the recorded identity is live."""
    obs = {}
    pid, start = record.get("pid"), record.get("start")
    ident = L.identity(pid) if pid else None
    obs["identity_at_pid"] = ident
    same = L.same_identity(pid, start, ident) if (pid and start) else False
    alive_same = same and ident["status"] != "zombie"
    zombie_same = same and ident["status"] == "zombie"
    recorded = {(d["pid"], tuple(d["start"])) for d in record.get("descendants", [])}
    if pid and start:
        recorded.add((pid, tuple(start)))
    live_recorded = []
    for key in sorted(recorded):
        i = L.identity(key[0])
        if i and tuple(i["start"]) == key[1] and i["status"] != "zombie":
            live_recorded.append(i)
    group = L.group_members(record.get("pgid")) if record.get("pgid") else []
    unrecorded_group = [i for i in group if (i["pid"], tuple(i["start"])) not in recorded]
    lst = L.listeners(record["port"]) if record.get("port") else {"pids": [], "rc": None, "timeout": False}
    tagged = L.tag_scan(record["tag"]) if record.get("tag") else []
    obs.update(live_recorded=[(i["pid"], i["status"]) for i in live_recorded],
               unrecorded_group_members=[i["pid"] for i in unrecorded_group], listeners=lst,
               tagged_live=[i["pid"] for i in tagged], probe="NOT_USED_NO_SOCKET")
    if alive_same:
        return L.ALIVE, ["recorded (pid, start) is live"], obs
    if live_recorded:
        return L.ALIVE, ["a recorded descendant is live"], obs
    if tagged:
        return L.ALIVE, ["a live process carries the instance tag"], obs
    if not (pid and start):
        return L.INDETERMINATE, ["record lacks pid or start time"], obs
    if not record.get("binding_verified"):
        return L.INDETERMINATE, ["listener binding was never verified for the recorded pid"], obs
    if unrecorded_group:
        return L.INDETERMINATE, ["live unrecorded member(s) in the recorded process group"], obs
    if lst.get("timeout") or lst["rc"] not in (0, 1):
        return L.INDETERMINATE, ["listener inventory unavailable"], obs
    why = ["recorded process has exited (zombie, not reaped)" if zombie_same else
           ("kernel reports no process at the recorded pid" if ident is None else
            "pid now belongs to a different process (start time differs): original is gone")]
    if lst["pids"]:
        why.append("a foreign listener holds the port; not treated as ownership evidence")
    return L.TERMINATED, why, obs


EXIT_BASIS_NONPARENT = "non_parent_kernel_identity_and_conjunction"
# Three distinct facts about how the exit became known (never merged):
#   NOTE_EXIT_observed         the kernel's exit notification for the verified identity was received;
#   exit_notification_unavailable  the runtime was observed ALIVE first, and its exit was established by the
#                              identity/conjunction polling only (no notification was registered or received);
#   absent_at_first_observation    the identity was already gone at the observer's very first look, WITHIN THAT OBSERVER'S SCOPE:
#                              the Successor's first classification, or the Driver's looks from the kill instant on (the kill-instant
#                              check, the orphan window, its finalizer). The Driver monitor's earlier, pre-trigger samples are not
#                              consulted, so this never says the runtime was not alive before the observer began.
EXIT_OBSERVED, EXIT_UNOBSERVED = "NOTE_EXIT_observed", "absent_at_first_observation"
EXIT_NO_NOTIFICATION = "exit_notification_unavailable"
FIRST_OBSERVATION_SCOPE = ("successor: its first classification; driver: its looks from the kill instant on (kill-instant check, orphan "
                           "window, finalizer); pre-trigger monitor samples are not consulted")


def nonparent_checks(rec, port, tag):
    """The conjunction available to a process that is not the parent: no ``reaped`` (waitpid) fact."""
    pid, start = rec["pid"], rec["start"]
    ident = L.identity(pid)
    recorded = {(d["pid"], tuple(d["start"])) for d in rec.get("descendants", [])}
    live_desc = [p for p, st in recorded if (lambda i: i and tuple(i["start"]) == st and i["status"] != "zombie")(L.identity(p))]
    group = [i for i in L.group_members(rec.get("pgid")) if i["pid"] != pid] if rec.get("pgid") else []
    lst = L.listeners(port)
    return {"identity_gone": (not L.same_identity(pid, start, ident)) or ident["status"] == "zombie",
            "recorded_descendants_dead": not live_desc, "group_clear": not group,
            "tag_scan_clear": not L.tag_scan(tag), "port_free": not lst["timeout"] and not lst["pids"]}


def verify_nonparent(rec, port, tag, verify_s, sleep=time.sleep):
    """Poll the conjunction until it holds or ``verify_s`` passes; then the classifier must agree."""
    t0, checks = time.monotonic(), {}
    while True:
        checks = nonparent_checks(rec, port, tag)
        if all(checks.values()) or time.monotonic() - t0 > verify_s:
            break
        sleep(0.2)
    verdict = classify_os(rec)[0] if rec.get("binding_verified") else None
    return {"checks": checks, "classify_os": verdict, "verified": all(checks.values()) and verdict == L.TERMINATED}


def write_final(records, rec, verified, checks, cleared_by, exit_event, extra=None):
    """The single final write for an orphan: EXIT_VERIFIED only when verified AND no owner review is
    pending; otherwise QUARANTINED. Never claims a waitpid fact or an exit code."""
    extra = dict(extra or {})
    try:
        records._refresh(rec)
        policy = "owner review flagged during the run" if rec.get("owner_review_required") else None
        if verified and not policy:
            records.advance(rec, "EXIT_VERIFIED", exit_basis=EXIT_BASIS_NONPARENT, exit_event=exit_event,
                            waitpid_evidence=False, exit_code=None, cleared_by=cleared_by, checks=checks, **extra)
        elif verified:
            records.advance(rec, "QUARANTINED", reason=policy, owner_review_required=True, exit_verified_facts=checks,
                            waitpid_evidence=False, cleared_by=None, **extra)
        else:
            records.advance(rec, "QUARANTINED", reason=policy or "exit not verified", checks=checks,
                            owner_review_required=bool(policy), waitpid_evidence=False, **extra)
        return True
    except Exception as exc:  # the record then stays unresolved on disk
        return type(exc).__name__


NO_SIGNAL, SIGNALLED, UNDETERMINED = "NO_SIGNAL_RECORDED", "SIGNALLED", "UNDETERMINED"


def record_stop_state(rec):
    """The stop evidence a process that reads only the durable record (the Successor, or the Driver's
    finalizer next to its own in-memory stops) can use for ``exit_attribution``: the Driver's published
    ``e3.killing_stop`` (a stop that kills or quarantines was seen) and the sticky owner-review flag (a
    quarantining stop was seen). Either one makes a missing delivery undetermined. The flag alone is NOT the
    stop state: a non-quarantining immediate stop (S1, S7) never sets it, which is why the Driver publishes
    ``killing_stop`` separately."""
    out = []
    if (rec.get("e3") or {}).get("killing_stop"):
        out.append({"immediate": True})
    if rec.get("owner_review_required"):
        out.append({"quarantine": True})
    return out


def exit_attribution(entries, pid, start, stops=None):
    """Who can have caused the exit of the runtime identity (pid, start)? ``entries`` are the signal
    ledger's lines. SIGNALLED when any signal to that identity was sent (by the Successor, the Driver's
    monitor or backstop, or the Owner): the exit is then never reported as spontaneous. UNDETERMINED
    when nothing was sent but a stop that kills or quarantines was active (the ledger should show that
    kill, so its absence is not evidence of a spontaneous exit). NO_SIGNAL_RECORDED otherwise: the
    ledger covers only the experiment's own signallers, so a signal from outside it cannot be excluded
    and this is never stronger than 'no experiment signal was recorded'."""
    start = list(start)
    sent = [e for e in entries if e.get("pid") == pid and list(e.get("start") or []) == start and e.get("sent")]
    if sent:
        return {"cause": SIGNALLED, "by": sorted({str(e.get("who")) for e in sent})}
    if any(s.get("immediate") or s.get("quarantine") for s in (stops or [])):
        return {"cause": UNDETERMINED, "by": [], "why": "a killing or quarantining stop was active but the ledger shows no signal"}
    return {"cause": NO_SIGNAL, "by": []}


def termination_label(attr, gone):
    """The one label for who ended the runtime, derived only from the ledger's DELIVERED signals (the
    attribution ``attr`` of ``exit_attribution``) and from whether the identity is observed gone. The
    durable record, the raw report and the committed view all use it: a self-exit is never labelled as a
    Successor or Driver termination, and a termination is never labelled a self-exit."""
    if attr["cause"] == SIGNALLED:
        by = attr["by"]
        return by[0] if len(by) == 1 else "multiple_signallers"
    if attr["cause"] == UNDETERMINED:
        return "undetermined"
    return "self_exit" if gone else "undetermined"  # no experiment signal recorded: nothing stronger is claimed


def label_matches_attribution(label, attr):
    """Cross-check of a recorded ``terminated_by`` against the ledger attribution."""
    if label is None or label == "undetermined":
        return True  # nothing was claimed
    if attr["cause"] == SIGNALLED:
        return (label == "multiple_signallers" and len(attr["by"]) > 1) or label in attr["by"]
    if attr["cause"] == UNDETERMINED:
        return label == "undetermined"
    return label in ("self_exit", "undetermined")


SIGNAL_ACCOUNTING_BASIS = ("attempts that obtained the signal-ledger lock (the ledger file), plus lock-timeout refusals that the signalling "
                           "process reported (``unrecorded``). A signaller that ended before it could report (for example a Successor stopped "
                           "by the backstop) may have made further refused attempts that cannot be counted: the counts are a lower bound "
                           "on attempts. ``delivered`` counts RECORDED deliveries (kill(2) returned success and the entry was appended): the ledger "
                           "entry is written after kill(2), so a signaller that died between the two may have delivered a signal that is not "
                           "recorded, and delivered is a lower bound too. kill(2) success is acceptance by the kernel, not an effect on the target.")


def signal_accounting(entries, unrecorded=None):
    """Attempts versus recorded delivery per signaller, without pids: ``delivered`` counts only signals
    that passed every check and reached ``kill(2)`` without error AND were appended to the ledger (the append follows
    ``kill(2)``, so a signaller that died in between delivered a signal this cannot see: a lower bound; delivery to
    the process is not the same as its exit); ``refused`` counts the reasons the rest were not sent. ``unrecorded`` maps a
    signaller to the number of attempts it reported as refused for want of the ledger lock; they are added
    to ``attempted`` and ``refused`` and shown apart under ``unrecorded`` (only where there are any)."""
    out = {}
    for e in entries:
        w = out.setdefault(str(e.get("who")), {"attempted": 0, "delivered": 0, "refused": {}})
        w["attempted"] += 1
        if e.get("sent"):
            w["delivered"] += 1
        else:
            why = str(e.get("why"))
            w["refused"][why] = w["refused"].get(why, 0) + 1
    for who, n in sorted((unrecorded or {}).items()):
        if not n:
            continue
        w = out.setdefault(str(who), {"attempted": 0, "delivered": 0, "refused": {}})
        w["attempted"] += n
        w["refused"]["ledger_lock_timeout"] = w["refused"].get("ledger_lock_timeout", 0) + n
        w["unrecorded"] = n
    return out


# --------------------------------------------------------------------------------------------
# successor sandbox profile


def sbpl_quote(path):
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def successor_profile(denied_read_subpaths=()):
    """Kernel-enforced: no network of any kind, and no read access to the listed directories
    (fixtures, models, run scratch where the key lives)."""
    # the sandbox matches resolved paths (/var -> /private/var), so resolve before quoting
    deny = "".join(f"(deny file-read* (subpath {sbpl_quote(os.path.realpath(p))}))" for p in denied_read_subpaths)
    return "(version 1)(allow default)(deny network*)" + deny


# --------------------------------------------------------------------------------------------
# interruption latch (signal-handler safe)
#
# Python runs a signal handler in the main thread between two bytecodes, also while that thread is inside
# ``threading.Event.set()`` or ``wait()`` holding the Event's internal, NON-reentrant lock (and a second signal can
# run a handler inside the first). A handler that calls ``Event.set()`` can therefore block forever on a lock its
# own thread holds, with the runtime live. So the handler does one thing: assign to the latch. Nothing in it
# locks, calls, logs, waits or writes. ``InterruptEvent`` reads the latch without a lock, so every guard and
# bounded wait sees an interrupt as soon as the handler has run; a watcher thread (outside the handler) also
# propagates it to ordinary Events.

WAIT_SLICE_S = 0.05  # an InterruptEvent wait re-reads the latch at least this often; a wait is never longer than asked


class InterruptLatch:
    """Monotonic: ``hit`` goes from False to True and never back. Plain attribute stores only."""

    __slots__ = ("hit", "signum")

    def __init__(self):
        self.hit, self.signum = False, None


def make_signal_handler(latch):
    """The only code that runs in signal context. Assignments only (a static test asserts this)."""
    def on_signal(signum, frame):
        latch.hit = True
        latch.signum = signum
    return on_signal


class InterruptEvent(threading.Event):
    """An Event that also reports the latch: ``is_set()`` takes no lock and is true as soon as the latch is hit;
    ``wait(timeout)`` polls in slices of ``WAIT_SLICE_S`` (a signal arriving during the underlying lock wait only
    runs the lock-free handler), is never longer than ``timeout`` and returns the state like ``Event.wait``."""

    def __init__(self, latch=None):
        super().__init__()
        self.latch = latch if latch is not None else InterruptLatch()

    def is_set(self):
        return self._flag or self.latch.hit

    isSet = is_set

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.is_set():
                return True
            step = WAIT_SLICE_S if end is None else min(WAIT_SLICE_S, end - time.monotonic())
            if step <= 0:
                return self.is_set()
            super().wait(step)


def start_latch_watcher(latch, events, period_s=0.02):
    """Outside the handler: when the latch is hit, ``set()`` every Event in ``events`` (so ordinary Events, and threads
    blocked on them, see it too). Returns ``stop()``; the thread is a daemon and ends at the latch or at ``stop()``."""
    done = threading.Event()

    def run():
        while not done.wait(period_s):
            if latch.hit:
                for e in events:
                    e.set()
                return
    t = threading.Thread(target=run, daemon=True)
    t.start()

    def stop():
        done.set()
        t.join(2.0)
    return stop


# --------------------------------------------------------------------------------------------
# evidence acceptance (the report is provisional until sealing is confirmed)

SEAL_FILE = "seal-confirmation.json"
SEALED_REPORT_FILES = ("summary.json", "summary-committed-view.json")


def evidence_acceptance(run_dir, exit_status):
    """Independent check of a finished run's files and of the process exit status, with no trust in any earlier success
    file. ``sealed`` = the final sealing step completed and the two report files are the ones it confirmed (the seal
    confirmation is written last and carries their digests; it is removed before every rewrite and never written on a
    failure path). ``supports_verdicts`` additionally needs a normal completion (exit status 0, equal to the confirmed
    exit code), outcome PILOT_COMPLETED, no stop, no finalize error and every raw artifact the view lists unchanged.
    A run that is not ``sealed`` is provisional: none of its rows is evidence. Returns
    ``{"sealed", "supports_verdicts", "reasons"}``."""
    reasons = []

    def read(name):
        """(parsed, ok): ok is False when the file is missing, unreadable or not JSON."""
        try:
            with open(os.path.join(run_dir, name)) as f:
                return json.load(f), True
        except (OSError, ValueError):
            return None, False
    (conf, conf_ok), (summary, summary_ok), (view, view_ok) = read(SEAL_FILE), read("summary.json"), read("summary-committed-view.json")
    if not conf_ok:
        reasons.append("no seal confirmation: sealing did not complete")
    elif not isinstance(conf, dict):
        reasons.append("the seal confirmation is not a JSON object")
    for name, obj, ok in (("summary.json", summary, summary_ok), ("summary-committed-view.json", view, view_ok)):
        if not ok:
            reasons.append(f"report file {name} is missing or unreadable")
        elif not isinstance(obj, dict):
            reasons.append(f"report file {name} is not a JSON object")
    if not reasons:  # the nested structure the checks below read
        for label, obj, key, kind in (("summary.json", summary, "stops", list), ("summary.json", summary, "seal", dict),
                                      ("summary-committed-view.json", view, "raw_artifacts", dict)):
            if obj.get(key) is not None and not isinstance(obj[key], kind):
                reasons.append(f"{label}: {key} is not a JSON {'array' if kind is list else 'object'}")
        if isinstance(view.get("raw_artifacts"), dict) and not all(isinstance(v, dict) for v in view["raw_artifacts"].values()):
            reasons.append("summary-committed-view.json: a raw_artifacts entry is not a JSON object")
    if reasons:
        return {"sealed": False, "supports_verdicts": False, "reasons": reasons}
    got = {n: E.sha256_file(os.path.join(run_dir, n)) for n in SEALED_REPORT_FILES}
    if conf.get("sealed") is not True:
        reasons.append("the seal confirmation does not say sealed")
    if got["summary.json"] != conf.get("summary_sha256") or got["summary-committed-view.json"] != conf.get("view_sha256"):
        reasons.append("a report file differs from the one the seal confirmed")
    if ((view.get("raw_artifacts") or {}).get("summary.json") or {}).get("sha256") != got["summary.json"]:
        reasons.append("the committed view does not describe the raw report on disk")
    if not (summary.get("outcome") == view.get("outcome") == conf.get("outcome")):
        reasons.append("the outcome differs between the raw report, the committed view and the seal confirmation")
    if summary.get("run_id") != view.get("run_id") or summary.get("run_id") != conf.get("run_id"):
        reasons.append("the run identity differs between the files")
    if exit_status is None or exit_status != conf.get("exit_code"):
        reasons.append("normal completion is not confirmed: the process exit status is missing or differs from the confirmed exit code")
    if summary.get("finalize_error") or view.get("finalize_error"):
        reasons.append("finalization reported an error")
    sealed = not reasons
    for name, meta in sorted((view.get("raw_artifacts") or {}).items()):
        path = os.path.join(run_dir, name)
        if name != "summary.json" and (not os.path.isfile(path) or E.sha256_file(path) != meta.get("sha256")):
            reasons.append(f"raw artifact {name} differs from the digest in the committed view")
    supports = sealed and not reasons
    for why, bad in (("the outcome is not PILOT_COMPLETED", summary.get("outcome") != "PILOT_COMPLETED"),
                     ("the exit status is not 0", exit_status != 0),
                     ("a stop is recorded", bool(summary.get("stops"))),
                     ("an interrupt was accepted before the seal", (summary.get("seal") or {}).get("interrupt_seen") is not False)):
        if bad:
            supports = False
            reasons.append(why)
    return {"sealed": sealed, "supports_verdicts": supports, "reasons": reasons}


def withhold_rows(rows):
    """In place, on the failure path: every verdict row INCONCLUSIVE, whatever it said."""
    if isinstance(rows, dict) and isinstance(rows.get("rows"), dict):
        for name in VERDICT_ROWS:
            if name in rows["rows"]:
                rows["rows"][name] = "INCONCLUSIVE"
        rows.setdefault("notes", {})["verdicts_withheld_by_finalize_error"] = True
    return rows


# --------------------------------------------------------------------------------------------
# verdict rows and committed view

OBS_LABEL = "n=1"
NOT_TESTED = ("B3_instance_reported_terminal", "B5_slot_idle", "request_cancel", "requester_disconnect",
              "late_delivery_excluded", "adoption_for_generation")
VERDICT_ROWS = ("O1_orphan_survival", "O3_successor_classification_consistency", "O4_successor_termination",
                "B4_successor_side")


def reader_outcome_class(rd):
    if not rd:
        return "NO_READER_RESULT"
    if rd.get("status") == 200 and rd.get("finish_reason") and not rd.get("timed_out") and not rd.get("error"):
        return "COMPLETE_RESPONSE"
    if rd.get("status") is None:
        return "NO_RESPONSE_" + ("TIMEOUT" if rd.get("timed_out") else ("ERROR" if rd.get("error") else "CONNECTION_CLOSED"))
    return "OTHER"


def e3_rows(summary):
    """Rows from what was observed, each with n=1. Any stop withholds every verdict row (D1). B4 is
    informed only when the Successor, not the backstop, performed and verified the termination."""
    st = summary.get("stops") or []
    o = summary.get("orphan") or {}
    s = summary.get("successor") or {}
    r, notes = {}, {}
    survived = bool(o.get("alive_at_first_successor_observation"))
    r["O1_orphan_survival"] = f"SUPPORTS ({OBS_LABEL}: runtime alive at first successor classification)" if survived else "INCONCLUSIVE"
    cls = s.get("classifications") or []
    consistent = bool(cls) and all(c["verdict"] != L.TERMINATED or c.get("identity_gone") for c in cls)
    r["O3_successor_classification_consistency"] = (f"SUPPORTS ({OBS_LABEL}; consistency only: never PROVEN_TERMINATED while identity live)"
                                                    if consistent else "INCONCLUSIVE")
    by_successor = (s.get("terminated_by") == "successor" and s.get("verified") is True and bool(s.get("signals_by_successor"))
                    and (summary.get("exit") or {}).get("attribution_consistent") is not False)
    r["O4_successor_termination"] = (f"SUPPORTS ({OBS_LABEL}; kill by verified identity, non-parent conjunction, no waitpid evidence)"
                                     if by_successor else "INCONCLUSIVE")
    r["B4_successor_side"] = (f"SUPPORTS (conditional; {OBS_LABEL}; harness-owned test configuration; not reproduced)"
                              if by_successor and summary.get("record_state") == "EXIT_VERIFIED" and not summary.get("backstop_used") else "INCONCLUSIVE")
    if st:
        for name in VERDICT_ROWS:
            r[name] = "INCONCLUSIVE"
        notes["verdicts_withheld_by_stops"] = sorted({str(x.get("id")) for x in st})
    observations = {
        "O2_exited_by_itself_before_window_end": o.get("exited_by_itself"),
        "O2_exit_cause": o.get("exit_cause"),
        "O5_reader_outcome_class": reader_outcome_class(summary.get("reader")),
        "O5_note": "one in-flight attempt; not B3; not a late_delivery_excluded qualification; client completion is not server idleness",
    }
    for name in NOT_TESTED:
        r[name] = "NOT_TESTED"
    return {"rows": r, "observations": observations, "notes": notes, "n": 1}


def committed_view(summary, raw_artifacts=None):
    """Counts, booleans, labels, hashes and numbers: no prompts, outputs, logs, paths, keys or
    addresses. ``reader`` carries status class, lengths and a content hash, never content."""
    rd = summary.get("reader") or {}
    return {
        "run_id": summary.get("run_id"), "scope": SCOPE, "outcome": summary.get("outcome"),
        "interpretation": summary.get("interpretation"),
        "stops": [{"id": t["id"], "why": (t["why"].split(":")[0] if t["id"] in ("S8", "S9") else t["why"]),
                   "quarantine": bool(t.get("quarantine"))} for t in summary.get("stops", [])],
        "gate": {k: v["ok"] for k, v in (summary.get("gate") or {}).items()},
        "controls_passed": (summary.get("controls") or {}).get("passed"),
        "trigger": summary.get("trigger"),
        "timeline": summary.get("timeline"),
        "reader": {k: rd.get(k) for k in ("status", "finish_reason", "prompt_tokens", "completion_tokens", "content_len",
                                          "content_sha256", "elapsed", "timed_out", "error", "client_completed")},
        "orphan": summary.get("orphan"),
        "successor": {k: v for k, v in (summary.get("successor") or {}).items() if k != "raw"},
        "owner_kill": summary.get("owner_kill"),
        "key_file": summary.get("key_file"),
        "http_after_kill": summary.get("http_after_kill"), "successor_sandbox": summary.get("successor_sandbox"),
        "successor_returncode": summary.get("successor_returncode"),
        "backstop_used": summary.get("backstop_used"), "quarantine_cleanup": summary.get("quarantine_cleanup"),
        "record_state": summary.get("record_state"), "owner_review_required": summary.get("owner_review_required"),
        "owner_review_persisted": summary.get("owner_review_persisted"), "quarantine_takeover": summary.get("quarantine_takeover"),
        "exit": summary.get("exit"), "signals": summary.get("signals"), "signals_basis": summary.get("signals_basis"),
        "owner_shutdown": summary.get("owner_shutdown"),
        "rows": summary.get("rows"), "model_unchanged": summary.get("model_unchanged"),
        "seal": summary.get("seal"), "finalize_error": summary.get("finalize_error"),
        "identities": summary.get("tool_identities"), "raw_artifacts": raw_artifacts,
    }
