#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

Slice 0B-2 E2-B evidence harness: Phase 1 load gate, Phase 2 containment controls, Phase 3 one
bounded server lifetime, Phase 4 shutdown and verification, plus owner-directed recovery.
Standard library only; loopback only; synthetic fixtures read from outside the repository.

Protocol: docs/evidence/v0-0b2-e2b-protocol.md (the authorization file binds to its hash).
Commands (``python3 -B e2b_harness.py --help``): host-probe, verify-fixtures, records, recover,
scan-committed, run. ``run`` refuses to start without the owner's AUTHORIZATION.json, without
``--attended``, and while any execution record is unresolved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib as L  # noqa: E402
import e2b_lib as E  # noqa: E402

LIM = E.LIMITS


class Config:
    def __init__(self, bench=E.DEFAULT_BENCH, pins=None, **override):
        self.pins = pins or E.load_pins()
        self.bench = bench
        self.root = os.path.join(bench, "e2b")
        self.binary = os.path.join(bench, "tools", "llama-b11440", "llama-b11440", "llama-server")
        self.model = os.path.join(bench, "models", self.pins["model"]["filename"])
        self.fixtures_dir = os.path.join(bench, "fixtures", "e2b")
        self.port = self.pins["port"]
        self.profile, self.base_profile = E.SANDBOX_NOFORK, E.SANDBOX
        self.version_string = self.pins["runtime"]["version_string"]
        self.python = sys.executable
        self.protocol_doc = E.PROTOCOL_DOC
        self.readiness_s = LIM["readiness_s"]
        self.control_runs, self.control_c3_runs = 5, 3  # protocol counts; tests may lower them
        self.log_runner = None  # injectable runner for the sandbox deny-line query
        for k, v in override.items():
            setattr(self, k, v)


class AnyEvent:
    """Read-only view that is set when any of the given events is set. In-flight waits and HTTP
    exchanges watch this, so an operator interrupt and a monitor trigger both end them promptly
    however the interrupt flag was raised."""

    def __init__(self, *events):
        self.events = events

    def is_set(self):
        return any(e.is_set() for e in self.events)

    def wait(self, timeout=None):
        end = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            if end is not None and time.monotonic() >= end:
                break
            time.sleep(0.02)
        return self.is_set()


class StopRun(Exception):
    def __init__(self, sid, why, quarantine=False, immediate=False):
        super().__init__(f"{sid}: {why}")
        self.sid, self.why, self.quarantine, self.immediate = sid, why, quarantine, immediate


# --------------------------------------------------------------------------------------------
# HTTP (raw socket, wall-clock deadline independent of socket timeouts, body cap, cancel flag)


def dechunk(b):
    out, i = b"", 0
    while True:
        j = b.find(b"\r\n", i)
        if j < 0:
            return out
        try:
            n = int(b[i:j].split(b";")[0], 16)
        except ValueError:
            return out
        if n == 0:
            return out
        out += b[j + 2: j + 2 + n]
        i = j + 2 + n + 2


def http_call(port, method, path, body=None, key=None, deadline=LIM["call_s"], cancel=None, cap=LIM["body_cap"]):
    t0 = time.monotonic()
    res = {"status": None, "body": b"", "elapsed": None, "timed_out": False, "overflow": False,
           "cancelled": False, "error": None}
    buf = b""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=min(deadline, 2.0))
    except OSError as e:
        return dict(res, error=type(e).__name__, elapsed=time.monotonic() - t0)
    try:
        s.settimeout(0.25)
        hdr = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", "Connection: close",
               "Content-Type: application/json", f"Content-Length: {len(body or b'')}"]
        if key:
            hdr.append(f"Authorization: Bearer {key}")
        s.sendall(("\r\n".join(hdr) + "\r\n\r\n").encode() + (body or b""))
        while True:
            if cancel is not None and cancel.is_set():
                res["cancelled"] = True
                break
            if time.monotonic() - t0 > deadline:
                res["timed_out"] = True
                break
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            except OSError as e:
                res["error"] = type(e).__name__
                break
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap + 8192:
                res["overflow"] = True
                break
    finally:
        s.close()
    res["elapsed"] = time.monotonic() - t0
    head, sep, rest = buf.partition(b"\r\n\r\n")
    if sep:
        try:
            res["status"] = int(head.split(b" ", 2)[1])
        except (IndexError, ValueError):
            pass
        if b"transfer-encoding: chunked" in head.lower():
            rest = dechunk(rest)
        res["body"] = rest
        res["overflow"] = res["overflow"] or len(rest) > cap
    return res


