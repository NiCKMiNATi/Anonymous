#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

Slice 0B-2 E2-B evidence support: pure decision logic (gate, stop conditions, authentication and
accounting classification), fixture verification, the persisted execution-record store, host
probes and owner-directed recovery. Standard library only. Reuses the E1 identity, listener,
tag-scan and classifier primitives unchanged.

Protocol: docs/evidence/v0-0b2-e2b-protocol.md. No prompt text lives in this file: fixtures are
external canonical JSON verified against full SHA-256 values pinned in e2b_pins.json.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e1_lib as L  # noqa: E402

TAG_ENV = "E2B_INSTANCE_TAG"
L.TAG_ENV = TAG_ENV  # E1's tag_scan/classify read this module global at call time

SANDBOX = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))'
SANDBOX_NOFORK = SANDBOX + "(deny process-fork)"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PROTOCOL_DOC = os.path.join(REPO, "docs", "evidence", "v0-0b2-e2b-protocol.md")
PINS_FILE = os.path.join(HERE, "e2b_pins.json")
DEFAULT_BENCH = os.path.expanduser("~/Library/Application Support/AnonymousRuntimeBench/20261006-v01")

# Numeric limits. Accepted ones are marked (A); the rest are the owner-reviewed protocol values.
LIMITS = {
    "gate_samples": 61, "gate_stale_s": 120.0,
    "swap_gate_mib": 64.0, "free_gate_pct": 30.0, "cpu_idle_gate_pct": 70.0, "disk_min_gib": 50.0,  # (A) disk
    "hid_idle_gate_s": 120.0, "hid_idle_advisory_s": 300.0, "attendance_lapse_margin_s": 120.0,
    "readiness_s": 120.0, "stage_s": 60.0, "call_s": 2.0, "p2_s": 90.0, "short_s": 30.0,
    "lifetime_s": 600.0, "term_s": 10.0, "kill_s": 5.0, "verify_s": 10.0, "post_sample_s": 60,
    "level2_s": 10.0, "swap_stop_mib": 512.0, "swap_stop_s": 10.0,  # (A) baseline J1
    "sampler_gap_s": 3.0, "sleep_skew_s": 2.0, "rss_cap_mib": 5120.0, "body_cap": 65536,
    # S13 (new): a safety observation may be missing this many consecutive ticks before the run stops.
    # Fast signals tick at 1 Hz (3 = the S6 sampler-gap bound); slow signals tick every 5 s (2 = 10 s).
    "probe_fast_misses": 3, "probe_slow_misses": 2, "baseline_samples": 10,
}

# --------------------------------------------------------------------------------------------
# canonical JSON, hashes, pins, fixtures


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return h.hexdigest()
            h.update(b)


def tree_manifest(root):
    """Every entry under ``root``: regular files as {bytes, sha256}, symlinks as their target text.
    Anything else (directories are only descended into) is reported so it cannot hide."""
    files, links, other = {}, {}, []
    for dp, dns, fns in os.walk(root):
        for name in sorted(dns + fns):
            path = os.path.join(dp, name)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                links[rel] = os.readlink(path)
            elif os.path.isdir(path):
                continue
            elif os.path.isfile(path):
                files[rel] = {"bytes": os.path.getsize(path), "sha256": sha256_file(path)}
            else:
                other.append(rel)
    return {"files": files, "links": links, "other": other}


def verify_tree(root, spec):
    """Compare the live tree with the pinned manifest. Fails closed: no pin, an extra, missing or
    changed file, a retargeted symlink, or a non-regular entry all fail. Returns {ok, problems}."""
    if not spec or "files" not in spec:
        return {"ok": False, "problems": ["no runtime tree pin"]}
    try:
        live = tree_manifest(root)
    except OSError as exc:
        return {"ok": False, "problems": [f"unreadable: {type(exc).__name__}"]}
    problems = []
    for kind, pinned, found in (("file", spec["files"], live["files"]), ("link", spec.get("links", {}), live["links"])):
        problems += [f"{kind} missing: {k}" for k in sorted(set(pinned) - set(found))]
        problems += [f"{kind} unpinned: {k}" for k in sorted(set(found) - set(pinned))]
        problems += [f"{kind} changed: {k}" for k in sorted(set(pinned) & set(found)) if pinned[k] != found[k]]
    problems += [f"non-regular entry: {k}" for k in live["other"]]
    return {"ok": not problems, "problems": problems, "files": len(live["files"]), "links": len(live["links"])}


