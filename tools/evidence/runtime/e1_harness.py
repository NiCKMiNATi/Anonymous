#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Slice 0B-2 E1 harness: seven scenarios, repeated trials.

Run:  python3 -B e1_harness.py --out DIR [--trials 20] [--only S1,S2,...] [--reuse-real N]
Standard library only; synthetic data only; loopback only; no model; no network beyond 127.0.0.1.
Every spawned process carries the run marker; only identity-verified own processes are ever
signalled; a final audit proves nothing carrying the marker remains. Failed trials, cleanup
outcomes and unexpected behaviour are written to the raw JSONL, not only successes.
"""

import argparse
import json
import os
import platform
import select
import signal
import socket
import statistics
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib as L  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OWNER = os.path.join(HERE, "e1_owner.py")
LIB = os.path.join(HERE, "e1_lib.py")
STANDIN = L.STANDIN


class Run:
    def __init__(self, out, trials):
        self.out, self.trials = out, trials
        self.marker = "e1-" + uuid.uuid4().hex[:10]
        os.makedirs(out, mode=0o700, exist_ok=True)
        self.raw = open(os.path.join(out, "trials.jsonl"), "a")
        self.results = []

    def emit(self, row):
        self.results.append(row)
        self.raw.write(json.dumps(row, default=str) + "\n")
        self.raw.flush()


class Trial:
    """Everything spawned in one trial, and its cleanup (identity-verified kills only)."""

    def __init__(self, run):
        self.run = run
        self.procs = []     # Popen objects we own
        self.idents = []    # (role, pid, start) of every process we know we created
        self.fds = []
        self.tags = []
        self.cleanup_info = {}

    def nonce(self):
        return uuid.uuid4().hex

    def track(self, role, ident):
        if ident:
            self.idents.append((role, ident["pid"], list(ident["start"])))

    def track_record(self, record, role="child"):
        self.track(role, {"pid": record["pid"], "start": record["start"]})
        for d in record.get("descendants", []):
            self.track("descendant", d)
        if record.get("owner"):
            self.track("owner", record["owner"])

    def instance(self, standin_args=(), **kw):
        nonce, tag = self.nonce(), self.nonce()
        self.tags.append(tag)
        proc, record, wd = L.spawn_instance(self.run.marker, tag, nonce, standin_args, **kw)
        self.procs.append(proc)
        if wd is not None:
            self.fds.append(wd)
        self.track_record(record)
        return proc, record, wd

    def owned_instance(self, name, standin_args=(), child_new_session=1, watchdog=0, wrapper=0):
        """Owner process (to be SIGKILLed) + child + persisted record file."""
        nonce, tag = self.nonce(), self.nonce()
        self.tags.append(tag)
        rec_path = os.path.join(self.run.out, f"rec-{name}-{uuid.uuid4().hex[:6]}.json")
        cmd = [sys.executable, "-B", OWNER, "--record", rec_path, "--marker", self.run.marker,
               "--nonce", nonce, "--tag", tag, "--child-new-session", str(child_new_session),
               "--watchdog", str(watchdog), "--wrapper", str(wrapper), *standin_args]
        env = dict(os.environ)
        owner = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                 start_new_session=True)
        self.procs.append(owner)
        self.track("owner", L.identity(owner.pid))
        deadline = time.monotonic() + 10
        buf = b""
        while time.monotonic() < deadline and b"RECORDED" not in buf:
            r, _, _ = select.select([owner.stdout.fileno()], [], [], 0.5)
            if not r:
                continue
            chunk = os.read(owner.stdout.fileno(), 64)
            if not chunk:
                break
            buf += chunk
        if b"RECORDED" not in buf:
            raise RuntimeError("owner never recorded")
        record = json.load(open(rec_path))
        self.track_record(record)
        return owner, record, rec_path

    def cleanup(self):
        """Kill survivors by verified identity, then sweep by tag and by marker. Reports leaks."""
        leaked = []
        for role, pid, start in self.idents:
            i = L.identity(pid)
            if L.same_identity(pid, start, i) and i["status"] != "zombie":
                leaked.append({"role": role, "pid": pid, "status": i["status"]})
                L.safe_kill(pid, start, signal.SIGKILL)
        swept = []
        for tag in self.tags:
            for i in L.tag_scan(tag):
                swept.append({"via": "tag", "pid": i["pid"]})
                L.safe_kill(i["pid"], i["start"], signal.SIGKILL)
        for pid, i in marker_processes(self.run.marker):
            if not any(s["pid"] == pid for s in swept) and not any(l["pid"] == pid for l in leaked):
                swept.append({"via": "marker", "pid": pid})
            L.safe_kill(pid, i["start"], signal.SIGKILL)
        for p in self.procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            if p.stdout:
                try:
                    p.stdout.close()
                except OSError:
                    pass
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        time.sleep(0.05)
        remaining = [pid for _, pid in marker_processes(self.run.marker)]
        self.cleanup_info = {"leaked_after_trial": leaked, "swept_unrecorded": swept,
                             "remaining_after_cleanup": remaining}
        return self.cleanup_info


def marker_processes(marker):
    r = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10)
    out = []
    for line in r.stdout.splitlines():
        if f"--marker {marker}" in line:
            try:
                pid = int(line.split(None, 1)[0])
            except ValueError:
                continue
            i = L.identity(pid)
            if i and i["status"] != "zombie":
                out.append((pid, i))
    return out


def classify_fresh(record_path):
    r = subprocess.run([sys.executable, "-B", LIB, "classify", "--record", record_path],
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


def write_record(run, record, name):
    path = os.path.join(run.out, f"succ-{name}-{uuid.uuid4().hex[:6]}.json")
    with open(path, "w") as f:
        json.dump(record, f)
    return path


def watches_for(record):
    ws = []
    for pid, start in [(record["pid"], record["start"])] + [(d["pid"], d["start"]) for d in record.get("descendants", [])]:
        if L.same_identity(pid, start, L.identity(pid)):
            ws.append((pid, start, L.ExitWatch(pid)))
    return ws


def all_exited(ws, timeout):
    deadline = time.monotonic() + timeout
    fired = []
    for pid, start, w in ws:
        remaining = max(0.0, deadline - time.monotonic())
        ev = w.wait(remaining) if w.registered else None
        gone = not L.same_identity(pid, start, L.identity(pid))
        fired.append({"pid": pid, "kqueue_event": ev is not None, "identity_gone": gone})
    for _, _, w in ws:
        w.close()
    return all(f["kqueue_event"] for f in fired), fired


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def stats(xs):
    if not xs:
        return None
    xs = sorted(xs)
    return {"n": len(xs), "min": xs[0], "p50": statistics.median(xs),
            "p95": xs[min(len(xs) - 1, int(0.95 * len(xs)))], "max": xs[-1]}


# ------------------------------------------------------------------------------------------------
# scenarios: each returns (obs, checks) where checks is {name: bool}; failures are recorded

def s1_identity(run, t, variant, n):
    obs, checks = {}, {}
    if variant == "wrapper-sh":
        proc, rec, _ = t.instance(wrapper=True)
        obs["spawned_pid"] = proc.pid
        obs["listener_pids_at_bind"] = rec["listener_pids_at_bind"]
        checks["wrapper_mismatch_detected"] = (rec["binding_verified"] is False
                                               and rec["listener_pids_at_bind"] != [proc.pid])
        obs["wrapper_detected"] = checks["wrapper_mismatch_detected"]
        # the descendants of the wrapper include the real listener
        obs["recorded_descendant_pids"] = [d["pid"] for d in rec["descendants"]]
        checks["real_listener_recorded_as_descendant"] = len(rec["descendants"]) >= 1
        return obs, checks
    args = ["--grandchild", "same"] if variant == "with-grandchild" else []
    proc, rec, _ = t.instance(args)
    reads = [L.identity(proc.pid) for _ in range(3)]
    obs.update(pid=proc.pid, start=rec["start"], pgid=rec["pgid"], port=rec["port"],
               binding_verified=rec["binding_verified"], listener_pids=rec["listener_pids_at_bind"],
               descendants=[d["pid"] for d in rec["descendants"]])
    checks["binding_verified"] = rec["binding_verified"] is True
    checks["identity_stable_over_reads"] = all(r and r["start"] == rec["start"] for r in reads)
    checks["child_is_group_leader"] = rec["pgid"] == proc.pid
    pc = L.listener_ports_of(proc.pid)
    checks["pid_centric_lsof_agrees"] = pc["ports"] == [rec["port"]]
    if variant == "with-grandchild":
        checks["grandchild_recorded"] = len(rec["descendants"]) == 1
    obs["tuple"] = [proc.pid, *rec["start"]]
    return obs, checks


def s2_graceful(run, t, variant, n):
    obs, checks = {}, {}
    args = ["--grandchild", "same"] if variant == "with-grandchild" else []
    proc, rec, _ = t.instance(args)
    allws = watches_for(rec)
    main_w = [w for pid, _, w in allws if pid == proc.pid][0]
    ws = [x for x in allws if x[0] != proc.pid]  # the main watch is consumed below
    t0 = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    ev = main_w.wait(3.0)
    obs["t_kqueue_exit_s"] = time.monotonic() - t0 if ev else None
    mid = L.identity(proc.pid)  # between exit notification and reap
    obs["identity_between_exit_and_reap"] = mid["status"] if mid else None
    rc = proc.wait(timeout=3)
    obs["t_waitpid_s"] = time.monotonic() - t0
    obs["returncode"] = rc
    ok, fired = all_exited(ws, 2.0)
    obs["exit_events"] = fired
    after = classify_fresh(write_record(run, rec, "s2"))
    obs["verdict_v1"], obs["verdict_v2"] = after["v1_no_tag"]["verdict"], after["v2_tag"]["verdict"]
    obs["listeners_after"] = after["v2_tag"]["obs"]["listeners"]["pids"]
    obs["probe_after"] = after["v2_tag"]["obs"]["probe"]
    checks["kqueue_exit_observed"] = ev is not None
    checks["waitpid_clean_exit"] = rc == 0
    checks["all_exit_events"] = ok
    checks["classified_terminated_v2"] = obs["verdict_v2"] == L.TERMINATED
    checks["no_listener_after"] = obs["listeners_after"] == []
    checks["probe_no_answer_after"] = obs["probe_after"] == "NO_ANSWER"
    return obs, checks


def s3_escalation(run, t, variant, n):
    obs, checks = {}, {}
    gmap = {"plain": [], "gc-same-pid-kill": ["--grandchild", "same"],
            "gc-same-group-kill": ["--grandchild", "same"], "gc-escaped": ["--grandchild", "escaped"],
            "gc-inherit-listener": ["--grandchild", "inherit-listener"]}
    proc, rec, _ = t.instance(["--ignore-sigterm", *gmap[variant]])
    ws = watches_for(rec)
    path = write_record(run, rec, "s3")
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.5)  # grace budget
    still = L.identity(proc.pid)
    obs["alive_after_sigterm_grace"] = bool(still)
    v_mid = classify_fresh(path)
    obs["verdict_after_sigterm_v2"] = v_mid["v2_tag"]["verdict"]
    checks["not_declared_terminated_after_ignored_sigterm"] = v_mid["v2_tag"]["verdict"] == L.ALIVE
    t0 = time.monotonic()
    if variant == "gc-same-group-kill":
        os.killpg(rec["pgid"], signal.SIGKILL)
    else:
        proc.send_signal(signal.SIGKILL)
    rc = proc.wait(timeout=3)
    obs["t_sigkill_to_reap_s"] = time.monotonic() - t0
    obs["returncode"] = rc
    checks["sigkill_status"] = rc == -signal.SIGKILL
    time.sleep(0.3)
    obs["group_after_kill"] = [i["pid"] for i in L.group_members(rec["pgid"])]
    v1 = classify_fresh(path)
    obs["verdict_after_kill_v1"], obs["verdict_after_kill_v2"] = v1["v1_no_tag"]["verdict"], v1["v2_tag"]["verdict"]
    obs["listeners_after_kill"] = v1["v2_tag"]["obs"]["listeners"]["pids"]
    survivors = [d["pid"] for d in rec["descendants"] if L.same_identity(d["pid"], d["start"], L.identity(d["pid"]))]
    obs["descendant_survivors_after_main_kill"] = survivors
    if variant == "plain":
        checks["terminated_after_sigkill"] = obs["verdict_after_kill_v2"] == L.TERMINATED
    elif variant == "gc-same-group-kill":
        checks["group_kill_removes_all"] = survivors == [] and obs["group_after_kill"] == []
        checks["terminated_after_group_kill"] = obs["verdict_after_kill_v2"] == L.TERMINATED
    else:  # descendant survives a main-pid kill
        checks["descendant_survives_main_kill"] = len(survivors) == 1
        checks["not_terminated_while_descendant_lives"] = obs["verdict_after_kill_v2"] == L.ALIVE
        if variant == "gc-inherit-listener":
            checks["port_still_listening_after_main_death"] = len(obs["listeners_after_kill"]) == 1
        # then the correct cleanup (group kill where the group contains it)
        if variant in ("gc-same-pid-kill", "gc-inherit-listener"):
            try:
                os.killpg(rec["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.3)
            fin = classify_fresh(path)
            obs["verdict_after_group_kill_v2"] = fin["v2_tag"]["verdict"]
            obs["binding_verified_at_record"] = rec["binding_verified"]
            obs["listener_pids_at_bind"] = rec["listener_pids_at_bind"]
            if variant == "gc-inherit-listener":
                # two processes held the listening socket at bind time: the listener binding is
                # ambiguous, so even a fully dead instance cannot reach PROVEN_TERMINATED
                checks["ambiguous_listener_binding_blocks_proof"] = (
                    rec["binding_verified"] is False and fin["v2_tag"]["verdict"] == L.INDETERMINATE)
            else:
                checks["terminated_after_group_kill"] = fin["v2_tag"]["verdict"] == L.TERMINATED
        else:  # escaped: group kill cannot reach it
            try:
                os.killpg(rec["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(0.2)
            still = [d["pid"] for d in rec["descendants"] if L.same_identity(d["pid"], d["start"], L.identity(d["pid"]))]
            obs["escaped_descendant_survives_group_kill"] = bool(still)
            checks["escaped_descendant_survives_group_kill"] = bool(still)
    for _, _, w in ws:
        w.close()
    return obs, checks


def s4_owner_sigkill(run, t, variant, n):
    obs, checks = {}, {}
    cfg = {"own-session": dict(child_new_session=1, watchdog=0),
           "owner-group": dict(child_new_session=0, watchdog=0),
           "watchdog-pipe": dict(child_new_session=1, watchdog=1),
           "watchdog-ignores-sigterm": dict(child_new_session=1, watchdog=1)}[variant]
    extra = ["--ignore-sigterm"] if variant == "watchdog-ignores-sigterm" else []
    owner, rec, path = t.owned_instance("s4", extra, **cfg)
    obs["child_pgid_equals_owner_pgid"] = rec["pgid"] == (rec["owner"]["pgid"])
    w = L.ExitWatch(rec["pid"])
    t0 = time.monotonic()
    L.safe_kill(rec["owner"]["pid"], rec["owner"]["start"], signal.SIGKILL)
    owner.wait(timeout=3)
    ev = w.wait(1.5)
    obs["child_exit_after_owner_sigkill_s"] = (time.monotonic() - t0) if ev else None
    obs["child_survived_1_5s"] = ev is None
    mid = L.identity(rec["pid"])
    obs["child_ppid_after_owner_death"] = mid["ppid"] if mid else None
    v = classify_fresh(path)
    obs["verdict_v1"], obs["verdict_v2"] = v["v1_no_tag"]["verdict"], v["v2_tag"]["verdict"]
    w.close()
    if variant in ("own-session", "owner-group"):
        checks["child_survives_owner_sigkill"] = ev is None
        checks["child_reparented"] = obs["child_ppid_after_owner_death"] == 1
        checks["successor_sees_alive"] = obs["verdict_v2"] == L.ALIVE
    else:
        checks["watchdog_terminates_child"] = ev is not None
        checks["watchdog_within_1s"] = ev is not None and obs["child_exit_after_owner_sigkill_s"] < 1.0
        checks["successor_sees_terminated"] = obs["verdict_v2"] == L.TERMINATED
    return obs, checks


class Decoy:
    """An unrelated live process (never ours to signal except by verified identity)."""

    def __init__(self, t):
        self.p = subprocess.Popen(["/bin/sleep", "60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t.procs.append(self.p)
        self.ident = L.identity(self.p.pid)
        t.track("decoy", self.ident)


def s5_successor(run, t, variant, n):
    obs, checks, truth = {}, {}, None
    expected = {}
    path = None
    owner = rec = None

    def owned(**kw):
        nonlocal owner, rec, path
        owner, rec, path = t.owned_instance("s5", **kw)

    def kill_owner():
        L.safe_kill(rec["owner"]["pid"], rec["owner"]["start"], signal.SIGKILL)
        owner.wait(timeout=3)

    def kill_real(sig=signal.SIGKILL, group=False):
        for d in rec["descendants"]:
            L.safe_kill(d["pid"], d["start"], sig)
        if group:
            try:
                os.killpg(rec["pgid"], sig)
            except ProcessLookupError:
                pass
        L.safe_kill(rec["pid"], rec["start"], sig)

    unsound_expected = {}
    if variant == "alive-after-owner-death":
        owned(); ws = watches_for(rec); kill_owner(); truth = "alive"
        expected = {"v1": L.ALIVE, "v2": L.ALIVE}
    elif variant == "dead-graceful":
        owned(); ws = watches_for(rec); L.safe_kill(rec["pid"], rec["start"], signal.SIGTERM); kill_owner()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        expected = {"v1": L.TERMINATED, "v2": L.TERMINATED}
    elif variant == "dead-killed-after-owner-death":
        owned(); ws = watches_for(rec); kill_owner(); kill_real()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        expected = {"v1": L.TERMINATED, "v2": L.TERMINATED}
    elif variant == "pid-reuse-simulated-original-dead":
        owned(); ws = watches_for(rec); kill_owner(); kill_real()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        decoy = Decoy(t)
        rec = dict(rec, pid=decoy.ident["pid"])  # record pid now names an unrelated live process
        path = write_record(run, rec, "s5r")
        expected = {"v1": L.TERMINATED, "v2": L.TERMINATED}
    elif variant == "pid-reuse-simulated-original-alive":
        owned(); kill_owner(); truth = "alive"
        decoy = Decoy(t)
        rec = dict(rec, pid=decoy.ident["pid"], descendants=[])
        path = write_record(run, rec, "s5r")
        expected = {"v1": L.ALIVE, "v2": L.ALIVE}  # nonce answered / tag found
    elif variant == "port-reuse-foreign-listener":
        owned(); ws = watches_for(rec); L.safe_kill(rec["pid"], rec["start"], signal.SIGTERM); kill_owner()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        dn, dt = t.nonce(), t.nonce()
        t.tags.append(dt)
        d = subprocess.Popen([sys.executable, "-B", STANDIN, "--marker", run.marker, "--nonce", dn,
                              "--port", str(rec["port"])], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, **{L.TAG_ENV: dt}), start_new_session=True)
        t.procs.append(d)
        ready = L.read_json_line(d.stdout, 5)
        t.track("foreign-listener", L.identity(d.pid))
        obs["foreign_listener_bound"] = bool(ready) and ready["port"] == rec["port"]
        expected = {"v1": L.TERMINATED, "v2": L.TERMINATED}
    elif variant == "sigstopped-alive-unresponsive":
        owned(); kill_owner(); L.safe_kill(rec["pid"], rec["start"], signal.SIGSTOP); time.sleep(0.1)
        truth = "alive"; obs["stopped_status"] = (L.identity(rec["pid"]) or {}).get("status")
        expected = {"v1": L.ALIVE, "v2": L.ALIVE}
    elif variant == "wrapper-unverified-dead":
        owned(wrapper=1); ws = watches_for(rec); kill_owner(); kill_real(group=True)
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        expected = {"v1": L.INDETERMINATE, "v2": L.INDETERMINATE}
    elif variant == "wrapper-unverified-alive":
        owned(wrapper=1); kill_owner(); L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL); truth = "alive"
        expected = {"v1": L.ALIVE, "v2": L.ALIVE}
    elif variant == "late-grandchild-same-group":
        owned(); kill_owner()
        urllib_get(rec["port"], "/spawn-late?mode=same"); time.sleep(0.3)
        L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL); time.sleep(0.3); truth = "alive"
        expected = {"v1": L.INDETERMINATE, "v2": L.ALIVE}
    elif variant == "late-grandchild-escaped-tag-inherited":
        owned(); kill_owner()
        urllib_get(rec["port"], "/spawn-late?mode=escaped"); time.sleep(0.3)
        L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL); time.sleep(0.3); truth = "alive"
        expected = {"v1": L.TERMINATED, "v2": L.ALIVE}
        unsound_expected = {"v1": True}
    elif variant == "late-grandchild-escaped-tag-scrubbed":
        owned(); kill_owner()
        urllib_get(rec["port"], "/spawn-late?mode=escaped-scrubbed"); time.sleep(0.3)
        L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL); time.sleep(0.3); truth = "alive"
        expected = {"v1": L.TERMINATED, "v2": L.TERMINATED}
        unsound_expected = {"v1": True, "v2": True}
    elif variant == "record-missing-start":
        owned(); ws = watches_for(rec); kill_owner(); kill_real()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        rec = {k: v for k, v in rec.items() if k not in ("start", "descendants")}
        path = write_record(run, rec, "s5m")
        expected = {"v1": L.INDETERMINATE, "v2": L.INDETERMINATE}
    elif variant == "nonce-only-alive":
        owned(); kill_owner(); truth = "alive"
        rec = {"port": rec["port"], "nonce": rec["nonce"]}
        path = write_record(run, rec, "s5n")
        expected = {"v1": L.ALIVE, "v2": L.ALIVE}
    elif variant == "nonce-only-dead":
        owned(); ws = watches_for(rec); kill_owner(); kill_real()
        ok, _ = all_exited(ws, 3); truth = "terminated" if ok else "unknown"; ws = []
        rec = {"port": rec["port"], "nonce": rec["nonce"]}
        path = write_record(run, rec, "s5n")
        expected = {"v1": L.INDETERMINATE, "v2": L.INDETERMINATE}
    else:
        raise ValueError(variant)

    time.sleep(0.15)
    v = classify_fresh(path)
    got = {"v1": v["v1_no_tag"]["verdict"], "v2": v["v2_tag"]["verdict"]}
    obs.update(truth=truth, verdict_v1=got["v1"], verdict_v2=got["v2"], expected=expected,
               why_v2=v["v2_tag"]["why"], classify_seconds=v["v2_tag"]["seconds"],
               foreign_listener_flag=bool(v["v2_tag"]["obs"]["listeners"]["pids"]) and got["v2"] == L.TERMINATED)
    for k in ("v1", "v2"):
        unsound = (got[k] == L.TERMINATED and truth == "alive") or (got[k] == L.ALIVE and truth == "terminated")
        obs[f"unsound_{k}"] = unsound
        checks[f"{k}_as_expected"] = got[k] == expected[k]
        if unsound and not unsound_expected.get(k):
            checks[f"{k}_sound"] = False
    if variant.startswith("pid-reuse-simulated"):
        checks["unrelated_process_not_signalled"] = L.same_identity(decoy.ident["pid"], decoy.ident["start"], L.identity(decoy.ident["pid"]))
    if truth == "unknown":
        checks["truth_established_by_kqueue"] = False
    return obs, checks


def urllib_get(port, path):
    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
        s.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
        while s.recv(4096):
            pass


def s6_listener(run, t, variant, n):
    obs, checks = {}, {}
    if variant == "steady-state":
        proc, rec, _ = t.instance()
        port_q = [L.listeners(rec["port"]) for _ in range(5)]
        pid_q = [L.listener_ports_of(proc.pid) for _ in range(5)]
        obs["port_query_pids"] = [q["pids"] for q in port_q]
        obs["port_query_seconds"] = [round(q["seconds"], 4) for q in port_q]
        checks["port_centric_stable_and_correct"] = all(q["pids"] == [proc.pid] for q in port_q)
        checks["pid_centric_agrees"] = all(q["ports"] == [rec["port"]] for q in pid_q)
    elif variant == "listener-persists-after-owner-process-death":
        proc, rec, _ = t.instance(["--grandchild", "inherit-listener"])
        gc = rec["descendants"][0]
        L.safe_kill(proc.pid, rec["start"], signal.SIGKILL); proc.wait(timeout=3); time.sleep(0.2)
        q = L.listeners(rec["port"])
        probe, _ = L.probe_identity(rec["port"], rec["nonce"])
        obs.update(listeners=q["pids"], recorded_main=proc.pid, recorded_descendant=gc["pid"], probe=probe)
        checks["listener_is_descendant_not_main"] = q["pids"] == [gc["pid"]]
        checks["port_listening_but_nobody_serving"] = probe == "NO_ANSWER"
    elif variant == "foreign-listener-after-exit":
        proc, rec, _ = t.instance()
        proc.send_signal(signal.SIGTERM); proc.wait(timeout=3); time.sleep(0.1)
        none_after = L.listeners(rec["port"])["pids"]
        dn, dt = t.nonce(), t.nonce(); t.tags.append(dt)
        d = subprocess.Popen([sys.executable, "-B", STANDIN, "--marker", run.marker, "--nonce", dn, "--port", str(rec["port"])],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=dict(os.environ, **{L.TAG_ENV: dt}), start_new_session=True)
        t.procs.append(d); ready = L.read_json_line(d.stdout, 5); t.track("foreign", L.identity(d.pid))
        q = L.listeners(rec["port"]); probe, payload = L.probe_identity(rec["port"], rec["nonce"])
        obs.update(listeners_before_decoy=none_after, listeners_with_decoy=q["pids"], decoy_pid=d.pid, probe=probe)
        checks["no_listener_right_after_exit"] = none_after == []
        checks["reports_the_foreign_pid"] = q["pids"] == [d.pid] and d.pid != proc.pid
        checks["foreign_nonce_is_OTHER"] = probe == "OTHER"
    elif variant == "reuseport-two-listeners":
        # bind ours with SO_REUSEPORT on a fixed port, then a second instance on the same port
        port = free_port()
        n1, n2, t1, t2 = t.nonce(), t.nonce(), t.nonce(), t.nonce(); t.tags += [t1, t2]
        a = subprocess.Popen([sys.executable, "-B", STANDIN, "--marker", run.marker, "--nonce", n1, "--port", str(port), "--reuseport"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(os.environ, **{L.TAG_ENV: t1}), start_new_session=True)
        t.procs.append(a); ra = L.read_json_line(a.stdout, 5); t.track("ours", L.identity(a.pid))
        b = subprocess.Popen([sys.executable, "-B", STANDIN, "--marker", run.marker, "--nonce", n2, "--port", str(port), "--reuseport"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(os.environ, **{L.TAG_ENV: t2}), start_new_session=True)
        t.procs.append(b); rb = L.read_json_line(b.stdout, 5); t.track("other", L.identity(b.pid))
        q = L.listeners(port)
        results = [L.probe_identity(port, n1)[0] for _ in range(12)]
        obs.update(listeners=q["pids"], probes=results, ours=a.pid, other=b.pid)
        checks["both_bound"] = bool(ra) and bool(rb)
        checks["lsof_lists_both"] = sorted(q["pids"]) == sorted([a.pid, b.pid])
        obs["probe_match_count"] = results.count("MATCH")
        obs["probe_other_count"] = results.count("OTHER")
    elif variant == "queries-under-cpu-load":
        proc, rec, _ = t.instance(["--spin"])
        lat = [L.listeners(rec["port"])["seconds"] for _ in range(5)]
        obs["lsof_seconds"] = [round(x, 4) for x in lat]
        ids = []
        for _ in range(50):
            t0 = time.monotonic(); L.identity(proc.pid); ids.append(time.monotonic() - t0)
        obs["identity_call_max_s"] = max(ids)
        checks["lsof_under_load_bounded_2s"] = max(lat) < 2.0
        checks["identity_calls_bounded_50ms"] = max(ids) < 0.05
    return obs, checks


def s7_bounded(run, t, variant, n):
    obs, checks = {}, {}
    if variant == "sigstopped-sigterm-pending":
        proc, rec, _ = t.instance()
        proc.send_signal(signal.SIGSTOP); time.sleep(0.1)
        proc.send_signal(signal.SIGTERM); time.sleep(0.5)
        i = L.identity(proc.pid)
        obs["alive_0_5s_after_sigterm"] = bool(i); obs["status"] = i["status"] if i else None
        checks["sigterm_does_not_terminate_stopped_process"] = bool(i)
        w = L.ExitWatch(proc.pid); t0 = time.monotonic(); proc.send_signal(signal.SIGKILL)
        ev = w.wait(2.0); obs["sigkill_exit_s"] = time.monotonic() - t0 if ev else None; w.close()
        checks["sigkill_terminates_stopped_process"] = ev is not None
        proc.wait(timeout=3)
    elif variant == "sigstopped-sigcont-delivers-pending-sigterm":
        proc, rec, _ = t.instance()
        proc.send_signal(signal.SIGSTOP); time.sleep(0.1); proc.send_signal(signal.SIGTERM); time.sleep(0.2)
        w = L.ExitWatch(proc.pid); t0 = time.monotonic(); proc.send_signal(signal.SIGCONT)
        ev = w.wait(3.0); obs["exit_after_sigcont_s"] = time.monotonic() - t0 if ev else None; w.close()
        checks["pending_sigterm_delivered_after_sigcont"] = ev is not None
        proc.wait(timeout=3)
    elif variant == "inflight-request-graceful":
        proc, rec, _ = t.instance()
        s = socket.create_connection(("127.0.0.1", rec["port"]), timeout=2)
        s.sendall(b"GET /slow?ms=5000 HTTP/1.0\r\n\r\n"); time.sleep(0.15)
        t0 = time.monotonic(); p, _ = L.probe_identity(rec["port"], rec["nonce"])
        obs["probe_during_request"] = p; obs["probe_seconds"] = time.monotonic() - t0
        checks["control_probe_served_during_generation_standin"] = p == "MATCH"
        w = L.ExitWatch(proc.pid); t0 = time.monotonic(); proc.send_signal(signal.SIGTERM)
        ev = w.wait(3.0); obs["sigterm_exit_s"] = time.monotonic() - t0 if ev else None; w.close()
        checks["exits_within_1s_with_request_in_flight"] = ev is not None and obs["sigterm_exit_s"] < 1.0
        s.close(); proc.wait(timeout=3)
    elif variant == "cpu-spin-escalation-budget":
        proc, rec, _ = t.instance(["--spin", "--ignore-sigterm"])
        w = L.ExitWatch(proc.pid); t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM); time.sleep(0.5); proc.send_signal(signal.SIGKILL)
        ev = w.wait(3.0); total = time.monotonic() - t0; w.close(); proc.wait(timeout=3)
        obs["total_escalation_s"] = total
        checks["escalation_total_under_1_5s"] = ev is not None and total < 1.5
    elif variant == "probe-bounded-when-nobody-serves":
        proc, rec, _ = t.instance(["--grandchild", "inherit-listener"])
        L.safe_kill(proc.pid, rec["start"], signal.SIGKILL); proc.wait(timeout=3); time.sleep(0.1)
        t0 = time.monotonic(); p, _ = L.probe_identity(rec["port"], rec["nonce"], timeout=0.5)
        el = time.monotonic() - t0
        obs["probe"] = p; obs["probe_seconds"] = el
        checks["probe_returns_NO_ANSWER_within_bound"] = p == "NO_ANSWER" and el < 1.2
    return obs, checks


SCENARIOS = [
    ("S1", "identity", s1_identity, ["direct", "with-grandchild", "wrapper-sh"]),
    ("S2", "graceful-termination", s2_graceful, ["plain", "with-grandchild"]),
    ("S3", "escalation-and-cleanup", s3_escalation,
     ["plain", "gc-same-pid-kill", "gc-same-group-kill", "gc-escaped", "gc-inherit-listener"]),
    ("S4", "owner-sigkill", s4_owner_sigkill,
     ["own-session", "owner-group", "watchdog-pipe", "watchdog-ignores-sigterm"]),
    ("S5", "successor-recovery", s5_successor,
     ["alive-after-owner-death", "dead-graceful", "dead-killed-after-owner-death",
      "pid-reuse-simulated-original-dead", "pid-reuse-simulated-original-alive",
      "port-reuse-foreign-listener", "sigstopped-alive-unresponsive", "wrapper-unverified-dead",
      "wrapper-unverified-alive", "late-grandchild-same-group",
      "late-grandchild-escaped-tag-inherited", "late-grandchild-escaped-tag-scrubbed",
      "record-missing-start", "nonce-only-alive", "nonce-only-dead"]),
    ("S6", "listener-ownership", s6_listener,
     ["steady-state", "listener-persists-after-owner-process-death", "foreign-listener-after-exit",
      "reuseport-two-listeners", "queries-under-cpu-load"]),
    ("S7", "bounded-control", s7_bounded,
     ["sigstopped-sigterm-pending", "sigstopped-sigcont-delivers-pending-sigterm",
      "inflight-request-graceful", "cpu-spin-escalation-budget", "probe-bounded-when-nobody-serves"]),
]


def run_trials(run, only):
    for sid, name, fn, variants in SCENARIOS:
        if only and sid not in only:
            continue
        for variant in variants:
            count = run.trials if not (sid == "S1" and variant == "wrapper-sh") else max(10, run.trials // 2)
            for n in range(count):
                t = Trial(run)
                row = {"scenario": sid, "name": name, "variant": variant, "trial": n, "ts": time.time()}
                t0 = time.monotonic()
                try:
                    obs, checks = fn(run, t, variant, n)
                    row.update(obs=obs, checks=checks, ok=all(checks.values()), error=None)
                except Exception as error:  # a harness or product error is data, never hidden
                    row.update(obs={}, checks={}, ok=False, error=repr(error))
                finally:
                    row["cleanup"] = t.cleanup()
                row["seconds"] = time.monotonic() - t0
                row["leak"] = bool(row["cleanup"]["remaining_after_cleanup"])
                run.emit(row)
            bad = [r for r in run.results if r["scenario"] == sid and r["variant"] == variant and not r["ok"]]
            print(f"{sid} {variant}: {count - len(bad)}/{count} ok", flush=True)


def real_pid_reuse(run, attempts, cap_seconds):
    """Bounded attempt to obtain *real* pid reuse: kill a recorded child, then fork until the
    kernel hands the same pid to a new process, hold it, and classify the unmodified record."""
    for a in range(attempts):
        t = Trial(run)
        row = {"scenario": "S5", "name": "successor-recovery", "variant": "pid-reuse-real", "trial": a, "ts": time.time()}
        t0 = time.monotonic()
        try:
            owner, rec, path = t.owned_instance("s5real")
            ws = watches_for(rec)
            L.safe_kill(rec["owner"]["pid"], rec["owner"]["start"], signal.SIGKILL); owner.wait(timeout=3)
            L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL)
            ok, _ = all_exited(ws, 3)
            target, forks, held = rec["pid"], 0, None
            while time.monotonic() - t0 < cap_seconds:
                r, w = os.pipe()
                pid = os.fork()
                if pid == 0:
                    os.close(w); os.read(r, 1); os._exit(0)
                os.close(r); forks += 1
                if pid == target:
                    held = (pid, w); break
                os.write(w, b"x"); os.close(w); os.waitpid(pid, 0)
            obs = {"forks": forks, "seconds": time.monotonic() - t0, "reused": held is not None,
                   "original_confirmed_dead": ok}
            checks = {}
            if held:
                now = L.identity(target)
                obs["reused_identity_start_differs"] = now["start"] != rec["start"]
                v = classify_fresh(path)
                obs.update(verdict_v1=v["v1_no_tag"]["verdict"], verdict_v2=v["v2_tag"]["verdict"])
                checks["start_time_distinguishes_reuse"] = obs["reused_identity_start_differs"]
                checks["original_declared_terminated"] = v["v2_tag"]["verdict"] == L.TERMINATED
                os.close(held[1]); os.waitpid(held[0], 0)
            else:
                checks["pid_reuse_obtained_within_cap"] = False
            row.update(obs=obs, checks=checks, ok=all(checks.values()), error=None)
        except Exception as error:
            row.update(obs={}, checks={}, ok=False, error=repr(error))
        finally:
            row["cleanup"] = t.cleanup()
        row["seconds"] = time.monotonic() - t0
        row["leak"] = bool(row["cleanup"]["remaining_after_cleanup"])
        run.emit(row)
        print(f"S5 pid-reuse-real attempt {a}: reused={row['obs'].get('reused')} forks={row['obs'].get('forks')} ok={row['ok']}", flush=True)


def summarize(run, host):
    by = {}
    for r in run.results:
        k = (r["scenario"], r["variant"])
        d = by.setdefault(k, {"trials": 0, "ok": 0, "errors": 0, "leaks": 0, "unsound_v1": 0, "unsound_v2": 0,
                              "verdicts_v1": {}, "verdicts_v2": {}, "failed_checks": {}})
        d["trials"] += 1; d["ok"] += 1 if r["ok"] else 0; d["errors"] += 1 if r["error"] else 0
        d["leaks"] += 1 if r["leak"] else 0
        o = r.get("obs", {})
        for k2 in ("unsound_v1", "unsound_v2"):
            d[k2] += 1 if o.get(k2) else 0
        for k2, key in (("verdicts_v1", "verdict_v1"), ("verdicts_v2", "verdict_v2")):
            if o.get(key):
                d[k2][o[key]] = d[k2].get(o[key], 0) + 1
        for c, v in r.get("checks", {}).items():
            if not v:
                d["failed_checks"][c] = d["failed_checks"].get(c, 0) + 1
    return {"host": host, "marker": run.marker, "variants": {f"{k[0]}/{k[1]}": v for k, v in sorted(by.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--only", default="")
    ap.add_argument("--reuse-real", type=int, default=0)
    ap.add_argument("--reuse-cap-seconds", type=float, default=150.0)
    a = ap.parse_args()
    run = Run(a.out, a.trials)
    host = {"os": platform.platform(), "python": platform.python_version(), "machine": platform.machine(),
            "kern_maxprocperuid": int(subprocess.run(["sysctl", "-n", "kern.maxprocperuid"], capture_output=True, text=True).stdout or 0)}
    print("run marker:", run.marker, flush=True)
    only = {s for s in a.only.split(",") if s}
    run_trials(run, only)
    if a.reuse_real:
        real_pid_reuse(run, a.reuse_real, a.reuse_cap_seconds)
    stray = [pid for pid, _ in marker_processes(run.marker)]
    summary = summarize(run, host)
    summary["final_audit_processes_with_marker"] = stray
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    print("final audit, processes still carrying the marker:", stray, flush=True)
    bad = sum(1 for r in run.results if not r["ok"])
    print(f"trials={len(run.results)} not_ok={bad}", flush=True)


if __name__ == "__main__":
    main()
