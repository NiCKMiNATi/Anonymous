#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

Slice 0B-2 E1 evidence support: macOS process identity, exit observation, listener ownership
and a conservative alive/terminated/indeterminate classifier, standard library only
(ctypes -> libproc, select.kqueue, lsof, ps). Synthetic, loopback-only, no network access.
Nothing here is a design choice for Anonymous; it measures what the OS can prove.

Plan: .agent/plans/2026-10-12-slice-0b2-runtime-evidence.md (E1).
"""

import ctypes
import ctypes.util
import json
import os
import select
import signal
import socket
import subprocess
import sys
import time

PROC_PIDTBSDINFO = 3
PROC_ALL_PIDS = 1
PROC_PGRP_ONLY = 2
SIDL, SRUN, SSLEEP, SSTOP, SZOMB = 1, 2, 3, 4, 5
STATUS_NAMES = {SIDL: "idle", SRUN: "run", SSLEEP: "sleep", SSTOP: "stopped", SZOMB: "zombie"}
TAG_ENV = "E1_INSTANCE_TAG"

ALIVE = "PROVEN_ALIVE"
TERMINATED = "PROVEN_TERMINATED"
INDETERMINATE = "INDETERMINATE"


class ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64),
    ]


assert ctypes.sizeof(ProcBsdInfo) == 136, "libproc struct layout changed"
_libproc = ctypes.CDLL(ctypes.util.find_library("proc"), use_errno=True)
_libproc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                  ctypes.c_void_p, ctypes.c_int]
_libproc.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]


def identity(pid):
    """Kernel-reported identity of ``pid`` or None when the kernel has no such process.

    The tuple (pid, start_s, start_us) is issued by the kernel at process creation; a reused pid
    has a different start time. A zombie is reported with status 'zombie' (exited, not reaped)."""
    if pid is None or pid <= 0:
        return None
    info = ProcBsdInfo()
    n = _libproc.proc_pidinfo(int(pid), PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    if n != ctypes.sizeof(info):
        return None
    return {"pid": int(info.pbi_pid), "start": [int(info.pbi_start_tvsec), int(info.pbi_start_tvusec)],
            "ppid": int(info.pbi_ppid), "pgid": int(info.pbi_pgid),
            "status": STATUS_NAMES.get(int(info.pbi_status), str(info.pbi_status))}


def list_pids(flavor=PROC_ALL_PIDS, arg=0):
    size = _libproc.proc_listpids(flavor, arg, None, 0)
    if size <= 0:
        return []
    for _ in range(4):  # the table can grow between the two calls
        buf = (ctypes.c_int * (size // 4 + 64))()
        got = _libproc.proc_listpids(flavor, arg, buf, ctypes.sizeof(buf))
        if 0 <= got < ctypes.sizeof(buf):
            return [p for p in buf[: got // 4] if p > 0]
        size = got + 256
    return []


def group_members(pgid):
    """Live (non-zombie) members of a process group as identities."""
    out = []
    for pid in list_pids(PROC_PGRP_ONLY, pgid):
        i = identity(pid)
        if i and i["status"] != "zombie":
            out.append(i)
    return out


def descendants(root_pid):
    """Identities of the process tree below root (by ppid), root excluded, at this instant."""
    table = {}
    for pid in list_pids():
        i = identity(pid)
        if i:
            table[pid] = i
    out, frontier = [], [root_pid]
    while frontier:
        parent = frontier.pop()
        for pid, i in table.items():
            if i["ppid"] == parent and pid != root_pid and i["status"] != "zombie" and i not in out:
                out.append(i)
                frontier.append(pid)
    return out


def same_identity(rec_pid, rec_start, ident):
    return bool(ident) and ident["pid"] == rec_pid and ident["start"] == list(rec_start)


def listeners(port, timeout=3.0):
    """Port-centric listener query via lsof (OS-backed; sees only this user's processes)."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
                           capture_output=True, text=True, timeout=timeout)
        pids = sorted({int(l[1:]) for l in r.stdout.splitlines() if l.startswith("p")})
        return {"pids": pids, "rc": r.returncode, "seconds": time.monotonic() - t0, "timeout": False}
    except subprocess.TimeoutExpired:
        return {"pids": [], "rc": None, "seconds": time.monotonic() - t0, "timeout": True}