def load_pins(path=PINS_FILE):
    with open(path) as f:
        return json.load(f)


class FixtureError(Exception):
    """Message names fixture ids and kinds of mismatch only, never fixture content."""


def load_fixtures(fx_dir, pins):
    """Read external canonical-JSON fixtures; require exact byte length, full SHA-256 and that the
    file bytes equal the canonical encoding of what they parse to. Returns (bodies, meta)."""
    bodies, problems = {}, []

    def read(fid, spec):
        try:
            with open(os.path.join(fx_dir, fid + ".json"), "rb") as f:
                raw = f.read()
        except OSError:
            problems.append(f"{fid}: unreadable")
            return None
        if len(raw) != spec["bytes"] or sha256_bytes(raw) != spec["sha256"]:
            problems.append(f"{fid}: length or sha256 mismatch")
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except ValueError:
            problems.append(f"{fid}: not json")
            return None
        if canon(obj) != raw:
            problems.append(f"{fid}: not canonical")
            return None
        return obj

    for fid, spec in pins["fixtures"].items():
        obj = read(fid, spec)
        if obj is not None:
            bodies[fid] = obj
    meta = read("meta", pins["meta"])
    for did, spec in pins.get("derived", {}).items():
        src = bodies.get(spec["from"])
        if src is None:
            continue
        raw = canon({"messages": src["messages"]})
        if len(raw) != spec["bytes"] or sha256_bytes(raw) != spec["sha256"]:
            problems.append(f"{did}: derived length or sha256 mismatch")
    if problems:
        raise FixtureError("; ".join(problems))
    return bodies, meta


def forbidden_strings(bodies, meta, extra=()):
    out = set(extra)
    for body in bodies.values():
        out.update(m["content"] for m in body["messages"])
    out.add(meta["label"])
    return sorted(s for s in out if s)


def scan_files(paths, forbidden):
    """Return [(path, index_of_forbidden_string)]; never returns the string itself."""
    hits = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            hits.append((p, -1))
            continue
        hits.extend((p, i) for i, s in enumerate(forbidden) if s in text)
    return hits


# --------------------------------------------------------------------------------------------
# host probes (read-only commands)


def run_cmd(cmd, timeout=5.0):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def parse_pmset_batt(text):
    m = re.search(r"drawing from '([^']+)'", text)
    return m.group(1) if m else None


def parse_swap_mib(text):
    m = re.search(r"used = ([\d.]+)([MG])", text)
    return None if not m else float(m.group(1)) * (1024.0 if m.group(2) == "G" else 1.0)


def parse_free_pct(text):
    m = re.search(r"free percentage: (\d+)%", text)
    return int(m.group(1)) if m else None


def parse_vm_counters(text):
    out = {}
    for k, v in re.findall(r'^"?([A-Za-z ]+?)"?:\s+(\d+)\.', text, re.M):
        out[k.strip()] = int(v)
    m = re.search(r"page size of (\d+) bytes", text)
    out["_page_size"] = int(m.group(1)) if m else None
    return out


def parse_top_idle(text):
    """Per-sample CPU idle percentages from ``top -l N`` output; the first sample is cumulative
    since boot and is dropped by the caller of this function's consumer (see ``cpu_window``)."""
    return [float(x) for x in re.findall(r"CPU usage:.*?([\d.]+)% idle", text)]


def cpu_window(text, n):
    """Exactly ``n`` usable samples (the since-boot first sample dropped) or None."""
    vals = parse_top_idle(text)[1:]
    return vals if len(vals) == n else None


def thermal_warning(text):
    """Fail closed: a warning unless both 'No ... warning level has been recorded' lines exist."""
    return not ("No thermal warning level has been recorded" in text
                and "No performance warning level has been recorded" in text)


def parse_hid_idle_s(text):
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', text)
    return int(m.group(1)) / 1e9 if m else None


def parse_boottime(text):
    m = re.search(r"sec = (\d+), usec = (\d+)", text)
    return [int(m.group(1)), int(m.group(2))] if m else None


def parse_pm_timers(text, section="AC Power"):
    """displaysleep/sleep minutes of one pmset -g custom section."""
    block = text.split(f"{section}:")[1] if f"{section}:" in text else ""
    block = block.split(":")[0] if ":" in block else block
    out = {}
    for key in ("displaysleep", "sleep"):
        m = re.search(rf"^\s*{key}\s+(\d+)", block, re.M)
        out[key] = int(m.group(1)) if m else None
    return out