def jbody(r):
    try:
        return json.loads(r["body"].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def classify_sockets(names, port):
    """lsof -Fn names -> (listen_bad, egress). A listener must be exactly 127.0.0.1:port; every
    connection endpoint must be loopback."""
    bad, egress = [], []
    for n in names:
        local, _, remote = n.partition("->")
        lh = local.rsplit(":", 1)[0]
        if not remote:
            if local != f"127.0.0.1:{port}":
                bad.append("listen:" + local)
            continue
        rh = remote.rsplit(":", 1)[0]
        if lh not in ("127.0.0.1", "[::1]") or rh not in ("127.0.0.1", "[::1]"):
            egress.append("conn:" + n)
    return bad, egress


def lsof_names(pid):
    try:
        r = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-i", "-Fn"], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return None
    return [l[1:] for l in r.stdout.splitlines() if l.startswith("n")]


# --------------------------------------------------------------------------------------------
# instance ownership


class Instance:
    """One runtime process owned by this harness: intent -> spawn -> identity -> binding -> exit.

    The execution record is persisted BEFORE the spawn (INTENT) and again immediately after it
    (SPAWNED, with the kernel identity). SIGINT/SIGTERM/SIGHUP are blocked across that window so a
    catchable signal cannot interrupt it; SIGKILL cannot be blocked, which leaves an INTENT-only
    record that recovery treats as INDETERMINATE.

    Every descendant ever observed is remembered WITH its kernel identity (and persisted), because a
    root's children are re-parented the moment it dies and can no longer be found by parent pid.
    Nothing is ever signalled except a recorded root or a remembered descendant whose (pid, start)
    the kernel still confirms. After any unexpected failure ``contain`` kills by that same rule and
    records only what the exit-verification conjunction proves."""

    def __init__(self, cfg, records, run_id, run_dir, wrap=True, kill_fn=E.kill_identified, interrupted=None, cancel=None):
        self.cfg, self.records, self.run_id, self.run_dir = cfg, records, run_id, run_dir
        self.wrap, self.kill_fn = wrap, kill_fn
        self.interrupted = interrupted if interrupted is not None else threading.Event()
        self.cancel = cancel if cancel is not None else threading.Event()
        self.tag = secrets.token_hex(16)
        self.cache = os.path.join(run_dir, "cache")
        self.scratch = os.path.join(run_dir, "scratch")
        self.key_file = os.path.join(self.scratch, "api-key")
        self.key = secrets.token_hex(24)
        self.proc = self.rec = self.watch = None
        self.root = None
        self.bound = False
        self.bind_detail = {}
        self.known = {}  # (pid, start tuple) -> identity of every descendant ever observed
        self._known_lock = threading.Lock()
        self.persist_errors = []
        self.finished, self.result = False, None

    def env(self):
        keep = ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "__CF_USER_TEXT_ENCODING")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update(PATH="/usr/bin:/bin", LLAMA_CACHE=self.cache, HF_HUB_OFFLINE="1")
        env[E.TAG_ENV] = self.tag
        return env

    def argv(self):
        c = self.cfg
        target = [c.binary, "-m", c.model, "--host", "127.0.0.1", "--port", str(c.port), "-c", "2048", "-np", "1",
                  "-ngl", "all", "-t", "6", "-b", "512", "-ub", "128", "-fit", "off", "--perf", "--no-webui",
                  "--offline", "--api-key-file", self.key_file, "--no-cache-prompt", "--cache-ram", "0",
                  "--no-context-shift", "-to", "120", "--log-timestamps",
                  "--chat-template-kwargs", '{"enable_thinking":false}']
        full = ["/usr/bin/sandbox-exec", "-p", self.cfg.profile] + target if self.wrap else target
        return target, full

    # -- launch ------------------------------------------------------------------------------

    def _abort_requested(self, sigs):
        return self.interrupted.is_set() or self.cancel.is_set() or bool(signal.sigpending() & sigs)

    def launch(self, hashes):
        """Persist INTENT, spawn, persist SPAWNED. Any failure leaves either a resolved record (nothing
        was spawned, or the process was killed and verified gone) or an unresolved one; it raises
        StopRun and never leaves a live runtime without a kill path."""
        try:
            for d in (self.cache, self.scratch):
                os.makedirs(d, mode=0o700, exist_ok=True)
            fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, (self.key + "\n").encode())
            os.close(fd)
            target, full = self.argv()
            me = L.identity(os.getpid())
            self.rec = self.records.create({
                "v": 1, "run_id": self.run_id, "state": "INTENT", "tag": self.tag, "port": self.cfg.port,
                "argv_target": target, "argv_full": full, "argv_digest": E.sha256_bytes(E.canon(full)),
                "profile_sha256": E.sha256_bytes(self.cfg.profile.encode()), "binary_sha256": hashes.get("binary"),
                "model_sha256": hashes.get("model"), "boottime": E.HostProbes().boottime(),
                "harness": {"pid": os.getpid(), "start": me["start"] if me else None}, "created_utc": time.time(),
                "history": [{"state": "INTENT", "utc": time.time()}]})
            log = open(os.path.join(self.run_dir, "server.log"), "wb")
            sigs = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, sigs)
            try:
                # Last chance to refuse: with the catchable signals blocked, honour anything already
                # requested (flag set, or a signal pending in the kernel). Nothing exists yet.
                if self._abort_requested(sigs):
                    self._abandon("stop or interrupt requested before spawn")
                    raise StopRun("PRE_SPAWN_ABORT", "stop or interrupt requested before spawn")
                try:
                    # The blocked mask is inherited across exec; the runtime must start with it empty or
                    # it would never honour SIGTERM. The harness has no other signal-sensitive thread here.
                    self.proc = subprocess.Popen(full, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                                 env=self.env(), start_new_session=True,
                                                 preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, []))
                except OSError as exc:
                    self._spawn_failed(exc)
                    raise StopRun("SPAWN", f"spawn raised {type(exc).__name__}")
                ident = L.identity(self.proc.pid)
                if ident is None:
                    raise RuntimeError("kernel reported no identity for the new process")
                self.root = {"pid": self.proc.pid, "start": ident["start"], "pgid": ident["pgid"]}
                self.records.advance(self.rec, "SPAWNED", pid=self.proc.pid, start=ident["start"], pgid=ident["pgid"],
                                     sid=os.getsid(self.proc.pid), binding_verified=False, descendants=[])
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
                log.close()
            self.watch = L.ExitWatch(self.proc.pid)
        except StopRun:
            raise
        except BaseException as exc:
            what = type(exc).__name__
            if self.proc is not None:
                self.contain(f"launch bookkeeping failed after spawn: {what}")
            elif self.rec is not None:
                self._abandon(f"launch failed before spawn: {what}")
            raise StopRun("LAUNCH", f"launch failed: {what}")

    def _abandon(self, reason):
        """Resolve an INTENT record for which Popen never returned a process. The tag scan must agree
        (nothing carrying the tag exists); otherwise the record is quarantined. If the write fails the
        record simply stays unresolved."""
        try:
            if L.tag_scan(self.tag):
                self.records.advance(self.rec, "QUARANTINED", reason=f"{reason}; a tagged process exists")
            else:
                self.records.advance(self.rec, "EXIT_VERIFIED", exit_basis="launch_aborted_before_spawn", reason=reason,
                                     cleared_by="harness")
        except Exception as exc:
            self.persist_errors.append("abandon: " + type(exc).__name__)

    def _spawn_failed(self, exc):
        clean = not L.tag_scan(self.tag) and not L.listeners(self.cfg.port)["pids"]
        if clean:
            self.records.advance(self.rec, "EXIT_VERIFIED", exit_basis="spawn_raised_no_tagged_process",
                                 error=type(exc).__name__, cleared_by="harness")
        else:
            self.records.advance(self.rec, "QUARANTINED", reason="spawn raised and a tagged process or listener exists")

    def wait_ready(self, cancel, limit=LIM["readiness_s"]):
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit:
            if cancel.is_set():
                return "CANCELLED", None
            if self.proc.poll() is not None:
                return "EXITED", self.proc.returncode
            r = http_call(self.cfg.port, "GET", "/health", deadline=LIM["call_s"], cancel=cancel)
            if r["status"] == 200:
                return "READY", time.monotonic() - t0
            cancel.wait(0.5)
        return "TIMEOUT", None

    def bind(self):
        """Verify the sole listener is the recorded pid AND that it is exactly 127.0.0.1:port, snapshot
        descendants, persist BOUND. Called before any authenticated request is sent."""
        lst = L.listeners(self.cfg.port)
        pid_ok = lst["pids"] == [self.proc.pid] and not lst["timeout"]
        names = lsof_names(self.proc.pid)
        listens = [n for n in (names or []) if "->" not in n]
        addr_ok = names is not None and listens == [f"127.0.0.1:{self.cfg.port}"]
        verified = pid_ok and addr_ok
        self.bind_detail = {"pid_ok": pid_ok, "addr_ok": addr_ok, "listener_count": len(listens)}
        self._remember(L.descendants(self.proc.pid))
        self.records.advance(self.rec, "BOUND", binding_verified=verified, listener_pids_at_bind=lst["pids"],
                             listener_exact_loopback=addr_ok, descendants=self._descendant_records())
        self.bound = verified
        return verified

    # -- observation ---------------------------------------------------------------------------

    def _remember(self, found):
        new = False
        with self._known_lock:
            for i in found:
                key = (i["pid"], tuple(i["start"]))
                if key not in self.known:
                    self.known[key] = {"pid": i["pid"], "start": list(i["start"]), "ppid": i.get("ppid"), "pgid": i.get("pgid")}
                    new = True
        if new:
            try:
                self.records.annotate(self.rec, descendants=self._descendant_records())
            except Exception as exc:  # best effort: the in-memory knowledge is what the kill path uses
                self.persist_errors.append("descendants: " + type(exc).__name__)

    def _descendant_records(self):
        with self._known_lock:
            known = list(self.known.values())
        have = {(d["pid"], tuple(d["start"])) for d in known}
        return known + [d for d in (self.rec or {}).get("descendants", []) if (d["pid"], tuple(d["start"])) not in have]

    def _known_targets(self):
        return [{"pid": d["pid"], "start": d["start"], "role": "descendant"} for d in self._descendant_records()]

    def observe(self):
        """Topology, listener and egress observation. Never signals anything."""
        pid = self.root["pid"]
        d = L.descendants(pid)
        self._remember(d)
        group = [i for i in L.group_members(self.root["pgid"]) if i["pid"] != pid]
        tagged = [i for i in L.tag_scan(self.tag) if i["pid"] != pid]
        pol = E.tree_policy(self.root, d, group, tagged)
        names = lsof_names(pid)
        bad, egress = classify_sockets(names or [], self.cfg.port)
        if os.path.isdir(self.cache) and os.listdir(self.cache):
            bad.append("cache_nonempty")
        tree = [f"descendant:{x['pid']}" for x in d] + [f"stranger:{x['pid']}" for x in pol["strangers"]]
        # a bound runtime always holds its listener: an empty answer is not a healthy reading
        lsof_ok = names is not None and (bool(names) or not self.bound)
        return {"tree": tree, "listen_bad": bad, "egress": egress, "lsof_ok": lsof_ok, "policy": pol}

    def rss_mib(self):
        try:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(self.root["pid"])], capture_output=True, text=True,
                                 timeout=3).stdout.strip()
            return int(out) / 1024.0 if out else None
        except (subprocess.TimeoutExpired, ValueError):
            return None

    # -- ownership flags and termination ---------------------------------------------------------

    def mark_owner_review(self, reason):
        """Persist the owner-review requirement the moment a policy violation is detected. Never
        raises. If the write fails the flag still lives in the in-memory record (so every later write
        carries it and the exit can never be recorded as a plain EXIT_VERIFIED), and the failure is
        remembered for the summary."""
        if self.rec is None:
            return False
        try:
            self.records.annotate(self.rec, owner_review_required=True, owner_review_reason=reason)
            return True
        except Exception as exc:
            self.persist_errors.append("owner_review: " + type(exc).__name__)
            return False

    def emergency_kill(self):
        """Immediate SIGKILL by verified identity: the live tree is captured with identities FIRST (once
        the root dies its children are no longer reachable by parent pid), then the root, then every
        remembered descendant. An unidentified process is never signalled."""
        res = {}
        try:
            self._remember(L.descendants(self.root["pid"]))
        except Exception as exc:
            self.persist_errors.append("pre-kill snapshot: " + type(exc).__name__)
        res["root"] = self.kill_fn([{"pid": self.root["pid"], "start": self.root["start"]}])
        desc = self._known_targets()
        if desc:
            res["descendants"] = self.kill_fn(desc)
        return res

    def _wait(self, limit):
        try:
            self.proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            pass
        return self.proc.poll() is not None

    def shutdown(self, immediate=False, policy_quarantine=None):
        """TERM (unless immediate) then KILL, by verified identity; reap; verify by conjunction;
        persist EXIT_VERIFIED, or QUARANTINED when the exit is unverified or policy requires owner
        review (topology violation, non-loopback socket, unauthorized access). Strangers are
        reported and never signalled."""
        out = {"steps": [], "term_sent": False, "kill_sent": False, "errors": []}
        key = {"pid": self.root["pid"], "start": self.root["start"]}
        pre = None
        if self.proc.poll() is None:
            try:
                pre = self.observe()
            except Exception as exc:  # observation is best effort; termination must not depend on it
                out["errors"].append("pre-observation: " + type(exc).__name__)
        out["strangers_not_signalled"] = ((pre or {}).get("policy") or {}).get("strangers", [])
        if self.proc.poll() is None and not immediate:
            L.safe_kill(key["pid"], key["start"], signal.SIGTERM)
            out["term_sent"] = True
            self._wait(LIM["term_s"])
        if self.proc.poll() is None:
            self.kill_fn([key])
            out["kill_sent"] = True
            self._wait(LIM["kill_s"])
        # descendants captured with identity (at any earlier observation) die with the root
        desc = self._known_targets()
        if desc:
            self.kill_fn(desc)
        return self._finalize(out, policy_quarantine)

    def contain(self, reason):
        """Last resort after an unexpected failure. Kills by verified identity (an unreaped direct child
        whose identity could not be read is signalled through its own Popen handle: its pid cannot have
        been reused while it is unreaped), then verifies and records through the same conjunction as a
        normal shutdown. Never raises. If anything here fails the record simply stays unresolved."""
        out = {"contained_after": reason, "errors": [], "term_sent": False, "kill_sent": False}
        try:
            if self.proc is not None and self.proc.poll() is None:
                if self.root is not None:
                    self.kill_fn([{"pid": self.root["pid"], "start": self.root["start"]}])
                else:
                    self.proc.kill()
                out["kill_sent"] = True
                self._wait(LIM["kill_s"])
            desc = self._known_targets() if self.rec is not None else []
            if desc:
                self.kill_fn(desc)
        except BaseException as exc:
            out["errors"].append("kill: " + type(exc).__name__)
        try:
            return self._finalize(out, None)
        except BaseException as exc:
            out["errors"].append("finalize: " + type(exc).__name__)
            out["verified"] = False
            return out

    def safe_shutdown(self, immediate=False, policy_quarantine=None):
        try:
            return self.shutdown(immediate, policy_quarantine)
        except BaseException as exc:
            info = self.contain(f"shutdown raised {type(exc).__name__}")
            info["shutdown_error"] = type(exc).__name__
            info["verified"] = bool(info.get("verified"))
            return info

    def _finalize(self, out, policy_quarantine):
        """Exit verification by conjunction, then the single record write. EXIT_VERIFIED only when every
        fact holds AND no owner review is pending; the owner-review flag is read from the record itself
        so a violation detected earlier (even if its write failed) can never be dropped."""
        reaped = self.proc.poll() is not None
        out["reaped"], out["returncode"] = reaped, self.proc.returncode
        root_pid = self.root["pid"] if self.root else self.proc.pid
        root_start = self.root["start"] if self.root else None
        pgid = self.root["pgid"] if self.root else self.proc.pid  # start_new_session: pgid == pid
        t0, checks = time.monotonic(), {}
        while True:
            ident = L.identity(root_pid)
            recorded = {(d["pid"], tuple(d["start"])) for d in self._descendant_records()}
            live_desc = [p for p, st in recorded if (lambda i: i and tuple(i["start"]) == st and i["status"] != "zombie")(L.identity(p))]
            group = [i for i in L.group_members(pgid) if i["pid"] != root_pid]
            lst = L.listeners(self.cfg.port)
            gone = (not L.same_identity(root_pid, root_start, ident) or ident["status"] == "zombie") if root_start else reaped
            checks = {"reaped": reaped, "identity_gone": gone,
                      "recorded_descendants_dead": not live_desc, "group_clear": not group,
                      "tag_scan_clear": not L.tag_scan(self.tag),
                      "port_free": not lst["timeout"] and not lst["pids"]}
            if all(checks.values()) or time.monotonic() - t0 > LIM["verify_s"]:
                break
            time.sleep(0.2)
        out["checks"] = checks
        try:
            verdict = L.classify(self.rec)[0] if self.rec.get("binding_verified") else None
        except Exception as exc:
            verdict = None
            out["errors"].append("classify: " + type(exc).__name__)
        out["e1_classify"] = verdict
        verified = all(checks.values())
        policy = policy_quarantine or ("owner review flagged during the run" if self.rec.get("owner_review_required") else None)
        try:
            if verified and policy:
                self.records.advance(self.rec, "QUARANTINED", reason=policy, owner_review_required=True,
                                     exit_verified_facts=checks)
                out["policy_quarantine"] = policy
            elif verified:
                self.records.advance(self.rec, "EXIT_VERIFIED", exit_basis="owner_waitpid_and_conjunction",
                                     exit_code=self.proc.returncode, cleared_by="harness", checks=checks)
            else:
                # a requested policy quarantine must survive an unverified exit as well
                self.records.advance(self.rec, "QUARANTINED", reason=policy or "exit not verified", checks=checks,
                                     owner_review_required=bool(policy))
            out["record_written"] = True
            out["verified"] = verified
        except Exception as exc:
            out["errors"].append("record: " + type(exc).__name__)
            out["record_written"] = False
            out["verified"] = False  # the facts may hold, but ownership stays unresolved on disk
        if self.watch:
            self.watch.close()
        self.finished, self.result = True, out
        return out

    def cleanup_secrets(self):
        try:
            os.unlink(self.key_file)
        except OSError:
            pass


