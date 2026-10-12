#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Disposable stand-in for an external runtime (E1).

A loopback-only HTTP server with controllable misbehaviour. It is NOT llama.cpp and proves
nothing about it: it exists so process-control facts can be measured without a model.
Standard library only; synthetic data only; every instance self-terminates after --max-life
seconds as a leak backstop (observation windows in E1 are far shorter).
"""

import argparse
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--role", default="server", choices=["server", "grandchild"])
ap.add_argument("--marker", required=True)
ap.add_argument("--nonce", required=True)
ap.add_argument("--port", type=int, default=0)
ap.add_argument("--ignore-sigterm", action="store_true")
ap.add_argument("--grandchild", default="none",
                choices=["none", "same", "escaped", "inherit-listener", "escaped-scrubbed"])
ap.add_argument("--watchdog-fd", type=int, default=None)
ap.add_argument("--spin", action="store_true", help="busy-loop one thread (CPU-bound child)")
ap.add_argument("--reuseport", action="store_true")
ap.add_argument("--max-life", type=float, default=90.0)
args = ap.parse_args()

started = time.monotonic()
children = []


def spawn_grandchild(mode, listen_fd=None):
    cmd = [sys.executable, "-B", os.path.abspath(__file__), "--role", "grandchild",
           "--marker", args.marker, "--nonce", args.nonce, "--max-life", str(args.max_life)]
    env = dict(os.environ)
    kw = {}
    if mode.startswith("escaped"):
        kw["start_new_session"] = True
    if mode == "escaped-scrubbed":
        env.pop(e1_lib.TAG_ENV, None)
    if mode == "inherit-listener":
        kw["pass_fds"] = (listen_fd,)
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    children.append(p)
    return p


def lifetime_guard():
    while time.monotonic() - started < args.max_life:
        time.sleep(0.25)
    os._exit(3)


threading.Thread(target=lifetime_guard, daemon=True).start()

if args.role == "grandchild":
    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(0.25)

me = e1_lib.identity(os.getpid())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/identity"):
            self.reply({"nonce": args.nonce, "pid": os.getpid(), "start": me["start"]})
        elif self.path.startswith("/slow"):
            time.sleep(float(self.path.split("ms=")[-1]) / 1000.0 if "ms=" in self.path else 1.0)
            self.reply({"nonce": args.nonce, "slow": True})
        elif self.path.startswith("/spawn-late"):
            mode = self.path.split("mode=")[-1] if "mode=" in self.path else "same"
            spawn_grandchild(mode)
            self.reply({"spawned": True, "mode": mode})
        else:
            self.send_error(404)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self):
        if args.reuseport:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        super().server_bind()


server = Server(("127.0.0.1", args.port), Handler)
port = server.server_address[1]


def graceful(signum, frame):
    threading.Thread(target=server.shutdown, daemon=True).start()


signal.signal(signal.SIGTERM, signal.SIG_IGN if args.ignore_sigterm else graceful)

if args.watchdog_fd is not None:
    def watchdog():
        try:
            while os.read(args.watchdog_fd, 1):
                pass
        except OSError:
            pass
        os._exit(0)  # owner end closed: the owner is gone
    threading.Thread(target=watchdog, daemon=True).start()

if args.spin:
    def spin():
        while True:
            pass
    threading.Thread(target=spin, daemon=True).start()

if args.grandchild != "none":
    spawn_grandchild(args.grandchild, listen_fd=server.socket.fileno())

print(json.dumps({"ready": True, "pid": os.getpid(), "port": port, "start": me["start"]}), flush=True)
try:
    server.serve_forever(poll_interval=0.05)
finally:
    server.server_close()
    for c in children:
        try:
            c.terminate()
        except OSError:
            pass
    sys.exit(0)