def parse_display_awake_assertion(text):
    m = re.search(r"PreventUserIdleSystemSleep\s+(\d+)", text)
    return bool(m and int(m.group(1)) > 0)


COMPETING = re.compile(r"(?i)(llama-server|llama-cli|ollama|mlx_lm|lm studio|lms\b|caffeinate|sandbox-exec)")


def parse_procargs(raw):
    """KERN_PROCARGS2 -> (exec_path, argv). Environment is not returned."""
    argc = int.from_bytes(raw[:4], "little")
    exe, _, rest = raw[4:].partition(b"\0")
    parts = rest.lstrip(b"\0").split(b"\0")
    return exe.decode(errors="replace"), [p.decode(errors="replace") for p in parts[:argc]]


class HostProbes:
    """Real probes. ``run`` is injectable so tests can feed canned command output."""

    def __init__(self, run=run_cmd):
        self.run = run

    def power(self):
        return parse_pmset_batt(self.run(["pmset", "-g", "batt"]))

    def pressure(self):
        return int(self.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip())

    def swap_mib(self):
        return parse_swap_mib(self.run(["sysctl", "-n", "vm.swapusage"]))

    def free_pct(self):
        return parse_free_pct(self.run(["memory_pressure", "-Q"]))

    def vm(self):
        return parse_vm_counters(self.run(["vm_stat"]))

    def thermal_warn(self):
        return thermal_warning(self.run(["pmset", "-g", "therm"]))

    def hid_idle_s(self):
        return parse_hid_idle_s(self.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], 10.0))

    def boottime(self):
        return parse_boottime(self.run(["sysctl", "-n", "kern.boottime"]))

    def disk_gib(self, path="/System/Volumes/Data"):
        return shutil.disk_usage(path).free / 2 ** 30

    def competing(self):
        out = []
        for line in self.run(["ps", "-axo", "pid=,comm="]).splitlines():
            if COMPETING.search(line) and "e2b_" not in line:
                out.append(line.strip())
        return out

    def attendance(self):
        return {"hid_idle_s": self.hid_idle_s(),
                "display_awake_assertion": parse_display_awake_assertion(self.run(["pmset", "-g", "assertions"])),
                "ac_timers_min": parse_pm_timers(self.run(["pmset", "-g", "custom"]))}

    def sample(self):
        vm = self.vm()
        return {"wall": time.time(), "up": time.clock_gettime(time.CLOCK_UPTIME_RAW), "src": self.power(),
                "press": self.pressure(), "swap": self.swap_mib(), "free": self.free_pct(),
                "pageouts": vm.get("Pageouts"), "swapouts": vm.get("Swapouts")}


def uptime_and_wall():
    return time.clock_gettime(time.CLOCK_UPTIME_RAW), time.time()


# --------------------------------------------------------------------------------------------
# Phase 1 load gate (pure)


def window_continuity(win, lim=LIMITS):
    """The Phase 1 window must be one uninterrupted observation: consecutive samples obey the same
    gap and sleep-skew rules as S6, and both clocks advance. Fails closed on missing timing."""
    for i in range(1, len(win)):
        try:
            dwall, dup = win[i]["wall"] - win[i - 1]["wall"], win[i]["up"] - win[i - 1]["up"]
        except (KeyError, TypeError):
            return False, f"sample {i}: timing fields missing"
        if dwall <= 0 or dup <= 0:
            return False, f"sample {i}: clock did not advance (wall {dwall:.2f} s, uptime {dup:.2f} s)"
        if max(dwall, dup) > lim["sampler_gap_s"]:
            return False, f"sample {i}: sampler gap {max(dwall, dup):.1f} s"
        if dwall - dup > lim["sleep_skew_s"]:
            return False, f"sample {i}: system slept ({dwall - dup:.1f} s wall/uptime skew)"
    return True, f"{max(len(win) - 1, 0)} intervals contiguous"