# --------------------------------------------------------------------------------------------
# monitor


class Monitor(threading.Thread):
    """1 Hz host sampling plus a 5 s slow tick (thermal, disk, attendance, topology). It runs from
    BEFORE the spawn, so swap, pressure and power are watched through the whole model load. A reading
    that is missing is never treated as healthy: the evaluator counts consecutive misses (S13).

    On a quarantining trigger the owner-review flag is persisted first; on an immediate trigger the
    runtime is then killed by verified identity (tree captured before the root dies)."""

    def __init__(self, probes, evaluator, inst, series_path, cancel, hid_ceiling=None, interval=1.0, slow_every=5):
        super().__init__(daemon=True)
        self.probes, self.ev, self.inst, self.cancel = probes, evaluator, inst, cancel
        self.series, self.hid_ceiling, self.interval, self.slow_every = open(series_path, "a"), hid_ceiling, interval, slow_every
        self.triggers, self.halt, self.t_spawn = [], threading.Event(), None
        self.advisory_sent, self.tree_snapshot = False, None
        self.ready, self.first_sample_ok = threading.Event(), False  # set once the first tick has been evaluated

    def mark_spawn(self):
        self.t_spawn = E.uptime_and_wall()[0]

    def _slow(self, s, live):
        pr = self.probes
        for name, fn in (("thermal_warn", pr.thermal_warn), ("disk_gib", pr.disk_gib), ("hid_idle_s", pr.hid_idle_s)):
            try:
                s[name] = fn()
            except Exception as exc:
                s[name + "_error"] = repr(exc)
        s["hid_ceiling_s"] = self.hid_ceiling
        if s.get("hid_idle_s") and s["hid_idle_s"] > LIM["hid_idle_advisory_s"] and not self.advisory_sent:
            self.advisory_sent = True
            print("ATTENDANCE: no operator input for > 300 s; touch the trackpad (no assertion is used)", file=sys.stderr)
        if live:
            s["expect_topology"] = True
            try:
                o = self.inst.observe()
                s.update(tree=o["tree"], listen_bad=o["listen_bad"], egress=o["egress"], observed=o["lsof_ok"])
                self.tree_snapshot = o["policy"]
            except Exception as exc:
                s["observed"], s["observe_error"] = False, repr(exc)

    def _act(self, t):
        self.triggers.append(t)
        inst = self.inst
        if t["quarantine"] and inst is not None:
            inst.mark_owner_review(f"{t['id']}: {t['why']}")  # durable before anything slower happens
        if t["immediate"] and inst is not None and inst.root is not None:
            try:
                inst.emergency_kill()
            except Exception as exc:
                t["kill_error"] = type(exc).__name__
        self.cancel.set()

    def run(self):
        """A monitor that stops working must not leave the run unwatched: any failure becomes an S13
        trigger and cancels the run, and the first-sample gate is released (still not 'ok')."""
        try:
            self._loop()
        except BaseException as exc:
            self.triggers.append({"id": "S13", "why": f"monitor failed: {type(exc).__name__}", "immediate": False, "quarantine": False})
            self.cancel.set()
        finally:
            try:
                self.series.close()
            except Exception:
                pass
            self.ready.set()

    def _loop(self):
        k, nxt = 0, time.monotonic()
        while not self.halt.is_set():
            slow = k % self.slow_every == 0
            try:
                s = self.probes.sample()
            except Exception as exc:  # a probe failure is itself recorded, never silently skipped
                s = {"wall": time.time(), "up": time.clock_gettime(time.CLOCK_UPTIME_RAW), "probe_error": repr(exc)}
            s["slow"] = slow
            if self.t_spawn is not None:
                s["life"] = s["up"] - self.t_spawn
            inst = self.inst
            live = inst is not None and inst.root is not None and inst.proc is not None and inst.proc.poll() is None
            if live:
                s["expect_rss"], s["rss"] = True, inst.rss_mib()
            if slow:
                self._slow(s, live)
            for t in self.ev.feed(s):
                self._act(t)
            self.series.write(json.dumps(s, default=str) + "\n")
            self.series.flush()
            if not self.ready.is_set():
                self.first_sample_ok = all(s.get(name) is not None for name in E.FAST_REQUIRED)
                self.ready.set()
            k += 1
            nxt += self.interval
            self.halt.wait(max(0.0, nxt - time.monotonic()))


