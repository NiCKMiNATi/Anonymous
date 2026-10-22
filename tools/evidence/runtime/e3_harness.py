#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

Slice 0B-2 E3 pilot DRIVER: the stable parent (never killed by the experiment). It runs the E2-B
Load Gate and containment controls, the S1-S13 safety monitor for the WHOLE lifetime (owner alive or
dead), creates and deletes the API key file, starts the Owner and the Reader, evaluates the
trigger, SIGKILLs the Owner (only), starts the sandboxed Successor, bounds the orphan window,
enforces the backstop and writes the evidence. One lifetime, variant V1, no retry.

Protocol: docs/evidence/v0-0b2-e3-pilot-protocol.md. Commands (``--help``): verify, records,
recover, scan-committed, run. ``run`` refuses without the owner's separate AUTHORIZATION-E3.json
(scope e3-pilot-v1, bound to the protocol and implementation hashes, single use), without
``--attended``, with unresolved records, and with unfrozen pins. Nothing here starts a runtime unless
``run`` passes all of that. After the owner kill the Driver sends NO HTTP to the runtime (an HttpGate
enforces it).
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e2b_harness as H  # noqa: E402
import e2b_lib as E  # noqa: E402
import e3_lib as T  # noqa: E402

OWNER = os.path.join(HERE, "e3_owner.py")
READER = os.path.join(HERE, "e3_reader.py")
SUCCESSOR = os.path.join(HERE, "e3_successor.py")
RAW_ARTIFACTS = ("events.jsonl", "gate-window.jsonl", "gate-context.json", "series.jsonl", "post-unload.jsonl",
                 "server.log", "summary.json", "signals.jsonl", "owner.jsonl", "owner.err", "reader.jsonl",
                 "successor.jsonl", "successor.err")
SCRUB_KEYS = ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "__CF_USER_TEXT_ENCODING")
CHILD_REAP_S = 5.0  # bound on waiting for a child we SIGKILLed to be reaped (an OS-level stall is not guaranteed against)


class HttpAfterKill(RuntimeError):
    pass


class HttpGate:
    """Every Driver HTTP request to the runtime goes through ``call``. After ``close`` (executed
    BEFORE the owner kill) any call raises and is counted: the Driver sends nothing to the orphan."""

    def __init__(self):
        self._lock = threading.Lock()
        self.open, self.closed_up, self.attempts_after = True, None, 0

    def call(self, *a, **kw):
        with self._lock:
            if not self.open:
                self.attempts_after += 1
                raise HttpAfterKill("HTTP to the runtime after the owner kill")
        return H.http_call(*a, **kw)

    def close(self):
        with self._lock:
            self.open, self.closed_up = False, T.uptime()


class RemoteInstance(H.Instance):
    """The Driver's view of a runtime it did not spawn. The E2-B observation code (topology, RSS,
    emergency kill by verified identity) is inherited so the same Monitor and S1-S13 evaluator watch
    it; every action that needs a Popen handle is disabled. Record writes are held back until the
    Owner has reported BOUND (the Owner is the writer before that) and go through the locked store."""

    def __init__(self, cfg, records, run_id, run_dir, kill_fn):
        super().__init__(cfg, records, run_id, run_dir, wrap=True, kill_fn=kill_fn)
        self.writer_enabled, self.pending_review = False, None
        # ``review_persisted``: the owner-review flag is known to be on disk. ``review_failed``: a write of the flag
        # failed and has not been repeated successfully (the intent then lives in memory and is re-applied by the
        # Driver's own finalizer; see Pilot.persist_quarantine_intent).
        self.review_persisted, self.review_failed = False, False
        self._tl = threading.local()  # per-thread staging area of one observation
        self.unverified_observations = 0

    def attach(self, spawned):
        self.tag = spawned["tag"]
        self.root = {"pid": spawned["pid"], "start": spawned["start"], "pgid": spawned["pgid"]}
        self.proc = T.IdentityProc(spawned["pid"], spawned["start"])

    def enable_writer(self, rec, bound):
        self.rec, self.bound, self.writer_enabled = rec, bool(bound), True
        if self.pending_review:
            self.mark_owner_review(self.pending_review)

    def _remember(self, found):
        # never raises (a kill path calls this): an instance without the staging area simply retains immediately
        staged = getattr(getattr(self, "_tl", None), "staged", None)
        if staged is not None:  # inside observe(): held back until the root identity has been verified again
            staged.extend(found)
            return
        new = False
        with self._known_lock:
            for i in found:
                key = (i["pid"], tuple(i["start"]))
                if key not in self.known:
                    self.known[key] = {"pid": i["pid"], "start": list(i["start"]), "ppid": i.get("ppid"), "pgid": i.get("pgid")}
                    new = True
        if new and self.writer_enabled and self.rec is not None:
            try:
                self.records.annotate(self.rec, descendants=self._descendant_records())
            except Exception as exc:
                self.persist_errors.append("descendants: " + type(exc).__name__)

    def mark_owner_review(self, reason):
        """The policy flag is written whenever the record exists, even before the Owner reports BOUND:
        the store serialises writers and re-reads the record, and the Owner re-reads it before its final
        write, so a quarantine detected early cannot be lost to an Owner that finalises first.

        A failed write (the bounded record lock was not obtained) does not discard the requirement: it stays in
        ``pending_review`` and in the in-memory record (the E2-B contract, which the bounded store raises past
        because it fails before it touches the record), ``review_failed`` is set, and the Driver re-applies it
        in every write of its own and retries the write (Pilot.persist_quarantine_intent)."""
        self.pending_review = self.pending_review or reason
        if self.rec is None:
            try:
                self.rec = self.records.read(self.run_id)
            except (OSError, ValueError):
                self.review_failed = True
                return False
        try:
            self.records.annotate(self.rec, owner_review_required=True, owner_review_reason=reason)
            self.review_persisted, self.review_failed = True, False
            return True
        except Exception as exc:
            msg = "owner_review: " + type(exc).__name__
            if msg not in self.persist_errors:
                self.persist_errors.append(msg)
            self.rec["owner_review_required"], self.rec["owner_review_reason"] = True, reason
            self.review_failed = True
            return False

    def _unverified_observation(self):
        """What an observation reports when the recorded root identity could not be verified around it: nothing
        about a tree, sockets or a listener (they would belong to whatever holds the pid now), and
        ``lsof_ok`` false because the safety observation was not made."""
        return {"tree": [], "listen_bad": [], "egress": [], "lsof_ok": False,
                "policy": {"killable": [], "strangers": [], "violation": False}, "root_unverified": True}

    def observe(self):
        """E2-B's observation with one difference. The inherited code enumerates the descendants of whatever
        process holds the root pid and remembers them (and the Monitor runs the slower RSS and lsof probes just
        before it), so a runtime that exited and whose pid was reused would put an unrelated process's children
        into the retained kill targets and the durable record. Here the root's (pid, kernel start) is verified
        live before the observation and again after it; the descendants it found are retained only if both
        checks pass (the enumeration lies between them, and one process cannot leave and re-enter), and
        otherwise the whole observation is discarded."""
        pid, start = self.root["pid"], self.root["start"]
        if not T.root_is_live(pid, start):
            self.unverified_observations += 1
            return self._unverified_observation()
        self._tl.staged = []
        try:
            out = super().observe()
            staged = self._tl.staged
        finally:
            self._tl.staged = None
        if not T.root_is_live(pid, start):
            self.unverified_observations += 1
            return self._unverified_observation()
        self._remember(staged)
        return out

    def emergency_kill(self):
        """E2-B's immediate kill with one difference: fresh descendants are discovered only through a root
        whose (pid, start) is verified live before and after the enumeration. If the runtime has already
        exited and its pid belongs to an unrelated process, that process's children are never
        discovered, remembered or signalled; only identities captured earlier (while the root was
        verified) are killed. Every signal still goes through the ledger and its identity check."""
        res = {}
        root = {"pid": self.root["pid"], "start": self.root["start"]}
        try:
            if T.root_is_live(root["pid"], root["start"]):
                found = L.descendants(root["pid"])
                if T.root_is_live(root["pid"], root["start"]):
                    self._remember(found)
        except Exception as exc:
            self.persist_errors.append("pre-kill snapshot: " + type(exc).__name__)
        res["root"] = self.kill_fn([root])
        desc = self._known_targets()
        if desc:
            res["descendants"] = self.kill_fn(desc)
        return res

    def _never(self, *a, **kw):
        raise NotImplementedError("the Driver never launches, binds or waits on the runtime; the Owner does")

    launch = wait_ready = bind = shutdown = contain = safe_shutdown = _never


def pump(stream, q, tag, sink):
    """Reader thread: JSON lines from a child's stdout into a queue and a raw sink file."""
    def run():
        for line in stream:
            sink.write(line)
            sink.flush()
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            msg["_src"] = tag
            q.put(msg)
        q.put({"e": "EOF", "_src": tag})
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def parse_cpu_time(text):
    """ps TIME ([[H:]M:]SS.hh) -> seconds, or None."""
    try:
        parts = text.strip().split(":")
        secs = 0.0
        for p in parts:
            secs = secs * 60 + float(p)
        return secs
    except ValueError:
        return None