def evaluate_gate(win, cpu_idle, ctx, n=None):
    """Return {id: {"ok": bool, "detail": str}}. ``win`` is the list of 1 Hz samples, ``cpu_idle``
    the per-second idle list over the SAME window (None if it could not be measured), ``ctx`` the
    single-shot facts (thermal, competing, disk, attendance, artifacts, clean_state)."""
    n = n or LIMITS["gate_samples"]
    g = {}

    def put(gid, ok, detail):
        g[gid] = {"ok": bool(ok), "detail": detail}

    full = len(win) == n
    put("WINDOW", full, f"{len(win)} samples (need exactly {n})")
    if not win:
        return g
    cont_ok, cont_detail = window_continuity(win)
    put("CONT", cont_ok, cont_detail)
    put("G1", full and all(s["src"] == "AC Power" for s in win), "AC Power in every sample")
    put("G2", full and all(s["press"] == 1 for s in win), f"max pressure level {max(s['press'] for s in win)}")
    swaps = [s["swap"] for s in win]
    put("G3", None not in swaps and max(swaps) - swaps[0] <= LIMITS["swap_gate_mib"],
        f"max swap rise {max(x for x in swaps if x is not None) - swaps[0]:.2f} MiB" if None not in swaps else "swap unreadable")
    po, so = win[-1]["pageouts"], win[-1]["swapouts"]
    po0, so0 = win[0]["pageouts"], win[0]["swapouts"]
    counters = None not in (po, so, po0, so0)
    put("G4", counters and po - po0 == 0 and so - so0 == 0,
        f"pageouts delta {po - po0 if counters else '?'}, swapouts delta {so - so0 if counters else '?'} (zero required)")
    frees = [s["free"] for s in win]
    put("G5", None not in frees and min(frees) >= LIMITS["free_gate_pct"], f"min free {min(f for f in frees if f is not None) if frees and any(f is not None for f in frees) else '?'}%")
    cpu_ok = cpu_idle is not None and len(cpu_idle) == n
    mean = sum(cpu_idle) / len(cpu_idle) if cpu_ok else None
    put("G6", cpu_ok and mean >= LIMITS["cpu_idle_gate_pct"],
        f"mean idle {mean:.1f}% min {min(cpu_idle):.1f}% over {len(cpu_idle)} window samples" if cpu_ok else "cpu window incomplete")
    put("G7", ctx.get("thermal_warning") is False, "no thermal/performance warning recorded")
    put("G8", ctx.get("competing") == [], f"{len(ctx.get('competing') or [])} competing process(es); names stay in the raw record")
    put("G9", ctx.get("disk_gib", 0) >= LIMITS["disk_min_gib"], f"{ctx.get('disk_gib', 0):.0f} GiB free")
    a = ctx.get("attendance") or {}
    hid = a.get("hid_idle_s")
    put("G10", bool(ctx.get("attended_flag")) and hid is not None and hid <= LIMITS["hid_idle_gate_s"]
        and a.get("display_awake_assertion") is True,
        f"flag={bool(ctx.get('attended_flag'))} hid_idle={hid} display_awake_assertion={a.get('display_awake_assertion')} timers={a.get('ac_timers_min')}")
    put("G11", ctx.get("artifacts", {}).get("ok") is True, str(ctx.get("artifacts", {}).get("detail")))
    put("G12", ctx.get("clean_state", {}).get("ok") is True, str(ctx.get("clean_state", {}).get("detail")))
    return g


def gate_passed(g):
    return bool(g) and all(v["ok"] for v in g.values())


# --------------------------------------------------------------------------------------------
# stop conditions (pure)

IMMEDIATE = {"S1", "S7", "S8", "S9"}
FAST_REQUIRED = ("press", "swap", "src")
SLOW_REQUIRED = ("thermal_warn", "disk_gib", "hid_idle_s")