# --------------------------------------------------------------------------------------------
# Phase 1


def stat_identity(st):
    """What a replacement of the file would have to forge: size, mtime, inode, ctime (not settable by a
    user), device."""
    return [st.st_size, st.st_mtime_ns, st.st_ino, st.st_ctime_ns, st.st_dev]


def artifacts_check(cfg):
    pins = cfg.pins
    try:
        st = os.stat(cfg.model)
        size_ok = st.st_size == pins["model"]["bytes"]
        model_hash = E.sha256_file(cfg.model)
        bin_hash = E.sha256_file(cfg.binary)
        tree = E.verify_tree(os.path.dirname(cfg.binary), pins["runtime"].get("tree"))
        model_ok, bin_ok = model_hash == pins["model"]["sha256"], bin_hash == pins["runtime"]["binary_sha256"]
        detail = [f"model size {'ok' if size_ok else 'MISMATCH'}", f"model sha {'ok' if model_ok else 'MISMATCH'}",
                  f"binary sha {'ok' if bin_ok else 'MISMATCH'}",
                  f"runtime tree {'ok' if tree['ok'] else 'MISMATCH (' + str(len(tree['problems'])) + ' problem(s))'}"]
        return {"ok": size_ok and model_ok and bin_ok and tree["ok"], "detail": "; ".join(detail),
                "model_sha256": model_hash, "binary_sha256": bin_hash, "model_stat": stat_identity(st),
                "runtime_tree": {"ok": tree["ok"], "files": tree.get("files"), "links": tree.get("links"),
                                 "problems": tree["problems"]}}
    except OSError as exc:
        return {"ok": False, "detail": f"unreadable: {type(exc).__name__}"}


def prespawn_check(cfg, art):
    """Immediately before the spawn: the runtime tree (small) is re-hashed and the model must still be
    the very file Phase 1 hashed (size, mtime, inode, ctime, device). Closes the avoidable replacement
    window; the interval between this check and the runtime opening the file remains (documented)."""
    try:
        st = os.stat(cfg.model)
        tree = E.verify_tree(os.path.dirname(cfg.binary), cfg.pins["runtime"].get("tree"))
        model_same = stat_identity(st) == art.get("model_stat")
        return {"ok": model_same and tree["ok"], "model_same_file": model_same, "runtime_tree_ok": tree["ok"],
                "problems": tree["problems"]}
    except OSError as exc:
        return {"ok": False, "detail": f"unreadable: {type(exc).__name__}"}


def swap_baseline(probes, n, interval, abort):
    """The swap level S3 is measured against: the median of ``n`` readings taken just before the spawn.
    Fails closed if a reading is unavailable or the level was not stable (spread above the G3 bound)."""
    vals = []
    for _ in range(n):
        if abort.is_set():
            return {"ok": False, "why": "interrupted", "samples": vals}
        try:
            vals.append(probes.swap_mib())
        except Exception:
            vals.append(None)
        abort.wait(interval)
    if None in vals:
        return {"ok": False, "why": "swap reading unavailable", "samples": vals}
    spread = max(vals) - min(vals)
    if spread > LIM["swap_gate_mib"]:
        return {"ok": False, "why": f"swap not stable before spawn (spread {spread:.1f} MiB)", "samples": vals}
    return {"ok": True, "median_mib": sorted(vals)[len(vals) // 2], "spread_mib": spread, "samples": vals}


def clean_state(cfg, records):
    leftovers = []
    needle = (E.TAG_ENV + "=").encode()
    for pid in L.list_pids():
        a = L.procargs(pid)
        if a and needle in a and pid != os.getpid():
            leftovers.append(pid)
    unresolved = records.unresolved()
    port = L.listeners(cfg.port)
    cache_ok = True
    detail = f"tagged_processes={len(leftovers)} port_listeners={len(port['pids'])} unresolved_records={len(unresolved)}"
    ok = not leftovers and not port["pids"] and not port["timeout"] and not unresolved and cache_ok
    return {"ok": ok, "detail": detail, "unresolved": unresolved}


def collect_window(probes, n, interval=1.0, top_cmd=None, sleep=time.sleep, abort=None):
    top = subprocess.Popen(top_cmd or ["top", "-l", str(n + 1), "-s", "1", "-n", "0"], stdout=subprocess.PIPE, text=True)
    samples, t0 = [], time.monotonic()
    for i in range(n):
        if abort is not None and abort.is_set():
            top.kill()  # our own direct child
            top.communicate()
            return samples, None
        sleep(max(0.0, t0 + i * interval - time.monotonic()))
        samples.append(probes.sample())
    try:
        out, _ = top.communicate(timeout=interval * 3 + 20)
    except subprocess.TimeoutExpired:
        top.kill()
        out, _ = top.communicate()
    return samples, E.cpu_window(out, n)


def phase1(cfg, probes, records, attended, n=LIM["gate_samples"], interval=1.0, top_cmd=None, abort=None):
    art = artifacts_check(cfg)  # before the window so its I/O cannot pollute the window
    samples, cpu = collect_window(probes, n, interval, top_cmd, abort=abort)
    ctx = {"thermal_warning": probes.thermal_warn(), "competing": probes.competing(), "disk_gib": probes.disk_gib(),
           "attendance": probes.attendance(), "attended_flag": attended, "artifacts": art,
           "clean_state": clean_state(cfg, records)}
    gate = E.evaluate_gate(samples, cpu, ctx, n=n)
    return {"gate": gate, "passed": E.gate_passed(gate), "samples": samples, "cpu_idle": cpu, "ctx": ctx,
            "ended_up": time.clock_gettime(time.CLOCK_UPTIME_RAW), "interrupted": bool(abort is not None and abort.is_set())}


# --------------------------------------------------------------------------------------------
# Phase 2

FORK_CODE = ("import os,sys\ntry:\n    pid=os.fork()\nexcept OSError as e:\n    sys.exit(10+(e.errno or 0))\n"
             "if pid==0:\n    os._exit(0)\nos.waitpid(pid,0)\n")
CONNECT_CODE = ("import socket,sys\ns=socket.socket()\ns.settimeout(2)\ntry:\n    s.connect((sys.argv[1],int(sys.argv[2])))\n"
                "except PermissionError:\n    sys.exit(21)\nexcept ConnectionRefusedError:\n    sys.exit(22)\nexcept OSError:\n    sys.exit(23)\nsys.exit(0)\n")
UDP_CODE = ("import socket,sys\ns=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\ntry:\n    s.connect((sys.argv[1],int(sys.argv[2])))\n"
            "except PermissionError:\n    sys.exit(21)\nexcept OSError as e:\n    sys.exit(30+(e.errno or 0)%30)\nsys.exit(0)\n")
NONLOCAL_UDP = "192.0.2.1"  # RFC 5737 TEST-NET-1; UDP connect() sends nothing
METAL = __import__("re").compile(r"(?i)\b(metal|mtl\d*)\b")


def child(cmd, env, timeout=10.0, abort=None):
    p = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.monotonic()
    while True:
        try:
            out, _ = p.communicate(timeout=0.25)
            return p.returncode, out
        except subprocess.TimeoutExpired:
            if time.monotonic() - t0 > timeout or (abort is not None and abort.is_set()):
                p.kill()  # our own direct child
                out, _ = p.communicate()
                return None, out


def local_ipv4():
    try:
        text = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "inet" and not parts[1].startswith(("127.", "169.254.")):
            return parts[1]
    return None


def controls(cfg, runs=5, c3_runs=3, budget=80.0, abort=None):
    t0, env = time.monotonic(), {"PATH": "/usr/bin:/bin"}
    res, nofork, base = {}, ["/usr/bin/sandbox-exec", "-p", cfg.profile], ["/usr/bin/sandbox-exec", "-p", cfg.base_profile]
    py = [cfg.python, "-I", "-c"]

    def many(cmd, k, want, parse=None):
        got = []
        for _ in range(k):
            if abort is not None and abort.is_set():
                got.append("CANCELLED")
                break
            if time.monotonic() - t0 > budget:
                got.append("BUDGET")
                break
            rc, out = child(cmd, env, abort=abort)
            got.append(rc if parse is None else parse(rc, out))
        return {"results": got, "ok": len(got) == k and all(g == want for g in got)}

    res["C1_fork_denied_under_profile"] = many(nofork + py + [FORK_CODE], runs, 11)  # 10 + EPERM
    res["C1_fork_allowed_without_deny"] = many(base + py + [FORK_CODE], runs, 0)
    # C2. Scoped to what can be established without sending a packet: a UDP connect() performs only
    # a route lookup, so its sandbox verdict on a documentation-range address (RFC 5737) is a
    # zero-transmission test of the outbound rule. A TCP connect to this host's own interface
    # address is NOT a valid denial test: the recorded profile's "localhost" allowance covers the
    # host's own addresses (observed 2026-10-17: refused, not denied), so it is recorded only.
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(16)
    lport = ls.getsockname()[1]
    res["C2a_udp_connect_nonlocal_denied_under_profile"] = many(nofork + py + [UDP_CODE, NONLOCAL_UDP, "9"], runs, 21)
    res["C2b_udp_connect_nonlocal_allowed_without_profile"] = many(py + [UDP_CODE, NONLOCAL_UDP, "9"], runs, 0)
    res["C2c_loopback_tcp_allowed_under_profile"] = many(nofork + py + [CONNECT_CODE, "127.0.0.1", str(lport)], runs, 0)
    ip = local_ipv4()
    if ip is not None:
        probe = socket.socket()
        probe.bind((ip, 0))
        closed_port = probe.getsockname()[1]
        probe.close()
        rc, _ = child(nofork + py + [CONNECT_CODE, ip, str(closed_port)], env, abort=abort)
        res["C2d_local_interface_tcp_observation"] = {"result": rc, "informational": True,
                                                    "meaning": "21 denied, 22 refused (profile allows own addresses), other"}
    ls.close()
    res["C2_scope"] = ("IPv4 UDP connect() from a sandboxed probe to a non-local documentation-range address, "
                       "no packet transmitted; not external TCP egress, DNS, IPv6, nor llama-server itself")

    def version_ok(rc, out):
        return rc == 0 and cfg.version_string in out.decode(errors="replace")

    def metal_ok(rc, out):
        return rc == 0 and bool(METAL.search(out.decode(errors="replace")))

    for tag, wrap in (("unconfined", []), ("under_profile", nofork)):
        res[f"C3a_version_{tag}"] = many(wrap + [cfg.binary, "--version"], c3_runs, True, version_ok)
        res[f"C3b_metal_devices_{tag}"] = many(wrap + [cfg.binary, "--list-devices"], c3_runs, True, metal_ok)
    res["elapsed_s"] = time.monotonic() - t0
    res["budget_exceeded"] = res["elapsed_s"] > budget
    res["cancelled"] = bool(abort is not None and abort.is_set())
    checks = [v["ok"] for k, v in res.items() if isinstance(v, dict) and "ok" in v]
    res["passed"] = bool(checks) and all(checks) and not res["budget_exceeded"] and not res["cancelled"]
    return res


# --------------------------------------------------------------------------------------------
# Phase 3 helpers

TRIALS = [("P1", LIM["short_s"])] * 3 + [("P2", LIM["p2_s"])] * 2 + [("P3", LIM["short_s"]), ("P4", LIM["short_s"])]
MSGSET = {"P1": "APPLY_P1", "P4": "APPLY_P1", "P2": "APPLY_P2", "P3": "APPLY_P2"}


def trial_facts(fid, body, r, label):
    facts = {"id": fid, "http": r["status"], "elapsed": r["elapsed"], "timed_out": r["timed_out"], "overflow": r["overflow"]}
    if r["status"] != 200:
        return dict(facts, status="FAIL_RUNTIME")
    if body.get("stream"):
        content, finish, usage = E.parse_stream(r["body"])
        timings = None
    else:
        j = jbody(r) or {}
        ch = (j.get("choices") or [{}])[0]
        content, finish, usage = (ch.get("message") or {}).get("content") or "", ch.get("finish_reason"), j.get("usage")
        timings = j.get("timings")
    facts.update(finish_reason=finish, prompt_tokens=(usage or {}).get("prompt_tokens"),
                 completion_tokens=(usage or {}).get("completion_tokens"), content_len=len(content),
                 content_sha256=E.sha256_bytes(content.encode()), label_present=label in content,
                 cache_n=(timings or {}).get("cache_n"))
    facts["status"] = "PASS" if finish is not None and usage else "FAIL_RUNTIME"
    return facts


def sandbox_denials(cfg, pid, since_epoch):
    """Sandbox deny lines for the runtime pid: operation -> count (no targets, no paths)."""
    iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since_epoch))
    cmd = ["/usr/bin/log", "show", "--start", iso, "--style", "compact", "--predicate",
           f'sender == "Sandbox" AND eventMessage CONTAINS "({pid})"']
    try:
        text = (cfg.log_runner or (lambda c: subprocess.run(c, capture_output=True, text=True, timeout=45).stdout))(cmd)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False}
    ops = {}
    for m in __import__("re").finditer(rf"\({pid}\) deny\(\d+\) (\S+)", text):
        ops[m.group(1)] = ops.get(m.group(1), 0) + 1
    return {"available": True, "ops": ops}


