#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Synthetic stand-in for llama-server, used ONLY by the E3 pilot
tests. It is not llama.cpp and proves nothing about it. It accepts the E2-B command line, serves
/health, /slots and /v1/chat/completions on loopback, enforces a bearer key, keeps serving after its
launcher dies (like an orphan), and writes a log of every accepted TCP connection (uptime-clock
nanoseconds) next to the run directory so tests can prove that nothing connected after the owner
kill. The generation time comes from the request body field ``x_synthetic_gen_s`` (test fixtures
only). Modes (``--mode a,b``): normal, exit_after_gen, ignore_term, fork_child, no_processing,
slots_tokens, fork_late, die_on_start, processing_str, processing_int, slots_malformed. Standard library only; no model; no network beyond 127.0.0.1.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="normal")
ap.add_argument("--port", type=int, default=0)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--api-key-file")
ap.add_argument("--startup-delay", type=float, default=0.3)
ap.add_argument("--version", action="store_true")
ap.add_argument("--list-devices", action="store_true")
args, _unknown = ap.parse_known_args()
MODES = set(args.mode.split(","))

if args.version:
    print("version: 0.6.0-dev (build 11440, commit 1a3011cc0)")
    sys.exit(0)
if args.list_devices:
    print("Available devices:\n  MTL0: Synthetic GPU (stand-in)")
    sys.exit(0)
if "ignore_term" in MODES:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if "die_on_start" in MODES:
    sys.exit(1)

KEY = open(args.api_key_file).read().strip() if args.api_key_file else None
RUN_DIR = os.path.dirname(os.path.dirname(args.api_key_file)) if args.api_key_file else None
CONN_LOG = os.path.join(RUN_DIR, "conn.log") if RUN_DIR else None
REQ_LOG = os.path.join(RUN_DIR, "req.log") if RUN_DIR else None
T0 = time.monotonic()
busy = threading.Event()
decoded = [0]


def up_ns():
    return int(time.clock_gettime(time.CLOCK_UPTIME_RAW) * 1e9)


def log_req(method, path):
    if REQ_LOG:
        with open(REQ_LOG, "a") as f:
            f.write(f"{up_ns()} {method} {path}\n")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        return self.path == "/health" or KEY is None or self.headers.get("Authorization") == f"Bearer {KEY}"

    def do_GET(self):
        log_req("GET", self.path)
        if not self.authed():
            return self.send(401, {"error": {"code": 401}})
        if self.path == "/health":
            ready = time.monotonic() - T0 >= args.startup_delay
            return self.send(200 if ready else 503, {"status": "ok" if ready else "loading model"})
        if self.path == "/slots":
            slot = {"id": 0, "is_processing": busy.is_set() and "no_processing" not in MODES}
            if busy.is_set():  # wrong-typed "processing" values that a truthiness test would accept
                if "processing_str" in MODES:
                    slot["is_processing"] = "false"
                elif "processing_int" in MODES:
                    slot["is_processing"] = 1
                elif "slots_malformed" in MODES:
                    return self.send(200, ["busy", {"is_processing": True}])
            if "slots_tokens" in MODES:
                slot["next_token"] = [{"n_decoded": decoded[0]}]
            return self.send(200, [slot])
        self.send(404, {"error": "not found"})

    def do_POST(self):
        log_req("POST", self.path)
        if not self.authed():
            return self.send(401, {"error": {"code": 401}})
        n = int(self.headers.get("Content-Length") or 0)
        b = json.loads(self.rfile.read(n) or b"{}")
        if self.path != "/v1/chat/completions":
            return self.send(404, {"error": "not found"})
        gen = float(b.get("x_synthetic_gen_s", 0.6))
        busy.set()
        decoded[0] = 0
        try:
            end = time.monotonic() + gen
            while time.monotonic() < end:
                time.sleep(0.05)
                decoded[0] += 2
            out = "ok " * 20
            usage = {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60}
            self.send(200, {"choices": [{"message": {"content": out}, "finish_reason": "stop"}], "usage": usage})
        except OSError:
            pass
        finally:
            busy.clear()
        if "fork_late" in MODES:  # a descendant appears after the first generation (topology violation)
            subprocess.Popen(["/bin/sleep", "60"])
        if "exit_after_gen" in MODES:
            threading.Thread(target=lambda: (time.sleep(1.0), os._exit(0)), daemon=True).start()


class Srv(ThreadingHTTPServer):
    daemon_threads = True

    def get_request(self):
        conn, addr = super().get_request()
        if CONN_LOG:
            with open(CONN_LOG, "a") as f:
                f.write(f"{up_ns()} {addr[1]}\n")
        return conn, addr


srv = Srv((args.host, args.port), H)
print("listening", flush=True)
if "fork_child" in MODES:
    threading.Thread(target=lambda: (time.sleep(args.startup_delay + 0.2), subprocess.Popen(["/bin/sleep", "60"])), daemon=True).start()
threading.Thread(target=lambda: (time.sleep(150), os._exit(3)), daemon=True).start()  # leak backstop for tests
srv.serve_forever()