def cpu_seconds(pid):
    try:
        return parse_cpu_time(subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True, timeout=3).stdout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def child_env():
    """Scrubbed environment for the experiment's helper processes (sysctl and lsof live in /usr/sbin)."""
    return {k: os.environ[k] for k in SCRUB_KEYS if k in os.environ} | {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


class Pilot:
    """One pilot lifetime. Methods are ordered as the protocol's sequence."""

    def __init__(self, cfg, probes, auth, bodyG, bounds, summary, run_dir, ev, interrupted, cancel, opts, e3pins=None):
        self.cfg, self.probes, self.auth, self.bodyG, self.b = cfg, probes, auth, bodyG, bounds
        self.summary, self.run_dir, self.ev, self.interrupted, self.cancel, self.o = summary, run_dir, ev, interrupted, cancel, opts
        self.run_id = summary["run_id"]
        self.e3pins = e3pins
        self.records = T.LockedRecords(cfg.root, lock_timeout_s=bounds["lock_timeout_s"])
        self.ledger = T.SignalLedger(run_dir, lock_timeout_s=bounds["lock_timeout_s"])
        self.gate = HttpGate()
        self.inst = RemoteInstance(cfg, self.records, self.run_id, run_dir, self.ledger.kill_fn("driver-monitor", "monitor_or_cleanup"))
        self.mon = None
        self.key = secrets.token_hex(24)
        self.key_file = os.path.join(run_dir, "scratch", "api-key")
        self.q = queue.Queue()
        self.owner = self.owner_ident = self.reader = self.successor = None
        self.owner_dead = False
        self.tl, self.e3 = {}, {}
        self.reader_result = None
        self.final_stop = None  # a StopRun raised while the final trigger check ran inside the ledger critical section
        self.runtime_seen_alive = False  # the Driver has observed the recorded runtime identity alive from the kill instant on (not the pre-trigger monitor samples)
        self._e3_lock = threading.RLock()  # annotate_e3 is called from the main thread only, but the dict it serialises is shared
        self.successor_msgs, self.successor_pump, self.baseline_conns = [], None, set()
        self.stops = summary["stops"]
        self.sinks = {}

    # -- helpers -----------------------------------------------------------------------------------

    def sink(self, name):
        if name not in self.sinks:
            self.sinks[name] = open(os.path.join(self.run_dir, name), "a")
        return self.sinks[name]

    def close_sinks(self):
        for f in self.sinks.values():
            try:
                f.close()
            except OSError:
                pass

    def fault(self, point):
        """Test-only fault injection (never set from the CLI): the Driver kills itself at a named point."""
        faults = self.o.get("faults") or {}
        if faults.get("die_at") == point:
            signal.raise_signal(signal.SIGKILL)
        held = faults.get("signals_in_event_lock") or {}
        if held.get("at") == point:
            # the main thread holds the internal lock of both Events while repeated, nested signals arrive: with a handler that
            # calls ``Event.set()`` the second one blocks forever on a lock its own thread holds
            with self.interrupted._cond, self.cancel._cond:
                for n in held["signals"]:
                    signal.raise_signal(n)
                time.sleep(0.05)

    def stop_active(self):
        """True as soon as any stop exists. The E2-B monitor appends its trigger BEFORE its slower
        persistence and signalling and sets ``cancel`` only after them, so the trigger list is consulted
        as well: a stop is visible here the instant the monitor has decided it."""
        return (self.interrupted.is_set() or self.cancel.is_set() or bool(self.mon.triggers)
                or (not self.mon.is_alive() and not self.mon.halt.is_set()))

    def guard(self):
        if self.interrupted.is_set():
            raise H.StopRun("S11", "operator interrupt")
        if not self.mon.is_alive() and not self.mon.halt.is_set():
            raise H.StopRun("S13", "monitor thread is not running")
        if self.cancel.is_set() or self.mon.triggers:
            t = self.mon.triggers[-1] if self.mon.triggers else {"id": "S?", "why": "cancelled", "quarantine": False}
            raise H.StopRun(t["id"], t["why"], t.get("quarantine", False))

    def stop_successor(self):
        """Stop our own child first so that exactly one signaller remains. The wait is bounded; a child
        that cannot be reaped (an OS-level stall) is reported, not waited for."""
        s = self.successor
        if s is None or s.poll() is not None:
            return True
        s.kill()
        try:
            s.wait(CHILD_REAP_S)
        except subprocess.TimeoutExpired:
            self.summary["successor_not_reaped"] = True
            return False
        return True

    def next_msg(self, src, timeout):
        """Next queue message from ``src`` (others are kept in order for their consumers)."""
        end = time.monotonic() + timeout
        held = []
        try:
            while time.monotonic() < end:
                try:
                    m = self.q.get(timeout=0.05)
                except queue.Empty:
                    continue
                if m.get("_src") == src:
                    return m
                held.append(m)
            return None
        finally:
            for m in held:
                self.q.put(m)

    def drain(self, prekill):
        """Process every queued message without blocking. Reader completion is recorded; before the
        kill an Owner exit report is a stop; successor lines are kept for the evidence."""
        while True:
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                return
            src, e = msg.get("_src"), msg.get("e")
            if src == "reader" and e == "DONE":
                self.reader_result = msg
                self.tl["reader_done_up"] = msg["up"]
            elif src == "successor":
                self.successor_msgs.append(msg)
            elif src == "owner" and prekill and e in ("RUNTIME_EXITED", "EOF", "FINAL"):
                raise H.StopRun("RUNTIME_EXIT", f"owner reported {e} before the trigger")

    def annotate_e3(self, **changes):
        with self._e3_lock:
            self.e3.update(changes)
            try:
                self.records.annotate(self.inst.rec, e3=json.loads(json.dumps(self.e3, default=list)))
                return True
            except Exception as exc:
                msg = "e3_annotate: " + type(exc).__name__
                if msg not in self.inst.persist_errors:
                    self.inst.persist_errors.append(msg)
                return False

    # -- stop state shared by every writer (interrupt, quarantine intent, killing stops) -----------

    def reconcile_interrupt(self):
        """An operator interrupt is a stop. The signal handler only sets a flag, so every place that decides an
        outcome (the observation loop before any early exit, and the verdict after the last blocking finalization
        step) converts the flag into the S11 stop, once. Returns whether an interrupt has been accepted."""
        seen = self.interrupted.is_set()
        if seen:
            add_interrupt_stop(self.stops)
        return seen

    def all_stops(self):
        """Every stop the Driver knows: its own list and the monitor's trigger list (which the monitor fills BEFORE
        it persists or signals anything)."""
        mon = getattr(self, "mon", None)
        return list(getattr(self, "stops", None) or []) + list(getattr(mon, "triggers", None) or [])

    def killing_stops(self):
        """The stops that kill or quarantine. This, not the record's quarantine flag, is what an exit attribution needs."""
        return [s for s in self.all_stops() if s.get("immediate") or s.get("quarantine")]

    def attribution_stops(self, rec=None):
        """The stop evidence for ``exit_attribution`` in the Driver: its actual stops plus what the durable record says."""
        return self.killing_stops() + T.record_stop_state(rec or {})

    def quarantine_intent(self):
        """The reason of a mandatory quarantine the Driver knows about, or None. Taken from the instance's pending
        review and from the stops themselves, so it does not depend on any write having succeeded."""
        inst = getattr(self, "inst", None)
        if inst is not None and inst.pending_review:
            return inst.pending_review
        for s in self.all_stops():
            if s.get("quarantine"):
                return f"{s.get('id')}: {s.get('why')}"
        return None

    def persist_quarantine_intent(self):
        """(reason, persisted). Makes a mandatory quarantine durable if it is not yet (one bounded attempt) and
        reports whether the owner-review flag is on disk. A record that is already EXIT_VERIFIED can no longer be
        flagged: that is reported as not persisted, and ``finish`` then refuses every successful outcome."""
        reason = self.quarantine_intent()
        if reason is None:
            return None, True
        try:
            rec = self.records.read(self.run_id)
        except (OSError, ValueError):
            return reason, False
        if rec.get("owner_review_required"):
            return reason, True
        if rec.get("state") == "EXIT_VERIFIED" or self.inst is None:
            return reason, False
        return reason, bool(self.inst.mark_owner_review(reason))

    def delete_key(self):
        try:
            os.unlink(self.key_file)
        except OSError:
            pass
        return not os.path.exists(self.key_file)

    # -- sequence: start ---------------------------------------------------------------------------

    def start_owner(self, art):
        scratch = os.path.dirname(self.key_file)
        os.makedirs(scratch, mode=0o700, exist_ok=True)
        fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, (self.key + "\n").encode())
        os.close(fd)
        spec_path = os.path.join(self.run_dir, "owner-spec.json")
        me = L.identity(os.getpid())
        pins_path = os.path.join(self.run_dir, "owner-pins.json")
        with open(pins_path, "w") as f:
            json.dump(self.cfg.pins, f)
        spec = {"bench": self.cfg.bench, "root": self.cfg.root, "run_id": self.run_id, "run_dir": self.run_dir,
                "pins_path": pins_path, "pins_canonical_sha256": E.sha256_bytes(E.canon(self.cfg.pins)),
                "binary": self.cfg.binary, "model": self.cfg.model, "port": self.cfg.port, "readiness_s": self.cfg.readiness_s,
                "profile": self.cfg.profile, "lock_timeout_s": self.b["lock_timeout_s"],
                "wrap": self.o["wrap"], "driver": {"pid": os.getpid(), "start": me["start"] if me else None},
                "hashes": {"binary": art.get("binary_sha256"), "model": self.summary["model_sha256"]}}
        fd = os.open(spec_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, json.dumps(spec).encode())
        os.close(fd)
        # every bound identity (protocol, the ten implementation files, expiry, single use, the authorization id)
        # is verified again immediately before the authorization is consumed: the first check ran before Phases 1
        # and 2, and the Owner, Reader and Successor scripts are read from disk only now and later. Fixture G is
        # NOT re-read here: the execution input is the in-memory body that ``load_fixture_g`` verified by length and
        # SHA-256 earlier in this run (``self.bodyG``, sent to the Reader as canonical JSON); this call compares the
        # authorization's fixture hash with the pinned hash only.
        ok, why, again = T.check_authorization(self.cfg.root, self.cfg.protocol_doc, self.e3pins, self.o["impl"])
        if not ok or (again or {}).get("authorization_id") != self.auth.get("authorization_id"):
            raise H.StopRun("AUTH", "authorization or bound identity changed before consumption: " + (why if not ok else "authorization id differs"))
        # the authorization is consumed immediately before the first process that can spawn the runtime
        self.summary["consumed_marker"] = os.path.basename(T.consume_authorization(self.cfg.root, self.auth, self.run_id))
        with open(os.path.join(self.run_dir, "owner.err"), "w") as err:
            self.owner = subprocess.Popen([sys.executable, "-B", "-I", OWNER, spec_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=err, env=child_env(), text=True, start_new_session=True)
        self.owner_ident = L.identity(self.owner.pid)
        pump(self.owner.stdout, self.q, "owner", self.sink("owner.jsonl"))
        self.ev("owner_started")

    def await_bound(self):
        deadline = time.monotonic() + 30 + self.cfg.readiness_s + 10
        spawned = None
        while time.monotonic() < deadline:
            self.guard()
            m = self.next_msg("owner", 0.1)
            if m is None:
                continue
            e = m["e"]
            if e == "SPAWNED":
                spawned = m
                self.inst.attach(m)
                self.mon.mark_spawn()
                self.tl["spawned_up"] = T.uptime()
            elif e == "BOUND":
                self.tl["bound_up"] = T.uptime()
                rec = self.records.read(self.run_id)
                ok = (m.get("verified") is True and rec.get("state") == "BOUND" and rec.get("binding_verified") is True
                      and spawned is not None and rec.get("pid") == spawned["pid"] and rec.get("start") == spawned["start"])
                self.summary["bind_detail"] = m.get("bind_detail")
                if not ok:
                    if (m.get("bind_detail") or {}).get("pid_ok") and not (m.get("bind_detail") or {}).get("addr_ok"):
                        raise H.StopRun("S9", "listener is not exactly the loopback address", immediate=True)
                    raise H.StopRun("BINDING", "sole-listener binding not verified")
                self.inst.enable_writer(rec, True)
                return
            elif e in ("NOT_BOUND", "FINAL", "EOF", "RUNTIME_EXITED"):
                raise H.StopRun("READINESS", f"owner reported {e}")
        raise H.StopRun("READINESS", "owner did not report BOUND in time")

    def start_reader(self):
        cmd = [sys.executable, "-B", "-I", READER]
        if self.o["wrap"]:
            cmd = ["/usr/bin/sandbox-exec", "-p", E.SANDBOX] + cmd
        self.reader = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=child_env(),
                                       text=True, start_new_session=True)
        pump(self.reader.stdout, self.q, "reader", self.sink("reader.jsonl"))
        self.reader.stdin.write(json.dumps({"port": self.cfg.port, "key": self.key, "body": E.canon(self.bodyG).decode(),
                                            "deadline_s": self.b["reader_deadline_s"]}) + "\n")
        self.reader.stdin.flush()

    # -- sequence: trigger -------------------------------------------------------------------------

    def wait_trigger(self):
        """Poll /slots every 100 ms until the trigger decides. Returns (decision, trigger)."""
        b, trig = self.b, T.Trigger(self.b)
        self.reader.stdin.write("GO\n")
        self.reader.stdin.flush()
        m = self.next_msg("reader", 5.0)
        if not m or m["e"] != "SENT":
            raise H.StopRun("E3-READER", "reader did not report that the request was sent")
        trig.request_sent(m["up"])
        self.tl["request_sent_up"] = m["up"]
        diag = {"polls": 0, "slot_fields_seen": set(), "n_decoded_values": []}
        while True:
            self.guard()
            t_loop = time.monotonic()
            self.drain(prekill=True)
            if self.reader_result is not None and trig.reader_done_up is None:
                trig.reader_completed(self.reader_result["up"])
            r = self.gate.call(self.cfg.port, "GET", "/slots", None, self.key, 1.0)
            sl = H.jbody(r) if r["status"] == 200 else None
            ok, processing = T.slots_processing(sl)  # literal JSON true only; malformed or non-boolean values are no evidence
            now = T.uptime()
            trig.poll(now, ok, processing)
            diag["polls"] += 1
            if ok:  # token counts are diagnostic only and never gate anything
                for s in sl:
                    diag["slot_fields_seen"].update(s.keys())
                    nt = (s.get("next_token") or [{}])[0] if isinstance(s.get("next_token"), list) else {}
                    if isinstance(nt, dict) and isinstance(nt.get("n_decoded"), int):
                        diag["n_decoded_values"].append(nt["n_decoded"])
            d = trig.decide(now, stop_active=self.stop_active())
            if d != T.WAIT:
                self.summary["trigger"] = {"decision": d, "polls": diag["polls"], "consecutive": trig.consec,
                                           "slot_fields_seen": sorted(diag["slot_fields_seen"]),
                                           "n_decoded_last": diag["n_decoded_values"][-1] if diag["n_decoded_values"] else None,
                                           "n_decoded_note": "diagnostic only; never part of the trigger",
                                           "request_in_flight_s": round(now - trig.sent_up, 3)}
                return d, trig
            time.sleep(max(0.0, b["poll_interval_s"] - (time.monotonic() - t_loop)))

    # -- sequence: kill ----------------------------------------------------------------------------

    def final_trigger_check(self, trig):
        """The last validation of every mandatory trigger condition. It runs INSIDE the ledger critical
        section (after the ledger and identity checks, immediately before ``kill(2)``), so a stop, the
        reader's completion, an expired or stale trigger that arose while the ledger lock was awaited
        still prevents the kill. Returns None to proceed (the HTTP gate is closed here, as the very last
        step) or the reason for refusing. It never blocks: ``drain`` is non-blocking."""
        try:
            self.drain(prekill=True)
        except H.StopRun as stop:  # e.g. the Owner reported an exit
            self.final_stop = stop
            return "stop"
        now = T.uptime()
        if self.stop_active():
            return "stop"
        if self.reader_result is not None:
            if trig.reader_done_up is None:
                trig.reader_completed(self.reader_result["up"])
            return "reader_completed"
        d = trig.decide(now)  # processing eligibility: arm delay, consecutive processing polls, prekill bound
        if d == T.TIMEOUT:
            return "timeout"
        if d != T.FIRE:
            return "not_eligible"
        if not trig.fresh(now):
            return "stale"
        self.gate.close()  # from here on the Driver sends nothing to the runtime
        return None

    def kill_owner(self, trig):
        """Durable identity first, then the kill. Nothing is sent to the runtime afterwards."""
        inst = self.inst
        self.guard()  # no stop active, monitor alive, no interrupt: checked at the kill instant too
        rec = self.records.read(self.run_id)
        rt = inst.root
        rt_ident = L.identity(rt["pid"])
        if not (rec.get("state") == "BOUND" and rec.get("binding_verified") is True and rec.get("pid") == rt["pid"]
                and rec.get("start") == rt["start"] and L.same_identity(rt["pid"], rt["start"], rt_ident) and rt_ident["status"] != "zombie"):
            raise H.StopRun("E3-1", "pre-kill identity check failed: the record and the kernel do not agree on the runtime")
        self.runtime_seen_alive = True  # the record and the kernel agreed on a live runtime identity just now
        if not L.same_identity(self.owner.pid, self.owner_ident["start"], L.identity(self.owner.pid)):
            raise H.StopRun("E3-1", "owner identity changed before the kill")
        if not self.annotate_e3(scope=T.SCOPE, bounds=json.loads(json.dumps(self.b, default=list)),
                                owner={"pid": self.owner.pid, "start": self.owner_ident["start"]},
                                planned="owner_sigkill", pre_kill_up=T.uptime()):
            raise H.StopRun("E3-1", "pre-kill record could not be made durable")
        self.fault("before_kill")
        self.drain(prekill=True)
        # cheap early outs; the authoritative check is final_trigger_check inside the ledger critical section
        if self.reader_result is not None:
            return "TRIGGER_MISSED"
        if not trig.fresh(T.uptime()):
            return "TRIGGER_STALE"
        self.guard()
        res = self.ledger.send("driver", self.owner.pid, self.owner_ident["start"], signal.SIGKILL, "e3_owner_sigkill",
                               precheck=lambda: self.final_trigger_check(trig))
        if not res["sent"]:
            why = str(res["why"])
            self.summary["owner_kill_refused"] = why
            if why == "precheck:stop":
                if self.final_stop is not None:
                    raise self.final_stop
                self.guard()  # raises the StopRun for the active stop
                raise H.StopRun("E3-STOP", "a stop became active while the kill was being issued")
            if why == "precheck:reader_completed":
                return "TRIGGER_MISSED"
            if why.startswith("precheck:"):
                self.summary["trigger_refusal"] = why[len("precheck:"):]
                return "TRIGGER_STALE"
            raise H.StopRun("E3-1", "owner SIGKILL was not delivered: " + why)
        t0, wall0 = res["attempt_up"], res["attempt_wall"]  # the instant of the actual signal attempt, taken inside the lock
        key_deleted = self.delete_key()  # the runtime already holds the key; the Reader has its request in flight
        self.tl.update(t0=t0, t0_wall=wall0, key_deleted_up=T.uptime())
        try:
            rc = self.owner.wait(self.b["owner_dead_s"])
        except subprocess.TimeoutExpired:
            raise H.StopRun("E3-1", "owner survived SIGKILL")
        self.owner_dead = True
        self.tl["owner_dead_up"] = T.uptime()
        self.summary["owner_kill"] = {"signal_sent": res["sent"], "owner_returncode": rc, "key_deleted_before_successor": key_deleted,
                                      "t0_to_owner_dead_s": round(self.tl["owner_dead_up"] - t0, 3)}
        self.summary["key_file"] = {"deleted_at_t0_rel_s": round(self.tl["key_deleted_up"] - t0, 3), "exists_after_kill": os.path.exists(self.key_file)}
        self.fault("after_kill")
        self.baseline_conns = set(n for n in (H.lsof_names(inst.root["pid"]) or []) if "->" in n)
        self.annotate_e3(t0_up=t0, t0_wall=wall0, owner_dead_up=self.tl["owner_dead_up"],
                         window_deadline_up=T.window_deadline(t0, self.tl.get("reader_done_up"), None, self.b),
                         backstop_up=t0 + self.b["backstop_s"])
        return "KILLED"

    # -- sequence: orphan --------------------------------------------------------------------------

    def start_successor(self):
        rec_path = self.records.path(self.run_id)
        denied = [self.cfg.fixtures_dir, os.path.dirname(self.cfg.model), os.path.dirname(self.key_file)]
        cmd = self.o.get("successor_cmd") or [sys.executable, "-B", "-I", SUCCESSOR, rec_path]
        sandboxed = bool(self.o["wrap"] and not self.o.get("successor_cmd"))
        if sandboxed:
            cmd = ["/usr/bin/sandbox-exec", "-p", T.successor_profile(denied)] + cmd
        self.summary["successor_sandbox"] = {"network_denied_by_kernel": sandboxed, "file_read_denied": ["fixtures", "models", "run scratch"] if sandboxed else []}
        with open(os.path.join(self.run_dir, "successor.err"), "w") as err:
            self.successor = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, env=child_env(),
                                              text=True, start_new_session=True)
        self.successor_pump = pump(self.successor.stdout, self.q, "successor", self.sink("successor.jsonl"))
        self.tl["successor_start_up"] = T.uptime()
        self.fault("after_successor_start")

    def orphan_phase(self):
        """Observation window. Every call in the loop is bounded (shared locks by ``lock_timeout_s``,
        probes by their own timeouts), and the Successor-ended and backstop checks come first in each
        iteration, so a stalled Successor or a failed annotation cannot keep the Driver from its backstop.
        The backstop fires at the first iteration at or after ``backstop_s``; an iteration is bounded by
        its calls' own timeouts, and no deadline is guaranteed against an OS-level stall."""
        b, t0, inst = self.b, self.tl["t0"], self.inst
        self.start_successor()
        stop_up, last_diag, samples = None, 0.0, []
        deadline = T.window_deadline(t0, self.tl.get("reader_done_up"), None, b)
        new_conns, e33_published = set(), False
        pending, last_annot = False, -1e9  # a window update whose annotation failed is retried at most once per second
        published_kill, takeover = False, False
        while True:
            now = T.uptime()
            self.drain(prekill=False)
            self.reconcile_interrupt()  # a pending interrupt is published BEFORE any early exit below can hide it
            if inst.review_failed and not takeover:
                # a mandatory quarantine could not be written (the record lock was held past its bound). The Successor is
                # our own child and is the one other writer that could still resolve the record as EXIT_VERIFIED without
                # the flag: it is stopped now, the Driver finalizes with the intent it holds in memory.
                takeover = True
                self.summary["quarantine_takeover"] = True
                self.stop_successor()
            if self.successor.poll() is not None:
                break
            if now >= t0 + b["backstop_s"]:
                self.backstop("backstop deadline")
                break
            if stop_up is None and self.stop_active():
                stop_up = now
            nd = T.window_deadline(t0, self.tl.get("reader_done_up"), stop_up, b)
            kill_ids = sorted({str(s.get("id")) for s in self.killing_stops()})
            try_now = nd != deadline or bool(kill_ids) != published_kill
            published_kill = bool(kill_ids)
            if nd != deadline:
                deadline = nd
            # deadline-aware: a window annotation that could still be waiting on a lock when the backstop is due is skipped
            # (the Successor is about to be stopped; a stale deadline in the record only makes its window longer, never shorter)
            if (try_now or (pending and now - last_annot >= 1.0)) and t0 + b["backstop_s"] - now > b["lock_timeout_s"] + 0.2:
                last_annot = now
                # ``killing_stop`` tells the Successor (which reads only the record) that a stop that kills or quarantines
                # was seen, so a missing delivery is undetermined there too
                pending = not self.annotate_e3(window_deadline_up=deadline, reader_done_up=self.tl.get("reader_done_up"), stop_up=stop_up,
                                               killing_stop=bool(kill_ids), killing_stop_ids=kill_ids)
            if now - last_diag >= 1.0:
                last_diag = now
                alive = inst.proc.poll() is None  # the recorded (pid, start) is verified live: only then is the pid observed
                if alive:
                    self.runtime_seen_alive = True
                    names = H.lsof_names(inst.root["pid"])
                    if names is not None:
                        new_conns |= {n for n in names if "->" in n} - self.baseline_conns
                samples.append({"t_rel": round(now - t0, 2), "cpu_s": cpu_seconds(inst.root["pid"]) if alive else None, "alive": alive})
                if new_conns and not e33_published:
                    # the violation is published as a stop the moment it is seen, and the observation ends now
                    e33_published = True
                    self.stops.append({"id": "E3-3", "why": "new connection to the runtime after the owner kill", "quarantine": False, "immediate": False})
                    if stop_up is None:
                        stop_up = now
            time.sleep(0.1)
        self.tl["window_end_up"] = deadline
        self.summary["orphan_samples"] = samples
        self.summary["http_after_kill"] = {"driver_gate_attempts_after_close": self.gate.attempts_after,
                                           "driver_gate_closed_at_t0_rel_s": None if self.gate.closed_up is None else round(self.gate.closed_up - t0, 4),
                                           "new_connections_seen_by_lsof_after_baseline": len(new_conns),
                                           "method": "driver gate; lsof 1 Hz diff from the kill; blind interval = poll period"}
        self.stop_successor()  # a Successor still running here is our own child and is stopped before anything else
        self.summary["successor_returncode"] = self.successor.returncode
        if self.successor_pump is not None:
            self.successor_pump.join(3)
        self.drain(prekill=False)
        self.reconcile_interrupt()
        self.persist_quarantine_intent()  # one bounded attempt now that our own Successor no longer holds a lock
        state = self.records.read(self.run_id)["state"]
        if state == "QUARANTINED" and not self.summary.get("backstop_used"):
            self.quarantine_cleanup()
        elif state not in ("EXIT_VERIFIED", "QUARANTINED") and not self.summary.get("backstop_used"):
            self.backstop("successor ended without resolving the record")

    def backstop(self, reason):
        """Driver kill by verified identity when the Successor failed or timed out. The Successor is
        stopped first (our own child) so exactly one signaller remains; the result is labelled."""
        self.summary["backstop_used"], self.summary["backstop_reason"] = True, reason
        self.stop_successor()
        self.tl["backstop_up"] = T.uptime()
        self.finalize_nonparent("driver_backstop")

    def liveness_kill(self, rec, who):
        """SIGKILL of the recorded root and recorded descendants through the ledger only: it re-verifies
        (pid, kernel start) immediately before each signal, sends at most one SIGKILL per identity (so a
        Successor's or the monitor's earlier kill is never repeated) and never touches the record."""
        out = []
        if rec.get("pid") and rec.get("start"):
            out.append(self.ledger.send(who, rec["pid"], rec["start"], signal.SIGKILL, "driver_cleanup"))
            for d in rec.get("descendants", []):
                out.append(self.ledger.send(who, d["pid"], d["start"], signal.SIGKILL, "recorded_descendant"))
        return out

    def quarantine_cleanup(self):
        """The Successor (or anyone) left the record QUARANTINED: the quarantine stays sticky and is never
        rewritten, but a recorded process that is somehow still alive is killed by verified identity."""
        res = self.liveness_kill(self.records.read(self.run_id), "driver_cleanup")
        self.summary["quarantine_cleanup"] = {"attempts": [{"sent": r["sent"], "why": r["why"]} for r in res]}

    def finalize_nonparent(self, who):
        """Kill the recorded identities (ledger), verify the non-parent conjunction, write the record."""
        inst = self.inst
        rec = self.records.read(self.run_id)
        if rec["state"] == "EXIT_VERIFIED":
            return
        # the Driver's own first look at the recorded identity, before it signals anything
        alive_before = bool(rec.get("pid") and rec.get("start") and T.root_is_live(rec["pid"], rec["start"]))
        # a mandatory quarantine the Driver knows about is carried into this writer whether or not it could be written
        # earlier: made durable now if possible, and in any case set on the copy that ``write_final`` refreshes (the
        # refresh keeps owner-review flags), so this final write can never be an EXIT_VERIFIED
        intent, _ = self.persist_quarantine_intent()
        if intent and not rec.get("owner_review_required"):
            rec["owner_review_required"], rec["owner_review_reason"] = True, intent
        self.liveness_kill(rec, who)  # liveness safety first, also for a quarantined record
        if rec["state"] == "QUARANTINED":
            return  # the Driver never rewrites or clears a quarantine
        if not (rec.get("pid") and rec.get("start")):
            self.summary["finalize"] = {"verified": False, "why": "record has no identity (INTENT only)"}
            return
        v = T.verify_nonparent(rec, rec["port"], rec["tag"], self.b["backstop_verify_s"])
        # who ended the runtime comes from the ledger (delivered signals), not from who ran this method; a stop that
        # kills or quarantines with no delivery in the ledger makes the cause undetermined (the Driver's actual stops,
        # plus what the record says). The exit event is "no notification" for a runtime the Driver saw alive at any
        # earlier point of its scope (it registers no exit watch) and "absent at first observation" only if the Driver never saw
        # it alive FROM THE KILL INSTANT ON (the scope of ``runtime_seen_alive``; the monitor's pre-trigger samples are not
        # consulted): this finalizer's own first look is not the Driver's first observation in that scope.
        attr = T.exit_attribution(self.ledger.entries(), rec["pid"], rec["start"], self.attribution_stops(rec))
        label = T.termination_label(attr, v["checks"].get("identity_gone") is True)
        seen_alive = bool(alive_before or getattr(self, "runtime_seen_alive", False))
        written = T.write_final(self.records, rec, v["verified"], v["checks"], who,
                                T.EXIT_NO_NOTIFICATION if seen_alive else T.EXIT_UNOBSERVED,
                                extra={"terminated_by": label, "exit_cause": attr["cause"], "exit_by": attr["by"]})
        self.summary["finalize"] = {"verified": v["verified"], "checks": v["checks"], "record_written": written, "who": who,
                                    "alive_at_first_look": alive_before, "driver_saw_alive_from_kill_instant": bool(getattr(self, "runtime_seen_alive", False)),
                                    "first_observation_scope": T.FIRST_OBSERVATION_SCOPE}

    # -- pre-kill abort and containment ------------------------------------------------------------

    def shutdown_owner(self):
        """Normal E2-B shutdown through the live Owner (its code), after which the record is final."""
        policy = None
        q = [s["id"] for s in self.stops if s.get("quarantine")]
        if q or self.inst.pending_review:
            policy = "owner review required: " + (",".join(q) or "flagged by the monitor")
        imm = any(s.get("immediate") for s in self.stops)
        if self.owner is not None and self.owner.poll() is None and self.owner.stdin and not self.owner.stdin.closed:
            try:
                self.owner.stdin.write("SHUTDOWN " + json.dumps({"immediate": imm, "policy_quarantine": policy}) + "\n")
                self.owner.stdin.flush()
            except OSError:
                pass
        end = time.monotonic() + self.b["owner_shutdown_s"]
        while time.monotonic() < end:
            m = self.next_msg("owner", 0.2)
            if m and m["e"] == "FINAL":
                self.summary["shutdown"] = m.get("result")
                break
            if m and m["e"] == "EOF":
                break
        else:
            self.summary["shutdown"] = {"verified": False, "why": "owner did not finish the shutdown in time"}
        if self.owner.poll() is None:
            try:
                self.owner.wait(2)
            except subprocess.TimeoutExpired:
                pass
        rec = self.records.read(self.run_id) if os.path.exists(self.records.path(self.run_id)) else None
        if rec is not None and rec["state"] not in ("EXIT_VERIFIED", "QUARANTINED"):
            # the Owner could not finish: kill by identity and finalize as a non-parent
            if self.owner.poll() is None:
                self.ledger.send("driver", self.owner.pid, self.owner_ident["start"], signal.SIGKILL, "owner_unresponsive")
                self.owner.wait(5)
            self.owner_dead = True
            self.finalize_nonparent("driver_cleanup")

    def finalize_after_stop(self):
        """Every post-kill cleanup: stop the Successor first (bounded), then kill by verified identity and
        write the record as a non-parent. Used for a stop, for any unexpected exception and from cleanup."""
        self.stop_successor()
        self.finalize_nonparent("driver_cleanup")

    def cleanup(self):
        self.stop_successor()  # a Successor must never outlive the Driver's run, whatever path led here
        for child in (self.reader,):
            if child is not None and child.poll() is None:
                child.kill()
                try:
                    child.wait(CHILD_REAP_S)
                except subprocess.TimeoutExpired:
                    pass
        self.delete_key()
        if self.owner is not None and self.owner.poll() is None and self.owner_dead:
            self.owner.kill()


