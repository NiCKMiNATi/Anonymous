#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Optional E1 probe of the already-acquired llama-server b11440
binary WITHOUT any model. Observations here are about this one binary and are reported
separately from the stand-in results; they say nothing about inference.

No model is downloaded or loaded. --offline is passed, LLAMA_CACHE points at an empty directory,
and the process runs under a best-effort macOS sandbox profile that denies non-loopback outbound
networking (whether the profile took effect is recorded, not assumed). Loopback only, bounded
to --seconds, and the process is always terminated by verified identity.

Run: python3 -B e1_llama_probe.py --binary PATH --out FILE.json [--seconds 8]
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


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_get(port, path, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
            data = b""
            while True:
                c = s.recv(4096)
                if not c:
                    break
                data += c
        head, _, body = data.partition(b"\r\n\r\n")
        return {"status_line": head.split(b"\r\n")[0].decode(errors="replace"), "body_len": len(body),
                "body_head": body[:200].decode(errors="replace")}
    except OSError as e:
        return {"error": type(e).__name__}


def sanitize(text, *paths):
    for p in paths:
        text = text.replace(p, "<path>")
    return text.replace(os.path.expanduser("~"), "~")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=8.0)
    a = ap.parse_args()
    out = {"binary_version": subprocess.run([a.binary, "--version"], capture_output=True, text=True, timeout=20).stderr.strip().splitlines()[:2]}
    cache = tempfile.mkdtemp(prefix="e1-llama-cache-")
    port = free_port()
    tag = os.urandom(8).hex()
    env = dict(os.environ, LLAMA_CACHE=cache, HF_HUB_OFFLINE="1", **{L.TAG_ENV: tag})
    cmd = [a.binary, "--host", "127.0.0.1", "--port", str(port), "--offline", "--no-webui"]
    sandboxed = ["/usr/bin/sandbox-exec", "-p", SANDBOX] + cmd
    out["command"] = [os.path.basename(cmd[0])] + cmd[1:]
    out["sandbox_profile"] = SANDBOX
    t0 = time.monotonic()
    proc = subprocess.Popen(sandboxed, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)
    out["spawned_pid"] = proc.pid
    samples, listening_at = [], None
    try:
        while time.monotonic() - t0 < a.seconds:
            if proc.poll() is not None:
                break
            lst = L.listeners(port)
            if lst["pids"] and listening_at is None:
                listening_at = time.monotonic() - t0
            samples.append({"t": round(time.monotonic() - t0, 2), "listeners": lst["pids"],
                            "descendants": [d["pid"] for d in L.descendants(proc.pid)]})
            time.sleep(0.5)
        out["exited_by_itself"] = proc.poll() is not None
        out["exit_code"] = proc.poll()
        out["listening_after_s"] = listening_at
        out["samples"] = samples[:12]
        if proc.poll() is None:
            ident = L.identity(proc.pid)
            lst = L.listeners(port)
            out["identity"] = ident
            out["listener_pids"] = lst["pids"]
            out["spawned_pid_is_listener"] = lst["pids"] == [proc.pid]
            out["http"] = {p: http_get(port, p) for p in ("/health", "/props", "/v1/models")}
            desc = L.descendants(proc.pid)
            out["descendant_count"] = len(desc)
            sandbox_wrapper = ident is not None
            rec = {"pid": proc.pid, "start": ident["start"], "pgid": ident["pgid"], "port": port, "nonce": None,
                   "tag": tag, "binding_verified": lst["pids"] == [proc.pid], "descendants": desc}
            v, why, obs = L.classify(rec)
            out["classify_while_running"] = {"verdict": v, "why": why, "tagged_live": obs["tagged_live"]}
            ws = [(d["pid"], L.ExitWatch(d["pid"])) for d in desc]
            w = L.ExitWatch(proc.pid)
            t1 = time.monotonic()
            os.kill(proc.pid, signal.SIGTERM)
            ev = w.wait(5.0)
            out["sigterm_exit_s"] = (time.monotonic() - t1) if ev else None
            out["sigterm_exit_observed"] = ev is not None
            time.sleep(0.5)
            out["descendants_alive_after_main_exit"] = [d["pid"] for d in desc if L.same_identity(d["pid"], d["start"], L.identity(d["pid"]))]
            v2, why2, obs2 = L.classify(rec)
            out["classify_after_sigterm"] = {"verdict": v2, "why": why2, "listeners": obs2["listeners"]["pids"],
                                           "tagged_live": obs2["tagged_live"]}
            w.close()
            for _, x in ws:
                x.close()
        tail = b""
        try:
            os.set_blocking(proc.stdout.fileno(), False)
            tail = proc.stdout.read() or b""
        except (OSError, ValueError):
            pass
        out["output_head"] = [sanitize(l, cache) for l in tail.decode(errors="replace").splitlines()[:25]]
        out["output_lines_total"] = len(tail.decode(errors="replace").splitlines())
    finally:
        # verified cleanup: this process, its recorded descendants, and anything carrying the tag
        for i in L.tag_scan(tag):
            L.safe_kill(i["pid"], i["start"], signal.SIGKILL)
        ident = L.identity(proc.pid)
        if ident and ident["status"] != "zombie":
            os.killpg(proc.pid, signal.SIGKILL) if ident["pgid"] == proc.pid else None
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        out["remaining_tagged_after_cleanup"] = [i["pid"] for i in L.tag_scan(tag)]
        out["cache_dir_empty_after"] = os.listdir(cache) == []
        try:
            os.rmdir(cache)
        except OSError:
            pass
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    print(json.dumps({k: out.get(k) for k in ("exited_by_itself", "exit_code", "listening_after_s", "descendant_count", "sigterm_exit_observed")}))


if __name__ == "__main__":
    main()