class StopEvaluator:
    """Feed 1 Hz samples; get newly triggered stops. Nothing here signals a process."""

    def __init__(self, lim=LIMITS, swap_base=None):
        self.lim, self.prev, self.fired = lim, None, set()
        self.l2_since = self.swap_since = None
        self.swap_base = swap_base  # armed at construction when known, so S3 covers the model load
        self.miss = {}

    def set_phase_baseline(self, swap_mib):
        self.swap_base = swap_mib
        self.swap_since = None

    def _fire(self, out, sid, why, quarantine=False):
        """Once per (id, quarantine). A quarantining trigger is never swallowed by an earlier
        non-quarantining one of the same id, and a weaker one never repeats a stronger one."""
        if (sid, True) in self.fired or (sid, quarantine) in self.fired:
            return
        self.fired.add((sid, quarantine))
        out.append({"id": sid, "why": why, "immediate": sid in IMMEDIATE, "quarantine": quarantine})

    def _watch(self, out, name, available, limit):
        """S13: a safety observation that stays unavailable is not a healthy reading."""
        if available:
            self.miss[name] = 0
            return
        n = self.miss[name] = self.miss.get(name, 0) + 1
        if n >= limit:
            self._fire(out, "S13", f"safety observation unavailable: {name} ({n} consecutive ticks)")

    def feed(self, s):
        out, lim, up = [], self.lim, s["up"]
        for name in FAST_REQUIRED:
            self._watch(out, name, s.get(name) is not None, lim["probe_fast_misses"])
        if s.get("expect_rss"):
            self._watch(out, "rss", s.get("rss") is not None, lim["probe_fast_misses"])
        if s.get("slow"):
            for name in SLOW_REQUIRED:
                self._watch(out, name, s.get(name) is not None, lim["probe_slow_misses"])
            if s.get("expect_topology"):
                self._watch(out, "topology", s.get("observed") is True, lim["probe_slow_misses"])
        if s.get("press") == 4:
            self._fire(out, "S1", "pressure level 4")
        if s.get("press") == 2:
            self.l2_since = up if self.l2_since is None else self.l2_since
            if up - self.l2_since >= lim["level2_s"]:
                self._fire(out, "S2", "pressure level 2 for >= 10 s")
        else:
            self.l2_since = None
        if self.swap_base is not None and s.get("swap") is not None and s["swap"] > self.swap_base + lim["swap_stop_mib"]:
            self.swap_since = up if self.swap_since is None else self.swap_since
            if up - self.swap_since >= lim["swap_stop_s"]:
                self._fire(out, "S3", "swap > phase baseline + 512 MiB for >= 10 s")
        else:
            self.swap_since = None
        if s.get("src") is not None and s["src"] != "AC Power":
            self._fire(out, "S4", f"power source {s['src']}")
        if s.get("thermal_warn"):
            self._fire(out, "S5", "thermal or performance warning recorded")
        if self.prev is not None:
            dwall, dup = s["wall"] - self.prev["wall"], up - self.prev["up"]
            if dwall > lim["sampler_gap_s"] or dup > lim["sampler_gap_s"]:
                self._fire(out, "S6", f"sampler gap {max(dwall, dup):.1f} s")
            elif dwall - dup > lim["sleep_skew_s"]:
                self._fire(out, "S6", f"system slept ({dwall - dup:.1f} s wall/uptime skew)")
        self.prev = s
        if s.get("rss") is not None and s["rss"] > lim["rss_cap_mib"]:
            self._fire(out, "S7", f"runtime RSS {s['rss']:.0f} MiB")
        if s.get("tree"):
            self._fire(out, "S8", "topology violation: " + ",".join(map(str, s["tree"])), quarantine=True)
        if s.get("egress"):
            self._fire(out, "S9", "non-loopback socket: " + ",".join(map(str, s["egress"])), quarantine=True)
        if s.get("listen_bad"):
            self._fire(out, "S9", "listener/cache violation: " + ",".join(map(str, s["listen_bad"])))
        if s.get("disk_gib") is not None and s["disk_gib"] < lim["disk_min_gib"]:
            self._fire(out, "S11", "disk below 50 GiB")
        if s.get("life") is not None and s["life"] > lim["lifetime_s"]:
            self._fire(out, "S11", "lifetime exceeded 600 s")
        hid, ceiling = s.get("hid_idle_s"), s.get("hid_ceiling_s")
        if hid is not None and ceiling is not None and hid >= ceiling:
            self._fire(out, "S12", f"attendance lapse: {hid:.0f} s without operator input")
        return out


# --------------------------------------------------------------------------------------------
# authentication classification (S10 vs correct rejection)

AUTH_TARGETS = [("GET", "/health", "public"), ("GET", "/props", "expected"), ("GET", "/slots", "expected"),
                ("GET", "/v1/models", "expected"), ("POST", "/tokenize", "must"),
                ("POST", "/apply-template", "must"), ("POST", "/v1/chat/completions", "must")]
REJECT = (401, 403)