def add_interrupt_stop(stops):
    """The S11 stop for an accepted operator interrupt, added once. It neither kills nor quarantines, so it never
    changes the durable record; it only decides what the report may claim."""
    if not any(s.get("id") == "S11" and s.get("why") == "operator interrupt" for s in stops):
        stops.append({"id": "S11", "why": "operator interrupt", "quarantine": False, "immediate": False})


def committed_stop(stop):
    return {"id": stop["id"], "why": stop["why"], "quarantine": bool(stop.get("quarantine")), "immediate": bool(stop.get("immediate"))}


def tool_identities(cfg, impl=None):
    return {"protocol_sha256": E.sha256_file(cfg.protocol_doc), "implementation": impl or T.implementation_hashes(),
            "pins_in_use_canonical": E.sha256_bytes(E.canon(cfg.pins))}


def raw_digests(run_dir):
    return {n: {"bytes": os.path.getsize(os.path.join(run_dir, n)), "sha256": E.sha256_file(os.path.join(run_dir, n))}
            for n in RAW_ARTIFACTS if os.path.isfile(os.path.join(run_dir, n))}


def default_opts(**kw):
    o = dict(gate_n=E.LIMITS["gate_samples"], interval=1.0, top_cmd=None, post_sample_s=E.LIMITS["post_sample_s"], post_delay=10.0,
             install_signals=True, interrupted=None, baseline_n=E.LIMITS["baseline_samples"], baseline_interval=1.0,
             monitor_interval=1.0, monitor_slow_every=5, wrap=True, faults=None, successor_cmd=None, impl=None)
    o.update(kw)
    return o


