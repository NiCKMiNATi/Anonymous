#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Synthetic stand-in for llama-server, used ONLY by the E2-B
harness tests. It is not llama.cpp and proves nothing about it: it accepts the same command line,
serves the endpoints the harness uses on loopback, enforces a bearer key like the real server is
expected to, and misbehaves on request (--mode). Standard library only; no model; no network
beyond 127.0.0.1 (or 0.0.0.0 only in the deliberate listen_all mode).
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
ap.add_argument("--chat-delay", type=float, default=0.6)
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
    print("synthetic failure: cannot load model")
    sys.exit(1)

KEY = open(args.api_key_file).read().strip() if args.api_key_file else None
T0 = time.monotonic()
busy = threading.Event()
PUBLIC = {"/health"}
UNAUTH_OK = set()
if "no_auth_chat" in MODES:
    UNAUTH_OK |= {"/v1/chat/completions", "/tokenize", "/apply-template"}
if "no_auth_slots" in MODES:
    UNAUTH_OK |= {"/slots"}


def ntok(text):
    return len(text) // 4 + 1


def render(messages):
    out = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n"
    return out if "wrong_template" in MODES else out + "<think>\n\n</think>\n\n"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        if self.headers.get("Authorization"):
            print("BEARER_SEEN", flush=True)  # lets a test prove no credential reached an unverified listener
        if self.path in PUBLIC or self.path in UNAUTH_OK or KEY is None:
            return True
        return self.headers.get("Authorization") == f"Bearer {KEY}"

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self.authed():
            return self.send(401, {"error": {"code": 401, "message": "Invalid API Key"}})
        if self.path == "/health":
            ready = time.monotonic() - T0 >= args.startup_delay and "never_ready" not in MODES
            return self.send(200 if ready else 503, {"status": "ok" if ready else "loading model"})
        if self.path == "/props":
            return self.send(200, {"build_info": "b11440-1a3011cc0", "model_path": "synthetic.gguf"})
        if self.path == "/v1/models":
            return self.send(200, {"data": [{"id": "synthetic"}]})
        if self.path == "/slots":
            return self.send(200, [{"id": 0, "is_processing": busy.is_set()}])
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.authed():
            return self.send(401, {"error": {"code": 401, "message": "Invalid API Key"}})
        b = self.body()
        if self.path == "/apply-template":
            return self.send(200, {"prompt": render(b["messages"])})
        if self.path == "/tokenize":
            n = ntok(b.get("content", "")) + (1 if b.get("add_special") else 0)
            return self.send(200, {"tokens": list(range(n))})
        if self.path == "/v1/chat/completions":
            print("GEN request", flush=True)
            if "crash_in_chat" in MODES:
                os._exit(9)
            if "chat_error" in MODES:
                return self.send(500, {"error": {"code": 500, "message": "synthetic failure"}})
            busy.set()
            try:
                time.sleep(100 if "slow_chat" in MODES else args.chat_delay)
                n_out = min(b.get("max_tokens", 16), 20)
                finish = "length" if b.get("max_tokens", 16) <= 20 else "stop"
                n_in = ntok(render(b["messages"])) + (7 if "token_mismatch" in MODES else 0)
                usage = {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out}
                if b.get("stream"):
                    ev = [{"choices": [{"delta": {"content": "ok " * n_out}, "finish_reason": None}]},
                          {"choices": [{"delta": {}, "finish_reason": finish}], "usage": usage}]
                    raw = ("".join(f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n").encode()
                    return self.send(200, None, raw=raw, ctype="text/event-stream")
                return self.send(200, {"choices": [{"message": {"content": "ok " * n_out}, "finish_reason": finish}],
                                       "usage": usage, "timings": {"cache_n": 0}})
            finally:
                busy.clear()
        self.send(404, {"error": "not found"})


srv = ThreadingHTTPServer(("0.0.0.0" if "listen_all" in MODES else args.host, args.port), H)
srv.daemon_threads = True
print("listening", flush=True)


def after_ready():
    time.sleep(args.startup_delay + 0.2)
    if "try_fork" in MODES:
        try:
            subprocess.Popen(["/bin/sleep", "30"]).kill()
            print("FORK_ALLOWED", flush=True)
        except OSError as e:
            print(f"FORK_DENIED errno={e.errno}", flush=True)
    if "fork_child" in MODES:  # an env-inheriting descendant, for the topology-violation test
        subprocess.Popen(["/bin/sleep", "60"])


threading.Thread(target=after_ready, daemon=True).start()
threading.Thread(target=lambda: (time.sleep(120), os._exit(3)), daemon=True).start()  # leak backstop
srv.serve_forever()