def auth_outcome(klass, cred, status):
    """Classify one authentication probe. ``cred`` is none | wrong | correct.

    S10 is true only for an UNAUTHORIZED success on a must-enforce endpoint. A correct 401/403 is
    REJECTED_OK and never triggers S10; an unusable answer is INDETERMINATE (stop, but not claimed
    as unauthorized access)."""
    ok2 = status is not None and 200 <= status < 300
    r = {"outcome": None, "s10": False, "stop": False, "finding": None}
    if cred == "correct":
        if ok2:
            r["outcome"] = "ACCEPTED_OK"
        elif status in REJECT:
            r.update(outcome="VALID_KEY_REJECTED", stop=True, finding="harness or key configuration error")
        else:
            r.update(outcome="NO_USABLE_ANSWER" if status is None else "UNEXPECTED_STATUS", stop=klass == "must")
        return r
    if klass == "public":
        r["outcome"] = "PUBLIC_OK" if ok2 else ("PUBLIC_REQUIRES_KEY" if status in REJECT else "PUBLIC_UNEXPECTED")
        r["finding"] = None if ok2 else r["outcome"]
    elif ok2:
        if klass == "must":
            r.update(outcome="UNAUTHORIZED_ACCESS", s10=True, stop=True, finding="AUTH_NOT_ENFORCED_MUST")
        else:
            r.update(outcome="AUTH_NOT_ENFORCED", finding="AUTH_NOT_ENFORCED")
    elif status in REJECT:
        r["outcome"] = "REJECTED_OK"
    else:
        r.update(outcome="INDETERMINATE", stop=klass == "must",
                 finding="AUTH_INDETERMINATE" if klass == "must" else None)
    return r


# --------------------------------------------------------------------------------------------
# template and token accounting (self-consistency only)


def check_template(rendered, messages):
    """Mandatory: every message content appears verbatim and in order, and the text ends with an
    assistant generation prefix. Expected (published Qwen3 template, unverified): an empty
    reasoning block follows the prefix when thinking is disabled."""
    pos, in_order = 0, True
    for m in messages:
        i = rendered.find(m["content"], pos)
        if i < 0:
            in_order = False
            break
        pos = i + len(m["content"])
    prefix = re.search(r"assistant\s*(<think>\s*</think>\s*)?$", rendered) is not None
    empty_think = re.search(r"<think>\s*</think>\s*$", rendered) is not None
    return {"mandatory_ok": in_order and prefix, "messages_in_order": in_order,
            "assistant_prefix": prefix, "empty_think_block": empty_think}


def classify_accounting(n_u, n_t, n_t_bos):
    if n_u is None or n_t is None:
        return "ACCOUNTING_UNEXPLAINED"
    if n_u == n_t:
        return "ACCOUNTING_CONSISTENT"
    if n_t_bos is not None and n_u == n_t_bos:
        return "ACCOUNTING_EXPLAINED_BOS"
    return "ACCOUNTING_UNEXPLAINED"


def parse_stream(raw):
    """SSE body -> (content, finish_reason, usage). Tolerates [DONE] and comment lines."""
    content, finish, usage = [], None, None
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        for ch in ev.get("choices") or []:
            content.append((ch.get("delta") or {}).get("content") or "")
            finish = ch.get("finish_reason") or finish
        usage = ev.get("usage") or usage
    return "".join(content), finish, usage


# --------------------------------------------------------------------------------------------
# persisted execution records

STATES = ["INTENT", "SPAWNED", "BOUND", "EXIT_VERIFIED"]


def atomic_write_json(path, obj):
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(obj, indent=1, sort_keys=True).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dfd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


OWNER_FLAGS = ("owner_review_required", "owner_review_reason")