def execute(cfg, probes, through, attended, auth, e3pins, bounds, summary, run_dir, ev, interrupted, cancel, o, seal):
    def done(outcome, code=1, **kw):
        summary.update(outcome=outcome, **kw)
        return dict(summary, exit_code=code)

    records = T.LockedRecords(cfg.root)
    un = records.unresolved()
    if un:
        return done("REFUSED_UNRESOLVED", 3, why=f"{len(un)} unresolved execution record(s)", unresolved=un)
    summary["tool_identities"] = tool_identities(cfg, o["impl"])
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt before Phase 1")
    p1 = H.phase1(cfg, probes, records, attended, o["gate_n"], o["interval"], o["top_cmd"], abort=interrupted)
    summary["gate"], summary["model_sha256"] = p1["gate"], p1["ctx"]["artifacts"].get("model_sha256")
    with open(os.path.join(run_dir, "gate-window.jsonl"), "w") as f:
        f.write("".join(json.dumps(s) + "\n" for s in p1["samples"]))
    with open(os.path.join(run_dir, "gate-context.json"), "w") as f:
        json.dump(p1["ctx"], f, indent=1, default=str)
    ev("phase1", passed=p1["passed"])
    if p1["interrupted"]:
        return done("INTERRUPTED", why="operator interrupt during Phase 1")
    if not p1["passed"] or through == 1:
        return done("GATE_PASSED" if p1["passed"] else "GATE_FAILED", 0 if p1["passed"] else 1)
    art = p1["ctx"]["artifacts"]
    c = H.controls(cfg, cfg.control_runs, cfg.control_c3_runs, abort=interrupted)
    summary["controls"] = c
    ev("phase2", passed=c["passed"])
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt during Phase 2")
    if not c["passed"] or through == 2:
        return done("CONTROLS_PASSED" if c["passed"] else "CONTROLS_FAILED_INCONCLUSIVE", 0 if c["passed"] else 1)
    try:
        bodyG = T.load_fixture_g(cfg.fixtures_dir, e3pins)
    except E.FixtureError as exc:
        return done("FIXTURE_ERROR", why=str(exc))
    pre = H.prespawn_check(cfg, art)
    summary["artifact_integrity"] = {"gate_check_ok": art["ok"], "prespawn": {k: v for k, v in pre.items() if k != "problems"}}
    if not pre["ok"]:
        return done("ARTIFACT_CHANGED", why="model or runtime tree differs from what Phase 1 verified")
    base = H.swap_baseline(probes, o["baseline_n"], o["baseline_interval"], interrupted)
    summary["swap_baseline"] = base
    if not base["ok"]:
        return done("INTERRUPTED" if base["why"] == "interrupted" else "BASELINE_FAILED", why=base["why"])
    if T.uptime() - p1["ended_up"] > E.LIMITS["gate_stale_s"]:
        return done("GATE_STALE")
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt before spawn")
    pilot = Pilot(cfg, probes, auth, bodyG, bounds, summary, run_dir, ev, interrupted, cancel, o, e3pins)
    hid = p1["ctx"]["attendance"]
    tm = (hid.get("ac_timers_min") or {}).get("displaysleep")
    ceiling = tm * 60 - E.LIMITS["attendance_lapse_margin_s"] if tm else None
    pilot.mon = H.Monitor(probes, E.StopEvaluator(lim=T.stop_limits(bounds), swap_base=base["median_mib"]), pilot.inst,
                          os.path.join(run_dir, "series.jsonl"), cancel, ceiling, interval=o["monitor_interval"],
                          slow_every=o["monitor_slow_every"])
    pilot.mon.start()  # before the spawn, and it stays up until the end, owner alive or dead
    try:
        if not pilot.mon.ready.wait(15) or not pilot.mon.first_sample_ok:
            return done("MONITOR_NOT_READY", why="the monitor produced no complete first sample; nothing was spawned")
        if T.uptime() - p1["ended_up"] > E.LIMITS["gate_stale_s"]:
            return done("GATE_STALE")
        lifetime(pilot, art)
    finally:
        pilot.mon.halt.set()
        pilot.mon.join(5)
        pilot.cleanup()
        pilot.close_sinks()
    return finish(pilot, cfg, probes, through, art, summary, run_dir, o, done, p1, seal)