def listener_ports_of(pid, timeout=3.0):
    """Pid-centric query: TCP LISTEN ports held by ``pid``."""
    try:
        r = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN", "-Fn"],
                           capture_output=True, text=True, timeout=timeout)
        ports = sorted({int(l.rsplit(":", 1)[1]) for l in r.stdout.splitlines() if l.startswith("n")})
        return {"ports": ports, "rc": r.returncode, "timeout": False}
    except subprocess.TimeoutExpired:
        return {"ports": [], "rc": None, "timeout": True}


def probe_identity(port, expect_nonce, timeout=0.5):
    """Application-level probe. MATCH / OTHER / NO_ANSWER. A reported nonce proves only that
    something answers with it; NO_ANSWER or OTHER prove nothing about the bound instance."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"GET /identity HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        body = data.split(b"\r\n\r\n", 1)[1]
        payload = json.loads(body.decode())
        return ("MATCH" if payload.get("nonce") == expect_nonce else "OTHER"), payload
    except (OSError, ValueError, IndexError):
        return "NO_ANSWER", None


_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
CTL_KERN, KERN_PROCARGS2 = 1, 49


def procargs(pid):
    """Raw KERN_PROCARGS2 (argv + environment) of a same-user process, or None. Finding (E1):
    ``ps -axeww`` does not print the environment on this macOS, ``ps eww -p PID`` does, and this
    per-pid sysctl is the reliable, fast route; other users' and system processes return None."""
    mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, int(pid))
    size = ctypes.c_size_t(1 << 20)
    buf = ctypes.create_string_buffer(size.value)
    if _libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return None
    return buf.raw[: size.value]


def tag_scan(tag):
    """Live processes carrying the instance tag in their environment (inherited across fork and
    exec unless scrubbed). Only this user's processes are inspectable."""
    needle = f"{TAG_ENV}={tag}".encode() + b"\0"
    out = []
    for pid in list_pids():
        args = procargs(pid)
        if args and needle in args:
            i = identity(pid)
            if i and i["status"] != "zombie":
                out.append(i)
    return out


class ExitWatch:
    """Kernel exit notification (kqueue EVFILT_PROC / NOTE_EXIT). Works for non-children."""

    def __init__(self, pid):
        self.kq = select.kqueue()
        self.registered = True
        ev = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                           flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
        try:
            self.kq.control([ev], 0, 0)
        except OSError as error:  # ESRCH: nothing to watch (already gone or never existed)
            self.registered = False
            self.error = repr(error)

    def wait(self, timeout):
        if not self.registered:
            return None
        events = self.kq.control(None, 1, timeout)
        return events[0] if events else None

    def close(self):
        self.kq.close()


# --------------------------------------------------------------------------------------------
# classifier

def classify(record, use_tag=True):
    """Conservative successor-side classification from a persisted record plus OS observation.

    PROVEN_ALIVE      positive evidence that the bound instance (or a recorded descendant) runs.
    PROVEN_TERMINATED requires ALL of: complete record with a verified listener binding; kernel
                      reports no live process with the recorded (pid, start); no recorded
                      descendant alive; no unrecorded live member in the recorded process group;
                      (use_tag) no live process carrying the instance tag.
    INDETERMINATE     everything else. Never sufficient on its own: pid absence, absence of a
                      listener, a missing or foreign nonce answer, a reused pid.
    """
    obs, why = {}, []
    pid, start = record.get("pid"), record.get("start")
    ident = identity(pid) if pid else None
    obs["identity_at_pid"] = ident
    same = same_identity(pid, start, ident) if (pid and start) else False
    alive_same = same and ident["status"] != "zombie"
    zombie_same = same and ident["status"] == "zombie"
    recorded = {(d["pid"], tuple(d["start"])) for d in record.get("descendants", [])}
    if pid and start:
        recorded.add((pid, tuple(start)))
    live_recorded = []
    for key in sorted(recorded):
        i = identity(key[0])
        if i and tuple(i["start"]) == key[1] and i["status"] != "zombie":
            live_recorded.append(i)
    obs["live_recorded"] = [(i["pid"], i["status"]) for i in live_recorded]
    pgid = record.get("pgid")
    group = group_members(pgid) if pgid else []
    unrecorded_group = [i for i in group if (i["pid"], tuple(i["start"])) not in recorded]
    obs["unrecorded_group_members"] = [i["pid"] for i in unrecorded_group]
    port, nonce = record.get("port"), record.get("nonce")
    lst = listeners(port) if port else {"pids": [], "rc": None, "timeout": False}
    obs["listeners"] = lst
    probe, _ = probe_identity(port, nonce) if (port and nonce) else ("NO_ANSWER", None)
    obs["probe"] = probe
    tagged = tag_scan(record["tag"]) if (use_tag and record.get("tag")) else []
    tagged_unrecorded = [i for i in tagged if (i["pid"], tuple(i["start"])) not in recorded]
    obs["tagged_live"] = [i["pid"] for i in tagged]
    obs["tagged_unrecorded"] = [i["pid"] for i in tagged_unrecorded]

    if alive_same:
        return ALIVE, ["recorded (pid, start) is live"], obs
    if live_recorded:
        return ALIVE, ["a recorded descendant is live"], obs
    if tagged:
        return ALIVE, ["a live process carries the instance tag"], obs
    if probe == "MATCH":
        return ALIVE, ["the recorded port answers with the recorded nonce"], obs
    if not (pid and start):
        return INDETERMINATE, ["record lacks pid or start time; absence of a pid is not evidence"], obs
    if not record.get("binding_verified"):
        return INDETERMINATE, ["listener binding was never verified for the recorded pid"], obs
    if unrecorded_group:
        return INDETERMINATE, ["live unrecorded member(s) in the recorded process group"], obs
    if zombie_same:
        why.append("recorded process has exited (zombie, not reaped)")
    elif ident is None:
        why.append("kernel reports no process at the recorded pid")
    else:
        why.append("pid now belongs to a different process (start time differs): original is gone")
    if lst["pids"]:
        why.append("a foreign listener holds the port; not treated as ownership evidence")
    return TERMINATED, why, obs