class Records:
    """One JSON file per instance. Resolved means state EXIT_VERIFIED; anything else, including an
    unreadable or unknown file, is unresolved ownership and blocks new execution (fail closed).

    ``owner_review_required`` is sticky: once set it cannot be unset, a record carrying it is never
    advanced to EXIT_VERIFIED by this code, and it survives a failed write (the in-memory record keeps
    it so the next successful write includes it). A failed write never leaves the in-memory record
    claiming a state that was not persisted. Writers are serialised (monitor thread and main thread)."""

    def __init__(self, root):
        self.dir = os.path.join(root, "records")
        os.makedirs(root, mode=0o700, exist_ok=True)  # parents otherwise get the default umask
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, run_id):
        return os.path.join(self.dir, run_id + ".json")

    def read(self, run_id):
        with open(self.path(run_id)) as f:
            return json.load(f)

    def create(self, rec):
        with self._lock:
            if rec["state"] != "INTENT" or os.path.exists(self.path(rec["run_id"])):
                raise ValueError("a new record must be INTENT and must not already exist")
            atomic_write_json(self.path(rec["run_id"]), rec)
            return rec

    def _write(self, rec, snapshot):
        try:
            atomic_write_json(self.path(rec["run_id"]), rec)
        except BaseException:
            keep = {k: rec[k] for k in OWNER_FLAGS if k in rec}
            rec.clear()
            rec.update(snapshot)
            rec.update(keep)
            raise

    def advance(self, rec, state, **fields):
        with self._lock:
            cur = rec["state"]
            if cur == "EXIT_VERIFIED":
                raise ValueError("record already resolved")
            if state == "EXIT_VERIFIED" and rec.get("owner_review_required"):
                raise ValueError("a record flagged owner_review_required is never cleared by this tool")
            if state != "QUARANTINED":
                if cur == "QUARANTINED":
                    if state != "EXIT_VERIFIED":
                        raise ValueError("a quarantined record can only be cleared to EXIT_VERIFIED")
                elif STATES.index(state) <= STATES.index(cur):
                    raise ValueError(f"illegal transition {cur} -> {state}")
            snapshot = json.loads(json.dumps(rec))
            if rec.get("owner_review_required"):
                fields["owner_review_required"] = True
            rec.update(fields)
            rec["state"] = state
            rec.setdefault("history", []).append({"state": state, "utc": time.time()})
            self._write(rec, snapshot)
            return rec

    def annotate(self, rec, **fields):
        """Persist extra facts without a state transition. Cannot touch a resolved record and can
        never lower owner_review_required."""
        with self._lock:
            if rec["state"] == "EXIT_VERIFIED":
                raise ValueError("record already resolved")
            if rec.get("owner_review_required"):
                fields["owner_review_required"] = True
            snapshot = json.loads(json.dumps(rec))
            rec.update(fields)
            self._write(rec, snapshot)
            return rec

    def unresolved(self):
        out = []
        for name in sorted(os.listdir(self.dir)):
            p = os.path.join(self.dir, name)
            if not os.path.isfile(p):
                continue
            try:
                with open(p) as f:
                    st = json.load(f).get("state")
            except (OSError, ValueError, AttributeError):
                st = "UNREADABLE"
            if not (name.endswith(".json") and ".tmp." not in name and st == "EXIT_VERIFIED"):
                out.append((name, st))
        return out


class RunLockHeld(RuntimeError):
    pass