def lifetime(p, art):
    stops, summary = p.stops, p.summary
    killed = False
    try:
        p.start_owner(art)
        p.await_bound()
        p.start_reader()
        decision, trig = p.wait_trigger()
        if decision == T.FIRE:
            r = p.kill_owner(trig)
            if r == "KILLED":
                killed = True
                p.orphan_phase()
            elif r == "TRIGGER_MISSED":
                stops.append({"id": "E3-MISSED", "why": "the reader completed before the kill was issued; no kill was sent", "quarantine": False, "immediate": False})
                summary["pilot_result"] = "TRIGGER_MISSED"
                p.shutdown_owner()
            else:
                why = summary.get("trigger_refusal")
                stops.append({"id": "E3-STALE", "why": "trigger was stale at the kill" + (f" ({why})" if why else "") + "; no kill was sent",
                              "quarantine": False, "immediate": False})
                summary["pilot_result"] = "TRIGGER_STALE"
                p.shutdown_owner()
        elif decision == T.STOP:
            p.guard()  # raises the StopRun for the active stop
            stops.append({"id": "E3-STOP", "why": "stop active at the trigger", "quarantine": False, "immediate": False})
            p.shutdown_owner()
        else:
            summary["pilot_result"] = "TRIGGER_MISSED" if decision == T.MISSED else "PILOT_NOT_REACHED"
            stops.append({"id": "E3-" + decision, "why": "reader completed before the trigger" if decision == T.MISSED
                          else f"no qualifying generation within {p.b['prekill_abort_s']:.0f} s of the request",
                          "quarantine": False, "immediate": False})
            p.shutdown_owner()
    except H.StopRun as stop:
        stops.append(committed_stop({"id": stop.sid, "why": stop.why, "quarantine": stop.quarantine, "immediate": stop.immediate}))
        if stop.quarantine:
            p.inst.mark_owner_review(f"{stop.sid}: {stop.why}")
        try:
            if killed or p.owner_dead:
                p.finalize_after_stop()
            elif p.owner is not None:
                p.shutdown_owner()
        except BaseException as exc:
            stops.append({"id": "HARNESS_EXCEPTION", "why": "containment: " + type(exc).__name__, "quarantine": False, "immediate": False})
    except HttpAfterKill:
        stops.append({"id": "E3-3", "why": "HTTP attempted after the owner kill", "quarantine": False, "immediate": False})
        try:
            if p.owner_dead or p.successor is not None:
                p.finalize_after_stop()
        except BaseException:
            pass
    except BaseException as exc:
        stops.append({"id": "HARNESS_EXCEPTION", "why": type(exc).__name__, "quarantine": False, "immediate": False})
        try:
            if p.owner_dead or p.successor is not None:  # after the kill: the same bounded, Successor-first cleanup as a stop
                p.finalize_after_stop()
            elif p.owner is not None:
                p.shutdown_owner()
        except BaseException:
            pass