def attribute(failed, denials):
    if not failed:
        return "NONE"
    if denials.get("available") and any(o in ("process-fork", "network-outbound") for o in denials.get("ops", {})):
        return "FAIL_SANDBOX_CANDIDATE"  # final label also needs the passing Phase 2 controls
    return "INCONCLUSIVE_ATTRIBUTION"


def run_phase3(cfg, probes, bodies, meta, inst, mon, cancel, ev, interrupted, out):
    """Everything between a successful spawn and shutdown. Raises StopRun on any stop condition;
    ``out`` is owned by the caller so partial results survive a stop."""
    port, key = cfg.port, inst.key
    out.update(trials=[], auth=[])

    def guard():
        if interrupted.is_set():
            raise StopRun("S11", "operator interrupt")
        if not mon.is_alive() and not mon.halt.is_set():
            raise StopRun("S13", "monitor thread is not running")
        if cancel.is_set():
            t = mon.triggers[-1] if mon.triggers else {"id": "S?", "why": "cancelled", "quarantine": False}
            raise StopRun(t["id"], t["why"], t.get("quarantine", False))

    state, val = inst.wait_ready(cancel, cfg.readiness_s)
    out["readiness"] = {"state": state, "value": val}
    guard()
    if state != "READY":
        raise StopRun("READINESS", f"{state}")
    # Binding (sole listener AND exactly 127.0.0.1:port) is verified before ANY authenticated request.
    out["binding_verified"] = inst.bind()
    out["bind_detail"] = dict(inst.bind_detail)
    if not out["binding_verified"]:
        if inst.bind_detail.get("pid_ok") and not inst.bind_detail.get("addr_ok"):
            raise StopRun("S9", f"listener is not exactly 127.0.0.1:{port}", immediate=True)
        raise StopRun("BINDING", "sole-listener binding not verified")
    s0 = time.monotonic()

    def call(method, path, body, cred):
        guard()
        k = key if cred == "correct" else ("wrong-" + key[::-1] if cred == "wrong" else None)
        r = http_call(port, method, path, body, k, LIM["call_s"], cancel)
        if time.monotonic() - s0 > LIM["stage_s"]:
            raise StopRun("S11", "stage-check budget exceeded")
        return r

    apply_body = {k: E.canon({"messages": bodies[v]["messages"]}) for k, v in (("APPLY_P1", "P1"), ("APPLY_P2", "P2"))}
    tok_body = E.canon({"content": "x"})
    probe_bodies = {"/tokenize": tok_body, "/apply-template": apply_body["APPLY_P1"]}
    chat = "/v1/chat/completions"

    def auth(method, path, klass, body, creds):
        for cred in creds:
            r = call(method, path, body, cred)
            o = E.auth_outcome(klass, cred, r["status"])
            o.update(path=path, cred=cred, status=r["status"], class_=klass)
            out["auth"].append(o)
            ev("auth", **{k: o[k] for k in ("path", "cred", "status", "outcome", "s10")})
            if o["s10"]:
                raise StopRun("S10", f"unauthorized success on {path}", True)
            if o["stop"]:
                raise StopRun("AUTH", f"{o['outcome']} on {path}")
        return r

    for method, path, klass in E.AUTH_TARGETS:
        if path != chat:
            r = auth(method, path, klass, probe_bodies.get(path), ("none", "wrong", "correct"))
            if path in ("/props", "/v1/models") and r["status"] == 200:
                out[path] = E.sha256_bytes(r["body"])
                out.setdefault("reported", {})[path] = (jbody(r) or {})
    # template and token accounting
    tt = {}
    for name, ab in apply_body.items():
        r = call("POST", "/apply-template", ab, "correct")
        rendered = (jbody(r) or {}).get("prompt", "")
        fid = "P1" if name == "APPLY_P1" else "P2"
        chk = E.check_template(rendered, bodies[fid]["messages"])
        nt = call("POST", "/tokenize", E.canon({"content": rendered, "add_special": False, "parse_special": True}), "correct")
        nb = call("POST", "/tokenize", E.canon({"content": rendered, "add_special": True, "parse_special": True}), "correct")
        tt[name] = {"prompt_sha256": E.sha256_bytes(rendered.encode()), "prompt_len": len(rendered), "check": chk,
                    "n_t": len((jbody(nt) or {}).get("tokens", [])) or None, "n_t_bos": len((jbody(nb) or {}).get("tokens", [])) or None}
        if not chk["mandatory_ok"] or not chk["empty_think_block"]:
            out["tt"] = tt
            raise StopRun("TEMPLATE_CHECK_FAILED", "rendered prompt failed the structural check; no generation attempted")
    out["tt"] = tt
    # chat authentication probes (must be rejected before any generation)
    probe_chat = E.canon(bodies["AUTH"])
    r = auth("POST", chat, "must", probe_chat, ("none", "wrong"))
    out["stage_seconds"] = time.monotonic() - s0
    # trials
    for idx, (fid, limit) in enumerate(TRIALS):
        guard()
        body = bodies[fid]
        stop_poll, polls = threading.Event(), []
        poller = None
        if fid == "P2":
            def poll():
                while not stop_poll.is_set():
                    for path, k in (("/health", None), ("/slots", key)):
                        pr = http_call(port, "GET", path, None, k, LIM["call_s"])
                        sl = jbody(pr) if path == "/slots" else None
                        polls.append({"path": path, "status": pr["status"], "elapsed": pr["elapsed"],
                                      "processing": any(s.get("is_processing") for s in sl) if isinstance(sl, list) else None})
                    stop_poll.wait(0.5)
            poller = threading.Thread(target=poll, daemon=True)
            poller.start()
        r = http_call(port, "POST", chat, E.canon(body), key, limit, cancel)
        stop_poll.set()
        if poller:
            poller.join(5)
        if r["cancelled"]:
            guard()  # an interrupted request is not a trial result
        facts = trial_facts(fid, body, r, meta["label"])
        nt = tt[MSGSET[fid]]
        facts["accounting"] = E.classify_accounting(facts.get("prompt_tokens"), nt["n_t"], nt["n_t_bos"])
        sl = jbody(http_call(port, "GET", "/slots", None, key, LIM["call_s"]))
        facts["slot_idle_after"] = (not any(s.get("is_processing") for s in sl)) if isinstance(sl, list) else None
        facts["polls"] = polls
        out["trials"].append(facts)
        ev("trial", **{k: v for k, v in facts.items() if k != "polls"})
        if r["overflow"]:
            raise StopRun("S11", "response body cap exceeded")
        if r["timed_out"]:
            raise StopRun("S11", f"trial {fid} exceeded {limit:.0f} s")
        if inst.proc.poll() is not None:
            raise StopRun("RUNTIME_EXIT", f"runtime exited rc={inst.proc.returncode} during trials")
    return out