@contextlib.contextmanager
def run_lock(root):
    """Exclusive, non-blocking; released by the kernel if the harness dies. Held by ``run`` for the
    whole run and taken by ``recover``, so recovery can never race a live run."""
    os.makedirs(root, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(root, "run.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RunLockHeld("another E2-B harness (or a recovery) holds the run lock")
    try:
        yield
    finally:
        os.close(fd)


def check_authorization(root, phases, protocol_doc=PROTOCOL_DOC, now=None):
    """The owner places AUTHORIZATION.json; it binds to the protocol document hash."""
    p = os.path.join(root, "AUTHORIZATION.json")
    try:
        with open(p) as f:
            a = json.load(f)
        doc_hash = sha256_file(protocol_doc)
    except (OSError, ValueError):
        return False, "authorization or protocol document unreadable"
    now = now or time.time()
    if a.get("scope") != "base":
        return False, "scope must be 'base' (Option C and A/B control are not implemented)"
    if a.get("protocol_sha256") != doc_hash:
        return False, "authorization does not match the current protocol document hash"
    if not set(phases) <= set(a.get("phases", [])):
        return False, f"phases {sorted(set(phases))} not all authorized"
    if not isinstance(a.get("expires_epoch"), (int, float)) or a["expires_epoch"] < now:
        return False, "authorization expired or has no expiry"
    return True, "ok"


# --------------------------------------------------------------------------------------------
# tree policy and recovery


def tree_policy(root, descendants, group_extra, tagged):
    """Decide what may be signalled. Only the recorded root and descendants whose identity was
    captured in the same observation are killable; tagged strangers and group members outside the
    tree are reported, never signalled; nothing is signalled by process group."""
    root_key = (root["pid"], tuple(root["start"]))
    tree = {(d["pid"], tuple(d["start"])): d for d in descendants}
    killable = [{"pid": root["pid"], "start": list(root["start"]), "role": "root"}]
    killable += [{"pid": d["pid"], "start": list(d["start"]), "role": "descendant"} for d in descendants]
    strangers = {}
    for i in list(group_extra) + list(tagged):
        key = (i["pid"], tuple(i["start"]))
        if key != root_key and key not in tree:
            strangers[key] = {"pid": i["pid"], "start": list(i["start"])}
    return {"killable": killable, "strangers": list(strangers.values()),
            "violation": bool(descendants or strangers)}


def kill_identified(targets, sig=signal.SIGKILL):
    """Signal each target only if the kernel still reports exactly (pid, start). pid-only and
    group signals are never used."""
    return {t["pid"]: L.safe_kill(t["pid"], t["start"], sig) for t in targets}


def _kill_recorded(rec, rep, kill_fn, sleep):
    """Signal the recorded root and every recorded or currently reachable descendant, each only if
    the kernel still reports exactly its (pid, start). Never by group, never an unidentified process."""
    seen = {}
    for i in list(rec.get("descendants", [])) + L.descendants(rec["pid"]):
        seen[(i["pid"], tuple(i["start"]))] = i
    pol = tree_policy({"pid": rec["pid"], "start": rec["start"]}, list(seen.values()), [], [])
    rep["actions"].append({"killed": kill_fn(pol["killable"])})
    sleep(0.5)


def recover(records, run_id, current_boottime, kill=False, confirm=None, sleep=time.sleep, kill_fn=kill_identified):
    """Owner-directed recovery of one unresolved record. Takes the run lock first, so it cannot race
    a live run (a held lock is reported, nothing is read or changed). Read-only unless kill and
    confirm == run_id.

    Admissible evidence for clearing: (a) the boot time differs from the recorded one (no process
    of a previous boot exists) with an empty tag scan; (b) E1 classify() says PROVEN_TERMINATED for
    a SPAWNED/BOUND record. An INTENT-only record (identity-binding window) is INDETERMINATE
    on the same boot and is never cleared. A policy-quarantined record (owner_review_required) is
    never cleared here, but ``--kill`` still terminates its identified processes. Returns a report."""
    try:
        with run_lock(os.path.dirname(records.dir)):
            return _recover_locked(records, run_id, current_boottime, kill, confirm, sleep, kill_fn)
    except RunLockHeld as exc:
        return {"run_id": run_id, "actions": [], "verdict": "REFUSED_RUN_LOCK_HELD", "why": str(exc)}


def _recover_locked(records, run_id, current_boottime, kill, confirm, sleep, kill_fn):
    rec = records.read(run_id)
    rep = {"run_id": run_id, "state_before": rec["state"], "actions": []}
    confirmed = bool(kill and confirm == run_id)
    if rec["state"] == "EXIT_VERIFIED":
        return dict(rep, verdict="ALREADY_RESOLVED")
    if rec.get("owner_review_required"):
        # Policy quarantine (topology violation, non-loopback socket, unauthorized access): process
        # termination evidence does not lift it and this tool never attests on the owner's behalf.
        # Terminating the identified processes is still permitted so no orphan stays running.
        if confirmed and rec.get("pid") and rec.get("start"):
            _kill_recorded(rec, rep, kill_fn, sleep)
            rep["process_state_after"] = L.classify(rec)[0]
        return dict(rep, verdict="QUARANTINE_OWNER_REVIEW", why=rec.get("owner_review_reason") or rec.get("reason"))
    tagged_now = L.tag_scan(rec["tag"]) if rec.get("tag") else []
    rep["tagged_live"] = [i["pid"] for i in tagged_now]
    if rec.get("boottime") and rec["boottime"] != current_boottime and not tagged_now:
        records.advance(rec, "EXIT_VERIFIED", exit_basis="boot_time_changed", cleared_by="recover")
        return dict(rep, verdict=L.TERMINATED, basis="boot_time_changed", state_after=rec["state"])
    if rec["state"] in ("INTENT",) or not (rec.get("pid") and rec.get("start")):
        cands = []
        for i in tagged_now:
            raw = L.procargs(i["pid"])
            exe, argv = parse_procargs(raw) if raw else (None, None)
            cands.append({"pid": i["pid"], "start": i["start"],
                          "argv_matches_intent": argv in (rec.get("argv_full"), rec.get("argv_target"))})
        rep["candidates"] = cands
        if confirmed:
            todo = [c for c in cands if c["argv_matches_intent"]]
            rep["actions"].append({"killed": kill_fn(todo)})
            rep["unidentified_not_signalled"] = [c["pid"] for c in cands if not c["argv_matches_intent"]]
        return dict(rep, verdict=L.INDETERMINATE,
                    why="identity-binding window: no recorded pid/start; absence is not evidence on the same boot")
    verdict, why, obs = L.classify(rec)
    if verdict == L.ALIVE and confirmed:
        _kill_recorded(rec, rep, kill_fn, sleep)
        verdict, why, obs = L.classify(rec)
    rep.update(verdict=verdict, why=why)
    if verdict == L.TERMINATED:
        records.advance(rec, "EXIT_VERIFIED", exit_basis="successor_classify", cleared_by="recover")
        rep["state_after"] = "EXIT_VERIFIED"
    return rep