def finish(pilot, cfg, probes, through, art, summary, run_dir, o, done, p1, seal):
    inst, stops = pilot.inst, summary["stops"]
    stops.extend(committed_stop(t) for t in pilot.mon.triggers)
    pilot.reconcile_interrupt()  # an interrupt that coincided with an early exit of the observation is still a stop
    try:
        intent, persisted = pilot.persist_quarantine_intent()  # the Successor and the monitor are done; one bounded attempt
    except Exception as exc:
        intent, persisted = pilot.quarantine_intent(), False
        inst.persist_errors.append("owner_review_final: " + type(exc).__name__)
    rec = None
    try:
        rec = pilot.records.read(pilot.run_id) if os.path.exists(pilot.records.path(pilot.run_id)) else None
    except (OSError, ValueError):
        pass
    summary["record_state"] = (rec or {}).get("state")
    summary["owner_review_required"] = bool((rec or {}).get("owner_review_required")) or bool(intent)
    summary["owner_review_persisted"] = None if not intent else bool(persisted)
    entries = pilot.ledger.entries()
    # attempts versus confirmed delivery, per signaller, no pids; refusals for want of the ledger lock are not in the
    # ledger file, so the ones each signaller reported are added (the Driver's own, the Successor's FINAL, the Owner's FINAL)
    unrecorded = {}
    for who, n in ((e.get("who"), 1) for e in pilot.ledger.unrecorded):
        unrecorded[who] = unrecorded.get(who, 0) + n
    for m in getattr(pilot, "successor_msgs", []):
        if m.get("e") == "FINAL":
            n = sum(1 for s in m.get("signals", []) if s.get("why") == "ledger_lock_timeout")
            if n:
                unrecorded["successor"] = unrecorded.get("successor", 0) + n
    n_owner = ((summary.get("shutdown") or {}).get("unrecorded_signal_attempts")) or 0
    if n_owner:
        unrecorded["owner"] = n_owner
    summary["signals"] = T.signal_accounting(entries, unrecorded)
    summary["signals_basis"] = T.SIGNAL_ACCOUNTING_BASIS
    sd = summary.get("shutdown") or {}
    if sd:
        summary["owner_shutdown"] = {k: sd.get(k) for k in ("term_attempted", "term_delivery", "kill_attempted", "kill_delivered_by_ledger")}
    t0 = pilot.tl.get("t0")
    msgs = getattr(pilot, "successor_msgs", [])
    final = next((m for m in msgs if m.get("e") == "FINAL"), None)
    cls = (final or {}).get("classifications") or [m for m in msgs if m.get("e") == "CLASSIFY"]
    sig_all = (final or {}).get("signals", [])
    sig_s = [s for s in sig_all if s.get("sent")]
    # ONE attribution: the label is the durable record's (derived from the ledger's delivered signals by the
    # writer); the raw report and the committed view repeat it and the ledger attribution, and say whether
    # they agree. Nothing here recomputes a different story.
    rec_label = (rec or {}).get("terminated_by")
    exit_cause = None
    if inst.root is not None and t0 is not None:
        # the same stop evidence the Driver's finalizer uses (its actual stops plus the record), and the Successor reads
        # from the record (``killing_stop``, the flag), so the three views cannot differ for want of a communicated stop
        exit_cause = T.exit_attribution(entries, inst.root["pid"], inst.root["start"], pilot.attribution_stops(rec))
        exit_cause["killing_or_quarantining_stop_seen"] = any(x.get("immediate") or x.get("quarantine") for x in stops)
        exit_cause["note"] = "the ledger covers only the experiment's own signallers; 'self_exit' means no experiment signal was recorded"
    summary["exit"] = {k: (rec or {}).get(k) for k in ("exit_basis", "exit_event", "waitpid_evidence", "cleared_by", "terminated_by", "exit_cause", "exit_by")}
    summary["exit"]["attribution_consistent"] = None if exit_cause is None else T.label_matches_attribution(rec_label, exit_cause)
    summary["persist_errors"] = list(inst.persist_errors)
    summary["successor"] = {"started": bool(msgs), "classifications": [{k: c[k] for k in ("t_rel", "verdict", "identity_gone")} for c in cls],
                            "verified": (final or {}).get("verified"), "checks": (final or {}).get("checks"),
                            "exit_event": (final or {}).get("exit_event"), "self_exit": (final or {}).get("self_exit"),
                            "terminated_by": rec_label,  # the record is the single source (a backstop's label is its own)
                            "signals": [{"sig": s["sig"], "sent": s["sent"], "why": s["why"]} for s in sig_all],
                            "signals_by_successor": [{"sig": s["sig"]} for s in sig_s], "final_t_rel_s": (final or {}).get("t_rel"),
                            "exit_t_rel_s": (final or {}).get("exit_t_rel")}
    first = cls[0] if cls else None
    exited_by_itself = None  # unknown stays unknown
    if exit_cause is not None:
        gone = not T.root_is_live(inst.root["pid"], inst.root["start"])
        label_now = T.termination_label(exit_cause, gone)
        if exit_cause["cause"] == T.SIGNALLED:
            exited_by_itself = False
        elif label_now == "self_exit":
            exited_by_itself = True
    summary["orphan"] = {"alive_at_first_successor_observation": bool(first and first["verdict"] == L.ALIVE),
                         "first_observation_t_rel_s": first["t_rel"] if first else None,
                         "exited_by_itself": exited_by_itself, "exit_cause": exit_cause,
                         "window_s": None if t0 is None or "window_end_up" not in pilot.tl else round(pilot.tl["window_end_up"] - t0, 3),
                         "cpu_samples_diagnostic": summary.pop("orphan_samples", None),
                         "client_completion_note": "reader completion is a client-side fact, not server idleness"}
    rd = pilot.reader_result
    summary["reader"] = {k: (rd or {}).get(k) for k in ("status", "finish_reason", "prompt_tokens", "completion_tokens", "content_len",
                                                      "content_sha256", "elapsed", "timed_out", "error", "client_completed")}
    if rd is None:
        summary["reader"]["client_completed"] = False
    if t0 is not None:
        summary["timeline"] = {k[:-3] + "_rel_s": round(v - t0, 3) for k, v in pilot.tl.items() if k.endswith("_up")}
    summary["timeline_note"] = "uptime-clock seconds relative to the owner kill (t0); negative = before"
    try:
        summary["model_unchanged"] = H.stat_identity(os.stat(cfg.model)) == art["model_stat"]
    except OSError:
        summary["model_unchanged"] = False
    post = []
    for _ in range(int(o["post_sample_s"]) if through >= 3 and inst.root else 0):
        if pilot.interrupted.is_set():
            break
        post.append(probes.sample())
        pilot.interrupted.wait(1.0)
    with open(os.path.join(run_dir, "post-unload.jsonl"), "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in post))
    leftovers = H.clean_state(cfg, pilot.records)  # the last potentially blocking step (process enumeration, lsof)
    summary["leftovers"] = {"ok": leftovers["ok"], "detail": leftovers["detail"]}

    def verdict():
        """Interpretation, verdict rows, outcome and exit code, derived from the stops as they are NOW. Nothing in it
        blocks (no probe, no subprocess, no record or ledger lock), and it is the only place that decides them. The
        interrupt is reconciled first, after every blocking step above; ``seal_report`` runs it again if an interrupt is
        accepted after this check, so a late interrupt re-derives the whole verdict instead of being patched in."""
        seen = pilot.reconcile_interrupt()
        summary["seal"] = {"interrupt_seen": seen}
        pilot.ev("verdict", interrupt_seen=seen)
        if any(H.is_environmental(x) for x in stops):
            summary["interpretation"] = "INTERRUPTED_ENVIRONMENT"
        summary["rows"] = T.e3_rows(summary)
        state, pr = summary["record_state"], summary.get("pilot_result")
        if intent and not persisted:
            # a mandatory quarantine that is not on disk: whatever the record says, no successful outcome is reported and the
            # owner review is required (summary["owner_review_required"] is true and ``owner_review_persisted`` false)
            outcome = "QUARANTINE_NOT_PERSISTED"
        elif inst.root is None:
            outcome = {"INTENT": "UNRESOLVED_INTENT", "QUARANTINED": "QUARANTINED"}.get(state, "NOT_SPAWNED")
        elif state != "EXIT_VERIFIED":
            outcome = "QUARANTINED" if state == "QUARANTINED" else "UNRESOLVED"
        elif pr:
            outcome = pr
        elif stops:
            outcome = "STOPPED"
        elif summary.get("backstop_used"):
            outcome = "PILOT_COMPLETED_BACKSTOP"
        elif t0 is None:
            outcome = "STOPPED"
        else:
            outcome = "PILOT_COMPLETED"
        return done(outcome, 0 if outcome == "PILOT_COMPLETED" else 1)
    seal.rederive = verdict
    return verdict()


# --------------------------------------------------------------------------------------------
# the finalization boundary
#
# Interrupts (SIGINT, SIGTERM and SIGHUP alike) are accepted by a latch-only handler (``T.make_signal_handler``: plain
# assignments, no lock) that stays installed from the start of the run until the report is sealed; none of them can end the process with a half-written report, and a second
# signal does not skip anything. The flag is monotonic (set once, never cleared). The report is SEALED when its files
# are written and the flag is read again afterwards and the report already reflects it: the verdict is derived from the
# flag, the files are written atomically, and the flag is then re-read; if an interrupt was accepted after the verdict's
# check, the verdict is re-derived and the files are rewritten (at most one extra pass, as the flag cannot be cleared).
# So an interrupt accepted before the seal is in the report; one that arrives after the seal read cannot change a report
# that is already complete, and is outside it by definition (``seal`` states the interrupt state the report reflects).


class Seal:
    """Holds the verdict derivation of ``finish`` (``rederive``, registered only once all its inputs exist) and settles
    a report against the interrupt flag."""

    def __init__(self, interrupted, latch=None):
        self.interrupted, self.latch, self.rederive = interrupted, latch, None

    def accepted(self):
        """An interrupt has been accepted: the Event says so, or the signal handler has already run (the latch is read
        directly, so a propagation that has not happened yet cannot hide it)."""
        return bool(self.interrupted.is_set() or (self.latch is not None and self.latch.hit))

    def settle(self, summary, result):
        """Make ``summary`` and ``result`` reflect the interrupt state read now; returns the (possibly new) result."""
        reflects = (summary.get("seal") or {}).get("interrupt_seen")
        if self.accepted() and reflects is not True:
            result = self.rederive() if self.rederive is not None else self.fixup(summary, result)
        elif reflects is None:
            summary["seal"] = {"interrupt_seen": False}
            result["seal"] = summary["seal"]
        return result

    def fixup(self, summary, result):
        """No verdict was derived (an early phase outcome, or an exception before the verdict): the interrupt is still a stop,
        any verdict rows already present are re-derived so they are withheld, and a success outcome becomes INTERRUPTED."""
        add_interrupt_stop(summary["stops"])
        summary["seal"] = {"interrupt_seen": True}
        if any(H.is_environmental(x) for x in summary["stops"]):
            summary["interpretation"] = "INTERRUPTED_ENVIRONMENT"
        if "rows" in summary:
            summary["rows"] = T.e3_rows(summary)
        code = result.get("exit_code", 1)
        if code == 0:
            summary.update(outcome="INTERRUPTED", why="operator interrupt accepted before the report was sealed")
            code = 1
        return dict(summary, exit_code=code)

    def stable(self, summary):
        """The report reflects every interrupt accepted so far."""
        return (not self.accepted()) or (summary.get("seal") or {}).get("interrupt_seen") is True


def write_json_atomic(path, obj):
    """Whole-file replacement: a reader (or a crash) sees the previous complete file or the new complete file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_report(run_dir, summary, result):
    """The raw report, then the committed view (which carries the raw report's digest). Returns the raw digests."""
    write_json_atomic(os.path.join(run_dir, "summary.json"), summary)
    raw = raw_digests(run_dir)
    write_json_atomic(os.path.join(run_dir, "summary-committed-view.json"), T.committed_view(summary, raw))
    return raw


def write_seal_confirmation(run_dir, summary, result):
    """The LAST step of a successful seal: digests of the two report files as they are on disk, the outcome and the exit code
    the process will return. Absent on every failure path (it is removed before any rewrite), so its presence and match
    is what ``T.evidence_acceptance`` requires."""
    write_json_atomic(os.path.join(run_dir, T.SEAL_FILE), {
        "sealed": True, "run_id": summary.get("run_id"), "outcome": result.get("outcome"), "exit_code": result.get("exit_code"),
        "passes": (summary.get("seal") or {}).get("passes"), "interrupt_seen": (summary.get("seal") or {}).get("interrupt_seen"),
        "summary_sha256": E.sha256_file(os.path.join(run_dir, "summary.json")),
        "view_sha256": E.sha256_file(os.path.join(run_dir, "summary-committed-view.json"))})


def remove_seal_confirmation(run_dir):
    try:
        os.unlink(os.path.join(run_dir, T.SEAL_FILE))
    except FileNotFoundError:
        pass


def fail_closed(seal, summary, result, run_dir, exc):
    """Sealing failed (or finalization raised): whatever report files exist are PROVISIONAL (no seal confirmation, which is removed
    here, so nothing earlier can be mistaken for a sealed report). A pending interrupt is reconciled (S11), every verdict row is
    withheld, the exit code is 1, and a success outcome becomes FINALIZE_ERROR (a non-success outcome is kept, with
    ``finalize_error`` set: the outcome is not rewritten in that case). The files are rewritten best effort, still unconfirmed."""
    try:
        remove_seal_confirmation(run_dir)
    except OSError:
        pass
    if seal.accepted():
        add_interrupt_stop(summary["stops"])
        if any(H.is_environmental(x) for x in summary["stops"]):
            summary["interpretation"] = "INTERRUPTED_ENVIRONMENT"
    summary["seal"] = dict(summary.get("seal") or {}, interrupt_seen=bool(seal.accepted()), sealed=False)
    if "rows" in summary:
        T.withhold_rows(summary["rows"])
        result["rows"] = summary["rows"]
    result["stops"], result["seal"] = summary["stops"], summary["seal"]
    summary["finalize_error"] = result["finalize_error"] = type(exc).__name__
    if result.get("exit_code", 1) == 0:
        result["outcome_unsealed"] = result.get("outcome")
        summary.update(outcome="FINALIZE_ERROR", outcome_unsealed=result["outcome_unsealed"])
        result["outcome"] = "FINALIZE_ERROR"
    result["exit_code"] = 1
    try:
        result["raw_artifacts"] = write_report(run_dir, summary, result)
    except Exception:
        pass  # provisional either way: without the confirmation nothing here is accepted
    return result


def seal_report(seal, summary, result, run_dir, ev):
    """Settle against the interrupt flag, write, re-read the flag; repeat until the written report reflects it, then write the seal
    confirmation last. Never raises: any failure is ``fail_closed`` (no confirmation, no supporting rows, exit code 1)."""
    try:
        for passes in range(1, 5):
            remove_seal_confirmation(run_dir)  # a rewrite invalidates any earlier confirmation
            result = seal.settle(summary, result)
            summary["seal"]["passes"] = passes
            if ev is not None:
                ev("seal_pass", n=passes, interrupt_seen=summary["seal"]["interrupt_seen"])
            result["raw_artifacts"] = write_report(run_dir, summary, result)
            if seal.stable(summary):
                write_seal_confirmation(run_dir, summary, result)
                return result
        raise RuntimeError("the report did not settle against the interrupt state")
    except Exception as exc:
        return fail_closed(seal, summary, result, run_dir, exc)


def run_pilot(cfg, probes, through, attended, *, e3pins=None, bounds=None, **kw):
    o = default_opts(**kw)
    bounds = bounds or T.BOUNDS
    e3pins = e3pins if e3pins is not None else T.load_pins()
    ok, why, auth = T.check_authorization(cfg.root, cfg.protocol_doc, e3pins, o["impl"])
    if not ok:
        return {"outcome": "REFUSED", "why": why, "exit_code": 2}
    if not attended:
        return {"outcome": "REFUSED", "why": "--attended is required", "exit_code": 2}
    ok, why = T.pins_ready(e3pins)
    if not ok:
        return {"outcome": "REFUSED", "why": why, "exit_code": 2}
    problems = T.check_bounds(bounds, cfg.readiness_s)
    if problems:
        return {"outcome": "REFUSED", "why": "inconsistent bounds: " + "; ".join(problems), "exit_code": 2}
    lock = E.run_lock(cfg.root)
    try:
        lock.__enter__()
    except E.RunLockHeld as exc:
        return {"outcome": "REFUSED", "why": str(exc), "exit_code": 2}
    latch = T.InterruptLatch()
    interrupted = o["interrupted"] if o["interrupted"] is not None else T.InterruptEvent(latch)
    cancel = T.InterruptEvent(latch)
    seal = Seal(interrupted, latch)
    old, result, ev_f, ev, run_dir, stop_watcher = {}, None, None, None, None, None
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)
    summary = {"run_id": run_id, "through": through, "stops": [], "outcome": None}
    try:
        if o["install_signals"]:
            # the handler only assigns to the latch (no Event, lock, call, log or I/O: see T.InterruptLatch) and stays installed until
            # the report is sealed: an interrupt after the kill still completes the termination. ``interrupted`` and ``cancel`` read the
            # latch lock-free, and the watcher sets them (and an injected plain Event) outside the handler.
            handler = T.make_signal_handler(latch)
            for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                old[sg] = signal.signal(sg, handler)
            stop_watcher = T.start_latch_watcher(latch, (interrupted, cancel))
        run_dir = os.path.join(cfg.root, "runs", run_id)
        os.makedirs(run_dir, mode=0o700)
        ev_f = open(os.path.join(run_dir, "events.jsonl"), "a")

        def ev(name, **kw2):
            ev_f.write(json.dumps(dict(kw2, e=name, up=T.uptime()), default=str) + "\n")
            ev_f.flush()

        result = execute(cfg, probes, through, attended, auth, e3pins, bounds, summary, run_dir, ev, interrupted, cancel, o, seal)
    except BaseException as exc:
        summary.update(outcome="HARNESS_ERROR", why=type(exc).__name__)
        result = dict(summary, exit_code=1)
    finally:
        try:
            if run_dir is not None:
                result = seal_report(seal, summary, result, run_dir, ev if ev_f is not None else None)
        finally:  # the handlers go back, the event log closes and the lock is released only after the seal
            for sg, h in old.items():
                signal.signal(sg, h)
            if stop_watcher is not None:
                stop_watcher()
            if ev_f is not None:
                ev_f.close()
            lock.__exit__(None, None, None)
    return result


# --------------------------------------------------------------------------------------------
# recovery and CLI


def make_config(bench, **kw):
    base = dict(root=os.path.join(bench, "e3"), fixtures_dir=os.path.join(bench, "fixtures", "e3"), protocol_doc=T.PROTOCOL_DOC)
    base.update(kw)
    return H.Config(bench, **base)


def recover(cfg, run_id, kill=False, confirm=None):
    """Owner-directed recovery (E2-B rules, E3 kill step: no descendant is discovered through an unverified
    root pid) for an E3 record, plus removal of the run's key file. Used after a Driver failure; it takes
    the run lock, so it cannot race a live run."""
    records = T.LockedRecords(cfg.root)
    try:
        with E.run_lock(cfg.root):  # as E2-B's recover(): a live run holds the lock, so recovery cannot race it
            rep = T.recover_locked(records, run_id, E.HostProbes().boottime(), kill, confirm)
    except E.RunLockHeld as exc:
        rep = {"run_id": run_id, "actions": [], "verdict": "REFUSED_RUN_LOCK_HELD", "why": str(exc)}
    key = os.path.join(cfg.root, "runs", run_id, "scratch", "api-key")
    if rep.get("verdict") != "REFUSED_RUN_LOCK_HELD" and os.path.exists(key):
        try:
            os.unlink(key)
            rep["key_file_removed"] = True
        except OSError:
            rep["key_file_removed"] = False
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bench", default=E.DEFAULT_BENCH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="read-only: bounds, pins state, implementation hashes, authorization state")
    sub.add_parser("records", help="list execution records and their states")
    r = sub.add_parser("recover", help="classify (read-only) or, with --kill --confirm RUN_ID, kill recorded identities")
    r.add_argument("run_id")
    r.add_argument("--kill", action="store_true")
    r.add_argument("--confirm")
    ac = sub.add_parser("accept", help="read-only: are a finished run's report files acceptable evidence? needs the process exit status")
    ac.add_argument("run_id")
    ac.add_argument("--exit-status", type=int, default=None)
    s = sub.add_parser("scan-committed", help="fail if fixture strings appear in the given files")
    s.add_argument("paths", nargs="+")
    g = sub.add_parser("run", help="gate (1), controls (2) or the pilot (3); needs AUTHORIZATION-E3.json and --attended")
    g.add_argument("--through", type=int, default=3, choices=[1, 2, 3])
    g.add_argument("--attended", action="store_true")
    a = ap.parse_args(argv)
    cfg = make_config(a.bench)
    if a.cmd == "verify":
        pins = T.load_pins()
        ok, why, _ = T.check_authorization(cfg.root, cfg.protocol_doc, pins)
        print(json.dumps({"bounds_problems": T.check_bounds(), "worst_case_lifetime_s": T.worst_case_lifetime(),
                          "pins_ready": T.pins_ready(pins), "authorization": [ok, why],
                          "implementation": T.implementation_hashes(), "protocol_sha256": E.sha256_file(T.PROTOCOL_DOC)}, indent=1))
    elif a.cmd == "records":
        rec = T.LockedRecords(cfg.root)
        print(json.dumps({"unresolved": rec.unresolved(), "all": sorted(os.listdir(rec.dir))}, indent=1))
    elif a.cmd == "recover":
        rep = recover(cfg, a.run_id, a.kill, a.confirm)
        print(json.dumps(rep, indent=1, default=str))
        if rep.get("verdict") == "REFUSED_RUN_LOCK_HELD":
            return 2
        return 0 if rep.get("verdict") in (L.TERMINATED, "ALREADY_RESOLVED") else 1
    elif a.cmd == "accept":
        rep = T.evidence_acceptance(os.path.join(cfg.root, "runs", a.run_id), a.exit_status)
        print(json.dumps(rep, indent=1))
        return 0 if rep["supports_verdicts"] else 1
    elif a.cmd == "scan-committed":
        forbidden = []
        for d in (os.path.join(a.bench, "fixtures", "e2b"), cfg.fixtures_dir):
            for name in ("P1", "P2", "P3", "P4", "AUTH", "G"):
                try:
                    obj = json.load(open(os.path.join(d, name + ".json")))
                except (OSError, ValueError):
                    continue
                forbidden += [m["content"] for m in obj.get("messages", [])]
        hits = E.scan_files(a.paths, sorted(set(x for x in forbidden if x)))
        print(json.dumps({"files": len(a.paths), "hits": [(p, i) for p, i in hits]}))
        return 1 if hits else 0
    elif a.cmd == "run":
        res = run_pilot(cfg, E.HostProbes(), a.through, a.attended)
        print(json.dumps(T.committed_view(res, res.get("raw_artifacts")) if res.get("run_id") else res, indent=1, default=str))
        return res.get("exit_code", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