def safe_kill(pid, start, sig):
    """Signal only a process whose kernel identity still equals (pid, start)."""
    i = identity(pid)
    if not same_identity(pid, start, i) or i["status"] == "zombie":
        return False
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False


def read_json_line(stream, timeout):
    deadline = time.monotonic() + timeout
    buf = b""
    fd = stream.fileno()
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], max(0.0, deadline - time.monotonic()))
        if not r:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        buf += chunk
        if b"\n" in buf:
            return json.loads(buf.split(b"\n", 1)[0].decode())
    return None


HERE = os.path.dirname(os.path.abspath(__file__))
STANDIN = os.path.join(HERE, "e1_standin.py")


def spawn_instance(marker, tag, nonce, standin_args=(), new_session=True, watchdog=False,
                   wrapper=False, timeout=8.0):
    """Start a stand-in, wait for its ready line, and build the persisted record.

    Returns (popen, record, watchdog_write_fd). The record is what a successor would persist:
    kernel identity, listener binding verification, recorded descendants, process group, tag."""
    env = dict(os.environ)
    env[TAG_ENV] = tag
    pass_fds = ()
    wd_r = wd_w = None
    args = [sys.executable, "-B", STANDIN, "--marker", marker, "--nonce", nonce, *standin_args]
    if wrapper:  # the spawned pid is a shell; the listener is its child (the wrapper-pid trap)
        args = ["/bin/sh", "-c", '"$@" & wait', "sh", *args]
    if watchdog:
        wd_r, wd_w = os.pipe()
        args += ["--watchdog-fd", str(wd_r)]
        pass_fds = (wd_r,)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                            start_new_session=new_session, pass_fds=pass_fds)
    if wd_r is not None:
        os.close(wd_r)
    ready = read_json_line(proc.stdout, timeout)
    if not ready:
        raise RuntimeError("stand-in did not become ready")
    ident = identity(proc.pid)
    lst = listeners(ready["port"])
    probe, payload = probe_identity(ready["port"], nonce)
    verified = (lst["pids"] == [proc.pid] and probe == "MATCH" and payload.get("pid") == proc.pid
                and payload.get("start") == ident["start"])
    time.sleep(0.15)  # let any startup grandchild appear before recording
    record = {
        "v": 1, "pid": proc.pid, "start": ident["start"], "pgid": ident["pgid"],
        "port": ready["port"], "nonce": nonce, "tag": tag, "binding_verified": bool(verified),
        "listener_pids_at_bind": lst["pids"], "descendants": descendants(proc.pid),
        "recorded_at": time.time(),
    }
    return proc, record, wd_w


if __name__ == "__main__":  # successor mode: classify a persisted record in a fresh process
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("classify")
    ap.add_argument("--record", required=True)
    a = ap.parse_args()
    rec = json.load(open(a.record))
    out = {}
    for name, use_tag in (("v1_no_tag", False), ("v2_tag", True)):
        t0 = time.monotonic()
        verdict, why, obs = classify(rec, use_tag=use_tag)
        out[name] = {"verdict": verdict, "why": why, "obs": obs, "seconds": time.monotonic() - t0}
    print(json.dumps(out))