# --------------------------------------------------------------------------------------------
# run

EXPECTED_TRIALS = len(TRIALS)
ENV_STOPS = {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S12", "S13"}
RAW_ARTIFACTS = ("events.jsonl", "gate-window.jsonl", "gate-context.json", "series.jsonl", "post-unload.jsonl",
                 "server.log", "summary.json")


def is_environmental(stop):
    """Stops that say something about the host, not about the runtime under test."""
    return stop["id"] in ENV_STOPS or (stop["id"] == "S11" and stop["why"].startswith(("operator interrupt", "disk below")))


def stop_entry(stop):
    return {"id": stop.sid, "why": stop.why, "quarantine": stop.quarantine, "immediate": stop.immediate}


def version_tokens(version_string):
    m, c = re.search(r"build (\d+)", version_string or ""), re.search(r"commit ([0-9a-f]{7,})", version_string or "")
    return [g for g in (m and m.group(1), c and c.group(1)) if g]


def tool_identities(cfg):
    """Hashes that bind a result to the exact protocol, harness and pins that produced it."""
    def h(path):
        try:
            return E.sha256_file(path)
        except OSError:
            return None
    return {"protocol_sha256": h(cfg.protocol_doc), "e2b_harness_py": h(os.path.abspath(__file__)),
            "e2b_lib_py": h(os.path.abspath(E.__file__)), "e1_lib_py": h(os.path.abspath(L.__file__)),
            "e2b_pins_json": h(E.PINS_FILE), "pins_in_use_canonical": E.sha256_bytes(E.canon(cfg.pins))}


def raw_artifact_digests(run_dir):
    out = {}
    for name in RAW_ARTIFACTS:
        path = os.path.join(run_dir, name)
        if os.path.isfile(path):
            out[name] = {"bytes": os.path.getsize(path), "sha256": E.sha256_file(path)}
    return out


def committed_why(stop):
    """Stop reasons for S8/S9 can carry socket endpoints; keep only the class."""
    return stop["why"].split(":")[0] if stop["id"] in ("S8", "S9") else stop["why"]


def committed_view(summary, raw_artifacts=None):
    """Counts, booleans, hashes and numbers only: no prompts, outputs, logs, paths or addresses."""
    p3 = summary.get("phase3") or {}
    trials = [{k: v for k, v in t.items() if k not in ("polls",)} for t in p3.get("trials", [])]
    gate = summary.get("gate") or {}
    controls = summary.get("controls") or {}
    return {"run_id": summary.get("run_id"), "through": summary.get("through"), "outcome": summary.get("outcome"),
            "interpretation": summary.get("interpretation"),
            "stops": [{"id": t["id"], "why": committed_why(t), "quarantine": bool(t.get("quarantine"))} for t in summary.get("stops", [])],
            "gate": {k: v["ok"] for k, v in gate.items()}, "gate_measured": {k: v["detail"] for k, v in gate.items()},
            "controls": {k: (v.get("ok") if isinstance(v, dict) else v) for k, v in controls.items() if k != "C2_scope"},
            "controls_results": {k: v["results"] for k, v in controls.items() if isinstance(v, dict) and "results" in v},
            "swap_baseline": {k: v for k, v in (summary.get("swap_baseline") or {}).items() if k != "samples"},
            "auth": [{k: a[k] for k in ("path", "cred", "status", "outcome")} for a in p3.get("auth", [])],
            "trials": trials,
            "accounting": {k: {"check": v["check"], "n_t": v["n_t"], "n_t_bos": v["n_t_bos"], "prompt_sha256": v["prompt_sha256"]} for k, v in (p3.get("tt") or {}).items()},
            "shutdown": {k: v for k, v in (summary.get("shutdown") or {}).items() if k in ("verified", "record_written", "reaped", "returncode", "checks", "e1_classify", "term_sent", "kill_sent")},
            "ownership": {"record_state": summary.get("record_state"), "owner_review_required": summary.get("owner_review_required"),
                          "persist_errors": len(summary.get("persist_errors") or [])},
            "artifact_integrity": summary.get("artifact_integrity"), "model_unchanged": summary.get("model_unchanged"),
            "rows": summary.get("rows"), "denials": summary.get("denials"), "attribution": summary.get("attribution"),
            "identities": summary.get("tool_identities"), "raw_artifacts": raw_artifacts}


VERDICT_ROWS = ("B4_identity_and_exit", "control_during_generation", "slot_idle_consistency", "finish_reason",
                "input_accounting", "version_artifact_reporting")


def rows(summary):
    """Row verdicts derived from the trials that actually completed, with their counts. A stop of any
    kind, a missing trial or a failed trial can never produce SUPPORTS or DOES_NOT_SUPPORT for a row
    that needed it; NOT_TESTED, ``inference_observed`` and ``row_counts`` are kept as observed."""
    p3 = summary.get("phase3") or {}
    tr, sd, stops = p3.get("trials", []), summary.get("shutdown") or {}, summary.get("stops", [])
    passed = [t for t in tr if t.get("status") == "PASS"]
    r, n = {}, {"lifetimes": 1, "trials_expected": EXPECTED_TRIALS, "trials_completed": len(passed)}
    r["B4_identity_and_exit"] = ("SUPPORTS (conditional; 1 lifetime; harness-owned; not reproduced)"
                                 if not stops and sd.get("verified") and p3.get("binding_verified")
                                 and sd.get("e1_classify") == L.TERMINATED else "INCONCLUSIVE")
    p2 = [t for t in passed if t["id"] == "P2"]
    polls = [[q for q in t.get("polls", [])] for t in p2]
    n["p2_trials"], n["p2_polls"] = len(p2), sum(len(x) for x in polls)
    control_ok = len(p2) == 2 and all(
        {"/health", "/slots"} <= {q["path"] for q in pl}
        and all(q["status"] == 200 and q["elapsed"] is not None and q["elapsed"] <= LIM["call_s"] for q in pl)
        and any(q.get("processing") for q in pl) for pl in polls)
    r["control_during_generation"] = "SUPPORTS" if control_ok else "INCONCLUSIVE"
    full = len(passed) == EXPECTED_TRIALS and len(tr) == EXPECTED_TRIALS
    idle = [t.get("slot_idle_after") for t in passed]
    n["slot_idle_observations"] = len(idle)
    r["slot_idle_consistency"] = "SUPPORTS (consistency only)" if full and all(i is True for i in idle) else "INCONCLUSIVE"
    p2f, p3f = [t.get("finish_reason") for t in p2], [t.get("finish_reason") for t in passed if t["id"] == "P3"]
    n["finish_reason_trials"] = len(p2f) + len(p3f)
    r["finish_reason"] = "SUPPORTS" if len(p2f) == 2 and set(p2f) == {"stop"} and p3f == ["length"] else "INCONCLUSIVE"
    n["accounting_trials"] = len([t for t in passed if t.get("accounting")])
    r["input_accounting"] = ("SUPPORTS (self-consistency only)" if full and all(
        t.get("accounting") in ("ACCOUNTING_CONSISTENT", "ACCOUNTING_EXPLAINED_BOS") for t in passed) else "INCONCLUSIVE")
    rep = p3.get("reported", {})
    props, models = rep.get("/props"), rep.get("/v1/models")
    if isinstance(props, dict) and isinstance(models, dict) and props and models:
        blob = json.dumps(rep).lower()
        has_version = any(tok.lower() in blob for tok in summary.get("version_tokens") or [])
        digest = bool(summary.get("model_sha256")) and summary["model_sha256"].lower() in blob
        if not has_version:
            r["version_artifact_reporting"] = "INCONCLUSIVE (pinned build number or commit not found in /props or /v1/models)"
        elif digest:
            r["version_artifact_reporting"] = "version info present; digest reported"
        else:
            r["version_artifact_reporting"] = ("version info present; digest DOES_NOT_SUPPORT (scoped: the exact 64-hex SHA-256, "
                                               "case-insensitive, is absent from /props and /v1/models; other digest forms not examined)")
    else:
        r["version_artifact_reporting"] = "INCONCLUSIVE"
    # Protocol §7 and §13: a stop of any kind (environmental, policy, template or configuration abort,
    # trial limit, harness exception) leaves no runtime-evidence verdict. Rows are evaluated above only
    # so their counts stay honest; none may keep SUPPORTS or DOES_NOT_SUPPORT after a stop.
    if stops:
        for name in VERDICT_ROWS:
            r[name] = "INCONCLUSIVE"
        n["verdicts_withheld_by_stops"] = sorted({str(s.get("id")) for s in stops})
    r["B3_cancel_disconnect_late_delivery_attempt_registration"] = "NOT_TESTED"
    r["inference_observed"] = len(passed)
    r["row_counts"] = n
    return r


def run_lifetime(cfg, probes, fx, meta, inst, mon, cancel, interrupted, ev, summary, hashes):
    """Spawn, drive, stop and verify one runtime. Whatever happens in here, a spawned runtime leaves
    through shutdown or containment by verified identity; if neither can prove the exit, its record
    stays unresolved. Results go into ``summary``; nothing here raises."""
    stops = summary["stops"]
    try:
        try:
            inst.launch(hashes)
        except StopRun as stop:
            stops.append(stop_entry(stop))
            return
        summary["t_spawn"] = time.time()
        mon.mark_spawn()
        try:
            run_phase3(cfg, probes, fx, meta, inst, mon, cancel, ev, interrupted, summary["phase3"])
        except StopRun as stop:
            stops.append(stop_entry(stop))
            if stop.quarantine:
                inst.mark_owner_review(f"{stop.sid}: {stop.why}")
        except BaseException as exc:  # never leave a runtime behind because of a harness bug
            stops.append({"id": "HARNESS_EXCEPTION", "why": type(exc).__name__, "quarantine": False, "immediate": False})
    finally:
        mon.halt.set()
        mon.join(5)
        stops.extend(dict(t) for t in mon.triggers)
        if mon.is_alive():
            summary["monitor_unjoined"] = True
        if inst.proc is not None and not inst.finished:
            q = [x["id"] for x in stops if x.get("quarantine")]
            summary["shutdown"] = inst.safe_shutdown(immediate=any(x.get("immediate") for x in stops),
                                                     policy_quarantine=("owner review required: " + ",".join(q)) if q else None)
        elif inst.finished:
            summary["shutdown"] = inst.result


def _execute(cfg, probes, through, attended, summary, run_dir, ev, interrupted, cancel, o):
    def done(outcome, code=1, **kw):
        summary.update(outcome=outcome, **kw)
        return dict(summary, exit_code=code)

    records = E.Records(cfg.root)
    un = records.unresolved()
    if un:
        return done("REFUSED_UNRESOLVED", 3, why=f"{len(un)} unresolved execution record(s)", unresolved=un)
    summary["tool_identities"] = tool_identities(cfg)
    summary["version_tokens"] = version_tokens(cfg.version_string)
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt before Phase 1")
    # Phase 1
    p1 = phase1(cfg, probes, records, attended, o["gate_n"], o["interval"], o["top_cmd"], abort=interrupted)
    summary["gate"], summary["model_sha256"] = p1["gate"], p1["ctx"]["artifacts"].get("model_sha256")
    with open(os.path.join(run_dir, "gate-window.jsonl"), "w") as f:
        for smp in p1["samples"]:
            f.write(json.dumps(smp) + "\n")
    with open(os.path.join(run_dir, "gate-context.json"), "w") as f:
        json.dump(p1["ctx"], f, indent=1, default=str)
    ev("phase1", passed=p1["passed"])
    if p1["interrupted"]:
        return done("INTERRUPTED", why="operator interrupt during Phase 1")
    if not p1["passed"] or through == 1:
        return done("GATE_PASSED" if p1["passed"] else "GATE_FAILED", 0 if p1["passed"] else 1)
    art = p1["ctx"]["artifacts"]
    # Phase 2
    c = controls(cfg, cfg.control_runs, cfg.control_c3_runs, abort=interrupted)
    summary["controls"] = c
    ev("phase2", passed=c["passed"])
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt during Phase 2")
    if not c["passed"] or through == 2:
        return done("CONTROLS_PASSED" if c["passed"] else "CONTROLS_FAILED_INCONCLUSIVE", 0 if c["passed"] else 1)
    try:
        fx, meta = E.load_fixtures(cfg.fixtures_dir, cfg.pins)
    except E.FixtureError as exc:
        return done("FIXTURE_ERROR", why=str(exc))
    # Everything below must complete before the spawn; nothing below may spawn after an interrupt.
    pre = prespawn_check(cfg, art)
    summary["artifact_integrity"] = {"gate_check_ok": art["ok"], "runtime_tree": art.get("runtime_tree", {}).get("ok"),
                                     "prespawn": {k: v for k, v in pre.items() if k != "problems"}, "prespawn_problems": len(pre.get("problems", []))}
    if not pre["ok"]:
        return done("ARTIFACT_CHANGED", why="model or runtime tree differs from what Phase 1 verified")
    base = swap_baseline(probes, o["baseline_n"], o["baseline_interval"], interrupted)
    summary["swap_baseline"] = base
    if not base["ok"]:
        return done("INTERRUPTED" if base["why"] == "interrupted" else "BASELINE_FAILED", why=base["why"])
    if time.clock_gettime(time.CLOCK_UPTIME_RAW) - p1["ended_up"] > LIM["gate_stale_s"]:
        return done("GATE_STALE")
    if interrupted.is_set():
        return done("INTERRUPTED", why="operator interrupt before spawn")
    # Phase 3
    inst = Instance(cfg, records, run_id=summary["run_id"], run_dir=run_dir, wrap=o["wrap"], kill_fn=o["kill_fn"],
                    interrupted=interrupted, cancel=cancel)
    hid = p1["ctx"]["attendance"]
    tm = (hid.get("ac_timers_min") or {}).get("displaysleep")
    ceiling = tm * 60 - LIM["attendance_lapse_margin_s"] if tm else None
    mon = Monitor(probes, E.StopEvaluator(swap_base=base["median_mib"]), inst, os.path.join(run_dir, "series.jsonl"), cancel,
                  ceiling, interval=o["monitor_interval"], slow_every=o["monitor_slow_every"])
    mon.start()  # before the spawn: swap, pressure and power are watched through the whole model load
    summary["phase3"] = {}
    try:
        # Never spawn unless the monitor is demonstrably working: its first tick must have produced
        # every fast reading. (A trigger on that first tick sets `cancel`, and the launch then refuses.)
        if not mon.ready.wait(15) or not mon.first_sample_ok:
            return done("MONITOR_NOT_READY", why="the monitor produced no complete first sample; nothing was spawned")
        if time.clock_gettime(time.CLOCK_UPTIME_RAW) - p1["ended_up"] > LIM["gate_stale_s"]:  # the bound is on the spawn itself
            return done("GATE_STALE")
        run_lifetime(cfg, probes, fx, meta, inst, mon, AnyEvent(cancel, interrupted), interrupted, ev, summary,
                     {"binary": art.get("binary_sha256"), "model": summary["model_sha256"]})
    finally:
        mon.halt.set()
        mon.join(5)  # its series file is hashed afterwards
        inst.cleanup_secrets()
    spawned = inst.proc is not None
    stops, sd = summary["stops"], summary.get("shutdown") or {}
    summary["record_state"] = (inst.rec or {}).get("state")
    summary["owner_review_required"] = bool((inst.rec or {}).get("owner_review_required"))
    summary["persist_errors"] = list(inst.persist_errors)
    if any(is_environmental(x) for x in stops):
        summary["interpretation"] = "INTERRUPTED_ENVIRONMENT"
    # Phase 4
    if spawned:
        interrupted.wait(o["post_delay"])
        summary["denials"] = ({"available": False, "skipped": "operator interrupt"} if interrupted.is_set()
                              else sandbox_denials(cfg, inst.root["pid"] if inst.root else inst.proc.pid, summary.get("t_spawn", time.time())))
    try:
        summary["model_unchanged"] = stat_identity(os.stat(cfg.model)) == art["model_stat"]
    except OSError:
        summary["model_unchanged"] = False
    post = []
    for _ in range(int(o["post_sample_s"]) if through >= 4 and spawned else 0):
        if interrupted.is_set():
            break
        post.append(probes.sample())
        interrupted.wait(1.0)
    with open(os.path.join(run_dir, "post-unload.jsonl"), "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in post))
    summary["rows"] = rows(summary)
    tr = (summary.get("phase3") or {}).get("trials", [])
    complete = len(tr) == EXPECTED_TRIALS and all(t.get("status") == "PASS" for t in tr)
    summary["attribution"] = attribute(bool(stops) or not complete, summary.get("denials") or {"available": False})
    rec_state = summary["record_state"]
    if not spawned:
        outcome = {"INTENT": "UNRESOLVED_INTENT", "QUARANTINED": "QUARANTINED"}.get(rec_state, "NOT_SPAWNED")
    elif not sd.get("verified"):
        outcome = "QUARANTINED"
    elif not stops:
        outcome = "COMPLETED" if complete else "COMPLETED_WITH_TRIAL_FAILURES"
    else:
        outcome = "STOPPED"
    return done(outcome, 0 if outcome == "COMPLETED" else 1)


def run_all(cfg, probes, through, attended, *, gate_n=LIM["gate_samples"], interval=1.0, top_cmd=None,
            wrap=True, kill_fn=E.kill_identified, post_sample_s=LIM["post_sample_s"], advisory=None, install_signals=True,
            post_delay=10.0, interrupted=None, baseline_n=LIM["baseline_samples"], baseline_interval=1.0,
            monitor_interval=1.0, monitor_slow_every=5):
    ok, why = E.check_authorization(cfg.root, list(range(1, through + 1)), cfg.protocol_doc)
    if not ok:
        return {"outcome": "REFUSED", "why": why, "exit_code": 2}
    if not attended:
        return {"outcome": "REFUSED", "why": "--attended is required", "exit_code": 2}
    lock = E.run_lock(cfg.root)
    try:
        lock.__enter__()
    except E.RunLockHeld as exc:
        return {"outcome": "REFUSED", "why": str(exc), "exit_code": 2}
    interrupted = interrupted if interrupted is not None else threading.Event()
    cancel = threading.Event()
    old, result, ev_f, run_dir = {}, None, None, None
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(3)
    summary = {"run_id": run_id, "through": through, "stops": [], "outcome": None}
    opts = {"gate_n": gate_n, "interval": interval, "top_cmd": top_cmd, "wrap": wrap, "kill_fn": kill_fn,
            "post_sample_s": post_sample_s, "post_delay": post_delay, "baseline_n": baseline_n,
            "baseline_interval": baseline_interval, "monitor_interval": monitor_interval, "monitor_slow_every": monitor_slow_every}
    try:
        if install_signals:
            # The handler only sets flags. Both are set: `interrupted` ends the run at the next decision
            # point, `cancel` ends any wait or HTTP exchange in flight so that point is reached promptly.
            def on_signal(*_):
                interrupted.set()
                cancel.set()
            for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                old[sg] = signal.signal(sg, on_signal)
        run_dir = os.path.join(cfg.root, "runs", run_id)
        os.makedirs(run_dir, mode=0o700)
        ev_f = open(os.path.join(run_dir, "events.jsonl"), "a")

        def ev(name, **kw):
            ev_f.write(json.dumps(dict(kw, e=name, up=time.clock_gettime(time.CLOCK_UPTIME_RAW)), default=str) + "\n")
            ev_f.flush()

        result = _execute(cfg, probes, through, attended, summary, run_dir, ev, interrupted, cancel, opts)
    except BaseException as exc:  # a spawned runtime is contained inside _execute; nothing is left to kill here
        summary.update(outcome="HARNESS_ERROR", why=type(exc).__name__)
        result = dict(summary, exit_code=1)
    finally:
        for sg, h in old.items():
            signal.signal(sg, h)
        if ev_f is not None:
            ev_f.close()
        try:
            if run_dir is not None:
                with open(os.path.join(run_dir, "summary.json"), "w") as f:
                    json.dump(summary, f, indent=1, default=str)
                raw = raw_artifact_digests(run_dir)
                if result is not None:
                    result["raw_artifacts"] = raw
                with open(os.path.join(run_dir, "summary-committed-view.json"), "w") as f:
                    json.dump(committed_view(summary, raw), f, indent=1, default=str)
        except Exception as exc:
            if result is not None:
                result["finalize_error"] = type(exc).__name__
        lock.__exit__(None, None, None)
    return result


# --------------------------------------------------------------------------------------------
# CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bench", default=E.DEFAULT_BENCH)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("host-probe", help="one-shot parsed host readings; no gate verdict")
    sub.add_parser("verify-fixtures", help="verify external fixtures against the pinned full hashes")
    sub.add_parser("records", help="list execution records and their states")
    r = sub.add_parser("recover", help="classify (read-only) or, with --kill --confirm RUN_ID, kill recorded identities")
    r.add_argument("run_id")
    r.add_argument("--kill", action="store_true")
    r.add_argument("--confirm")
    s = sub.add_parser("scan-committed", help="fail if fixture strings appear in the given files")
    s.add_argument("paths", nargs="+")
    g = sub.add_parser("run", help="Phase 1..N (needs AUTHORIZATION.json and --attended)")
    g.add_argument("--through", type=int, default=4, choices=[1, 2, 3, 4])
    g.add_argument("--attended", action="store_true")
    a = ap.parse_args(argv)
    cfg = Config(a.bench)
    if a.cmd == "host-probe":
        p = E.HostProbes()
        print(json.dumps({"sample": p.sample(), "thermal_warning": p.thermal_warn(), "disk_gib": p.disk_gib(),
                          "competing": p.competing(), "attendance": p.attendance(), "boottime": p.boottime()}, indent=1))
    elif a.cmd == "verify-fixtures":
        try:
            fx, meta = E.load_fixtures(cfg.fixtures_dir, cfg.pins)
            print(f"OK: {len(fx)} fixtures + meta verified against pinned lengths and full SHA-256")
        except E.FixtureError as exc:
            print(f"FIXTURE ERROR: {exc}")
            return 1
    elif a.cmd == "records":
        rec = E.Records(cfg.root)
        print(json.dumps({"unresolved": rec.unresolved(), "all": sorted(os.listdir(rec.dir))}, indent=1))
    elif a.cmd == "recover":
        rep = E.recover(E.Records(cfg.root), a.run_id, E.HostProbes().boottime(), a.kill, a.confirm)
        print(json.dumps(rep, indent=1, default=str))
        if rep.get("verdict") == "REFUSED_RUN_LOCK_HELD":
            return 2
        return 0 if rep.get("verdict") in (L.TERMINATED, "ALREADY_RESOLVED") else 1
    elif a.cmd == "scan-committed":
        fx, meta = E.load_fixtures(cfg.fixtures_dir, cfg.pins)
        hits = E.scan_files(a.paths, E.forbidden_strings(fx, meta))
        print(json.dumps({"files": len(a.paths), "hits": [(p, i) for p, i in hits]}))
        return 1 if hits else 0
    elif a.cmd == "run":
        res = run_all(cfg, E.HostProbes(), a.through, a.attended)
        print(json.dumps(committed_view(res, res.get("raw_artifacts")) if res.get("run_id") else res, indent=1, default=str))
        return res.get("exit_code", 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
