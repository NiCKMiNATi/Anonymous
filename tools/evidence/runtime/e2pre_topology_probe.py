#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. E2 preflight: process topology of the already-acquired
llama-server b11440 binary WITHOUT loading any model.

Technique: a router-mode server is started with a preset whose only model points at a path that
does not exist, then asked to load it. The router spawns a model-instance child, the child fails
to load (nothing to load) and exits; during its short life we record its identity, process group,
session, environment inheritance, listening sockets and what happens when the router is killed.
Single-model mode (-m on a missing path) is observed the same way.

Safety: loopback only; --offline; LLAMA_CACHE is an empty temp directory; no -hf/--hf-repo, no
POST /models (the download endpoint) and no real model path is ever passed; the whole tree runs
under a best-effort sandbox profile denying non-loopback outbound (effect not verified); every
signal goes to a process whose kernel identity (pid, start time) was recorded by this script, and
leftovers are swept by the per-run environment tag.

Run: python3 -B e2pre_topology_probe.py --binary PATH --out FILE.jsonl [--trials 10]
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib as L  # noqa: E402

SANDBOX = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))'
# same profile plus a kernel-enforced refusal to create any new process (fork/posix_spawn)
SANDBOX_NOFORK = SANDBOX + '(deny process-fork)'


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(port, method, path, body=None, timeout=2.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            data = json.dumps(body).encode() if body is not None else b""
            hdr = f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n"
            s.sendall(hdr.encode() + data)
            buf = b""
            while True:
                c = s.recv(65536)
                if not c:
                    break
                buf += c
        head, _, rest = buf.partition(b"\r\n\r\n")
        code = int(head.split(b" ", 2)[1])
        return code, rest.decode(errors="replace")
    except (OSError, ValueError, IndexError):
        return None, ""


def sid(pid):
    try:
        return os.getsid(pid)
    except OSError:
        return None


def env_facts(pid, tag):
    raw = L.procargs(pid)
    if raw is None:
        return {"readable": False}
    return {"readable": True, "has_tag": f"{L.TAG_ENV}={tag}".encode() in raw,
            "has_router_port_var": b"LLAMA_SERVER_ROUTER_PORT=" in raw,
            "has_child_mode_var": b"LLAMA_SERVER_CHILD_MODE=" in raw}


def fd_summary(pid, router_port):
    """Which sockets/pipes the process holds, via lsof (same user only)."""
    try:
        r = subprocess.run(["lsof", "-nP", "-p", str(pid), "-Fftn"], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return {"error": "lsof_timeout"}
    types, names = [], []
    cur = {}
    for line in r.stdout.splitlines():
        if line.startswith("f"):
            if cur:
                types.append(cur)
            cur = {}
        elif line.startswith("t"):
            cur["t"] = line[1:]
        elif line.startswith("n"):
            cur["n"] = line[1:]
    if cur:
        types.append(cur)
    listen = [c["n"] for c in types if c.get("t") in ("IPv4", "IPv6") and "LISTEN" in c.get("n", "")]
    holds_router_listener = any(f":{router_port}" in c.get("n", "") and "LISTEN" in c.get("n", "") for c in types)
    kinds = {}
    for c in types:
        kinds[c.get("t", "?")] = kinds.get(c.get("t", "?"), 0) + 1
    return {"fd_kinds": kinds, "listen_sockets": [n.split("->")[0] for n in listen],
            "holds_router_listening_socket": holds_router_listener}


class Tree:
    """One launched server plus everything we may need to clean up, by recorded identity."""

    def __init__(self, cmd, tag, cache, profile=None):
        env = dict(os.environ, LLAMA_CACHE=cache, HF_HUB_OFFLINE="1", **{L.TAG_ENV: tag})
        self.tag = tag
        self.proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile or SANDBOX] + cmd, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        self.ident = L.identity(self.proc.pid)
        self.t0 = time.monotonic()

    def sweep(self):
        killed = []
        for i in L.tag_scan(self.tag):
            if L.safe_kill(i["pid"], i["start"], signal.SIGKILL):
                killed.append(i["pid"])
        try:
            self.proc.kill()
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        return killed, [i["pid"] for i in L.tag_scan(self.tag)]

    def output(self, cache):
        try:
            os.set_blocking(self.proc.stdout.fileno(), False)
            tail = (self.proc.stdout.read() or b"").decode(errors="replace")
        except (OSError, ValueError):
            tail = ""
        return [l.replace(cache, "<cache>").replace(os.path.expanduser("~"), "~") for l in tail.splitlines()]


def wait_ready(port, tree, limit=25.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if tree.proc.poll() is not None:
            return None
        code, _ = http(port, "GET", "/health", timeout=0.5)
        if code == 200:
            return time.monotonic() - t0
        time.sleep(0.2)
    return None


def find_child(router_pid, router_ident, limit=8.0):
    """Poll tightly for a descendant of the router; return its identity and first-seen time."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        d = L.descendants(router_pid)
        if d:
            return d, time.monotonic() - t0
        time.sleep(0.003)
    return [], None


def observe_child(child, tag, router_port, router_pid, with_fds):
    """Cheap facts (identity, group, session, environment) always; lsof-based fd facts only when
    asked, because lsof takes tens to hundreds of ms and the model-less child is short-lived."""
    obs = {"pid": child["pid"], "ppid": child["ppid"], "pgid": child["pgid"], "sid": sid(child["pid"]),
           "same_pgid_as_router": child["pgid"] == router_pid, "same_sid_as_router": sid(child["pid"]) == sid(router_pid)}
    obs.update(env_facts(child["pid"], tag))
    if with_fds:
        obs["fds"] = fd_summary(child["pid"], router_port)
    return obs


def wait_gone(ident, limit):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        cur = L.identity(ident["pid"])
        if not L.same_identity(ident["pid"], ident["start"], cur) or cur["status"] == "zombie":
            return time.monotonic() - t0
        time.sleep(0.002)
    return None


def router_trial(binary, variant, workdir, keep_log=False):
    cache = tempfile.mkdtemp(prefix="e2pre-cache-", dir=workdir)
    ini = os.path.join(workdir, f"preset-{os.urandom(3).hex()}.ini")
    with open(ini, "w") as f:
        f.write("version = 1\n[synthetic-missing]\nmodel = %s\n" % os.path.join(workdir, "does-not-exist.gguf"))
    port, tag = free_port(), os.urandom(8).hex()
    cmd = [binary, "--host", "127.0.0.1", "--port", str(port), "--offline", "--no-webui", "--models-preset", ini,
           "--models-max", "1"]
    tree = Tree(cmd, tag, cache, profile=(SANDBOX_NOFORK if variant == "router_load_under_deny_fork" else None))
    rec = {"mode": "router", "variant": variant, "router_pid": tree.proc.pid, "router_start": tree.ident["start"] if tree.ident else None,
           "router_pgid": tree.ident["pgid"] if tree.ident else None, "router_sid": sid(tree.proc.pid)}
    try:
        rec["router_ready_s"] = wait_ready(port, tree)
        if rec["router_ready_s"] is None:
            rec["error"] = "router_not_ready"
            return rec
        before = L.descendants(tree.proc.pid)
        rec["children_before_load"] = len(before)
        rec["router_listener_pids"] = L.listeners(port)["pids"]
        # the record an owner would have persisted before any request: the router only; its
        # model-instance children do not exist yet and are therefore not recorded
        persisted = {"pid": tree.proc.pid, "start": tree.ident["start"], "pgid": tree.ident["pgid"], "port": port,
                     "nonce": None, "tag": tag, "binding_verified": rec["router_listener_pids"] == [tree.proc.pid],
                     "descendants": []}
        code, body = http(port, "POST", "/models/load", {"model": "synthetic-missing"})
        rec["load_request_status"] = code
        kids, seen_at = find_child(tree.proc.pid, tree.ident, limit=(2.0 if variant == "router_load_under_deny_fork" else 8.0))
        if variant == "router_load_under_deny_fork":
            time.sleep(0.5)
            rec["router_alive_after_load_attempt"] = tree.proc.poll() is None
            code, body = http(port, "GET", "/models")
            try:
                data = json.loads(body)
                rec["router_models_after"] = [{"id": m.get("id"), "status": (m.get("status") or {}).get("value")} for m in data.get("data", [])]
            except ValueError:
                rec["router_models_after"] = None
            rec["children_seen"] = len(kids)
            rec["any_descendant_after_0.5s"] = len(L.descendants(tree.proc.pid))
            return rec
        rec["child_first_seen_after_load_s"] = seen_at
        rec["children_seen"] = len(kids)
        if not kids:
            rec["note"] = "no child observed"
            return rec
        child = kids[0]
        child_watch = L.ExitWatch(child["pid"])
        t_seen = time.monotonic()
        rec["child"] = observe_child(child, tag, port, tree.proc.pid, with_fds=False)
        if variant == "observe_stopped_child":
            # freeze the short-lived child (by verified identity) so slow observers can see it
            rec["child_stopped"] = L.safe_kill(child["pid"], child["start"], signal.SIGSTOP)
            rec["child"]["fds"] = fd_summary(child["pid"], port)
            rec["router_listener_pids_with_child"] = L.listeners(port)["pids"]
            rec["child_listener_ports"] = L.listener_ports_of(child["pid"])
        alive_now = L.same_identity(child["pid"], child["start"], L.identity(child["pid"]))
        rec["child_alive_when_observed"] = alive_now
        rec["observation_took_s"] = time.monotonic() - t_seen

        if variant == "observe_stopped_child":
            rec["child_alive_when_observed_after_slow_queries"] = L.same_identity(child["pid"], child["start"], L.identity(child["pid"]))
            L.safe_kill(child["pid"], child["start"], signal.SIGCONT)
            ev = child_watch.wait(30.0)
            rec["child_lifetime_after_first_seen_s"] = (time.monotonic() - t_seen) if ev else None
            rec["child_exit_event"] = ev is not None
            time.sleep(0.3)
            code, body = http(port, "GET", "/models")
            rec["router_models_after"] = None
            try:
                data = json.loads(body.partition("\r\n\r\n")[2] or body)
                rec["router_models_after"] = [{"id": m.get("id"), "status": (m.get("status") or {}).get("value")} for m in data.get("data", [])]
            except ValueError:
                pass
        elif variant in ("router_sigkill", "router_sigkill_child_stopped"):
            if variant == "router_sigkill_child_stopped":
                rec["child_stopped"] = L.safe_kill(child["pid"], child["start"], signal.SIGSTOP)
            os.kill(tree.proc.pid, signal.SIGKILL)
            rec["router_gone_after_s"] = wait_gone(tree.ident, 3.0)
            cur = L.identity(child["pid"])
            same = L.same_identity(child["pid"], child["start"], cur)
            rec["child_alive_right_after_router_death"] = same and cur["status"] != "zombie"
            rec["child_ppid_after"] = cur["ppid"] if same else None
            if variant == "router_sigkill_child_stopped":
                time.sleep(0.5)
                cur = L.identity(child["pid"])
                rec["child_alive_0.5s_later_while_stopped"] = L.same_identity(child["pid"], child["start"], cur) and cur["status"] != "zombie"
                v1, why1, _ = L.classify(persisted, use_tag=False)
                v2, why2, _ = L.classify(persisted, use_tag=True)
                rec["classify_router_dead_child_alive"] = {"binding_verified": persisted["binding_verified"], "v1_no_tag": v1,
                                                           "v1_why": why1, "v2_tag": v2, "v2_why": why2}
                L.safe_kill(child["pid"], child["start"], signal.SIGCONT)
            rec["child_gone_after_router_death_s"] = wait_gone(child, 10.0)
            if variant == "router_sigkill_child_stopped":
                v1, _, _ = L.classify(persisted, use_tag=False)
                v2, _, _ = L.classify(persisted, use_tag=True)
                rec["classify_everything_gone"] = {"v1_no_tag": v1, "v2_tag": v2}
        elif variant == "router_sigterm":
            t1 = time.monotonic()
            os.kill(tree.proc.pid, signal.SIGTERM)
            rec["router_gone_after_sigterm_s"] = wait_gone(tree.ident, 20.0)
            rec["child_gone_after_sigterm_s"] = wait_gone(child, 20.0)
            rec["sigterm_total_s"] = time.monotonic() - t1
        child_watch.close()
        killed, remaining = tree.sweep()
        rec["swept"] = killed
        rec["remaining_after_sweep"] = remaining
        return rec
    finally:
        killed, remaining = tree.sweep()
        rec.setdefault("swept", killed)
        rec["remaining_after_sweep"] = remaining
        out_lines = tree.output(cache)
        rec["router_output_lines"] = len(out_lines)
        rec["router_output_head"] = [l.replace(workdir, "<work>") for l in out_lines[:60]] if keep_log else None
        rec["router_log_spawn_lines"] = [l.replace(workdir, "<work>")[:200] for l in out_lines if "spawn" in l.lower() or "fork" in l.lower()][:4]
        rec["cache_dir_empty_after"] = os.listdir(cache) == []
        rec["ok"] = not remaining
        try:
            os.rmdir(cache)
            os.unlink(ini)
        except OSError:
            pass


def single_trial(binary, workdir, deny_fork=False):
    cache = tempfile.mkdtemp(prefix="e2pre-cache-", dir=workdir)
    port, tag = free_port(), os.urandom(8).hex()
    cmd = [binary, "--host", "127.0.0.1", "--port", str(port), "--offline", "--no-webui", "-m",
           os.path.join(workdir, "does-not-exist.gguf")]
    tree = Tree(cmd, tag, cache, profile=(SANDBOX_NOFORK if deny_fork else None))
    rec = {"mode": "single", "variant": "missing_model_file_under_deny_fork" if deny_fork else "missing_model_file",
           "pid": tree.proc.pid}
    try:
        samples, t0 = [], time.monotonic()
        listening_at = None
        while time.monotonic() - t0 < 25 and tree.proc.poll() is None:
            if listening_at is None and L.listeners(port)["pids"]:
                listening_at = time.monotonic() - t0
                code, _ = http(port, "GET", "/health")
                rec["health_while_listening"] = code
            samples.append(len(L.descendants(tree.proc.pid)))
            time.sleep(0.05)
        rec["exited_by_itself"] = tree.proc.poll() is not None
        rec["exit_code"] = tree.proc.poll()
        rec["lifetime_s"] = time.monotonic() - t0
        rec["listened_before_exit_after_s"] = listening_at
        rec["max_descendants_seen"] = max(samples) if samples else 0
        return rec
    finally:
        killed, remaining = tree.sweep()
        out = tree.output(cache)
        rec["output_tail"] = out[-6:]
        rec["remaining_after_sweep"] = remaining
        rec["ok"] = not remaining
        try:
            os.rmdir(cache)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=10)
    a = ap.parse_args()
    workdir = tempfile.mkdtemp(prefix="e2pre-")
    variants = ["observe_stopped_child", "router_sigkill", "router_sigkill_child_stopped", "router_sigterm", "router_load_under_deny_fork"]
    n_ok = n = 0
    with open(a.out, "w") as out:
        out.write(json.dumps({"binary_version": subprocess.run([a.binary, "--version"], capture_output=True, text=True, timeout=20).stderr.strip().splitlines()[:2],
                              "sandbox_profile": SANDBOX}) + "\n")
        for v in variants:
            for t in range(a.trials):
                r = router_trial(a.binary, v, workdir, keep_log=(t == 0))
                r["trial"] = t
                out.write(json.dumps(r, default=str) + "\n")
                out.flush()
                n += 1
                n_ok += bool(r.get("ok"))
                print(v, t, "ok" if r.get("ok") else "NOT-OK", r.get("child_alive_when_observed"), flush=True)
        for deny in (False, True):
            for t in range(a.trials):
                r = single_trial(a.binary, workdir, deny_fork=deny)
                r["trial"] = t
                out.write(json.dumps(r, default=str) + "\n")
                out.flush()
                n += 1
                n_ok += bool(r.get("ok"))
                print("single", "deny_fork" if deny else "plain", t, "ok" if r.get("ok") else "NOT-OK", flush=True)
    try:
        for f in os.listdir(workdir):
            os.unlink(os.path.join(workdir, f))
        os.rmdir(workdir)
    except OSError:
        pass
    print(f"trials={n} clean_cleanup={n_ok}")


if __name__ == "__main__":
    main()
