#!/usr/bin/env python3
"""Tests for the E3 pilot harness. Standard library only (unittest); macOS (sandbox-exec, libproc,
kqueue). Everything runs against the synthetic stand-in runtime (e3_fake_runtime.py): the real model
and the real llama-server are never started, no real authorization is created, and no real bench
folder is touched (every test builds its own temporary bench). A real SIGKILL of a synthetic owner
process is part of the integration tests. Test fixtures use their own synthetic strings, never the
approved experiment fixtures.

Run: python3 -B test_e3.py            (all)      python3 -B test_e3.py TestTrigger  (one class)
"""

import ast
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e2b_harness as H  # noqa: E402
import e2b_lib as E  # noqa: E402
import e3_harness as D  # noqa: E402
import e3_lib as T  # noqa: E402
from test_e2b import TOP4, StubProbes, alive, make_env  # noqa: E402

FAKE3 = os.path.join(HERE, "e3_fake_runtime.py")

# Short bounds for tests; the production values are T.BOUNDS (asserted separately).
BT = dict(T.BOUNDS, arm_delay_s=0.4, poll_interval_s=0.05, stale_s=0.2, prekill_abort_s=6.0, idle_after_reader_s=1.0,
          orphan_max_s=8.0, backstop_s=14.0, successor_term_s=1.5, successor_kill_s=1.0, verify_s=1.5, backstop_verify_s=3.0, min_margin_s=0.5,
          owner_dead_s=3.0, owner_shutdown_s=15.0, reader_deadline_s=20.0, classify_offsets_s=(0.1, 0.5, 1.0), classify_period_s=1.0)


def make_env3(tmp, mode="normal", gen_s=3.0, extra_fixture=None, startup_delay=0.3):
    spec = make_env(tmp, mode)
    bench = spec["bench"]
    wrapper = spec["binary"]
    with open(wrapper, "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" -B "{FAKE3}" --mode {mode} --startup-delay {startup_delay} "$@"\n')
    os.chmod(wrapper, 0o755)
    pins = spec["pins"]
    pins["runtime"]["binary_sha256"] = E.sha256_file(wrapper)
    tree = E.tree_manifest(os.path.join(bench, "tools"))
    pins["runtime"]["tree"] = {"files": tree["files"], "links": tree["links"]}
    fx = os.path.join(bench, "fixtures", "e3")
    os.makedirs(fx, exist_ok=True)
    body = {"messages": [{"role": "system", "content": "unit-test e3 system alpha"}, {"role": "user", "content": "unit-test e3 ask bravo"}],
            "max_tokens": 384, "temperature": 0, "seed": 42, "stream": False, "cache_prompt": False, "x_synthetic_gen_s": gen_s}
    body.update(extra_fixture or {})
    raw = E.canon(body)
    with open(os.path.join(fx, "G.json"), "wb") as f:
        f.write(raw)
    e3pins = {"fixture_g": {"state": T.APPROVED, "bytes": len(raw), "sha256": E.sha256_bytes(raw), "max_tokens": 384}}
    root = os.path.join(bench, "e3")
    os.makedirs(root, mode=0o700, exist_ok=True)
    spec.update(e3pins=e3pins, root=root, fixtures=fx, forbidden=["unit-test e3 system alpha", "unit-test e3 ask bravo"])
    write_auth(spec)
    return spec


def write_auth(spec, **over):
    a = {"scope": T.SCOPE, "variant": "V1", "lifetimes": 1, "authorization_id": "auth-" + os.path.basename(spec["bench"])[:12] + "-1",
         "protocol_sha256": E.sha256_file(spec["doc"]), "implementation_sha256": T.implementation_hashes(),
         "fixture_g_sha256": spec["e3pins"]["fixture_g"]["sha256"], "expires_epoch": time.time() + 3600, "authorized_by": "unit test"}
    a.update(over)
    with open(T.auth_path(spec["root"]), "w") as f:
        json.dump(a, f)
    return a


def cfg3(spec, **kw):
    return D.make_config(spec["bench"], pins=spec["pins"], binary=spec["binary"], model=spec["model"], port=spec["port"],
                         protocol_doc=spec["doc"], readiness_s=kw.pop("readiness_s", 15.0), control_runs=kw.pop("control_runs", 2),
                         control_c3_runs=kw.pop("control_c3_runs", 1), log_runner=lambda c: "", **kw)


def recorded_identities(root):
    """(label, pid, start) of every process the records of a test bench name: the runtime, the Owner, the recorded
    descendants. Test hygiene only."""
    d = os.path.join(root, "records")
    out = []
    for name in os.listdir(d) if os.path.isdir(d) else []:
        try:
            rec = json.load(open(os.path.join(d, name)))
        except (OSError, ValueError):
            continue
        if rec.get("pid") and rec.get("start"):
            out.append(("runtime", rec["pid"], rec["start"]))
        o = rec.get("owner") or {}
        if o.get("pid") and o.get("start"):
            out.append(("owner", o["pid"], o["start"]))
        out += [("descendant", x["pid"], x["start"]) for x in rec.get("descendants", []) if x.get("pid") and x.get("start")]
    return out


def kill_recorded_and_verify_gone(root, timeout=10.0):
    """Test hygiene only: SIGKILL anything the records name, by recorded identity, and tagged strays, then check that no
    LIVE process with each identity remains. It does not wait for or reap anything (it has no wait handle for processes that
    are not its own children). Three different facts, kept apart:
      identity disappearance   the (pid, start) is no longer a live process as ``L.identity`` sees it: what the return value verifies;
      zombie treated as absent a killed child whose parent has not waited for it: on this OS ``L.identity`` reports no process
                               for it (the same answer as for a reaped one) and the helper cannot tell the two apart, so it
                               counts it as gone; it is still in the process table;
      wait/reap completion     only the parent's own wait() does that; a test that owns a Popen handle waits for it itself.
    Returns the SURVIVORS as (label, pid) pairs (live identities or tagged strays; empty = no live process remains). It
    needs the records, so it must run before the bench directory is removed."""
    d = os.path.join(root, "records")
    tags = []
    for name in os.listdir(d) if os.path.isdir(d) else []:
        try:
            tags.append(json.load(open(os.path.join(d, name))).get("tag", "none"))
        except (OSError, ValueError):
            pass
    ids = recorded_identities(root)
    end = time.monotonic() + timeout
    while True:
        for _, pid, start in ids:
            L.safe_kill(pid, start, signal.SIGKILL)
        stray = [i for tag in tags for i in L.tag_scan(tag)]  # one scan per round; a round that finds none verifies the tags
        for i in stray:
            L.safe_kill(i["pid"], i["start"], signal.SIGKILL)
        alive = [(label, pid) for label, pid, start in ids
                 if (lambda i: bool(i) and list(i["start"]) == list(start) and i["status"] != "zombie")(L.identity(pid))]
        if not alive and not stray:
            return []
        if time.monotonic() >= end:
            return alive + [("tagged", i["pid"]) for i in stray]
        time.sleep(0.1)


def conn_times(run_dir):
    try:
        return [int(l.split()[0]) / 1e9 for l in open(os.path.join(run_dir, "conn.log")) if l.strip()]
    except OSError:
        return []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="e3-test-")
        self.addCleanup(self._cleanup_bench)

    def _cleanup_bench(self):
        """ONE cleanup, in the only safe order: the records name the processes to kill, so processes are killed and
        their identities verified gone BEFORE the bench is removed (unittest runs cleanups in reverse order of
        registration; two separate cleanups, delete registered last, deleted the records first and left the killer blind).
        Verification is identity disappearance, with a zombie counted as absent; nothing is waited for or reaped here. If
        a live process survives, the bench is kept and its path and the survivors are written to stderr as diagnostics."""
        survivors = kill_recorded_and_verify_gone(os.path.join(self.tmp, "bench", "e3"))
        if survivors:
            sys.stderr.write(f"\n[e3-test cleanup] {len(survivors)} process(es) survived the kill-and-verify cleanup: {survivors}; kept for diagnosis: {self.tmp}\n")
            return
        subprocess.run(["rm", "-rf", self.tmp])

    def env(self, mode="normal", gen_s=3.0, **kw):
        self.spec = make_env3(self.tmp, mode, gen_s, kw.pop("extra_fixture", None), kw.pop("startup_delay", 0.3))
        self.cfg = cfg3(self.spec, **kw)
        self.root = self.spec["root"]
        return self.cfg

    def pilot(self, probes=None, bounds=None, through=3, **kw):
        opts = dict(gate_n=3, interval=0.2, top_cmd=TOP4, post_delay=0, post_sample_s=0, install_signals=False, baseline_n=3,
                    baseline_interval=0.1, e3pins=self.spec["e3pins"], bounds=bounds or BT)
        opts.update(kw)
        self.res = D.run_pilot(self.cfg, probes or StubProbes(), through, True, **opts)
        return self.res

    def run_dir(self):
        return os.path.join(self.root, "runs", self.res["run_id"])

    def record(self):
        return json.load(open(os.path.join(self.root, "records", self.res["run_id"] + ".json")))

    def signals(self):
        return T.SignalLedger(self.run_dir()).entries()

    def view(self):
        return json.load(open(os.path.join(self.run_dir(), "summary-committed-view.json")))

    def jsonl(self, name):
        try:
            return [json.loads(l) for l in open(os.path.join(self.run_dir(), name)) if l.strip()]
        except OSError:
            return []

    def assertNoLeftovers(self):
        rec = self.record()
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(L.listeners(self.spec["port"])["pids"], [])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(), "scratch", "api-key")))


class TestHappyPath(Base):
    def test_owner_sigkill_orphan_survives_and_successor_terminates_by_verified_identity(self):
        self.env(gen_s=3.0)
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res.get("stops"))
        self.assertEqual(res["stops"], [])
        rec = self.record()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertEqual(rec["exit_basis"], T.EXIT_BASIS_NONPARENT)
        self.assertIs(rec["waitpid_evidence"], False)
        self.assertIsNone(rec["exit_code"])
        sig = self.signals()
        owner_kill = [s for s in sig if s["who"] == "driver" and s["sig"] == int(signal.SIGKILL) and s["sent"]]
        self.assertEqual(len(owner_kill), 1)
        self.assertEqual(owner_kill[0]["pid"], rec["owner"]["pid"])
        runtime_sig = [s for s in sig if s["pid"] == rec["pid"] and s["sent"]]
        self.assertTrue(runtime_sig and all(s["who"] == "successor" for s in runtime_sig), runtime_sig)
        self.assertNoLeftovers()
        v = self.view()
        self.assertEqual(v["rows"]["rows"]["B4_successor_side"].split(" (")[0], "SUPPORTS")
        self.assertFalse(v["backstop_used"])
        self.assertEqual(v["http_after_kill"]["driver_gate_attempts_after_close"], 0)
        self.assertEqual(v["http_after_kill"]["new_connections_seen_by_lsof_after_baseline"], 0)
        self.assertLessEqual(v["http_after_kill"]["driver_gate_closed_at_t0_rel_s"], 0.0)  # closed before the kill signal went out
        self.assertEqual([s["sig"] for s in runtime_sig], [int(signal.SIGTERM)])  # TERM first; no KILL needed for a well-behaved runtime


def wait_until(cond, timeout=30.0, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return False


class TestBoundsAndWindow(unittest.TestCase):
    def test_production_bounds_are_consistent(self):
        self.assertEqual(T.check_bounds(), [])
        self.assertLessEqual(T.worst_case_lifetime(), T.BOUNDS["lifetime_s"])

    def test_owner_decisions_are_the_defaults(self):
        b = T.BOUNDS
        self.assertEqual((b["idle_after_reader_s"], b["orphan_max_s"], b["backstop_s"]), (10.0, 60.0, 75.0))

    def test_successor_worst_case_includes_verification_and_keeps_the_approved_backstop_margin(self):
        b = T.BOUNDS
        self.assertEqual(b["backstop_s"], 75.0)  # the approved backstop is unchanged
        self.assertEqual(T.successor_worst_case_s(b), b["orphan_max_s"] + b["successor_term_s"] + b["successor_kill_s"] + b["verify_s"])
        self.assertEqual(T.successor_worst_case_s(b), 70.0)
        self.assertEqual(b["backstop_s"] - T.successor_worst_case_s(b), 5.0)
        self.assertGreaterEqual(b["backstop_s"] - T.successor_worst_case_s(b), b["min_margin_s"])

    def test_the_backstop_margin_boundary(self):
        b = T.BOUNDS
        self.assertEqual(T.check_bounds(dict(b, verify_s=4.0)), [])  # exactly the minimum margin
        self.assertTrue(T.check_bounds(dict(b, verify_s=4.5)))
        self.assertTrue(T.check_bounds(dict(b, verify_s=7.0)))  # the pre-remediation verification time
        self.assertTrue(T.check_bounds(dict(b, successor_term_s=3.5)))
        self.assertTrue(T.check_bounds(dict(b, successor_kill_s=3.5)))
        self.assertTrue(T.check_bounds(dict(b, orphan_max_s=60.5)))
        self.assertEqual(T.check_bounds(dict(b, backstop_s=80.0, orphan_max_s=65.0)), [])
        # the pre-remediation arithmetic (60 + 5 + 3 s, verification omitted) would have passed with no margin at all
        self.assertTrue(T.check_bounds(dict(b, successor_term_s=5.0, successor_kill_s=3.0, verify_s=7.0)))

    def test_verification_overrun_is_bounded_and_far_inside_the_margin(self):
        p = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
        self.addCleanup(p.kill)
        i = L.identity(p.pid)
        rec = {"pid": p.pid, "start": i["start"], "pgid": i["pgid"], "descendants": [], "binding_verified": True, "tag": "zz-no-tag", "port": 59}
        t = time.monotonic()
        v = T.verify_nonparent(rec, 59, "zz-no-tag", 1.0)  # a live process: the conjunction can never hold
        elapsed = time.monotonic() - t
        self.assertFalse(v["verified"])
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLessEqual(elapsed, 1.0 + 2.0)  # at most one extra poll round plus the final classification
        self.assertLess(2.0, T.BOUNDS["min_margin_s"])

    def test_inconsistent_bounds_are_detected(self):
        self.assertTrue(T.check_bounds(dict(T.BOUNDS, backstop_s=60.0)))
        self.assertTrue(T.check_bounds(dict(T.BOUNDS, lifetime_s=100.0)))
        self.assertTrue(T.check_bounds(dict(T.BOUNDS, reader_deadline_s=30.0)))
        self.assertTrue(T.check_bounds(dict(T.BOUNDS, stale_s=2.0)))
        self.assertTrue(T.check_bounds(dict(T.BOUNDS, consecutive_polls=1)))

    def test_window_deadline_is_the_earliest_and_never_before_t0(self):
        b = T.BOUNDS
        self.assertEqual(T.window_deadline(100.0, None, None, b), 160.0)
        self.assertEqual(T.window_deadline(100.0, 120.0, None, b), 130.0)
        self.assertEqual(T.window_deadline(100.0, 155.0, None, b), 160.0)
        self.assertEqual(T.window_deadline(100.0, 120.0, 112.0, b), 112.0)
        self.assertEqual(T.window_deadline(100.0, 90.0, None, b), 100.0)  # completed before the kill: the window is at t0 + 0

    def test_e3_stop_limits_change_only_the_lifetime_ceiling(self):
        lim = T.stop_limits()
        diff = {k for k in E.LIMITS if lim[k] != E.LIMITS[k]}
        self.assertEqual(diff, {"lifetime_s"})

    def test_run_refuses_inconsistent_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = make_env3(tmp)
            res = D.run_pilot(cfg3(spec), StubProbes(), 3, True, e3pins=spec["e3pins"], bounds=dict(BT, stale_s=3.0))
            self.assertEqual(res["outcome"], "REFUSED")
            self.assertIn("bounds", res["why"])


class TestTrigger(unittest.TestCase):
    def trig(self, **kw):
        return T.Trigger(dict(T.BOUNDS, **kw))

    def test_fires_only_after_arming_delay_and_consecutive_polls(self):
        t = self.trig()
        t.request_sent(100.0)
        for k in range(3):
            t.poll(100.2 + k * 0.1, True, True)
        self.assertEqual(t.decide(100.5), T.WAIT)  # polls fine, delay not yet elapsed
        t.poll(101.6, True, True)
        self.assertEqual(t.decide(101.6), T.FIRE)

    def test_two_consecutive_polls_are_not_enough(self):
        t = self.trig()
        t.request_sent(100.0)
        t.poll(101.6, True, True)
        t.poll(101.7, True, True)
        self.assertEqual(t.decide(101.7), T.WAIT)

    def test_a_non_processing_or_failed_poll_resets_the_run(self):
        t = self.trig()
        t.request_sent(100.0)
        for u in (101.0, 101.1):
            t.poll(u, True, True)
        t.poll(101.2, True, False)
        t.poll(101.3, True, True)
        t.poll(101.4, False, None)  # failed poll
        t.poll(101.6, True, True)
        t.poll(101.7, True, True)
        self.assertEqual(t.decide(101.7), T.WAIT)
        t.poll(101.8, True, True)
        self.assertEqual(t.decide(101.8), T.FIRE)

    def test_processing_unknown_never_counts(self):
        t = self.trig()
        t.request_sent(100.0)
        for k in range(10):
            t.poll(102.0 + k * 0.1, True, None)
        self.assertEqual(t.decide(103.0), T.WAIT)

    def test_reader_completion_means_missed_even_with_qualifying_polls(self):
        t = self.trig()
        t.request_sent(100.0)
        for k in range(5):
            t.poll(101.6 + k * 0.1, True, True)
        t.reader_completed(102.0)
        self.assertEqual(t.decide(102.1), T.MISSED)

    def test_timeout_after_the_prekill_bound(self):
        t = self.trig()
        t.request_sent(100.0)
        self.assertEqual(t.decide(120.0), T.WAIT)
        self.assertEqual(t.decide(120.1), T.TIMEOUT)

    def test_active_stop_overrides_everything(self):
        t = self.trig()
        t.request_sent(100.0)
        for k in range(5):
            t.poll(101.6 + k * 0.1, True, True)
        self.assertEqual(t.decide(102.1, stop_active=True), T.STOP)

    def test_no_request_no_fire(self):
        t = self.trig()
        for k in range(5):
            t.poll(101.0 + k * 0.1, True, True)
        self.assertEqual(t.decide(102.0), T.WAIT)

    def test_staleness_window(self):
        t = self.trig()
        t.request_sent(100.0)
        t.poll(101.6, True, True)
        self.assertTrue(t.fresh(101.7))
        self.assertFalse(t.fresh(101.81))


class TestAuthorization(Base):
    def check(self, **kw):
        return T.check_authorization(self.root, self.spec["doc"], self.spec["e3pins"], **kw)

    def setUp(self):
        super().setUp()
        self.env()

    def test_valid(self):
        ok, why, a = self.check()
        self.assertTrue(ok, why)
        self.assertEqual(a["scope"], T.SCOPE)

    def test_missing_file(self):
        os.unlink(T.auth_path(self.root))
        self.assertFalse(self.check()[0])

    def test_other_scopes_and_base_file_do_not_authorize(self):
        for scope in ("base", "e3-pilot-v2", "", None):
            write_auth(self.spec, scope=scope)
            self.assertFalse(self.check()[0], scope)
        # an E2-B base authorization placed at the E2-B path is not read at all
        with open(os.path.join(self.root, "AUTHORIZATION.json"), "w") as f:
            json.dump({"scope": "base", "protocol_sha256": E.sha256_file(self.spec["doc"]), "phases": [1, 2, 3, 4],
                       "expires_epoch": time.time() + 99}, f)
        os.unlink(T.auth_path(self.root))
        self.assertFalse(self.check()[0])

    def test_only_one_lifetime_and_variant_v1(self):
        for over in ({"lifetimes": 2}, {"lifetimes": 0}, {"lifetimes": "1"}, {"variant": "V2"}, {"variant": None}):
            write_auth(self.spec, **over)
            self.assertFalse(self.check()[0], over)

    def test_protocol_hash_mismatch(self):
        write_auth(self.spec, protocol_sha256="0" * 64)
        self.assertIn("protocol", self.check()[1])

    def test_each_implementation_hash_is_bound(self):
        good = T.implementation_hashes()
        for name in T.IMPLEMENTATION_FILES:
            impl = dict(good)
            impl[name] = "f" * 64
            write_auth(self.spec, implementation_sha256=impl)
            ok, why, _ = self.check()
            self.assertFalse(ok, name)
            self.assertIn(name, why)

    def test_a_changed_implementation_file_invalidates_the_authorization(self):
        changed = dict(T.implementation_hashes(), **{"e3_lib.py": "a" * 64})
        ok, why, _ = self.check(impl=changed)
        self.assertFalse(ok)
        self.assertIn("e3_lib.py", why)

    def test_extra_or_missing_bound_files_are_refused(self):
        impl = T.implementation_hashes()
        impl.pop("e1_lib.py")
        write_auth(self.spec, implementation_sha256=impl)
        self.assertFalse(self.check()[0])
        impl = dict(T.implementation_hashes(), extra="a" * 64)
        write_auth(self.spec, implementation_sha256=impl)
        self.assertFalse(self.check()[0])

    def test_fixture_g_hash_mismatch(self):
        write_auth(self.spec, fixture_g_sha256="1" * 64)
        self.assertIn("fixture G", self.check()[1])

    def test_expired_or_no_expiry(self):
        write_auth(self.spec, expires_epoch=time.time() - 1)
        self.assertFalse(self.check()[0])
        write_auth(self.spec, expires_epoch="soon")
        self.assertFalse(self.check()[0])

    def test_authorization_id_is_required(self):
        write_auth(self.spec, authorization_id="")
        self.assertFalse(self.check()[0])

    def test_consumption_is_exclusive_and_blocks_a_second_use(self):
        ok, _, a = self.check()
        path = T.consume_authorization(self.root, a, "run-1")
        self.assertTrue(os.path.exists(path))
        with self.assertRaises(FileExistsError):
            T.consume_authorization(self.root, a, "run-2")
        ok, why, _ = self.check()
        self.assertFalse(ok)
        self.assertIn("consumed", why)

    def test_a_new_authorization_id_authorizes_a_new_lifetime(self):
        ok, _, a = self.check()
        T.consume_authorization(self.root, a, "run-1")
        write_auth(self.spec, authorization_id="second-authorization")
        self.assertTrue(self.check()[0])

    def test_concurrent_consumption_has_one_winner(self):
        ok, _, a = self.check()
        results = []

        def go(i):
            try:
                T.consume_authorization(self.root, a, f"run-{i}")
                results.append("won")
            except FileExistsError:
                results.append("lost")
        ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count("won"), 1)

    def test_pins_must_be_owner_approved(self):
        pins = json.loads(json.dumps(self.spec["e3pins"]))
        self.assertTrue(T.pins_ready(pins)[0])
        pins["fixture_g"]["state"] = "PROPOSED_AWAITING_OWNER_APPROVAL"
        self.assertFalse(T.pins_ready(pins)[0])
        pins["fixture_g"].update(state=T.APPROVED, max_tokens=512)
        self.assertFalse(T.pins_ready(pins)[0])
        pins["fixture_g"].update(max_tokens=384, sha256="short")
        self.assertFalse(T.pins_ready(pins)[0])

    APPROVED_G = {"state": "APPROVED_BY_OWNER", "bytes": 605, "max_tokens": 384, "file": "fixtures/e3/G.json",
                  "sha256": "ca2cdcc25dd149b8ac47c4e01ae57782bbb8c11f4e9d122af6f2f4a52bcebc6b"}

    def test_committed_pins_carry_the_owner_approved_fixture_g_identity(self):
        pins = T.load_pins()
        self.assertEqual(pins["fixture_g"], self.APPROVED_G)  # exact: no extra or changed field
        self.assertTrue(T.pins_ready(pins)[0])

    def test_altered_committed_pins_are_rejected(self):
        for field, value in (("state", "PROPOSED_AWAITING_OWNER_APPROVAL"), ("state", "approved_by_owner"), ("state", None),
                             ("max_tokens", 512), ("sha256", "short"), ("bytes", "605")):
            pins = json.loads(json.dumps(T.load_pins()))
            pins["fixture_g"][field] = value
            self.assertFalse(T.pins_ready(pins)[0], (field, value))

    def test_authorization_bound_to_the_approved_hash_refuses_a_different_pinned_hash(self):
        write_auth(self.spec, fixture_g_sha256=self.APPROVED_G["sha256"])
        pins = json.loads(json.dumps(T.load_pins()))
        ok, why, _ = T.check_authorization(self.root, self.spec["doc"], pins)
        self.assertTrue(ok, why)
        pins["fixture_g"]["sha256"] = "0" * 64
        ok, why, _ = T.check_authorization(self.root, self.spec["doc"], pins)
        self.assertFalse(ok)
        self.assertIn("fixture G", why)

    def test_fixture_file_that_differs_from_the_committed_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "G.json"), "wb") as f:
                f.write(E.canon({"messages": [{"role": "user", "content": "x"}], "max_tokens": 384, "stream": False}))
            with self.assertRaises(E.FixtureError):
                T.load_fixture_g(d, T.load_pins())

    def test_run_refuses_and_spawns_nothing_without_a_valid_authorization(self):
        os.unlink(T.auth_path(self.root))
        res = self.pilot()
        self.assertEqual((res["outcome"], res["exit_code"]), ("REFUSED", 2))
        self.assertFalse(os.path.exists(os.path.join(self.root, "runs")))

    def test_run_refuses_unapproved_pins(self):
        pins = json.loads(json.dumps(self.spec["e3pins"]))
        pins["fixture_g"]["state"] = "PROPOSED_AWAITING_OWNER_APPROVAL"
        write_auth(self.spec)
        res = self.pilot(e3pins=pins)
        self.assertEqual(res["outcome"], "REFUSED")
        self.assertIn("approved", res["why"])

    def test_run_refuses_without_attended(self):
        res = D.run_pilot(self.cfg, StubProbes(), 3, False, e3pins=self.spec["e3pins"], bounds=BT)
        self.assertEqual(res["outcome"], "REFUSED")

    def test_the_e2b_check_does_not_accept_the_e3_file(self):
        ok, why = E.check_authorization(self.root, [1, 2, 3, 4], self.spec["doc"])
        self.assertFalse(ok)  # no AUTHORIZATION.json at the E3 root, and the E3 file has the wrong name and scope


class TestSignalLedger(Base):
    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        self.ledger = T.SignalLedger(self.run_dir)
        self.procs = []
        self.addCleanup(lambda: [p.kill() for p in self.procs if p.poll() is None])

    def sleeper(self):
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.procs.append(p)
        return p, L.identity(p.pid)

    def test_sends_to_a_matching_identity_and_records_it(self):
        p, i = self.sleeper()
        r = self.ledger.send("t", p.pid, i["start"], signal.SIGKILL, "unit")
        self.assertTrue(r["sent"])
        p.wait(5)
        e = self.ledger.entries()
        self.assertEqual((e[0]["who"], e[0]["pid"], e[0]["sig"], e[0]["sent"]), ("t", p.pid, int(signal.SIGKILL), True))

    def test_a_reused_pid_with_a_different_start_is_never_signalled(self):
        p, i = self.sleeper()
        wrong = [i["start"][0] - 5, i["start"][1]]
        r = self.ledger.send("t", p.pid, wrong, signal.SIGKILL, "unit")
        self.assertFalse(r["sent"])
        self.assertEqual(r["why"], "identity_mismatch_or_gone")
        self.assertIsNone(p.poll())

    def test_a_second_sigkill_to_the_same_identity_is_refused(self):
        p, i = self.sleeper()
        self.assertTrue(self.ledger.send("a", p.pid, i["start"], signal.SIGKILL)["sent"])
        r = self.ledger.send("b", p.pid, i["start"], signal.SIGKILL)
        self.assertEqual((r["sent"], r["why"]), (False, "already_killed"))

    def test_term_is_allowed_once_and_kill_after_term(self):
        p, i = self.sleeper()
        self.assertTrue(self.ledger.send("a", p.pid, i["start"], signal.SIGTERM)["sent"])
        p.wait(5)

    def test_term_twice_refused_for_an_identity_that_survives_term(self):
        p = subprocess.Popen([sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('r',flush=True);time.sleep(60)"],
                             stdout=subprocess.PIPE)
        self.procs.append(p)
        p.stdout.readline()
        i = L.identity(p.pid)
        self.assertTrue(self.ledger.send("a", p.pid, i["start"], signal.SIGTERM)["sent"])
        self.assertEqual(self.ledger.send("b", p.pid, i["start"], signal.SIGTERM)["why"], "term_already_sent")
        self.assertTrue(self.ledger.send("b", p.pid, i["start"], signal.SIGKILL)["sent"])

    def test_a_gone_process_is_not_signalled(self):
        p, i = self.sleeper()
        p.kill()
        p.wait()
        r = self.ledger.send("t", p.pid, i["start"], signal.SIGKILL)
        self.assertFalse(r["sent"])

    def test_an_exited_but_unreaped_process_is_not_signalled(self):
        p, i = self.sleeper()
        os.kill(p.pid, signal.SIGKILL)
        self.assertTrue(wait_until(lambda: (L.identity(p.pid) or {}).get("status") in (None, "zombie"), 5))
        time.sleep(0.3)
        r = self.ledger.send("t", p.pid, i["start"], signal.SIGKILL)
        self.assertFalse(r["sent"])
        self.assertIn(r["why"], ("already_exited", "identity_mismatch_or_gone"))
        p.wait()

    def test_racing_signallers_deliver_exactly_one_sigkill(self):
        p, i = self.sleeper()
        out = []
        barrier = threading.Barrier(6)

        def go(n):
            barrier.wait()
            out.append(T.SignalLedger(self.run_dir).send(f"s{n}", p.pid, i["start"], signal.SIGKILL))
        ts = [threading.Thread(target=go, args=(n,)) for n in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sum(1 for r in out if r["sent"]), 1)
        self.assertEqual(sum(1 for e in self.ledger.entries() if e["sent"]), 1)

    def test_racing_processes_deliver_exactly_one_sigkill(self):
        p, i = self.sleeper()
        code = ("import sys;sys.path.insert(0,%r);import e3_lib as T,signal,json;"
                "r=T.SignalLedger(sys.argv[1]).send('x',int(sys.argv[2]),json.loads(sys.argv[3]),signal.SIGKILL);print(r['sent'])" % HERE)
        procs = [subprocess.Popen([sys.executable, "-B", "-c", code, self.run_dir, str(p.pid), json.dumps(i["start"])], stdout=subprocess.PIPE, text=True)
                 for _ in range(4)]
        sent = [q.communicate()[0].strip() for q in procs]
        self.assertEqual(sent.count("True"), 1, sent)

    def test_kill_fn_adapter_has_the_e2b_shape(self):
        p, i = self.sleeper()
        res = self.ledger.kill_fn("w")([{"pid": p.pid, "start": i["start"]}])
        self.assertEqual(res, {p.pid: True})


class TestLockedRecords(Base):
    def make(self):
        self.rs = T.LockedRecords(os.path.join(self.tmp, "root"))
        self.rec = self.rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        return self.rs, self.rec

    def test_stale_copy_does_not_lose_another_writers_update(self):
        rs, rec = self.make()
        other = rs.read("r1")
        rs.annotate(other, extra_from_other=1)
        rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])
        disk = rs.read("r1")
        self.assertEqual(disk["extra_from_other"], 1)
        self.assertEqual(disk["state"], "SPAWNED")

    def test_owner_review_flag_is_sticky_across_writers(self):
        rs, rec = self.make()
        other = rs.read("r1")
        rs.annotate(other, owner_review_required=True, owner_review_reason="x")
        rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])  # rec had no flag in memory
        self.assertTrue(rs.read("r1")["owner_review_required"])
        with self.assertRaises(ValueError):
            rs.advance(rec, "BOUND", binding_verified=True)
            rs.advance(rec, "EXIT_VERIFIED", exit_basis="x", cleared_by="harness")

    def test_in_memory_flag_survives_a_refresh(self):
        rs, rec = self.make()
        rec["owner_review_required"] = True
        rs.annotate(rec, a=1)
        self.assertTrue(rs.read("r1")["owner_review_required"])

    def test_quarantine_is_sticky_against_harness_clearing_but_not_recover(self):
        rs, rec = self.make()
        rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])
        rs.advance(rec, "QUARANTINED", reason="x")
        with self.assertRaises(ValueError):
            rs.advance(rec, "EXIT_VERIFIED", exit_basis="x", cleared_by="successor")
        with self.assertRaises(ValueError):
            rs.advance(rec, "EXIT_VERIFIED", exit_basis="x", cleared_by="driver_backstop")
        self.assertEqual(rs.read("r1")["state"], "QUARANTINED")
        rs.advance(rec, "EXIT_VERIFIED", exit_basis="successor_classify", cleared_by="recover")
        self.assertEqual(rs.read("r1")["state"], "EXIT_VERIFIED")

    def test_concurrent_writers_from_processes_keep_every_field(self):
        rs, rec = self.make()
        code = ("import sys;sys.path.insert(0,%r);import e3_lib as T;rs=T.LockedRecords(sys.argv[1]);r=rs.read('r1');"
                "[rs.annotate(r, **{'k'+sys.argv[2]+'_'+str(i): i}) for i in range(15)]" % HERE)
        ps = [subprocess.Popen([sys.executable, "-B", "-c", code, os.path.join(self.tmp, "root"), str(n)]) for n in range(4)]
        [p.wait() for p in ps]
        disk = rs.read("r1")
        for n in range(4):
            for i in range(15):
                self.assertEqual(disk[f"k{n}_{i}"], i)
        self.assertEqual([n for n in os.listdir(rs.dir) if ".tmp." in n], [])

    def test_lock_files_do_not_count_as_unresolved_records(self):
        rs, rec = self.make()
        rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])
        rs.advance(rec, "BOUND", binding_verified=True)
        rs.advance(rec, "EXIT_VERIFIED", exit_basis="x", cleared_by="harness")
        self.assertEqual(rs.unresolved(), [])


class TestClassifierWithoutSockets(Base):
    def spawn_record(self, verified=True):
        p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], preexec_fn=lambda: os.setpgid(0, 0))
        self.addCleanup(lambda: p.kill())
        i = L.identity(p.pid)
        return p, {"pid": p.pid, "start": i["start"], "pgid": i["pgid"], "port": 59, "tag": "no-such-tag-" + str(p.pid),
                   "binding_verified": verified, "descendants": []}

    def test_alive_while_the_identity_is_live(self):
        p, rec = self.spawn_record()
        v, why, obs = T.classify_os(rec)
        self.assertEqual(v, L.ALIVE)
        self.assertEqual(obs["probe"], "NOT_USED_NO_SOCKET")

    def test_terminated_only_after_exit_and_with_the_conjunction(self):
        p, rec = self.spawn_record()
        p.kill()
        p.wait()
        self.assertEqual(T.classify_os(rec)[0], L.TERMINATED)

    def test_indeterminate_without_a_verified_binding(self):
        p, rec = self.spawn_record(verified=False)
        p.kill()
        p.wait()
        self.assertEqual(T.classify_os(rec)[0], L.INDETERMINATE)

    def test_indeterminate_when_the_record_lacks_identity(self):
        self.assertEqual(T.classify_os({"port": 59, "binding_verified": True})[0], L.INDETERMINATE)

    def test_unrecorded_group_member_blocks_terminated(self):
        p, rec = self.spawn_record()
        helper = subprocess.Popen(["/bin/sleep", "30"], preexec_fn=lambda: os.setpgid(0, p.pid))
        self.addCleanup(helper.kill)
        time.sleep(0.2)
        p.kill()
        p.wait()
        v, why, obs = T.classify_os(rec)
        self.assertEqual(v, L.INDETERMINATE, why)

    def test_reused_pid_is_not_alive(self):
        p, rec = self.spawn_record()
        p.kill()
        p.wait()
        rec2 = dict(rec, start=[rec["start"][0] - 10, rec["start"][1]])
        rec2["pid"] = os.getpid()  # a live process with a different start time
        rec2["pgid"] = None
        v, why, obs = T.classify_os(rec2)
        self.assertEqual(v, L.TERMINATED)  # the live pid belongs to someone else: the recorded process is gone
        self.assertTrue(any("different process" in w for w in why), why)
        self.assertEqual(obs["live_recorded"], [])

    def test_classification_opens_no_socket(self):
        import socket
        p, rec = self.spawn_record()
        real = socket.socket

        class Boom(real):
            def __init__(self, *a, **k):
                raise AssertionError("classify_os opened a socket")
        socket.socket = Boom
        try:
            T.classify_os(rec)
            p.kill()
            p.wait()
            T.classify_os(rec)
            T.nonparent_checks(dict(rec, descendants=[]), 59, "tag")
        finally:
            socket.socket = real

    def test_a_foreign_listener_is_not_ownership_evidence(self):
        import socket
        p, rec = self.spawn_record()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        rec["port"] = s.getsockname()[1]
        p.kill()
        p.wait()
        v, why, obs = T.classify_os(rec)
        s.close()
        self.assertEqual(v, L.TERMINATED)
        self.assertTrue(any("foreign listener" in w for w in why))
        # but the exit conjunction refuses to call it verified while the port is held
        s2 = socket.socket()
        s2.bind(("127.0.0.1", 0))
        s2.listen(1)
        self.assertFalse(T.nonparent_checks(dict(rec, port=s2.getsockname()[1]), s2.getsockname()[1], "x")["port_free"])
        s2.close()


class TestNonParentFinalWrite(Base):
    def bound_record(self, flag=False):
        rs = T.LockedRecords(os.path.join(self.tmp, "root"))
        rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])
        rs.advance(rec, "BOUND", binding_verified=True)
        if flag:
            rs.annotate(rec, owner_review_required=True, owner_review_reason="S8")
        return rs, rec

    def test_verified_writes_exit_verified_without_a_waitpid_claim(self):
        rs, rec = self.bound_record()
        self.assertIs(T.write_final(rs, rec, True, {"identity_gone": True}, "successor", T.EXIT_OBSERVED), True)
        d = rs.read("r1")
        self.assertEqual((d["state"], d["exit_basis"], d["waitpid_evidence"], d["exit_code"]), ("EXIT_VERIFIED", T.EXIT_BASIS_NONPARENT, False, None))
        self.assertNotIn("reaped", d["checks"])
        self.assertNotIn("waitpid", d["exit_basis"])

    def test_unverified_is_quarantined(self):
        rs, rec = self.bound_record()
        T.write_final(rs, rec, False, {"identity_gone": False}, "successor", T.EXIT_UNOBSERVED)
        d = rs.read("r1")
        self.assertEqual(d["state"], "QUARANTINED")
        self.assertEqual(d["waitpid_evidence"], False)

    def test_policy_flag_forces_quarantine_even_when_verified(self):
        rs, rec = self.bound_record(flag=True)
        T.write_final(rs, rec, True, {"identity_gone": True}, "successor", T.EXIT_OBSERVED)
        d = rs.read("r1")
        self.assertEqual(d["state"], "QUARANTINED")
        self.assertTrue(d["owner_review_required"])

    def test_a_quarantined_record_is_not_rewritten_to_verified(self):
        rs, rec = self.bound_record()
        T.write_final(rs, rec, False, {}, "successor", T.EXIT_UNOBSERVED)
        res = T.write_final(rs, rec, True, {"identity_gone": True}, "driver_backstop", T.EXIT_UNOBSERVED)
        self.assertNotEqual(res, True)
        self.assertEqual(rs.read("r1")["state"], "QUARANTINED")

    def test_exit_event_labels_are_distinct(self):
        self.assertNotEqual(T.EXIT_OBSERVED, T.EXIT_UNOBSERVED)


class TestExitAttribution(unittest.TestCase):
    @staticmethod
    def ent(who, sent, pid=5, start=(1, 2)):
        return {"pid": pid, "start": list(start), "sent": sent, "who": who}

    def test_no_signal_and_no_stop_is_only_no_signal_recorded(self):
        self.assertEqual(T.exit_attribution([], 5, [1, 2])["cause"], T.NO_SIGNAL)
        self.assertEqual(T.exit_attribution([], 5, (1, 2), [{"id": "S4", "immediate": False, "quarantine": False}])["cause"], T.NO_SIGNAL)

    def test_any_sent_signal_to_the_identity_means_signalled_whoever_sent_it(self):
        for who in ("driver-monitor", "driver_backstop", "successor", "owner"):
            a = T.exit_attribution([self.ent(who, True)], 5, [1, 2])
            self.assertEqual((a["cause"], a["by"]), (T.SIGNALLED, [who]))

    def test_refused_signals_other_pids_and_reused_pids_do_not_count(self):
        self.assertEqual(T.exit_attribution([self.ent("successor", False)], 5, [1, 2])["cause"], T.NO_SIGNAL)
        self.assertEqual(T.exit_attribution([self.ent("successor", True, pid=6)], 5, [1, 2])["cause"], T.NO_SIGNAL)
        self.assertEqual(T.exit_attribution([self.ent("successor", True, start=(9, 9))], 5, [1, 2])["cause"], T.NO_SIGNAL)

    def test_a_killing_or_quarantining_stop_without_a_ledger_signal_is_undetermined(self):
        for stop in ({"immediate": True}, {"quarantine": True}):
            self.assertEqual(T.exit_attribution([], 5, [1, 2], [stop])["cause"], T.UNDETERMINED)
        self.assertEqual(T.exit_attribution([self.ent("driver-monitor", True)], 5, [1, 2], [{"immediate": True}])["cause"], T.SIGNALLED)


class TestRows(unittest.TestCase):
    def base(self):
        return {"stops": [], "orphan": {"alive_at_first_successor_observation": True, "exited_by_itself": False},
                "successor": {"classifications": [{"verdict": L.ALIVE, "identity_gone": False}], "terminated_by": "successor",
                              "verified": True, "signals_by_successor": [{"sig": 15}]}, "record_state": "EXIT_VERIFIED",
                "backstop_used": False, "reader": {"status": 200, "finish_reason": "stop"}}

    def test_clean_run_supports_with_n_equal_one(self):
        r = T.e3_rows(self.base())["rows"]
        for k in T.VERDICT_ROWS:
            self.assertTrue(r[k].startswith("SUPPORTS"), (k, r[k]))
            self.assertIn("n=1", r[k])

    def test_any_stop_withholds_every_verdict_but_keeps_observations(self):
        s = self.base()
        s["stops"] = [{"id": "S4", "why": "power source"}]
        out = T.e3_rows(s)
        for k in T.VERDICT_ROWS:
            self.assertEqual(out["rows"][k], "INCONCLUSIVE")
        self.assertEqual(out["notes"]["verdicts_withheld_by_stops"], ["S4"])
        self.assertEqual(out["observations"]["O5_reader_outcome_class"], "COMPLETE_RESPONSE")

    def test_backstop_never_counts_as_a_successor_demonstration(self):
        s = self.base()
        s["backstop_used"] = True
        s["successor"]["terminated_by"] = "driver_backstop"
        r = T.e3_rows(s)["rows"]
        self.assertEqual(r["O4_successor_termination"], "INCONCLUSIVE")
        self.assertEqual(r["B4_successor_side"], "INCONCLUSIVE")

    def test_self_exit_is_an_observation_not_a_successor_kill(self):
        s = self.base()
        s["successor"]["signals_by_successor"] = []
        s["orphan"]["exited_by_itself"] = True
        out = T.e3_rows(s)
        self.assertEqual(out["rows"]["O4_successor_termination"], "INCONCLUSIVE")
        self.assertTrue(out["observations"]["O2_exited_by_itself_before_window_end"])

    def test_untested_items_can_never_be_a_verdict(self):
        r = T.e3_rows(self.base())["rows"]
        for k in T.NOT_TESTED:
            self.assertEqual(r[k], "NOT_TESTED")
        for k in ("late_delivery_excluded", "B3_instance_reported_terminal", "request_cancel", "requester_disconnect"):
            self.assertEqual(r[k], "NOT_TESTED")

    def test_reader_outcome_classes(self):
        self.assertEqual(T.reader_outcome_class(None), "NO_READER_RESULT")
        self.assertEqual(T.reader_outcome_class({"status": None, "error": "ConnectionResetError"}), "NO_RESPONSE_ERROR")
        self.assertEqual(T.reader_outcome_class({"status": None, "timed_out": True}), "NO_RESPONSE_TIMEOUT")
        self.assertEqual(T.reader_outcome_class({"status": None, "error": None, "timed_out": False}), "NO_RESPONSE_CONNECTION_CLOSED")
        self.assertEqual(T.reader_outcome_class({"status": 200, "finish_reason": None}), "OTHER")


class TestStaticSafety(unittest.TestCase):
    FILES = ("e3_lib.py", "e3_harness.py", "e3_owner.py", "e3_reader.py", "e3_successor.py", "e3_fake_runtime.py")

    def tree(self, name):
        return ast.parse(open(os.path.join(HERE, name)).read())

    def calls(self, name):
        out = []
        for n in ast.walk(self.tree(name)):
            if isinstance(n, ast.Call):
                f = n.func
                out.append(ast.unparse(f) if hasattr(ast, "unparse") else getattr(f, "attr", getattr(f, "id", "")))
        return out

    def test_os_kill_is_confined_to_the_ledger(self):
        for name in self.FILES:
            if name == "e3_fake_runtime.py":
                continue
            hits = [c for c in self.calls(name) if c in ("os.kill", "os.killpg", "killpg")]
            if name == "e3_lib.py":
                self.assertEqual(hits, ["os.kill"], name)
            else:
                self.assertEqual(hits, [], name)

    def test_no_pid_only_helper_is_used(self):
        for name in self.FILES:
            self.assertEqual([c for c in self.calls(name) if c.endswith(("safe_kill", "kill_identified"))], [], name)

    def test_the_successor_and_its_library_contain_no_socket_or_http_code(self):
        banned = {"socket", "http", "urllib", "http_call", "probe_identity", "create_connection", "requests", "ssl"}
        for name in ("e3_successor.py", "e3_lib.py"):
            tree = self.tree(name)
            for n in ast.walk(tree):
                names = set()
                if isinstance(n, ast.Import):
                    names = {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom):
                    names = {(n.module or "").split(".")[0]} | {a.name for a in n.names}
                elif isinstance(n, ast.Name):
                    names = {n.id}
                elif isinstance(n, ast.Attribute):
                    names = {n.attr}
                self.assertFalse(names & banned, (name, names & banned))

    def test_the_successor_only_imports_what_it_needs(self):
        mods = set()
        for n in ast.walk(self.tree("e3_successor.py")):
            if isinstance(n, ast.Import):
                mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add(n.module)
        self.assertEqual(mods, {"__future__", "json", "os", "signal", "sys", "time", "e1_lib", "e3_lib"})

    def test_the_reader_never_loops_or_retries(self):
        tree = self.tree("e3_reader.py")
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.For))], [])
        self.assertEqual(self.calls("e3_reader.py").count("H.http_call"), 1)

    def test_the_owner_idle_loop_does_no_record_work(self):
        tree = self.tree("e3_owner.py")
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        loops = [n for n in ast.walk(main) if isinstance(n, ast.While)]
        self.assertEqual(len(loops), 1)
        text = ast.unparse(loops[0])
        for banned in ("records", "advance", "annotate", "http", "bind(", "write"):
            self.assertNotIn(banned, text)

    def test_the_driver_never_launches_or_binds_the_runtime(self):
        inst = D.RemoteInstance
        for name in ("launch", "wait_ready", "bind", "shutdown", "contain", "safe_shutdown"):
            self.assertRaises(NotImplementedError, getattr(inst, name), object())

    def test_the_owner_routes_its_sigkills_through_the_ledger(self):
        tree = ast.parse(open(os.path.join(HERE, "e3_owner.py")).read())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "OwnerInstance"]
        self.assertEqual(len(calls), 1)
        kw = {k.arg: ast.unparse(k.value) if hasattr(ast, "unparse") else "" for k in calls[0].keywords}
        self.assertIn("kill_fn", kw)
        if kw["kill_fn"]:
            self.assertIn("ledger.kill_fn", kw["kill_fn"])

    def test_driver_http_goes_through_the_gate_only(self):
        direct = [c for c in self.calls("e3_harness.py") if c in ("H.http_call", "http_call")]
        self.assertEqual(direct, ["H.http_call"])  # inside HttpGate.call and nowhere else

    def test_http_gate_blocks_after_close(self):
        g = D.HttpGate()
        g.close()
        with self.assertRaises(D.HttpAfterKill):
            g.call(1, "GET", "/slots")
        self.assertEqual(g.attempts_after, 1)

    def test_no_committed_source_contains_the_e2b_fixture_strings(self):
        bench = E.DEFAULT_BENCH
        fx = os.path.join(bench, "fixtures", "e2b")
        if not os.path.isdir(fx):
            self.skipTest("no local bench")
        strings = []
        for n in ("P1", "P2", "P3", "P4", "AUTH"):
            strings += [m["content"] for m in json.load(open(os.path.join(fx, n + ".json")))["messages"]]
        files = [os.path.join(HERE, n) for n in self.FILES + ("test_e3.py", "e3_pins.json")]
        self.assertEqual(E.scan_files(files, sorted(set(strings))), [])


class TestFrozenE2BFiles(unittest.TestCase):
    HASHES = {
        os.path.join("docs", "evidence", "v0-0b2-e2b-protocol.md"): "f27b7162265f94cc30c92117a9fc8a0f0e977068036087df6e9e024bee28e174",
        os.path.join("tools", "evidence", "runtime", "e2b_harness.py"): "246c5c17697c2573492f889c8bf4fcff13e2c117395321f35f52362655e14dba",
        os.path.join("tools", "evidence", "runtime", "e2b_lib.py"): "849415afb2625c47369a11857c8b5feae07999b1ef951ecd497be13ba8d0047f",
        os.path.join("tools", "evidence", "runtime", "e1_lib.py"): "6190a9753955e336badc9bdaee4fae6343996cb3b5d9e500cf2b6dc98a6e2e4e",
        os.path.join("tools", "evidence", "runtime", "e2b_pins.json"): "f25b500c5142b44455cb48f34ce28ccd22a874aecb5c52953266affe33f8bbed",
    }

    def test_e2b_protocol_harness_library_and_pins_are_byte_identical(self):
        for rel, want in self.HASHES.items():
            self.assertEqual(E.sha256_file(os.path.join(E.REPO, rel)), want, rel)


class TestSuccessorSandbox(Base):
    def test_the_profile_denies_every_socket_and_the_listed_reads(self):
        secret_dir = os.path.join(self.tmp, "denied")
        os.makedirs(secret_dir)
        open(os.path.join(secret_dir, "canary"), "w").write("x")
        code = ("import socket,sys\n"
                "for fam,typ in ((socket.AF_INET,socket.SOCK_STREAM),(socket.AF_INET,socket.SOCK_DGRAM)):\n"
                "    s=socket.socket(fam,typ)\n"
                "    try:\n        s.connect(('127.0.0.1',9)); print('CONNECTED')\n"
                "    except PermissionError: print('DENIED')\n"
                "    except OSError as e: print('OTHER', e.errno)\n"
                "try:\n    open(sys.argv[1]); print('READ')\nexcept PermissionError: print('READ_DENIED')\n")
        out = subprocess.run(["/usr/bin/sandbox-exec", "-p", T.successor_profile([secret_dir]), sys.executable, "-I", "-c", code,
                              os.path.join(secret_dir, "canary")], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["DENIED", "DENIED", "READ_DENIED"])

    def test_the_sandboxed_successor_toolkit_still_works(self):
        p = subprocess.Popen(["/bin/sleep", "30"])
        self.addCleanup(p.kill)
        code = ("import sys;sys.path.insert(0,%r);import e1_lib as L,e3_lib as T\n"
                "i=L.identity(%d);w=L.ExitWatch(%d);r=T.classify_os({'pid':%d,'start':i['start'],'pgid':i['pgid'],'port':59,'tag':'zz','binding_verified':True})\n"
                "print(w.registered, r[0])" % (HERE, p.pid, p.pid, p.pid))
        out = subprocess.run(["/usr/bin/sandbox-exec", "-p", T.successor_profile([]), sys.executable, "-I", "-c", code],
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.split(), ["True", L.ALIVE], out.stderr)

    def test_sandbox_quoting(self):
        self.assertEqual(T.sbpl_quote('a"b\\c'), '"a\\"b\\\\c"')


class Scenario(Base):
    """Integration scenarios against the synthetic runtime with real processes and a real SIGKILL."""

    def t0(self):
        return self.record()["e3"]["t0_up"]

    def assertOwnerNeverKilledBeforeIdentityRecorded(self):
        e3 = self.record()["e3"]
        self.assertEqual(e3["planned"], "owner_sigkill")
        self.assertLess(e3["pre_kill_up"], e3["t0_up"])
        self.assertEqual(e3["owner"]["pid"], self.record()["owner"]["pid"])

    def signalled(self, who=None):
        return [s for s in self.signals() if s["sent"] and (who is None or s["who"] == who)]


class TestHappyPathProperties(Scenario):
    def test_safety_properties_of_the_clean_run(self):
        self.env(gen_s=3.0)
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res.get("stops"))
        rec = self.record()
        self.assertOwnerNeverKilledBeforeIdentityRecorded()
        t0 = self.t0()
        # the key file is gone before the successor starts, and no key ever reached a file
        v = self.view()
        self.assertLess(v["key_file"]["deleted_at_t0_rel_s"], v["timeline"]["successor_start_rel_s"])
        self.assertFalse(v["key_file"]["exists_after_kill"])
        # exactly one generation request, all polls before the kill, and no connection after t0
        reqs = [l.split() for l in open(os.path.join(self.run_dir(), "req.log")) if l.strip()]
        posts = [r for r in reqs if r[1] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertTrue(all(int(r[0]) / 1e9 < t0 for r in reqs if r[2] == "/slots"))
        self.assertLess(max(conn_times(self.run_dir())), t0)
        # the in-flight request completed at the independent reader AFTER the owner was dead
        self.assertEqual(self.view()["reader"]["client_completed"], True)
        self.assertGreater(self.jsonl("reader.jsonl")[-1]["up"], t0)
        # the monitor kept sampling (with RSS) after the owner died
        series = self.jsonl("series.jsonl")
        post_kill = [s for s in series if s.get("up", 0) > t0 + 0.5]
        self.assertTrue(post_kill and all(s.get("rss") is not None for s in post_kill if s.get("expect_rss")))
        self.assertTrue(any(s.get("expect_rss") for s in post_kill))
        # the successor's classifications: ALIVE every time, never TERMINATED while the identity was live
        cls = self.jsonl("successor.jsonl")
        verdicts = [c["verdict"] for c in cls if c["e"] == "CLASSIFY"]
        self.assertTrue(verdicts and set(verdicts) == {L.ALIVE})
        self.assertEqual(rec["terminated_by"], "successor")
        self.assertTrue(self.res["successor_sandbox"]["network_denied_by_kernel"])
        self.assertLess(v["timeline"]["successor_start_rel_s"], 1.0)  # started within a second of the owner kill
        self.assertLess(v["owner_kill"]["t0_to_owner_dead_s"], 1.0)

    def test_no_secret_reaches_any_file(self):
        self.env(gen_s=2.0)
        known = "k" * 48
        real = D.secrets

        class S:
            def __getattr__(self, n):
                return getattr(real, n)

            @staticmethod
            def token_hex(n):
                return known if n == 24 else real.token_hex(n)
        D.secrets = S()
        try:
            self.pilot()
        finally:
            D.secrets = real
        hits = []
        for dp, dns, fns in os.walk(self.spec["bench"]):
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    if known.encode() in open(p, "rb").read():
                        hits.append(p)
                except OSError:
                    pass
        self.assertEqual(hits, [])

    def test_committed_view_has_no_paths_prompts_or_outputs(self):
        self.env(gen_s=2.0)
        self.pilot()
        text = json.dumps(self.view())
        for needle in (self.tmp, "/Users/", "unit-test e3", "api-key", "Bearer", "ok ok ok"):
            self.assertNotIn(needle, text)
        self.assertEqual(E.scan_files([os.path.join(self.run_dir(), "summary-committed-view.json")], self.spec["forbidden"]), [])


class TestPreKillPaths(Scenario):
    def test_trigger_missed_consumes_the_authorization_and_never_kills_the_owner(self):
        self.env(gen_s=0.2)
        res = self.pilot()
        self.assertEqual(res["outcome"], "TRIGGER_MISSED")
        self.assertEqual(self.signalled("driver"), [])
        rec = self.record()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertEqual(rec["exit_basis"], "owner_waitpid_and_conjunction")
        self.assertEqual(self.view()["rows"]["rows"]["B4_successor_side"], "INCONCLUSIVE")
        self.assertTrue(any(n.startswith("CONSUMED-") for n in os.listdir(self.root)))
        self.assertNoLeftovers()
        again = self.pilot()
        self.assertEqual(again["outcome"], "REFUSED")  # single use: no retry in code

    def test_runtime_that_never_reports_processing_is_not_reached_and_never_killed(self):
        self.env(mode="no_processing", gen_s=2.5)
        res = self.pilot(bounds=dict(BT, prekill_abort_s=1.5))
        self.assertEqual(res["outcome"], "PILOT_NOT_REACHED", res["stops"])
        self.assertEqual(self.signalled("driver"), [])
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def test_slots_token_counts_are_diagnostic_only(self):
        self.env(mode="no_processing,slots_tokens", gen_s=2.5)
        res = self.pilot(bounds=dict(BT, prekill_abort_s=1.5))
        self.assertEqual(res["outcome"], "PILOT_NOT_REACHED")  # tokens were visible, processing was not: no kill
        self.assertIn("next_token", self.view()["trigger"]["slot_fields_seen"])

    def test_monitor_stop_before_the_kill_shuts_down_through_the_owner(self):
        self.env(gen_s=8.0)
        probes = StubProbes()
        self.when_request = threading.Thread(
            target=lambda: (wait_until(lambda: os.path.exists(os.path.join(self.root, "runs")) and any(
                os.path.exists(os.path.join(self.root, "runs", d, "reader.jsonl")) for d in os.listdir(os.path.join(self.root, "runs"))), 30),
                            setattr(probes, "src", "Battery Power")), daemon=True)
        self.when_request.start()
        res = self.pilot(probes=probes, bounds=dict(BT, arm_delay_s=4.0, prekill_abort_s=10.0, reader_deadline_s=30.0),
                         monitor_interval=0.2, monitor_slow_every=2)
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertIn("S4", [s["id"] for s in res["stops"]])
        self.assertEqual(self.signalled("driver"), [])
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")
        self.assertNoLeftovers()

    def test_a_stop_during_the_prekill_write_prevents_the_owner_kill(self):
        self.env(gen_s=8.0)
        real = D.Pilot.annotate_e3

        def inject(self_, **kw):
            out = real(self_, **kw)
            if kw.get("planned") == "owner_sigkill":  # the durable pre-kill section has just been written
                self_.mon.triggers.append({"id": "S5", "why": "thermal (injected during the pre-kill write)", "immediate": False, "quarantine": False})
                self_.cancel.set()
            return out
        D.Pilot.annotate_e3 = inject
        self.addCleanup(lambda: setattr(D.Pilot, "annotate_e3", real))
        res = self.pilot(bounds=dict(BT, prekill_abort_s=6.0, reader_deadline_s=30.0))
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("S5", [s["id"] for s in res["stops"]])
        self.assertEqual(self.signalled("driver"), [])  # the Owner was never signalled
        v = self.view()
        self.assertIsNone(v["http_after_kill"])  # the gate was never closed, no orphan phase
        self.assertIsNone(v["owner_kill"])
        rec = self.record()
        self.assertNotIn("t0_up", rec["e3"])  # the durable section says planned; no kill time exists
        self.assertEqual((rec["state"], rec["exit_basis"]), ("EXIT_VERIFIED", "owner_waitpid_and_conjunction"))  # the live Owner shut down normally
        for k in T.VERDICT_ROWS:
            self.assertEqual(v["rows"]["rows"][k], "INCONCLUSIVE")
        self.assertNoLeftovers()

    def test_an_interrupt_during_the_prekill_write_prevents_the_owner_kill(self):
        self.env(gen_s=8.0)
        real = D.Pilot.annotate_e3
        interrupted = threading.Event()

        def inject(self_, **kw):
            out = real(self_, **kw)
            if kw.get("planned") == "owner_sigkill":
                interrupted.set()
            return out
        D.Pilot.annotate_e3 = inject
        self.addCleanup(lambda: setattr(D.Pilot, "annotate_e3", real))
        res = self.pilot(bounds=dict(BT, prekill_abort_s=6.0, reader_deadline_s=30.0), interrupted=interrupted)
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("operator interrupt", [s["why"] for s in res["stops"]])
        self.assertEqual(self.signalled("driver"), [])
        self.assertNotIn("t0_up", self.record()["e3"])
        self.assertNoLeftovers()

    def test_a_bound_file_changed_after_the_first_check_is_caught_before_consumption(self):
        self.env(gen_s=3.0)
        real_hashes, real_start, drift = T.implementation_hashes, D.Pilot.start_owner, {"on": False}

        def hashes(directory=T.HERE):
            h = real_hashes(directory)
            if drift["on"]:
                h["e3_successor.py"] = "d" * 64  # a bound file differs from what the authorization binds
            return h

        def start(self_, art):
            drift["on"] = True  # after the check at the start and after Phases 1 and 2, before consumption
            return real_start(self_, art)
        T.implementation_hashes, D.Pilot.start_owner = hashes, start
        self.addCleanup(lambda: (setattr(T, "implementation_hashes", real_hashes), setattr(D.Pilot, "start_owner", real_start)))
        res = self.pilot()
        self.assertEqual(res["outcome"], "NOT_SPAWNED", res.get("stops"))
        self.assertIn("AUTH", [s["id"] for s in res["stops"]])
        self.assertIn("e3_successor.py", [s["why"] for s in res["stops"] if s["id"] == "AUTH"][0])
        self.assertFalse(any(n.startswith("CONSUMED-") for n in os.listdir(self.root)))  # not consumed: nothing started
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "records"))], [])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(), "owner.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(), "scratch", "api-key")))
        self.assertEqual(L.listeners(self.spec["port"])["pids"], [])

    def test_a_replaced_authorization_after_the_first_check_is_caught_before_consumption(self):
        self.env(gen_s=3.0)
        real_start = D.Pilot.start_owner

        def start(self_, art):
            write_auth(self.spec, authorization_id="a-different-authorization")  # valid, but not the one that was checked
            return real_start(self_, art)
        D.Pilot.start_owner = start
        self.addCleanup(lambda: setattr(D.Pilot, "start_owner", real_start))
        res = self.pilot()
        self.assertEqual(res["outcome"], "NOT_SPAWNED", res.get("stops"))
        self.assertIn("AUTH", [s["id"] for s in res["stops"]])
        self.assertFalse(any(n.startswith("CONSUMED-") for n in os.listdir(self.root)))
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "records"))], [])

    def test_owner_abort_sigkill_goes_through_the_ledger_and_the_sigterm_is_reported(self):
        self.env(mode="ignore_term", gen_s=8.0)
        probes = StubProbes()
        threading.Thread(target=lambda: (wait_until(lambda: os.path.exists(os.path.join(self.root, "runs")) and any(
            os.path.exists(os.path.join(self.root, "runs", d, "reader.jsonl")) for d in os.listdir(os.path.join(self.root, "runs"))), 30),
            setattr(probes, "src", "Battery Power")), daemon=True).start()
        res = self.pilot(probes=probes, bounds=dict(BT, arm_delay_s=4.0, prekill_abort_s=10.0, reader_deadline_s=40.0, owner_shutdown_s=25.0),
                         monitor_interval=0.2, monitor_slow_every=2)
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        rec = self.record()
        owner_sent = [s for s in self.signals() if s["who"] == "owner" and s["sent"] and s["pid"] == rec["pid"]]
        self.assertEqual([s["sig"] for s in owner_sent], [int(signal.SIGKILL)])  # the SIGKILL is attributed in the ledger
        self.assertEqual(self.signalled("driver"), [])
        final = [m for m in self.jsonl("owner.jsonl") if m["e"] == "FINAL"][-1]
        self.assertIs(final["result"]["term_attempted"], True)  # the one unledgered SIGTERM is reported as an attempt only
        self.assertEqual(final["result"]["term_delivery"], "not_observable")  # its delivery is not observable through the inherited code
        self.assertIs(final["result"]["kill_attempted"], True)
        self.assertIs(final["result"]["kill_delivered_by_ledger"], True)  # the SIGKILL's delivery is confirmed by the ledger
        self.assertNotIn("term_sent", final["result"])  # the E2-B booleans that said "called", not "delivered", are not reported as facts
        self.assertEqual(self.view()["owner_shutdown"]["kill_delivered_by_ledger"], True)
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def test_tagged_stranger_before_the_kill_is_quarantined_and_never_signalled(self):
        self.env(gen_s=6.0)
        stranger = []

        def plant():
            wait_until(lambda: any(f.endswith(".json") for f in os.listdir(os.path.join(self.root, "records"))) if os.path.isdir(os.path.join(self.root, "records")) else False, 30)
            for _ in range(200):
                recs = [json.load(open(os.path.join(self.root, "records", f))) for f in os.listdir(os.path.join(self.root, "records")) if f.endswith(".json")]
                if recs and recs[0].get("state") in ("SPAWNED", "BOUND"):
                    # a non-platform process: the environment of Apple platform binaries is invisible to the tag scan (E2-B limitation)
                    env = {"PATH": "/usr/bin:/bin", E.TAG_ENV: recs[0]["tag"]}
                    stranger.append(subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], env=env, start_new_session=True))
                    return
                time.sleep(0.05)
        threading.Thread(target=plant, daemon=True).start()
        self.addCleanup(lambda: [p.kill() for p in stranger])
        res = self.pilot(bounds=dict(BT, arm_delay_s=4.0, prekill_abort_s=10.0, reader_deadline_s=30.0), monitor_interval=0.2, monitor_slow_every=2)
        self.assertTrue(stranger)
        self.assertIn("S8", [s["id"] for s in res["stops"]])
        self.assertIsNone(stranger[0].poll())  # tagged strangers are reported, never signalled
        rec = self.record()
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertTrue(rec["owner_review_required"])
        self.assertEqual(res["outcome"], "QUARANTINED")


class TestEarlyPolicyQuarantine(Scenario):
    def test_a_policy_stop_before_bound_is_not_lost_to_an_owner_that_finalises_first(self):
        self.env(gen_s=3.0, startup_delay=3.0)  # the runtime is still "loading" when the stranger appears
        stranger = []

        def plant():
            d = os.path.join(self.root, "records")
            for _ in range(2000):
                recs = [json.load(open(os.path.join(d, f))) for f in os.listdir(d) if f.endswith(".json")] if os.path.isdir(d) else []
                if recs and recs[0].get("state") == "SPAWNED":
                    env = {"PATH": "/usr/bin:/bin", E.TAG_ENV: recs[0]["tag"]}
                    stranger.append(subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], env=env, start_new_session=True))
                    return
                time.sleep(0.02)
        threading.Thread(target=plant, daemon=True).start()
        self.addCleanup(lambda: [p.kill() for p in stranger])
        res = self.pilot(monitor_interval=0.2, monitor_slow_every=2)
        self.assertTrue(stranger)
        self.assertIn("S8", [s["id"] for s in res["stops"]])
        rec = self.record()
        self.assertEqual(rec["state"], "QUARANTINED", res["stops"])
        self.assertTrue(rec["owner_review_required"])
        self.assertEqual(self.signalled("driver"), [])  # the owner was never killed
        self.assertIsNone(stranger[0].poll())

    def test_remote_instance_writes_the_flag_whenever_the_record_exists(self):
        rs = T.LockedRecords(os.path.join(self.tmp, "root"))
        rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        cfg = type("C", (), {"port": 1})()
        inst = D.RemoteInstance(cfg, rs, "r1", os.path.join(self.tmp, "rd"), lambda *a, **k: {})
        self.assertFalse(inst.writer_enabled)
        self.assertTrue(inst.mark_owner_review("S8: x"))
        d = rs.read("r1")
        self.assertEqual((d["state"], d["owner_review_required"]), ("INTENT", True))

    def test_owner_refreshes_the_record_before_its_final_write(self):
        import e3_owner as O
        rs = T.LockedRecords(os.path.join(self.tmp, "root"))
        rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        rs.annotate(rs.read("r1"), owner_review_required=True)  # another writer flags it; the Owner's copy is stale
        self.assertFalse(rec.get("owner_review_required"))
        seen = {}
        orig = H.Instance._finalize
        H.Instance._finalize = lambda self_, out, pol: seen.update(flag=self_.rec.get("owner_review_required")) or out
        try:
            fake = type("I", (), {"records": rs, "rec": rec})()
            O.OwnerInstance._finalize(fake, {}, None)
        finally:
            H.Instance._finalize = orig
        self.assertTrue(seen["flag"])


class TestBackstopSafetyForQuarantinedRecord(Scenario):
    def test_backstop_still_kills_a_live_process_of_a_quarantined_record_without_rewriting_it(self):
        self.env()
        rs = T.LockedRecords(self.root)
        run_dir = os.path.join(self.root, "runs", "r1")
        os.makedirs(run_dir)
        p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], preexec_fn=lambda: os.setpgid(0, 0))
        self.addCleanup(p.kill)
        i = L.identity(p.pid)
        rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "zz-" + str(p.pid), "port": 59})
        rs.advance(rec, "SPAWNED", pid=p.pid, start=i["start"], pgid=i["pgid"], binding_verified=False, descendants=[])
        rs.advance(rec, "BOUND", binding_verified=True)
        rs.advance(rec, "QUARANTINED", reason="synthetic")
        before = rs.read("r1")
        pilot = D.Pilot.__new__(D.Pilot)
        pilot.records, pilot.run_id, pilot.b, pilot.summary = rs, "r1", BT, {}
        pilot.ledger, pilot.inst = T.SignalLedger(run_dir), None
        pilot.finalize_nonparent("driver_backstop")
        p.wait(5)  # it was signalled by identity
        self.assertEqual(rs.read("r1"), before)  # and the sticky record was not touched


class TestOrphanVariants(Scenario):
    def test_orphan_that_exits_by_itself_is_an_observation_not_a_successor_kill(self):
        self.env(mode="exit_after_gen", gen_s=2.0)
        res = self.pilot(bounds=dict(BT, idle_after_reader_s=4.0))
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        self.assertIs(self.view()["orphan"]["exited_by_itself"], True)
        self.assertEqual(self.view()["orphan"]["exit_cause"]["cause"], T.NO_SIGNAL)  # no experiment signal recorded: not a stronger claim
        self.assertEqual(self.signalled("successor"), [])
        rows = self.view()["rows"]
        self.assertEqual(rows["rows"]["O4_successor_termination"], "INCONCLUSIVE")
        self.assertEqual(rows["rows"]["B4_successor_side"], "INCONCLUSIVE")
        self.assertEqual(self.record()["terminated_by"], "self_exit")
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    QUARANTINING_SUCCESSOR = (
        "import os,sys\n"
        "sys.path.insert(0, %r)\n"
        "import e3_lib as T\n"
        "records = T.LockedRecords(sys.argv[1])\n"
        "rid = [f for f in os.listdir(records.dir) if f.endswith('.json')][0][:-5]\n"
        "rec = records.read(rid)\n"
        "fields = {'reason': 'unit test: the successor left a quarantine behind', 'waitpid_evidence': False}\n"
        "if sys.argv[2] == 'wrong_start':\n"
        "    fields['start'] = [1, 1]  # the record and the kernel now disagree about the runtime's identity\n"
        "records.advance(rec, 'QUARANTINED', **fields)\n"
        "sys.exit(1)\n")

    def quarantining_successor(self, wrong_start):
        return [sys.executable, "-B", "-c", self.QUARANTINING_SUCCESSOR % HERE, self.root, "wrong_start" if wrong_start else "ok"]

    def test_driver_kills_a_live_runtime_left_behind_by_a_quarantining_successor(self):
        self.env(gen_s=20.0)  # the runtime is still generating when the successor quarantines the record
        res = self.pilot(bounds=dict(BT, reader_deadline_s=40.0), successor_cmd=self.quarantining_successor(False))
        rec = self.record()
        self.assertEqual((rec["state"], res["outcome"]), ("QUARANTINED", "QUARANTINED"))
        self.assertEqual([h["state"] for h in rec["history"]][-1], "QUARANTINED")  # sticky: never rewritten, never cleared
        self.assertNotIn("EXIT_VERIFIED", [h["state"] for h in rec["history"]])
        sent = [(s["who"], s["sig"]) for s in self.signals() if s["pid"] == rec["pid"] and s["sent"]]
        self.assertEqual(sent, [("driver_cleanup", int(signal.SIGKILL))])  # exactly one, through the ledger
        self.assertEqual(self.view()["quarantine_cleanup"]["attempts"], [{"sent": True, "why": None}])
        self.assertTrue(wait_until(lambda: (lambda i: i is None or i["status"] == "zombie")(L.identity(rec["pid"])), 10))
        self.assertEqual(L.tag_scan(rec["tag"]), [])

    def test_cleanup_sends_nothing_when_the_recorded_identity_does_not_match_the_kernel(self):
        self.env(gen_s=20.0)
        res = self.pilot(bounds=dict(BT, reader_deadline_s=40.0), successor_cmd=self.quarantining_successor(True))
        rec = self.record()
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertEqual(self.view()["quarantine_cleanup"]["attempts"], [{"sent": False, "why": "identity_mismatch_or_gone"}])
        self.assertEqual([s for s in self.signals() if s["pid"] == rec["pid"] and s["sent"]], [])  # fail closed: no signal at all
        alive_now = L.tag_scan(rec["tag"])
        self.addCleanup(lambda: [L.safe_kill(i["pid"], i["start"], signal.SIGKILL) for i in alive_now])  # by true kernel identity
        self.assertEqual(len(alive_now), 1)  # the real runtime is still alive: nothing was signalled

    def test_cleanup_does_not_repeat_a_sigkill_the_ledger_already_recorded(self):
        # a Successor that quarantined after its own SIGKILL: the ledger refuses a second SIGKILL to the same identity
        self.env(mode="ignore_term", gen_s=2.0)
        res = self.pilot()
        rec = self.record()
        ledger = T.SignalLedger(self.run_dir())
        n = len([s for s in ledger.entries() if s["sent"]])
        again = ledger.send("driver_cleanup", rec["pid"], rec["start"], signal.SIGKILL, "driver_cleanup")
        self.assertEqual((again["sent"], again["why"]), (False, "already_killed"))
        self.assertEqual(len([s for s in ledger.entries() if s["sent"]]), n)

    def test_runtime_that_ignores_term_is_killed_by_the_successor_after_the_grace(self):
        self.env(mode="ignore_term", gen_s=2.0)
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        sigs = [s["sig"] for s in self.signalled("successor") if s["pid"] == self.record()["pid"]]
        self.assertEqual(sigs, [int(signal.SIGTERM), int(signal.SIGKILL)])
        self.assertNoLeftovers()

    def test_successor_that_hangs_triggers_the_driver_backstop(self):
        self.env(gen_s=2.0)
        hang = [sys.executable, "-B", "-c", "import time;time.sleep(300)"]
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=hang)
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        v = self.view()
        self.assertTrue(v["backstop_used"])
        self.assertEqual(v["rows"]["rows"]["B4_successor_side"], "INCONCLUSIVE")
        rec = self.record()
        self.assertEqual((rec["state"], rec["cleared_by"], rec["terminated_by"]), ("EXIT_VERIFIED", "driver_backstop", "driver_backstop"))
        self.assertTrue(all(s["who"].startswith("driver") for s in self.signalled() if s["pid"] == rec["pid"]))
        self.assertIs(self.view()["orphan"]["exited_by_itself"], False)  # the backstop's kill is never a spontaneous exit
        self.assertEqual(self.view()["orphan"]["exit_cause"]["cause"], T.SIGNALLED)
        self.assertEqual(self.view()["orphan"]["exit_cause"]["by"], ["driver_backstop"])
        t_rel = v["timeline"]["backstop_rel_s"]
        self.assertGreaterEqual(t_rel, 7.9)
        self.assertEqual(v["successor_returncode"], -int(signal.SIGKILL))  # the hung successor was stopped, not left behind
        self.assertNoLeftovers()

    def test_successor_that_crashes_triggers_the_backstop_without_waiting_for_the_deadline(self):
        self.env(gen_s=2.0)
        crash = [sys.executable, "-B", "-c", "import sys;sys.exit(3)"]
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=crash)
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        self.assertLess(self.view()["timeline"]["backstop_rel_s"], 5.0)
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def test_environmental_stop_after_the_owner_died_ends_the_window_and_withholds_verdicts(self):
        self.env(gen_s=6.0)
        probes = StubProbes()
        threading.Thread(target=lambda: (wait_until(lambda: any(s["who"] == "driver" for s in self.live_signals()), 40),
                                         setattr(probes, "src", "Battery Power")), daemon=True).start()
        res = self.pilot(probes=probes, monitor_interval=0.2, monitor_slow_every=2, bounds=dict(BT, orphan_max_s=20.0, backstop_s=30.0,
                                                                                                reader_deadline_s=40.0, prekill_abort_s=8.0))
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("S4", [s["id"] for s in res["stops"]])
        self.assertLess(self.view()["orphan"]["window_s"], 8.0)  # ended at the stop, not at the reader + idle
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def live_signals(self):
        out = []
        runs = os.path.join(self.root, "runs")
        for d in os.listdir(runs) if os.path.isdir(runs) else []:
            out += T.SignalLedger(os.path.join(runs, d)).entries()
        return out

    def test_topology_violation_after_the_kill_kills_by_identity_and_quarantines(self):
        self.env(mode="fork_late", gen_s=2.0, profile=E.SANDBOX)  # the no-fork profile would deny the stand-in's fork
        real = H.controls
        H.controls = lambda *a, **k: {"passed": True}  # Phase 2 asserts the no-fork profile, which this scenario deliberately lacks
        self.addCleanup(lambda: setattr(H, "controls", real))
        res = self.pilot(monitor_interval=0.2, monitor_slow_every=2)
        self.assertIn("S8", [s["id"] for s in res["stops"]], res["stops"])
        rec = self.record()
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertTrue(rec["owner_review_required"])
        self.assertEqual(res["outcome"], "QUARANTINED")
        self.assertEqual(self.view()["rows"]["rows"]["B4_successor_side"], "INCONCLUSIVE")
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        orphan = self.view()["orphan"]  # the monitor's emergency kill is not a spontaneous exit, whatever the Successor saw
        self.assertIs(orphan["exited_by_itself"], False)
        self.assertEqual((orphan["exit_cause"]["cause"], orphan["exit_cause"]["by"]), (T.SIGNALLED, ["driver-monitor"]))
        self.assertNotEqual(rec.get("terminated_by"), "self_exit")


class TestSecondProcess(Scenario):
    """Driver failure and operator interruption, with the Driver in its own process."""

    def start_driver(self, faults=None, bounds=None):
        spec = {k: self.spec[k] for k in ("bench", "pins", "binary", "model", "port", "doc", "e3pins")}
        spec.update(faults=faults, bounds=bounds or BT)
        self.proc = subprocess.Popen([sys.executable, "-B", "-W", "ignore", os.path.abspath(__file__), "--driver", json.dumps(spec)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.proc.poll() is None and self.proc.kill())
        return self.proc

    def run_dirs(self):
        d = os.path.join(self.root, "runs")
        return [os.path.join(d, n) for n in os.listdir(d)] if os.path.isdir(d) else []

    def ledger_has(self, who, sig=None):
        for rd in self.run_dirs():
            for e in T.SignalLedger(rd).entries():
                if e["who"] == who and e["sent"] and (sig is None or e["sig"] == int(sig)):
                    return True
        return False

    def file_exists(self, name):
        return any(os.path.exists(os.path.join(rd, name)) for rd in self.run_dirs())

    def only_record_path(self):
        d = os.path.join(self.root, "records")
        names = [n for n in os.listdir(d) if n.endswith(".json")]
        return os.path.join(d, names[0])

    def rec(self):
        return json.load(open(self.only_record_path()))

    def test_interrupt_before_the_kill_shuts_down_through_the_owner(self):
        self.env(gen_s=10.0)
        p = self.start_driver(bounds=dict(BT, arm_delay_s=6.0, prekill_abort_s=15.0, reader_deadline_s=40.0))
        self.assertTrue(wait_until(lambda: self.file_exists("reader.jsonl") and "SENT" in open(os.path.join(self.run_dirs()[0], "reader.jsonl")).read(), 40))
        os.kill(p.pid, signal.SIGINT)
        p.wait(60)
        rec = self.rec()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertFalse(self.ledger_has("driver", signal.SIGKILL))
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(L.listeners(self.spec["port"])["pids"], [])
        view = json.load(open(os.path.join(self.run_dirs()[0], "summary-committed-view.json")))
        self.assertIn("S11", [s["id"] for s in view["stops"]])
        self.assertFalse(os.path.exists(os.path.join(self.run_dirs()[0], "scratch", "api-key")))

    def test_interrupt_after_the_kill_still_completes_the_termination(self):
        self.env(gen_s=12.0)
        p = self.start_driver(bounds=dict(BT, orphan_max_s=30.0, backstop_s=45.0, reader_deadline_s=60.0, idle_after_reader_s=20.0))
        self.assertTrue(wait_until(lambda: self.ledger_has("driver", signal.SIGKILL), 40))
        time.sleep(0.8)
        os.kill(p.pid, signal.SIGINT)
        os.kill(p.pid, signal.SIGINT)  # a second signal does not skip the termination
        p.wait(60)
        rec = self.rec()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        view = json.load(open(os.path.join(self.run_dirs()[0], "summary-committed-view.json")))
        self.assertIn("S11", [s["id"] for s in view["stops"]])
        self.assertLess(view["orphan"]["window_s"], 10.0)

    def test_driver_killed_right_before_the_owner_kill_owner_shuts_the_runtime_down(self):
        self.env(gen_s=6.0)
        p = self.start_driver(faults={"die_at": "before_kill"})
        p.wait(60)
        self.assertEqual(p.returncode, -int(signal.SIGKILL))
        rec = self.rec()
        self.assertTrue(wait_until(lambda: self.rec()["state"] in ("EXIT_VERIFIED", "QUARANTINED"), 30), rec["state"])
        self.assertEqual(self.rec()["state"], "EXIT_VERIFIED")  # stdin EOF made the live owner run the normal shutdown
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        key = os.path.join(self.run_dirs()[0], "scratch", "api-key")
        self.assertTrue(os.path.exists(key))  # a dead driver cannot delete it ...
        cfg = cfg3(self.spec)
        rep = D.recover(cfg, os.path.basename(self.only_record_path())[:-5])
        self.assertFalse(os.path.exists(key))  # ... recovery does
        self.assertTrue(rep["key_file_removed"])

    def test_driver_killed_after_the_owner_kill_orphan_is_recovered_by_the_owner_directed_tool(self):
        self.env(gen_s=3.0)
        p = self.start_driver(faults={"die_at": "after_kill"})
        p.wait(60)
        self.assertEqual(p.returncode, -int(signal.SIGKILL))
        rec = self.rec()
        self.assertEqual(rec["state"], "BOUND")  # nobody finalised it
        self.assertTrue(alive(rec["pid"], rec["start"]))  # the orphan lives; its bound is not guaranteed
        run_id = os.path.basename(self.only_record_path())[:-5]
        cfg = cfg3(self.spec)
        rep = D.recover(cfg, run_id)  # read-only classification
        self.assertEqual(rep["verdict"], L.ALIVE)
        self.assertTrue(alive(rec["pid"], rec["start"]))
        rep = D.recover(cfg, run_id, kill=True, confirm=run_id)
        self.assertEqual(rep["verdict"], L.TERMINATED, rep)
        self.assertEqual(self.rec()["state"], "EXIT_VERIFIED")
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(L.listeners(self.spec["port"])["pids"], [])

    def test_driver_killed_after_the_successor_started_the_successor_still_finishes(self):
        self.env(gen_s=2.0)
        p = self.start_driver(faults={"die_at": "after_successor_start"}, bounds=dict(BT, orphan_max_s=4.0, backstop_s=9.0))
        p.wait(60)
        self.assertEqual(p.returncode, -int(signal.SIGKILL))
        self.assertTrue(wait_until(lambda: self.rec()["state"] in ("EXIT_VERIFIED", "QUARANTINED"), 30))
        rec = self.rec()
        self.assertEqual((rec["state"], rec["terminated_by"]), ("EXIT_VERIFIED", "successor"))
        self.assertEqual(L.tag_scan(rec["tag"]), [])

    def test_a_live_driver_holds_the_run_lock_so_recovery_cannot_race_it(self):
        self.env(gen_s=8.0)
        p = self.start_driver(bounds=dict(BT, arm_delay_s=6.0, prekill_abort_s=15.0, reader_deadline_s=40.0))
        self.assertTrue(wait_until(lambda: self.file_exists("reader.jsonl"), 40))
        run_id = os.path.basename(self.only_record_path())[:-5]
        rep = D.recover(cfg3(self.spec), run_id, kill=True, confirm=run_id)
        self.assertEqual(rep["verdict"], "REFUSED_RUN_LOCK_HELD")
        os.kill(p.pid, signal.SIGINT)
        p.wait(60)


class TestMoreOrphanFacts(Scenario):
    def test_a_new_connection_after_the_kill_is_a_stop(self):
        self.env(gen_s=6.0)
        import socket
        held = []

        def connect_late():
            wait_until(lambda: any(s["who"] == "driver" for s in self.live_signals()), 40)
            time.sleep(0.6)
            c = socket.create_connection(("127.0.0.1", self.spec["port"]), timeout=2)
            held.append(c)
        threading.Thread(target=connect_late, daemon=True).start()
        self.addCleanup(lambda: [c.close() for c in held])
        res = self.pilot(bounds=dict(BT, orphan_max_s=5.0, backstop_s=10.0, reader_deadline_s=30.0))
        self.assertIn("E3-3", [s["id"] for s in res["stops"]], res["stops"])
        self.assertGreaterEqual(self.view()["http_after_kill"]["new_connections_seen_by_lsof_after_baseline"], 1)
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")

    def live_signals(self):
        out = []
        runs = os.path.join(self.root, "runs")
        for d in os.listdir(runs) if os.path.isdir(runs) else []:
            out += T.SignalLedger(os.path.join(runs, d)).entries()
        return out

    def test_a_stale_trigger_sends_no_kill(self):
        self.env(gen_s=4.0)
        real = D.Pilot.annotate_e3

        def slow(self_, **kw):
            if kw.get("planned") == "owner_sigkill":
                time.sleep(0.6)  # longer than the 0.2 s staleness bound
            return real(self_, **kw)
        D.Pilot.annotate_e3 = slow
        self.addCleanup(lambda: setattr(D.Pilot, "annotate_e3", real))
        res = self.pilot()
        self.assertEqual(res["outcome"], "TRIGGER_STALE")
        self.assertEqual([s for s in self.live_signals() if s["who"] == "driver"], [])
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def test_monitor_death_after_the_kill_ends_the_window_and_terminates(self):
        self.env(gen_s=12.0)
        real = E.StopEvaluator.feed

        def feed(self_, s):
            if any(e["who"] == "driver" for e in self.live_signals()):
                raise RuntimeError("synthetic monitor failure")
            return real(self_, s)
        E.StopEvaluator.feed = feed
        self.addCleanup(lambda: setattr(E.StopEvaluator, "feed", real))
        res = self.pilot(monitor_interval=0.2, bounds=dict(BT, orphan_max_s=30.0, backstop_s=45.0, reader_deadline_s=60.0, idle_after_reader_s=20.0))
        self.assertIn("S13", [s["id"] for s in res["stops"]], res["stops"])
        self.assertLess(self.view()["orphan"]["window_s"], 6.0)  # ended at the monitor failure, not at the 30 s bound
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertNoLeftovers()

    def test_request_cut_short_by_the_termination_is_recorded_as_such_and_is_not_a_verdict(self):
        self.env(gen_s=30.0)
        res = self.pilot(bounds=dict(BT, orphan_max_s=2.0, backstop_s=7.0, reader_deadline_s=30.0))
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        obs = self.view()["rows"]["observations"]
        self.assertEqual(obs["O5_reader_outcome_class"], "NO_RESPONSE_CONNECTION_CLOSED")
        self.assertFalse(self.view()["reader"]["client_completed"])
        self.assertIn("not B3", obs["O5_note"])
        self.assertEqual(self.view()["rows"]["rows"]["late_delivery_excluded"], "NOT_TESTED")


# ============================================================================================
# Independent-review remediation (R1-R6, N1-N2): each test reproduces the finding it is named for.
# ============================================================================================


def gone(pid, start=None):
    i = L.identity(pid)
    return i is None or i["status"] == "zombie" or (start is not None and i["start"] != list(start))


def live(pid):
    i = L.identity(pid)
    return bool(i) and i["status"] != "zombie"


class TestR1WrongTargetRecovery(Base):
    """R1: after root-pid reuse, recovery must never discover (or signal) the children of the unrelated process
    that now occupies the pid."""

    UNRELATED_PARENT = ("import subprocess, sys, time\n"
                        "kids = [subprocess.Popen(['/bin/sleep', '60']) for _ in range(2)]\n"
                        "print(' '.join(str(k.pid) for k in kids), flush=True)\n"
                        "time.sleep(60)\n")

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "e3root")
        self.procs = []
        self.addCleanup(self.kill_created)

    def kill_created(self):  # SIGKILL only: nothing is waited for here
        for p in self.procs:
            try:
                p.kill()
            except OSError:
                pass
        for pid in getattr(self, "kids", []):
            try:
                os.kill(pid, signal.SIGKILL)  # test hygiene only: processes this test created
            except OSError:
                pass

    def unrelated_family(self):
        p = subprocess.Popen([sys.executable, "-B", "-c", self.UNRELATED_PARENT], stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.kids = [int(x) for x in p.stdout.readline().split()]
        self.assertEqual(len(self.kids), 2)
        self.assertTrue(wait_until(lambda: all(live(k) for k in self.kids), 10))
        return p

    def sleeper(self):
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.procs.append(p)
        return p, L.identity(p.pid)

    def make_record(self, pid, start, descendants=(), review=True, rid="rr1"):
        rs = T.LockedRecords(self.root)
        rec = rs.create({"v": 1, "run_id": rid, "state": "INTENT", "tag": "no-such-tag-" + rid, "port": 59,
                         "boottime": E.HostProbes().boottime()})
        rs.advance(rec, "SPAWNED", pid=pid, start=list(start), pgid=pid, binding_verified=False, descendants=list(descendants))
        rs.advance(rec, "BOUND", binding_verified=True)
        if review:
            rs.annotate(rec, owner_review_required=True, owner_review_reason="unit test")
        return rs

    def recover(self, rs, rid="rr1"):
        return T.recover_locked(rs, rid, E.HostProbes().boottime(), kill=True, confirm=rid, sleep=lambda _: None)

    def test_the_e2b_recover_alone_would_kill_the_unrelated_children(self):
        # the finding, reproduced against the frozen E2-B code: it enumerates descendants of whatever holds the pid
        parent = self.unrelated_family()
        rs = self.make_record(parent.pid, [1, 1])  # the recorded root identity does not match the process now at that pid
        E.recover(rs, "rr1", E.HostProbes().boottime(), True, "rr1", sleep=lambda _: None)
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10), "the defect this test documents: children are signalled")
        self.assertIsNone(parent.poll())  # only the children: the parent is protected by its start time

    def test_e3_recovery_never_signals_the_children_of_a_process_that_reused_the_root_pid(self):
        for review in (True, False):
            with self.subTest(owner_review=review):
                parent = self.unrelated_family()
                rid = "rr-%s" % review
                rs = self.make_record(parent.pid, [1, 1], review=review, rid=rid)
                rep = self.recover(rs, rid)
                time.sleep(0.5)
                self.assertTrue(all(live(k) for k in self.kids), rep)
                self.assertIsNone(parent.poll())
                self.assertNotEqual(rs.read(rid)["state"], "EXIT_VERIFIED" if review else None)
                if review:
                    self.assertEqual(rep["verdict"], "QUARANTINE_OWNER_REVIEW")  # the quarantine stays: identity cannot be established
                    self.assertFalse(rep["actions"][0]["root_verified"])
                    self.assertEqual(rep["actions"][0]["fresh_descendants"], 0)
                    self.assertEqual(rs.read(rid)["state"], "BOUND")
                parent.kill()
                parent.wait(5)
                for k in self.kids:
                    os.kill(k, signal.SIGKILL)
                self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10))

    def test_recorded_descendants_are_still_killed_individually_when_the_root_identity_does_not_match(self):
        parent = self.unrelated_family()
        recorded, rident = self.sleeper()  # an earlier, individually verified descendant of the real runtime
        rs = self.make_record(parent.pid, [1, 1], descendants=[{"pid": recorded.pid, "start": rident["start"], "ppid": 1, "pgid": 1}])
        rep = self.recover(rs)
        self.assertEqual(recorded.wait(10), -int(signal.SIGKILL))
        self.assertTrue(all(live(k) for k in self.kids))
        self.assertEqual((rep["actions"][0]["recorded_descendants"], rep["actions"][0]["fresh_descendants"]), (1, 0))

    def test_a_recorded_descendant_whose_own_identity_changed_is_not_signalled(self):
        stranger, ident = self.sleeper()
        rs = self.make_record(self.unrelated_family().pid, [1, 1],
                         descendants=[{"pid": stranger.pid, "start": [ident["start"][0] - 9, ident["start"][1]], "ppid": 1, "pgid": 1}])
        self.recover(rs)
        time.sleep(0.4)
        self.assertIsNone(stranger.poll())

    def test_a_verified_root_still_has_its_fresh_descendants_and_itself_killed(self):
        parent = self.unrelated_family()  # here it genuinely IS the recorded root
        rs = self.make_record(parent.pid, L.identity(parent.pid)["start"])
        rep = self.recover(rs)
        self.assertEqual(parent.wait(10), -int(signal.SIGKILL))
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10), rep)
        self.assertTrue(rep["actions"][0]["root_verified"])
        self.assertEqual(rep["actions"][0]["fresh_descendants"], 2)

    def test_recovery_through_the_harness_entry_point_uses_the_same_rule(self):
        parent = self.unrelated_family()
        self.make_record(parent.pid, [1, 1])
        cfg = types.SimpleNamespace(root=self.root)
        rep = D.recover(cfg, "rr1", kill=True, confirm="rr1")
        time.sleep(0.5)
        self.assertEqual(rep["verdict"], "QUARANTINE_OWNER_REVIEW")
        self.assertTrue(all(live(k) for k in self.kids))

    def remote_instance(self, pid, start):
        inst = D.RemoteInstance.__new__(D.RemoteInstance)
        inst.root = {"pid": pid, "start": list(start), "pgid": pid}
        inst.known, inst._known_lock, inst.rec, inst.writer_enabled, inst.persist_errors = {}, threading.RLock(), None, False, []
        os.makedirs(os.path.join(self.tmp, "run"), exist_ok=True)
        inst.kill_fn = T.SignalLedger(os.path.join(self.tmp, "run")).kill_fn("driver-monitor", "test")
        return inst

    def test_the_monitors_emergency_kill_does_not_discover_through_an_unverified_root(self):
        parent = self.unrelated_family()
        D.RemoteInstance.emergency_kill(self.remote_instance(parent.pid, [1, 1]))
        time.sleep(0.5)
        self.assertTrue(all(live(k) for k in self.kids))
        self.assertIsNone(parent.poll())

    def test_the_inherited_emergency_kill_would_have_done_so(self):
        parent = self.unrelated_family()
        H.Instance.emergency_kill(self.remote_instance(parent.pid, [1, 1]))  # the frozen code the override replaces
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10), "the defect this test documents")

    def test_a_verified_runtime_is_still_killed_with_its_tree_by_the_emergency_kill(self):
        parent = self.unrelated_family()
        D.RemoteInstance.emergency_kill(self.remote_instance(parent.pid, L.identity(parent.pid)["start"]))
        self.assertEqual(parent.wait(10), -int(signal.SIGKILL))
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10))


STALL_SUCCESSOR = (
    "import fcntl, os, sys, time\n"
    "root, which = sys.argv[1], sys.argv[2]  # argv[3] is only a marker for test hygiene\n"
    "rid = [f for f in os.listdir(os.path.join(root, 'records')) if f.endswith('.json')][0][:-5]\n"
    "path = os.path.join(root, 'locks', rid + '.lock') if which == 'records' else os.path.join(root, 'runs', rid, 'signals.lock')\n"
    "fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "time.sleep(300)\n")


class Holder:
    """A process that holds a flock and sleeps (a stalled lock holder)."""

    def __init__(self, path, seconds=300):
        self.p = subprocess.Popen([sys.executable, "-B", "-c",
                                   "import fcntl,os,sys,time\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n"
                                   "fcntl.flock(fd,fcntl.LOCK_EX)\nprint('held',flush=True)\ntime.sleep(float(sys.argv[2]))\n", path, str(seconds)],
                                  stdout=subprocess.PIPE, text=True)
        assert self.p.stdout.readline().strip() == "held"

    def stop(self):
        self.p.kill()
        self.p.wait(5)


class TestR2BoundedLocks(Base):
    def setUp(self):
        super().setUp()
        self.holders = []
        self.addCleanup(lambda: [h.stop() for h in self.holders])

    def test_flock_bounded_gives_up_at_its_bound_and_the_holders_death_releases_it(self):
        path = os.path.join(self.tmp, "x.lock")
        h = Holder(path)
        self.holders.append(h)
        fd = os.open(path, os.O_RDWR)
        t = time.monotonic()
        self.assertRaises(T.LockTimeout, T.flock_bounded, fd, 0.3)
        self.assertLess(time.monotonic() - t, 1.5)
        h.stop()
        T.flock_bounded(fd, 0.5)  # free once the holder is dead
        os.close(fd)

    def test_a_record_write_behind_a_stalled_lock_holder_fails_within_its_bound(self):
        rs = T.LockedRecords(os.path.join(self.tmp, "root"), lock_timeout_s=0.3)
        rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        self.holders.append(Holder(rs._lock_file("r1")))
        for write in (lambda: rs.annotate(rec, a=1), lambda: rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])):
            t = time.monotonic()
            self.assertRaises(T.LockTimeout, write)
            self.assertLess(time.monotonic() - t, 1.5)
        self.assertNotIn("a", rs.read("r1"))  # nothing was written
        self.assertEqual(rs.read("r1")["state"], "INTENT")

    def test_a_signal_behind_a_stalled_ledger_lock_is_refused_within_its_bound_and_sends_nothing(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        ledger = T.SignalLedger(run, lock_timeout_s=0.3)
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(p.kill)
        self.holders.append(Holder(ledger.lock))
        t = time.monotonic()
        r = ledger.send("t", p.pid, L.identity(p.pid)["start"], signal.SIGKILL, "unit")
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual((r["sent"], r["why"]), (False, "ledger_lock_timeout"))
        self.assertIsNone(p.poll())
        self.assertEqual(ledger.entries(), [])  # it cannot be appended without the lock

    def test_a_per_call_deadline_shortens_the_wait(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        ledger = T.SignalLedger(run, lock_timeout_s=30.0)
        self.holders.append(Holder(ledger.lock))
        t = time.monotonic()
        self.assertEqual(ledger.send("t", 1, [1, 1], signal.SIGKILL, timeout_s=0.2)["why"], "ledger_lock_timeout")
        self.assertLess(time.monotonic() - t, 1.5)

    def test_the_lock_bound_is_a_checked_bound(self):
        self.assertIn("lock_timeout_s", T.BOUNDS)
        self.assertEqual(T.check_bounds(), [])
        for bad in (0, -1, 6.0):
            self.assertTrue(T.check_bounds(dict(T.BOUNDS, lock_timeout_s=bad)))

    def test_the_cleanup_and_stop_paths_stop_the_successor_first(self):
        tree = ast.parse(open(os.path.join(HERE, "e3_harness.py")).read())
        fns = {n.name: ast.unparse(n) for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "Pilot" for n in c.body if isinstance(n, ast.FunctionDef)}
        for name in ("backstop", "finalize_after_stop", "cleanup"):
            self.assertIn("self.stop_successor()", fns[name], name)
        self.assertLess(fns["finalize_after_stop"].index("stop_successor"), fns["finalize_after_stop"].index("finalize_nonparent"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lifetime")
        generic = ast.unparse(next(n for n in fn.body if isinstance(n, ast.Try)).handlers[-1])
        self.assertIn("HARNESS_EXCEPTION", generic)
        self.assertIn("finalize_after_stop", generic)
        self.assertNotIn("finalize_nonparent", generic)  # the generic post-kill exception path is the bounded, Successor-first one


class TestR2StalledSuccessor(Scenario):
    """A Successor stalled while holding a shared lock must not keep the Driver from its backstop."""

    def stalled(self, which, exception=False):
        self.env(gen_s=2.0)
        marker = self.marker = "stall-" + secrets.token_hex(4)
        self.addCleanup(lambda: subprocess.run(["pkill", "-9", "-f", marker]))  # test hygiene: only this test's stalled process
        cmd = [sys.executable, "-B", "-c", STALL_SUCCESSOR, self.root, which, marker]
        fired = threading.Event()

        def rescue():  # if the Driver were blocked, free it so the suite cannot hang, and fail the test
            fired.set()
            subprocess.run(["pkill", "-9", "-f", marker])
        watchdog = threading.Timer(45.0, rescue)
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        if exception:
            real = D.Pilot.drain

            def drain(self_, prekill):
                if (not prekill and self_.successor is not None and self_.successor.poll() is None
                        and T.uptime() - self_.tl["successor_start_up"] > 1.2):  # the stalled process holds its lock by now
                    raise RuntimeError("synthetic failure while observing the orphan")
                return real(self_, prekill)
            D.Pilot.drain = drain
            self.addCleanup(lambda: setattr(D.Pilot, "drain", real))
        t = time.monotonic()
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0, lock_timeout_s=0.4), successor_cmd=cmd)
        self.elapsed = time.monotonic() - t
        self.assertFalse(fired.is_set(), "the Driver was blocked by the stalled Successor")
        return res

    def assertBackstopped(self, res):
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        rec = self.record()
        self.assertEqual((rec["state"], rec["cleared_by"]), ("EXIT_VERIFIED", "driver_backstop"))
        t = self.view()["timeline"]["backstop_rel_s"]
        self.assertGreaterEqual(t, 7.9)
        self.assertLess(t, 8.0 + 3.0)  # reached at its deadline; an iteration is bounded by its own calls
        self.assertEqual(self.view()["successor_returncode"], -int(signal.SIGKILL))
        self.assertNoLeftovers()

    def test_a_successor_stalled_holding_the_record_lock(self):
        res = self.stalled("records")
        self.assertBackstopped(res)
        raw = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertIn("e3_annotate: LockTimeout", raw["persist_errors"])  # the failed annotation did not block the safety path

    def test_a_successor_stalled_holding_the_signal_ledger_lock(self):
        self.assertBackstopped(self.stalled("signals"))

    def test_an_exception_during_orphan_observation_with_the_successor_holding_the_record_lock(self):
        res = self.stalled("records", exception=True)
        self.assertCleanedUpAfterException(res)

    def test_an_exception_during_orphan_observation_with_the_successor_holding_the_ledger_lock(self):
        res = self.stalled("signals", exception=True)
        self.assertCleanedUpAfterException(res)

    def assertCleanedUpAfterException(self, res):
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("HARNESS_EXCEPTION", [s["id"] for s in res["stops"]])
        rec = self.record()
        self.assertEqual((rec["state"], rec["cleared_by"]), ("EXIT_VERIFIED", "driver_cleanup"))
        self.assertEqual(subprocess.run(["pgrep", "-f", self.marker], capture_output=True).returncode, 1)  # the stalled Successor was stopped
        self.assertNoLeftovers()  # and the runtime is dead
        self.assertLess(self.elapsed, 40.0)


class TestR3KillInstant(Scenario):
    """R3: every mandatory trigger condition is re-validated inside the ledger critical section."""

    def arm(self, effect):
        real = D.Pilot.kill_owner

        def kill(self_, trig):
            real_send = self_.ledger.send

            def send(*a, **kw):
                if a[0] == "driver" and a[3] == signal.SIGKILL:
                    effect(self_, trig)  # something happens while the ledger lock is awaited
                return real_send(*a, **kw)
            self_.ledger.send = send
            return real(self_, trig)
        D.Pilot.kill_owner = kill
        self.addCleanup(lambda: setattr(D.Pilot, "kill_owner", real))

    def assertNoKill(self, refusal):
        self.assertEqual([s for s in self.signals() if s["who"] == "driver" and s["sent"]], [])
        self.assertEqual([s["why"] for s in self.signals() if s["who"] == "driver"], [refusal])  # the refusal itself is on the ledger
        self.assertNotIn("t0_up", self.record()["e3"])
        self.assertIsNone(self.view()["http_after_kill"])  # the gate was never closed, no orphan phase
        self.assertIsNone(self.view()["owner_kill"])
        rec = self.record()
        self.assertEqual((rec["state"], rec["exit_basis"]), ("EXIT_VERIFIED", "owner_waitpid_and_conjunction"))  # the live Owner shut down normally
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")
        self.assertNoLeftovers()

    BIG = dict(BT, stale_s=0.2, prekill_abort_s=6.0, reader_deadline_s=30.0)

    def test_a_stop_that_arrives_while_the_ledger_lock_is_awaited_prevents_the_kill(self):
        self.env(gen_s=8.0)
        self.arm(lambda p, trig: p.mon.triggers.append({"id": "S5", "why": "thermal (during the ledger wait)", "immediate": False, "quarantine": False}))
        res = self.pilot(bounds=self.BIG)
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("S5", [s["id"] for s in res["stops"]])
        self.assertNoKill("precheck:stop")

    def test_an_interrupt_during_the_ledger_wait_prevents_the_kill(self):
        self.env(gen_s=8.0)
        ev = threading.Event()
        self.arm(lambda p, trig: ev.set())
        res = self.pilot(bounds=self.BIG, interrupted=ev)
        self.assertIn("operator interrupt", [s["why"] for s in res["stops"]])
        self.assertNoKill("precheck:stop")

    def test_reader_completion_during_the_ledger_wait_prevents_the_kill(self):
        self.env(gen_s=8.0)
        self.arm(lambda p, trig: p.q.put({"_src": "reader", "e": "DONE", "up": T.uptime(), "status": 200, "finish_reason": "stop",
                                          "client_completed": True}))
        res = self.pilot(bounds=self.BIG)
        self.assertEqual(res["outcome"], "TRIGGER_MISSED", res["stops"])
        self.assertIn("E3-MISSED", [s["id"] for s in res["stops"]])
        self.assertNoKill("precheck:reader_completed")

    def test_a_trigger_that_became_stale_during_the_ledger_wait_prevents_the_kill(self):
        self.env(gen_s=8.0)
        self.arm(lambda p, trig: time.sleep(0.5))  # longer than the 0.2 s staleness bound
        res = self.pilot(bounds=self.BIG)
        self.assertEqual(res["outcome"], "TRIGGER_STALE", res["stops"])
        self.assertIn("(stale)", [s["why"] for s in res["stops"] if s["id"] == "E3-STALE"][0])
        self.assertNoKill("precheck:stale")

    def test_a_trigger_that_timed_out_during_the_ledger_wait_prevents_the_kill(self):
        self.env(gen_s=8.0)
        self.arm(lambda p, trig: time.sleep(1.3))  # beyond the 1.0 s pre-kill bound counted from the request
        res = self.pilot(bounds=dict(self.BIG, prekill_abort_s=1.0))
        self.assertEqual(res["outcome"], "TRIGGER_STALE", res["stops"])
        self.assertIn("(timeout)", [s["why"] for s in res["stops"] if s["id"] == "E3-STALE"][0])
        self.assertNoKill("precheck:timeout")

    def test_a_published_but_not_yet_cancelled_trigger_prevents_the_kill(self):
        # the monitor appends its trigger BEFORE its slow persistence and sets cancel only afterwards
        self.env(gen_s=8.0)
        real = D.Pilot.annotate_e3

        def inject(self_, **kw):
            out = real(self_, **kw)
            if kw.get("planned") == "owner_sigkill":
                self_.mon.triggers.append({"id": "S5", "why": "thermal (published, cancel not yet set)", "immediate": False, "quarantine": False})
            return out
        D.Pilot.annotate_e3 = inject
        self.addCleanup(lambda: setattr(D.Pilot, "annotate_e3", real))
        res = self.pilot(bounds=self.BIG)
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertEqual([s for s in self.signals() if s["who"] == "driver"], [])
        self.assertNotIn("t0_up", self.record()["e3"])
        self.assertNoLeftovers()

    def test_the_stop_state_is_visible_from_the_trigger_list_alone(self):
        p = D.Pilot.__new__(D.Pilot)
        p.interrupted, p.cancel = threading.Event(), threading.Event()
        p.mon = types.SimpleNamespace(triggers=[], is_alive=lambda: True, halt=threading.Event())
        self.assertFalse(p.stop_active())
        p.mon.triggers.append({"id": "S1", "why": "x"})
        self.assertTrue(p.stop_active())
        self.assertRaises(H.StopRun, p.guard)

    def test_t0_is_the_instant_of_the_actual_signal_attempt_after_ledger_contention(self):
        self.env(gen_s=8.0)
        rel = {}

        def hold(p, trig):
            fd = os.open(os.path.join(p.run_dir, "signals.lock"), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)

            def release():
                time.sleep(0.15)
                rel["up"] = T.uptime()
                os.close(fd)
            threading.Thread(target=release, daemon=True).start()
        self.arm(hold)
        res = self.pilot(bounds=dict(self.BIG, stale_s=0.5))
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        t0 = self.record()["e3"]["t0_up"]
        self.assertGreaterEqual(t0, rel["up"])  # not the (earlier) instant before the lock wait
        sent = [s for s in self.signals() if s["who"] == "driver" and s["sent"]]
        self.assertEqual(len(sent), 1)
        self.assertAlmostEqual(sent[0]["up"], t0, places=6)  # the ledger and the record carry the same attempt time
        self.assertLessEqual(self.view()["http_after_kill"]["driver_gate_closed_at_t0_rel_s"], 0.0)

    def test_a_ledger_lock_that_stays_held_at_the_kill_instant_sends_nothing_and_shuts_down_normally(self):
        self.env(gen_s=8.0)

        def hold(p, trig):
            fd = os.open(os.path.join(p.run_dir, "signals.lock"), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            threading.Thread(target=lambda: (time.sleep(1.5), os.close(fd)), daemon=True).start()
        self.arm(hold)
        res = self.pilot(bounds=dict(self.BIG, lock_timeout_s=0.3))
        self.assertEqual(res["outcome"], "STOPPED", res["stops"])
        self.assertIn("E3-1", [s["id"] for s in res["stops"]])
        raw = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertEqual(raw["owner_kill_refused"], "ledger_lock_timeout")
        self.assertEqual([s for s in self.signals() if s["who"] == "driver" and s["sent"]], [])
        self.assertNotIn("t0_up", self.record()["e3"])
        self.assertIsNone(self.view()["http_after_kill"])
        self.assertEqual(self.record()["exit_basis"], "owner_waitpid_and_conjunction")
        self.assertNoLeftovers()


class TestR4StrictProcessingValue(Scenario):
    def test_only_the_literal_json_true_is_evidence(self):
        for good in ([{"is_processing": True}], [{"is_processing": False}, {"is_processing": True}]):
            self.assertEqual(T.slots_processing(good), (True, True))
        for no in ([{"is_processing": False}], [{}], [{"is_processing": None}], [{"is_processing": "true"}], [{"is_processing": "false"}],
                   [{"is_processing": 1}], [{"is_processing": 1.0}], [{"is_processing": "unknown"}], [{"is_processing": [True]}],
                   [{"is_processing": {"x": 1}}], [{"is_processing": 0}]):
            self.assertEqual(T.slots_processing(no), (True, False), no)

    def test_malformed_slot_responses_are_not_ok(self):
        for bad in (None, [], {}, {"is_processing": True}, "busy", 5, ["busy"], ["busy", {"is_processing": True}], [None], [[{"is_processing": True}]]):
            self.assertEqual(T.slots_processing(bad), (False, None), bad)

    def test_wrong_typed_values_can_never_make_the_trigger_fire(self):
        for val in ("true", "false", "unknown", 1, 1.0, [True], {"a": 1}):
            t = T.Trigger(dict(T.BOUNDS))
            t.request_sent(0.0)
            for k in range(10):
                ok, processing = T.slots_processing([{"is_processing": val}])
                t.poll(2.0 + k * 0.1, ok, processing)
            self.assertEqual(t.decide(3.5), T.WAIT, val)
        t = T.Trigger(dict(T.BOUNDS))
        t.request_sent(0.0)
        for k in range(10):
            ok, processing = T.slots_processing([{"is_processing": True}])
            t.poll(2.0 + k * 0.1, ok, processing)
        self.assertEqual(t.decide(3.0), T.FIRE)

    def not_reached(self, mode):
        self.env(mode=mode, gen_s=8.0)
        res = self.pilot(bounds=dict(BT, prekill_abort_s=2.5, reader_deadline_s=30.0))
        self.assertEqual(res["outcome"], "PILOT_NOT_REACHED", res["stops"])
        self.assertEqual([s for s in self.signals() if s["who"] == "driver"], [])  # the Owner was never killed
        self.assertNotIn("t0_up", self.record().get("e3", {}))
        self.assertEqual(self.record()["exit_basis"], "owner_waitpid_and_conjunction")
        self.assertNoLeftovers()

    def test_a_truthy_string_while_generating_is_not_active_generation(self):
        self.not_reached("processing_str")

    def test_a_number_while_generating_is_not_active_generation(self):
        self.not_reached("processing_int")

    def test_a_malformed_slot_list_is_not_active_generation_and_is_not_a_crash(self):
        self.not_reached("slots_malformed")


class TestR5TruthfulEvidence(Scenario):
    def raw(self):
        return json.load(open(os.path.join(self.run_dir(), "summary.json")))

    def assertOneStory(self, label, cause, exit_event=None):
        """The durable record, the raw report and the committed view say the same thing."""
        rec, raw, view = self.record(), self.raw(), self.view()
        self.assertEqual(rec["terminated_by"], label)
        self.assertEqual(rec["exit_cause"], cause)
        for name, d in (("raw", raw), ("committed", view)):
            self.assertEqual(d["exit"]["terminated_by"], label, name)
            self.assertEqual(d["successor"]["terminated_by"], label, name)
            self.assertEqual(d["exit"]["exit_cause"], cause, name)
            self.assertIs(d["exit"]["attribution_consistent"], True, name)
            self.assertEqual(d["orphan"]["exit_cause"]["cause"], cause, name)
        if exit_event is not None:
            self.assertEqual(rec["exit_event"], exit_event)
            self.assertEqual(view["exit"]["exit_event"], exit_event)

    def test_a_self_exit_is_never_labelled_a_successor_termination(self):
        self.env(mode="exit_after_gen", gen_s=2.0)
        res = self.pilot(bounds=dict(BT, idle_after_reader_s=4.0))
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        self.assertOneStory("self_exit", T.NO_SIGNAL)
        self.assertEqual(self.signalled("successor"), [])
        self.assertNotEqual(self.view()["successor"]["terminated_by"], "successor")
        self.assertIs(self.view()["orphan"]["exited_by_itself"], True)
        self.assertIn(self.record()["exit_event"], (T.EXIT_OBSERVED, T.EXIT_NO_NOTIFICATION))  # it was observed alive first: never "absent"
        self.assertNotEqual(self.record()["exit_event"], T.EXIT_UNOBSERVED)
        self.assertIsNone(self.record()["exit_code"])
        self.assertIs(self.record()["waitpid_evidence"], False)
        self.assertEqual(self.view()["rows"]["rows"]["O4_successor_termination"], "INCONCLUSIVE")

    def test_a_successor_termination_is_labelled_as_one_everywhere(self):
        self.env(gen_s=2.0)
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        self.assertOneStory("successor", T.SIGNALLED)
        self.assertEqual(self.view()["orphan"]["exit_cause"]["by"], ["successor"])
        self.assertEqual(self.view()["signals"]["successor"]["delivered"], 1)

    def test_a_backstop_termination_is_not_a_successor_termination_and_not_absent_at_first_observation(self):
        self.env(gen_s=2.0)
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=[sys.executable, "-B", "-c", "import time;time.sleep(300)"])
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        self.assertOneStory("driver_backstop", T.SIGNALLED, T.EXIT_NO_NOTIFICATION)  # the Driver saw it alive; it registers no exit watch
        self.assertEqual(self.view()["orphan"]["exit_cause"]["by"], ["driver_backstop"])
        self.assertEqual(self.raw()["finalize"]["alive_at_first_look"], True)
        self.assertEqual(self.view()["signals"]["driver_backstop"]["delivered"], 1)
        self.assertEqual(self.view()["rows"]["rows"]["B4_successor_side"], "INCONCLUSIVE")

    def test_a_backstop_that_finds_the_runtime_already_gone_says_so_and_claims_no_kill(self):
        self.env(mode="exit_after_gen", gen_s=2.0)
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=[sys.executable, "-B", "-c", "import time;time.sleep(300)"])
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        # absent at the finalizer's own first look, but the Driver had observed the identity alive earlier (at the kill instant and
        # in the orphan window): the exit was never "absent at first observation". Nothing was sent.
        self.assertOneStory("self_exit", T.NO_SIGNAL, T.EXIT_NO_NOTIFICATION)
        self.assertEqual(self.raw()["finalize"]["alive_at_first_look"], False)
        self.assertEqual(self.raw()["finalize"]["driver_saw_alive_from_kill_instant"], True)
        self.assertEqual([s for s in self.signals() if s["sent"] and s["who"] == "driver_backstop"], [])
        self.assertIs(self.view()["orphan"]["exited_by_itself"], True)

    def test_a_signal_refusal_is_reported_as_an_attempt_that_was_not_delivered(self):
        self.env(gen_s=20.0)
        QS = TestOrphanVariants.QUARANTINING_SUCCESSOR
        cmd = [sys.executable, "-B", "-c", QS % HERE, self.root, "wrong_start"]
        self.pilot(bounds=dict(BT, reader_deadline_s=40.0), successor_cmd=cmd)
        alive_now = L.tag_scan(self.record()["tag"])
        self.addCleanup(lambda: [L.safe_kill(i["pid"], i["start"], signal.SIGKILL) for i in alive_now])
        for d in (self.raw(), self.view()):
            acc = d["signals"]["driver_cleanup"]
            self.assertEqual((acc["attempted"], acc["delivered"], acc["refused"]), (1, 0, {"identity_mismatch_or_gone": 1}))
            self.assertEqual(d["signals"]["driver"]["delivered"], 1)  # the Owner SIGKILL was delivered
        self.assertEqual(self.view()["quarantine_cleanup"]["attempts"], [{"sent": False, "why": "identity_mismatch_or_gone"}])

    def test_the_owner_reports_attempts_and_ledger_confirmed_delivery_not_unconditional_booleans(self):
        self.env(mode="no_processing", gen_s=8.0)
        res = self.pilot(bounds=dict(BT, prekill_abort_s=2.5, reader_deadline_s=30.0))
        # a pre-kill abort: the Owner's normal shutdown sends TERM (an attempt; delivery not observable) and no KILL
        final = [m for m in self.jsonl("owner.jsonl") if m["e"] == "FINAL"][-1]["result"]
        self.assertIs(final["term_attempted"], True)
        self.assertEqual(final["term_delivery"], "not_observable")
        self.assertIs(final["kill_attempted"], False)
        self.assertIs(final["kill_delivered_by_ledger"], False)
        self.assertEqual(self.view()["owner_shutdown"]["term_delivery"], "not_observable")


class TestR5Labels(unittest.TestCase):
    A = staticmethod(lambda cause, by=(): {"cause": cause, "by": list(by)})

    def test_label_derivation(self):
        L_ = T.termination_label
        self.assertEqual(L_(self.A(T.SIGNALLED, ["successor"]), True), "successor")
        self.assertEqual(L_(self.A(T.SIGNALLED, ["driver_backstop"]), True), "driver_backstop")
        self.assertEqual(L_(self.A(T.SIGNALLED, ["driver-monitor", "successor"]), True), "multiple_signallers")
        self.assertEqual(L_(self.A(T.NO_SIGNAL), True), "self_exit")
        self.assertEqual(L_(self.A(T.NO_SIGNAL), False), "undetermined")  # nothing ended it as far as is known: no claim
        self.assertEqual(L_(self.A(T.UNDETERMINED), True), "undetermined")

    def test_a_label_is_cross_checked_against_the_ledger(self):
        M = T.label_matches_attribution
        self.assertTrue(M("successor", self.A(T.SIGNALLED, ["successor"])))
        self.assertFalse(M("successor", self.A(T.SIGNALLED, ["driver_backstop"])))
        self.assertFalse(M("successor", self.A(T.NO_SIGNAL)))  # a self-exit is never a Successor termination
        self.assertFalse(M("self_exit", self.A(T.SIGNALLED, ["successor"])))  # and a termination is never a self-exit
        self.assertFalse(M("self_exit", self.A(T.UNDETERMINED)))
        self.assertTrue(M("undetermined", self.A(T.SIGNALLED, ["successor"])))  # claims nothing
        self.assertTrue(M(None, self.A(T.NO_SIGNAL)))

    def test_attempts_and_delivery_are_counted_apart_without_pids(self):
        acc = T.signal_accounting([{"who": "a", "sent": True, "pid": 1}, {"who": "a", "sent": False, "why": "already_killed", "pid": 1},
                                   {"who": "a", "sent": False, "why": "already_killed", "pid": 2}, {"who": "b", "sent": False, "why": "gone"}])
        self.assertEqual(acc["a"], {"attempted": 3, "delivered": 1, "refused": {"already_killed": 2}})
        self.assertEqual(acc["b"], {"attempted": 1, "delivered": 0, "refused": {"gone": 1}})
        self.assertNotIn("pid", json.dumps(acc))

    def test_exit_event_labels_are_three_distinct_facts(self):
        self.assertEqual(len({T.EXIT_OBSERVED, T.EXIT_UNOBSERVED, T.EXIT_NO_NOTIFICATION}), 3)

    def test_a_successor_row_needs_a_consistent_attribution(self):
        s = {"stops": [], "orphan": {"alive_at_first_successor_observation": True},
             "successor": {"classifications": [{"verdict": L.ALIVE, "identity_gone": False}], "terminated_by": "successor", "verified": True,
                           "signals_by_successor": [{"sig": 15}]}, "record_state": "EXIT_VERIFIED", "backstop_used": False, "exit": {"attribution_consistent": True}}
        self.assertEqual(T.e3_rows(s)["rows"]["O4_successor_termination"].split(" (")[0], "SUPPORTS")
        s["exit"]["attribution_consistent"] = False
        self.assertEqual(T.e3_rows(s)["rows"]["O4_successor_termination"], "INCONCLUSIVE")


class TestR6AuthorizationValidation(Base):
    def setUp(self):
        super().setUp()
        self.env()

    def check(self, **kw):
        return T.check_authorization(self.root, self.spec["doc"], self.spec["e3pins"], **kw)

    def write_raw_expiry(self, literal):
        write_auth(self.spec, expires_epoch="@@")
        path = T.auth_path(self.root)
        text = open(path).read().replace('"@@"', literal)
        open(path, "w").write(text)

    def test_non_finite_and_malformed_expiries_are_refused(self):
        for literal in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999", "true", "false", "null", '"9999999999"', "[]", "{}", "1" + "0" * 400):
            self.write_raw_expiry(literal)
            ok, why, a = self.check()
            self.assertFalse(ok, literal)
            self.assertIsNone(a)

    def test_the_expiry_must_be_later_than_the_execution_start(self):
        start = 2_000_000_000.0
        write_auth(self.spec, expires_epoch=start)
        self.assertFalse(self.check(now=start)[0])  # equal is not later
        self.assertFalse(self.check(now=start + 1)[0])
        self.assertTrue(self.check(now=start - 1)[0])
        write_auth(self.spec, expires_epoch=int(start))
        self.assertTrue(self.check(now=start - 1)[0])  # an integer expiry is a real number too

    def test_lifetimes_must_be_the_integer_one(self):
        for literal in ("true", "1.0", '"1"', "[1]", "2", "0", "null", "-1"):
            write_auth(self.spec, lifetimes="@@")
            path = T.auth_path(self.root)
            with open(path) as f:
                text = f.read().replace('"@@"', literal)
            with open(path, "w") as f:
                f.write(text)
            ok, why, _ = self.check()
            self.assertFalse(ok, literal)
            self.assertIn("lifetime", why, literal)  # refused for this reason, not for an unreadable file
        write_auth(self.spec, lifetimes=1)
        self.assertTrue(self.check()[0])

    def test_valid_expiry_unit(self):
        for good in (10.5, 10, 1e12):
            self.assertTrue(T.valid_expiry(good, 5.0), good)
        for bad in (True, False, None, "1e12", float("nan"), float("inf"), float("-inf"), 5.0, 4, 10 ** 400, [], {}):
            self.assertFalse(T.valid_expiry(bad, 5.0), bad)

    def test_a_run_with_an_invalid_authorization_spawns_nothing(self):
        self.write_raw_expiry("Infinity")
        res = self.pilot()
        self.assertEqual(res["outcome"], "REFUSED")
        self.assertFalse(os.path.exists(os.path.join(self.root, "runs")) and os.listdir(os.path.join(self.root, "runs")))


class TestN1ConnectionViolationStop(Scenario):
    def test_a_prohibited_connection_publishes_the_stop_and_shortens_the_observation(self):
        self.env(gen_s=12.0)
        import socket
        held = []

        def connect_late():
            wait_until(lambda: any(s["who"] == "driver" for s in self.live_signals()), 40)
            time.sleep(0.6)
            held.append(socket.create_connection(("127.0.0.1", self.spec["port"]), timeout=2))
        threading.Thread(target=connect_late, daemon=True).start()
        self.addCleanup(lambda: [c.close() for c in held])
        res = self.pilot(bounds=dict(BT, orphan_max_s=8.0, backstop_s=14.0, reader_deadline_s=40.0, idle_after_reader_s=8.0))
        self.assertIn("E3-3", [s["id"] for s in res["stops"]], res["stops"])
        # without the early stop the window would run to the 8 s bound
        self.assertLess(self.view()["orphan"]["window_s"], 5.5)
        self.assertIsNotNone(self.record()["e3"]["stop_up"])  # published to the durable window record at detection
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertEqual(self.view()["rows"]["rows"]["O4_successor_termination"], "INCONCLUSIVE")  # verdicts withheld by the stop
        self.assertNoLeftovers()

    def live_signals(self):
        out = []
        runs = os.path.join(self.root, "runs")
        for d in os.listdir(runs) if os.path.isdir(runs) else []:
            out += T.SignalLedger(os.path.join(runs, d)).entries()
        return out


class TestN2FixtureInput(Scenario):
    def test_the_request_body_is_the_in_memory_fixture_verified_by_length_and_hash(self):
        self.env(gen_s=2.0)
        pinned = self.spec["e3pins"]["fixture_g"]["sha256"]
        seen = {}
        real = D.Pilot.start_reader

        def start(self_):
            seen["sha"] = E.sha256_bytes(E.canon(self_.bodyG))
            with open(os.path.join(self.spec["fixtures"], "G.json"), "wb") as f:  # the file changes AFTER it was verified
                f.write(b'{"changed":"after verification"}')
            return real(self_)
        D.Pilot.start_reader = start
        self.addCleanup(lambda: setattr(D.Pilot, "start_reader", real))
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED", res["stops"])
        self.assertEqual(seen["sha"], pinned)  # the executed input is the verified body, not whatever the file holds later
        self.assertNotEqual(E.sha256_file(os.path.join(self.spec["fixtures"], "G.json")), pinned)

    def test_the_pre_consumption_check_does_not_claim_to_reread_the_fixture(self):
        src = open(os.path.join(HERE, "e3_harness.py")).read()
        self.assertIn("NOT re-read here", src)
        self.assertNotIn("fixture G, expiry, single use", src)


# ============================================================================================
# Revision-3 review remediation (findings 1-7): each test reproduces the finding it is named for.
# ============================================================================================


class TestF1OrdinaryObservationRetention(Base):
    """Finding 1: descendants are retained from ordinary observation only through a root whose (pid, start) is verified
    live before AND after the enumeration, so a reused root pid never puts unrelated children into the kill targets."""

    unrelated_family = TestR1WrongTargetRecovery.unrelated_family
    sleeper = TestR1WrongTargetRecovery.sleeper
    kill_created = TestR1WrongTargetRecovery.kill_created
    UNRELATED_PARENT = TestR1WrongTargetRecovery.UNRELATED_PARENT

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "e3root")
        self.procs = []
        self.addCleanup(self.kill_created)

    def instance(self, parent, start, rid="f1"):
        rs = T.LockedRecords(self.root)
        rec = rs.create({"v": 1, "run_id": rid, "state": "INTENT", "tag": "no-such-tag-" + rid, "port": 59,
                         "boottime": E.HostProbes().boottime()})
        rs.advance(rec, "SPAWNED", pid=parent.pid, start=list(start), pgid=parent.pid, binding_verified=False, descendants=[])
        rs.advance(rec, "BOUND", binding_verified=True)
        rs.annotate(rec, owner_review_required=True, owner_review_reason="unit test")  # makes the owner-directed recovery take its kill path
        run_dir = os.path.join(self.tmp, "run-" + rid)
        os.makedirs(run_dir, exist_ok=True)
        inst = D.RemoteInstance(types.SimpleNamespace(port=59), rs, rid, run_dir, T.SignalLedger(run_dir).kill_fn("driver-monitor", "test"))
        inst.attach({"tag": "no-such-tag-" + rid, "pid": parent.pid, "start": list(start), "pgid": parent.pid})
        inst.enable_writer(rec, True)
        self.rs = rs
        return inst

    def persisted_descendants(self, rid="f1"):
        return self.rs.read(rid).get("descendants", [])

    def test_the_inherited_observation_retains_the_children_of_a_reused_pid_and_the_emergency_kill_then_kills_them(self):
        parent = self.unrelated_family()
        inst = self.instance(parent, [1, 1])  # the recorded root identity does not match the process now at that pid
        H.Instance.observe(inst)  # the frozen E2-B observation the override replaces
        self.assertEqual(len(inst.known), 2, "the defect this test documents: the unrelated children were retained")
        self.assertEqual(len(self.persisted_descendants()), 2)
        inst.emergency_kill()
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10), "and the retained identities are then signalled")

    def test_observing_a_reused_root_pid_retains_nothing_and_nothing_downstream_signals_the_children(self):
        parent = self.unrelated_family()
        inst = self.instance(parent, [1, 1])
        out = inst.observe()
        self.assertTrue(out["root_unverified"])
        self.assertEqual((out["tree"], out["lsof_ok"]), ([], False))  # no tree, no sockets, no health claimed about a foreign process
        self.assertEqual(inst.known, {})
        self.assertEqual(self.persisted_descendants(), [])
        self.assertEqual(inst.unverified_observations, 1)
        # the whole path onward: emergency cleanup, then the owner-directed recovery, from what observation retained
        inst.emergency_kill()
        rep = D.recover(types.SimpleNamespace(root=self.root), "f1", kill=True, confirm="f1")
        time.sleep(0.5)
        self.assertTrue(all(live(k) for k in self.kids), rep)
        self.assertIsNone(parent.poll())
        self.assertEqual(rep["actions"][0]["recorded_descendants"], 0)

    def test_a_root_that_exits_during_the_intervening_probes_discards_the_enumeration(self):
        # the real mechanism: the monitor's slower probes run between the liveness check and the enumeration; here the root
        # dies inside the observation, after its children were listed, and its children are re-parented
        parent = self.unrelated_family()
        inst = self.instance(parent, L.identity(parent.pid)["start"])
        real = H.lsof_names

        def lsof_after_root_death(pid):
            parent.kill()
            parent.wait(5)
            return []
        H.lsof_names = lsof_after_root_death
        self.addCleanup(lambda: setattr(H, "lsof_names", real))
        out = inst.observe()
        H.lsof_names = real
        self.assertTrue(out["root_unverified"])
        self.assertEqual(inst.known, {})
        self.assertEqual(self.persisted_descendants(), [])
        self.assertTrue(all(live(k) for k in self.kids))
        # the root's pid is now free for reuse; whatever holds it, a later emergency kill and recovery find no one to kill
        inst.emergency_kill()
        rep = D.recover(types.SimpleNamespace(root=self.root), "f1", kill=True, confirm="f1")
        time.sleep(0.5)
        self.assertTrue(all(live(k) for k in self.kids), rep)

    def test_a_verified_root_still_has_its_descendants_retained_and_they_stay_killable_after_the_pid_is_reused(self):
        parent = self.unrelated_family()
        inst = self.instance(parent, L.identity(parent.pid)["start"])
        out = inst.observe()
        self.assertNotIn("root_unverified", out)
        self.assertEqual(len(inst.known), 2)
        self.assertEqual(len(self.persisted_descendants()), 2)
        inst.root = dict(inst.root, start=[1, 1])  # from now on the pid belongs to "somebody else"
        inst.emergency_kill()
        self.assertTrue(wait_until(lambda: all(gone(k) for k in self.kids), 10), "identities captured while the root was verified stay valid targets")
        self.assertIsNone(parent.poll())  # and the process now at the pid is protected by its start time

    def test_an_exception_in_the_inherited_observation_leaves_no_staged_state_behind(self):
        parent = self.unrelated_family()
        inst = self.instance(parent, L.identity(parent.pid)["start"])
        real = H.lsof_names
        H.lsof_names = lambda pid: (_ for _ in ()).throw(RuntimeError("synthetic probe failure"))
        self.addCleanup(lambda: setattr(H, "lsof_names", real))
        self.assertRaises(RuntimeError, inst.observe)
        H.lsof_names = real
        self.assertIsNone(getattr(inst._tl, "staged", None))
        self.assertEqual(inst.known, {})  # nothing was retained from the aborted observation
        inst._remember([{"pid": 1, "start": [1, 1]}])
        self.assertEqual(len(inst.known), 1)  # and later retention outside an observation is immediate


class TestF2MandatoryQuarantine(Scenario):
    """Finding 2: a required quarantine survives the failure of its write under record-lock contention, and no later writer
    turns the run into a successful verdict."""

    def fork_late_env(self):
        self.env(mode="fork_late", gen_s=2.0, profile=E.SANDBOX)  # the no-fork profile would deny the stand-in's fork
        real = H.controls
        H.controls = lambda *a, **k: {"passed": True}  # Phase 2 asserts the no-fork profile, which this scenario deliberately lacks
        self.addCleanup(lambda: setattr(H, "controls", real))

    BOUNDS = dict(BT, lock_timeout_s=0.4, orphan_max_s=6.0, backstop_s=12.0, reader_deadline_s=30.0)

    def test_unit_a_failed_flag_write_keeps_the_intent_and_a_retry_persists_it(self):
        rs = T.LockedRecords(os.path.join(self.tmp, "root"), lock_timeout_s=0.3)
        rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT", "tag": "t"})
        inst = D.RemoteInstance(types.SimpleNamespace(port=1), rs, "r1", os.path.join(self.tmp, "rd"), lambda *a, **k: {})
        inst.rec = rec
        h = Holder(rs._lock_file("r1"))
        self.addCleanup(h.stop)
        t = time.monotonic()
        self.assertFalse(inst.mark_owner_review("S8: x"))
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual((inst.pending_review, inst.review_failed, inst.review_persisted), ("S8: x", True, False))
        self.assertTrue(inst.rec["owner_review_required"])  # the E2-B contract: the intent lives on in the in-memory record
        self.assertNotIn("owner_review_required", rs.read("r1"))  # and is not on disk
        h.stop()
        self.assertTrue(inst.mark_owner_review("S8: x"))
        self.assertEqual((inst.review_failed, inst.review_persisted), (False, True))
        self.assertTrue(rs.read("r1")["owner_review_required"])

    def stalled_successor(self):
        marker = "stall-" + secrets.token_hex(4)
        self.addCleanup(lambda: subprocess.run(["pkill", "-9", "-f", marker]))  # test hygiene: only this test's stalled process
        return [sys.executable, "-B", "-c", STALL_SUCCESSOR, self.root, "records", marker], marker

    def test_a_quarantining_stop_under_a_stalled_record_lock_still_ends_as_a_quarantine(self):
        self.fork_late_env()
        cmd, marker = self.stalled_successor()
        res = self.pilot(monitor_interval=0.2, monitor_slow_every=2, bounds=self.BOUNDS, successor_cmd=cmd)
        self.assertIn("S8", [s["id"] for s in res["stops"]], res["stops"])
        raw = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertIn("owner_review: LockTimeout", raw["persist_errors"])  # the monitor's write of the flag DID fail under the held lock
        rec = self.record()
        self.assertEqual(rec["state"], "QUARANTINED")  # the Driver finalized after the lock holder was stopped
        self.assertTrue(rec["owner_review_required"])
        self.assertNotIn("EXIT_VERIFIED", [h["state"] for h in rec["history"]])
        self.assertEqual(res["outcome"], "QUARANTINED")
        self.assertIs(raw["quarantine_takeover"], True)
        self.assertIs(self.view()["owner_review_persisted"], True)
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")
        self.assertEqual(subprocess.run(["pgrep", "-f", marker], capture_output=True).returncode, 1)  # the stalled holder was stopped
        self.assertNoLeftovers()

    def test_a_record_lock_that_stays_held_leaves_no_successful_outcome_and_an_unresolved_record(self):
        self.fork_late_env()
        held = []

        def hold_after_kill():  # a holder the Driver cannot stop: it has no relation to the Driver's children
            wait_until(lambda: any(s["who"] == "driver" and s["sent"] for s in self.live_signals()), 60)
            time.sleep(0.5)
            rid = [f for f in os.listdir(os.path.join(self.root, "records")) if f.endswith(".json")][0][:-5]
            held.append(Holder(os.path.join(self.root, "locks", rid + ".lock"), 120))
        threading.Thread(target=hold_after_kill, daemon=True).start()
        self.addCleanup(lambda: [h.stop() for h in held])
        res = self.pilot(monitor_interval=0.2, monitor_slow_every=2, bounds=self.BOUNDS, successor_cmd=[sys.executable, "-B", "-c", "import time;time.sleep(300)"])
        self.assertEqual(res["outcome"], "QUARANTINE_NOT_PERSISTED", res["stops"])
        self.assertNotEqual(self.record()["state"], "EXIT_VERIFIED")  # the record stays unresolved: new runs stay blocked
        self.assertIs(self.view()["owner_review_required"], True)
        self.assertIs(self.view()["owner_review_persisted"], False)
        self.assertEqual(res["exit_code"], 1)
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")

    def live_signals(self):
        out = []
        runs = os.path.join(self.root, "runs")
        for d in os.listdir(runs) if os.path.isdir(runs) else []:
            out += T.SignalLedger(os.path.join(runs, d)).entries()
        return out

    def test_a_successor_that_resolved_the_record_without_the_flag_is_not_reported_as_a_success(self):
        # the interleaving the takeover cannot prevent: the record is already EXIT_VERIFIED when the intent is found unpersisted
        self.env(gen_s=2.0)
        real = D.Pilot.quarantine_intent
        D.Pilot.quarantine_intent = lambda self_: "S8: synthetic quarantine that never reached the record"
        self.addCleanup(lambda: setattr(D.Pilot, "quarantine_intent", real))
        res = self.pilot()
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")
        self.assertEqual(res["outcome"], "QUARANTINE_NOT_PERSISTED")
        self.assertIs(self.view()["owner_review_persisted"], False)
        self.assertIs(self.view()["owner_review_required"], True)


class TestF3InterruptReconciliation(Scenario):
    """Finding 3: a genuine operator interrupt is a stop wherever it coincides with an early exit."""

    HANG = [sys.executable, "-B", "-c", "import time;time.sleep(300)"]

    def assertInterruptIsAStop(self, res):
        self.assertIn("S11", [s["id"] for s in res["stops"]], res["stops"])
        self.assertIn("S11", [s["id"] for s in self.view()["stops"]])
        self.assertEqual(res["outcome"], "STOPPED")
        for k in T.VERDICT_ROWS:
            self.assertEqual(self.view()["rows"]["rows"][k], "INCONCLUSIVE")

    def test_an_interrupt_that_coincides_with_the_successor_ending(self):
        self.env(gen_s=2.0)
        real = D.Pilot.start_successor

        def start(self_):
            real(self_)
            self_.successor.wait(10)  # the Successor has already ended when the loop first looks ...
            self_.interrupted.set()   # ... and the interrupt is pending at the same moment
        D.Pilot.start_successor = start
        self.addCleanup(lambda: setattr(D.Pilot, "start_successor", real))
        res = self.pilot(successor_cmd=[sys.executable, "-B", "-c", "pass"])
        self.assertInterruptIsAStop(res)
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")  # the termination was still completed

    def test_an_interrupt_that_coincides_with_the_backstop(self):
        self.env(gen_s=2.0)
        real = D.Pilot.drain

        def drain(self_, prekill):
            if not prekill and self_.successor is not None and "t0" in self_.tl and T.uptime() >= self_.tl["t0"] + self_.b["backstop_s"]:
                self_.interrupted.set()  # becomes pending in the very iteration whose backstop check fires
            return real(self_, prekill)
        D.Pilot.drain = drain
        self.addCleanup(lambda: setattr(D.Pilot, "drain", real))
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=self.HANG)
        self.assertTrue(self.view()["backstop_used"])
        self.assertInterruptIsAStop(res)
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")

    def test_an_interrupt_during_the_post_sampling(self):
        self.env(gen_s=2.0)

        class Trip(threading.Event):
            armed = False

            def wait(self, timeout=None):  # the post-sampling loop waits on the event between its samples
                if self.armed:
                    self.set()
                return super().wait(timeout)
        trip = Trip()
        real = D.Pilot.cleanup

        def cleanup(self_):
            real(self_)
            trip.armed = True  # everything up to the report is done; the interrupt arrives during the post-sampling
        D.Pilot.cleanup = cleanup
        self.addCleanup(lambda: setattr(D.Pilot, "cleanup", real))
        res = self.pilot(post_sample_s=3, interrupted=trip)
        self.assertEqual(len(self.jsonl("post-unload.jsonl")), 1)  # it ended the sampling early
        self.assertInterruptIsAStop(res)

    def test_without_an_interrupt_the_same_scenarios_are_unaffected(self):
        self.env(gen_s=2.0)
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0), successor_cmd=self.HANG)
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        self.assertNotIn("S11", [s["id"] for s in res["stops"]])


class TestRev5FinalizationBoundary(Scenario):
    """Revision 5: an interrupt accepted at any point up to the seal of the report is reflected in it. The interrupt is injected
    from inside each finalization step (the final clean-state scan, the verdict construction, the report write, a failing step)."""

    def assertSealedAsInterrupted(self, res, outcome="STOPPED"):
        self.assertEqual(res["outcome"], outcome, res.get("stops"))
        self.assertNotEqual(res["exit_code"], 0)
        raw = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        for name, stops in (("result", res["stops"]), ("raw report", raw["stops"]), ("committed view", self.view()["stops"])):
            self.assertIn("S11", [s["id"] for s in stops], name)
        self.assertEqual(raw["outcome"], outcome)
        self.assertEqual(self.view()["outcome"], outcome)
        self.assertTrue(raw["seal"]["interrupt_seen"])
        rows = self.view().get("rows")
        if rows:  # a verdict was built: every supporting row is withheld
            for k in T.VERDICT_ROWS:
                self.assertEqual(rows["rows"][k], "INCONCLUSIVE", k)
        # the committed view's digest of the raw report is the digest of the file that is on disk
        self.assertEqual(self.view()["raw_artifacts"]["summary.json"]["sha256"], E.sha256_file(os.path.join(self.run_dir(), "summary.json")))

    def patch(self, owner, name, fn):
        real = getattr(owner, name)
        setattr(owner, name, fn(real))
        self.addCleanup(lambda: setattr(owner, name, real))

    def finalizing(self):
        """A flag that becomes true when the lifetime is over and the report is being built (the Pilot's sinks are closed
        immediately before ``finish``); the Phase 1 gate calls the same clean-state scan, which must not be the injection point."""
        flag = {"on": False}
        self.patch(D.Pilot, "close_sinks", lambda real: (lambda self_: (real(self_), flag.update(on=True))[0]))
        return flag

    def interrupting(self, interrupted, then_raise=None, when=None):
        def wrap(real):
            state = {"n": 0}

            def inner(*a, **k):
                if when is None or when["on"]:
                    state["n"] += 1
                    if state["n"] == 1:
                        interrupted.set()
                        if then_raise is not None:
                            raise then_raise
                return real(*a, **k)
            return inner
        return wrap

    def test_an_interrupt_during_the_final_clean_state_scan_is_s11(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        self.patch(H, "clean_state", self.interrupting(ev, when=self.finalizing()))
        res = self.pilot(interrupted=ev)
        self.assertSealedAsInterrupted(res)
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")  # the durable record is untouched by a non-killing stop
        self.assertEqual(self.view()["seal"]["passes"], 1)  # it was already visible at the verdict: no second pass needed

    def test_an_interrupt_between_the_final_scan_and_the_verdict_is_s11(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        self.patch(T, "e3_rows", self.interrupting(ev))  # the verdict's first act after the scan has returned
        res = self.pilot(interrupted=ev)
        self.assertSealedAsInterrupted(res)
        self.assertEqual(self.view()["seal"]["passes"], 1)  # accepted after the verdict's check: found by the seal's settle before the first write and re-derived

    def test_an_interrupt_at_the_finalization_boundary_is_s11(self):
        self.env(gen_s=2.0)
        ev = threading.Event()

        def after_first_write(real):
            state = {"n": 0}

            def inner(*a, **k):
                out = real(*a, **k)
                state["n"] += 1
                if state["n"] == 1:
                    ev.set()  # the report is on disk, the interrupt has not been looked at yet: this is the window
                return out
            return inner
        self.patch(D, "write_report", after_first_write)
        res = self.pilot(interrupted=ev)
        self.assertSealedAsInterrupted(res)
        self.assertEqual(self.view()["seal"]["passes"], 2)
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")

    def test_an_interrupt_and_an_exception_in_finalization_are_both_reported(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        self.patch(H, "clean_state", self.interrupting(ev, then_raise=RuntimeError("synthetic scan failure"), when=self.finalizing()))
        res = self.pilot(interrupted=ev)
        self.assertSealedAsInterrupted(res, outcome="HARNESS_ERROR")
        self.assertEqual(self.record()["state"], "EXIT_VERIFIED")

    def test_an_exception_after_the_verdict_never_leaves_a_success_exit(self):
        self.env(gen_s=2.0)

        def failing(real):
            def inner(*a, **k):
                raise OSError("synthetic report write failure")
            return inner
        self.patch(D, "write_report", failing)
        res = self.pilot()
        self.assertEqual(res["finalize_error"], "OSError")
        self.assertEqual((res["outcome"], res["exit_code"]), ("FINALIZE_ERROR", 1))
        self.assertEqual(res["outcome_unsealed"], "PILOT_COMPLETED")

    def real_signal_in_the_final_scan(self, sg):
        self.env(gen_s=2.0)
        before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        flag = self.finalizing()
        self.patch(H, "clean_state", lambda real: (lambda *a, **k: (os.kill(os.getpid(), sg) if flag["on"] else None, real(*a, **k))[1]))
        res = self.pilot(install_signals=True)
        self.assertSealedAsInterrupted(res)
        self.assertEqual({s: signal.getsignal(s) for s in before}, before)  # restored only after the seal

    def test_a_real_sigint_in_the_final_scan_is_accepted(self):
        self.real_signal_in_the_final_scan(signal.SIGINT)

    def test_a_real_sigterm_in_the_final_scan_is_accepted(self):
        self.real_signal_in_the_final_scan(signal.SIGTERM)

    def test_a_real_sighup_in_the_final_scan_is_accepted(self):
        self.real_signal_in_the_final_scan(signal.SIGHUP)

    def test_a_real_signal_while_the_report_is_written_does_not_kill_the_process_or_contradict_the_report(self):
        self.env(gen_s=2.0)

        def after_first_write(real):
            state = {"n": 0}

            def inner(*a, **k):
                out = real(*a, **k)
                state["n"] += 1
                if state["n"] == 1:
                    os.kill(os.getpid(), signal.SIGTERM)  # default action would end the process here if the handler were already restored
                    time.sleep(0.05)
                return out
            return inner
        self.patch(D, "write_report", after_first_write)
        res = self.pilot(install_signals=True)
        self.assertSealedAsInterrupted(res)

    def test_a_run_without_an_interrupt_is_sealed_in_one_pass(self):
        self.env(gen_s=2.0)
        res = self.pilot()
        self.assertEqual((res["outcome"], res["exit_code"]), ("PILOT_COMPLETED", 0))
        self.assertEqual(self.view()["seal"], {"interrupt_seen": False, "passes": 1})

    def test_an_interrupt_after_an_early_phase_outcome_was_decided_is_not_a_success(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        self.patch(H, "phase1", lambda real: (lambda *a, **k: (lambda r: (ev.set(), r)[1])(real(*a, **k))))
        res = self.pilot(through=1, interrupted=ev)
        self.assertEqual(res["outcome"], "INTERRUPTED")
        self.assertNotEqual(res["exit_code"], 0)
        self.assertIn("S11", [s["id"] for s in res["stops"]])


PROBE_PRELUDE = """
import os, signal, sys, threading, time
sys.path.insert(0, %r)
import e3_lib as T
latch = T.InterruptLatch()
ev, cancel = T.InterruptEvent(latch), T.InterruptEvent(latch)
mode = sys.argv[1]
if mode == "old":  # the revision-5 handler: both Events set from signal context
    handler = lambda *_: (ev.set(), cancel.set())
else:
    handler = T.make_signal_handler(latch)
for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sg, handler)
""" % HERE


def run_probe(body, mode, timeout=6.0):
    """Run a signal scenario in its own interpreter so that a deadlock is a timeout, not a hung test run."""
    try:
        r = subprocess.run([sys.executable, "-B", "-c", PROBE_PRELUDE + body, mode], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"


class TestRev6SignalHandlerSafety(unittest.TestCase):
    """Revision 6: the handler never takes a lock. The unsafe revision-5 handler is reproduced in a child interpreter."""

    HOLD_AND_SIGNAL = """
with ev._cond, cancel._cond:   # the main thread holds the Events' internal, non-reentrant locks ...
    for n in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM):   # ... while repeated, nested signals arrive
        os.kill(os.getpid(), n)
    time.sleep(0.05)
print("survived", ev.is_set(), cancel.is_set())
"""

    def test_the_unsafe_revision_5_handler_deadlocks_when_a_signal_arrives_under_the_event_lock(self):
        self.assertEqual(run_probe(self.HOLD_AND_SIGNAL, "old", timeout=4.0), (None, "TIMEOUT"))

    def test_the_latch_handler_survives_repeated_nested_signals_under_the_event_locks(self):
        self.assertEqual(run_probe(self.HOLD_AND_SIGNAL, "new"), (0, "survived True True"))

    def test_signals_while_the_main_thread_is_inside_event_wait_end_the_wait_promptly(self):
        body = """
def burst():
    time.sleep(0.15)
    for n in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT) * 5:
        os.kill(os.getpid(), n)
threading.Thread(target=burst, daemon=True).start()
t = time.monotonic()
r1 = ev.wait(10)
r2 = cancel.wait(10)   # a second wait after the burst: still prompt, still True
print(r1, r2, round(time.monotonic() - t, 1) < 1.5)
"""
        self.assertEqual(run_probe(body, "new"), (0, "True True True"))

    def test_signals_while_a_second_thread_waits_on_the_events_end_that_wait_too(self):
        body = """
out = []
th = threading.Thread(target=lambda: out.append(cancel.wait(10)))
th.start()
time.sleep(0.1)
os.kill(os.getpid(), signal.SIGTERM)
th.join(3)
print(out, ev.is_set(), cancel.is_set())
"""
        self.assertEqual(run_probe(body, "new"), (0, "[True] True True"))

    def test_the_watcher_propagates_the_latch_to_ordinary_events_outside_the_handler(self):
        body = """
plain = threading.Event()
stop = T.start_latch_watcher(latch, (plain,))
os.kill(os.getpid(), signal.SIGHUP)
print(plain.wait(2), latch.hit == True, latch.signum == int(signal.SIGHUP))
stop()
"""
        self.assertEqual(run_probe(body, "new"), (0, "True True True"))

    def test_the_handler_is_assignments_only(self):
        import inspect
        tree = ast.parse(inspect.getsource(T.make_signal_handler))
        handler = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "on_signal"][0]
        body = [n for n in handler.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        self.assertTrue(body and all(isinstance(n, ast.Assign) for n in body))
        self.assertFalse([n for n in ast.walk(handler) if isinstance(n, (ast.Call, ast.With, ast.Await, ast.Yield, ast.Lambda))])
        self.assertIn("make_signal_handler(latch)", inspect.getsource(D.run_pilot))   # and it is what run_pilot installs
        self.assertNotIn(".set()", inspect.getsource(T.make_signal_handler))

    def test_waits_are_bounded_by_their_timeout_and_report_the_state(self):
        e = T.InterruptEvent()
        t = time.monotonic()
        self.assertFalse(e.wait(0.2))
        self.assertLess(time.monotonic() - t, 0.5)
        threading.Timer(0.1, e.set).start()
        self.assertTrue(e.wait(5))
        latched = T.InterruptEvent()
        latched.latch.hit = True
        self.assertTrue(latched.is_set() and latched.isSet() and latched.wait(0))


class TestRev6ActiveLifetimeSignals(Scenario):
    """Revision 6: repeated and nested signals while a (synthetic) runtime is live, delivered to the Driver in its own process."""

    start_driver = TestSecondProcess.start_driver
    run_dirs = TestSecondProcess.run_dirs
    ledger_has = TestSecondProcess.ledger_has
    file_exists = TestSecondProcess.file_exists
    only_record_path = TestSecondProcess.only_record_path
    rec = TestSecondProcess.rec

    def finished(self, p, limit=90):
        try:
            p.wait(limit)
        except subprocess.TimeoutExpired:
            self.fail("the Driver did not finish: it is hung")
        run = self.run_dirs()[0]
        view = json.load(open(os.path.join(run, "summary-committed-view.json")))
        self.assertIn("S11", [s["id"] for s in view["stops"]])
        acc = T.evidence_acceptance(run, json.load(open(os.path.join(run, T.SEAL_FILE)))["exit_code"])
        self.assertTrue(acc["sealed"], acc)            # the report was sealed ...
        self.assertFalse(acc["supports_verdicts"])     # ... and supports nothing: an interrupt is a stop
        rec = self.rec()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(L.listeners(self.spec["port"])["pids"], [])
        return view

    def test_nested_signals_under_the_event_locks_before_the_kill_do_not_hang_the_driver(self):
        self.env(gen_s=10.0)
        sigs = [int(signal.SIGTERM), int(signal.SIGHUP), int(signal.SIGINT), int(signal.SIGINT)]
        p = self.start_driver(faults={"signals_in_event_lock": {"at": "before_kill", "signals": sigs}},
                              bounds=dict(BT, arm_delay_s=0.4, prekill_abort_s=15.0, reader_deadline_s=40.0))
        self.finished(p)
        self.assertFalse(self.ledger_has("driver", signal.SIGKILL))  # the interrupt prevented the owner kill

    def test_nested_signals_under_the_event_locks_after_the_kill_still_complete_the_termination(self):
        self.env(gen_s=12.0)
        sigs = [int(signal.SIGHUP), int(signal.SIGTERM), int(signal.SIGHUP), int(signal.SIGINT)]
        p = self.start_driver(faults={"signals_in_event_lock": {"at": "after_kill", "signals": sigs}},
                              bounds=dict(BT, orphan_max_s=30.0, backstop_s=45.0, reader_deadline_s=60.0, idle_after_reader_s=20.0))
        view = self.finished(p)
        self.assertTrue(self.ledger_has("driver", signal.SIGKILL))
        self.assertLess(view["orphan"]["window_s"], 10.0)

    def test_a_burst_of_mixed_signals_from_outside_during_the_orphan_window(self):
        self.env(gen_s=12.0)
        p = self.start_driver(bounds=dict(BT, orphan_max_s=30.0, backstop_s=45.0, reader_deadline_s=60.0, idle_after_reader_s=20.0))
        self.assertTrue(wait_until(lambda: self.ledger_has("driver", signal.SIGKILL), 40))
        time.sleep(0.5)
        for n in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP) * 6:
            os.kill(p.pid, n)
        view = self.finished(p)
        self.assertLess(view["orphan"]["window_s"], 10.0)


class TestRev6InProcessSignals(Scenario):
    """Real signals in the Driver's own process (the test process) at points where the main thread is inside an Event wait."""

    def test_a_signal_before_the_spawn_ends_the_baseline_wait_promptly(self):
        self.env(gen_s=2.0)

        class P(StubProbes):
            sent = False

            def swap_mib(self_):
                if not P.sent:
                    P.sent = True
                    os.kill(os.getpid(), signal.SIGTERM)
                return super().swap_mib()
        t = time.monotonic()
        res = self.pilot(probes=P(), install_signals=True, baseline_n=4, baseline_interval=30.0)  # a 30 s wait per reading
        self.assertEqual(res["outcome"], "INTERRUPTED")
        self.assertLess(time.monotonic() - t, 25)
        self.assertEqual(self.record_count(), 0)  # nothing was spawned

    def record_count(self):
        d = os.path.join(self.root, "records")
        return len([n for n in os.listdir(d) if n.endswith(".json")]) if os.path.isdir(d) else 0

    def test_a_signal_in_the_post_sampling_wait_ends_it_and_is_s11(self):
        self.env(gen_s=2.0)
        flag = {"on": False, "sent": False}
        real = D.Pilot.close_sinks
        D.Pilot.close_sinks = lambda self_: (real(self_), flag.update(on=True))[0]
        self.addCleanup(lambda: setattr(D.Pilot, "close_sinks", real))

        class P(StubProbes):
            def sample(self_):
                if flag["on"] and not flag["sent"]:
                    flag["sent"] = True
                    os.kill(os.getpid(), signal.SIGHUP)
                return super().sample()
        t = time.monotonic()
        res = self.pilot(probes=P(), install_signals=True, post_sample_s=20)
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertIn("S11", [s["id"] for s in res["stops"]])
        self.assertEqual(len(self.jsonl("post-unload.jsonl")), 1)
        self.assertLess(time.monotonic() - t, 120)


class TestRev6FailClosedSealing(Scenario):
    """Revision 6: report files are provisional until the seal confirmation is written last and independently checked."""

    def patch(self, owner, name, fn):
        real = getattr(owner, name)
        setattr(owner, name, fn(real))
        self.addCleanup(lambda: setattr(owner, name, real))

    def accept(self, status=None):
        return T.evidence_acceptance(self.run_dir(), self.res["exit_code"] if status is None else status)

    def failing_after(self, n):
        def wrap(real):
            calls = {"n": 0}

            def inner(*a, **k):
                calls["n"] += 1
                if calls["n"] > n:
                    raise OSError("synthetic report write failure")
                return real(*a, **k)
            return inner
        return wrap

    def test_a_clean_run_is_sealed_and_supports_verdicts_only_with_a_matching_normal_exit(self):
        self.env(gen_s=2.0)
        res = self.pilot()
        self.assertEqual(res["outcome"], "PILOT_COMPLETED")
        self.assertEqual(self.accept(0), {"sealed": True, "supports_verdicts": True, "reasons": []})
        for status in (None, 1):
            a = T.evidence_acceptance(self.run_dir(), status)
            self.assertFalse(a["sealed"] or a["supports_verdicts"], status)
            self.assertTrue(any("normal completion is not confirmed" in r for r in a["reasons"]))

    def test_the_cli_acceptance_check_reads_only_the_files_and_the_exit_status(self):
        self.env(gen_s=2.0)
        self.pilot()
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = D.main(["--bench", self.spec["bench"], "accept", self.res["run_id"], "--exit-status", "0"])
        self.assertEqual((rc, json.loads(out.getvalue())["supports_verdicts"]), (0, True))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(D.main(["--bench", self.spec["bench"], "accept", self.res["run_id"], "--exit-status", "1"]), 1)

    def test_a_missing_seal_confirmation_alone_rejects_an_otherwise_valid_sealed_run(self):
        self.env(gen_s=2.0)
        self.pilot()
        self.assertEqual(self.accept(0), {"sealed": True, "supports_verdicts": True, "reasons": []})
        os.unlink(os.path.join(self.run_dir(), T.SEAL_FILE))   # ONLY the confirmation: both report files and every raw artifact are intact
        a = self.accept(0)
        self.assertIs(a["sealed"], False)
        self.assertIs(a["supports_verdicts"], False)
        # the reason is the explicit one and the ONLY one: a rejection that came from unrelated digest or outcome checks would
        # list those instead (this is what fails when the explicit missing-confirmation rejection is removed)
        self.assertEqual(a["reasons"], ["no seal confirmation: sealing did not complete"])
        self.assertEqual(T.evidence_acceptance(self.run_dir(), None)["reasons"], ["no seal confirmation: sealing did not complete"])

    def test_json_that_is_not_the_expected_structure_is_not_accepted_and_never_raises(self):
        self.env(gen_s=2.0)
        self.pilot()
        run = self.run_dir()
        originals = {n: open(os.path.join(run, n)).read() for n in (T.SEAL_FILE, "summary.json", "summary-committed-view.json")}

        def restore():
            for n, text in originals.items():
                with open(os.path.join(run, n), "w") as f:
                    f.write(text)

        def put(name, text):
            with open(os.path.join(run, name), "w") as f:
                f.write(text)
        self.addCleanup(restore)
        self.assertTrue(self.accept(0)["supports_verdicts"])
        for name in originals:
            for text in ("[]", '["a"]', '"text"', "null", "7", "true", "{not json"):
                with self.subTest(file=name, content=text):
                    restore()
                    put(name, text)
                    a = T.evidence_acceptance(run, 0)   # must return, not raise
                    self.assertIs(a["sealed"], False)
                    self.assertIs(a["supports_verdicts"], False)
                    self.assertTrue(a["reasons"])
                    if text in ("[]", '["a"]', '"text"', "7", "true"):
                        self.assertTrue(any("not a JSON object" in r for r in a["reasons"]), a["reasons"])
                    else:   # null and unparsable: indistinguishable from a missing file, reported as such
                        self.assertTrue(any(("no seal confirmation" in r) or ("missing or unreadable" in r) or ("not a JSON object" in r) for r in a["reasons"]), a["reasons"])
        for name, key, bad in (("summary.json", "stops", "x"), ("summary.json", "stops", {"a": 1}), ("summary.json", "seal", []),
                               ("summary-committed-view.json", "raw_artifacts", []), ("summary-committed-view.json", "raw_artifacts", "x")):
            with self.subTest(file=name, key=key, value=bad):
                restore()
                obj = json.loads(originals[name])
                obj[key] = bad
                put(name, json.dumps(obj))
                a = T.evidence_acceptance(run, 0)
                self.assertIs(a["sealed"], False)
                self.assertIs(a["supports_verdicts"], False)
                self.assertTrue(any(key in r for r in a["reasons"]), a["reasons"])
        restore()
        view = json.loads(originals["summary-committed-view.json"])
        view["raw_artifacts"]["events.jsonl"] = "not-an-object"
        put("summary-committed-view.json", json.dumps(view))
        a = T.evidence_acceptance(run, 0)
        self.assertFalse(a["sealed"] or a["supports_verdicts"])
        self.assertTrue(any("raw_artifacts entry" in r for r in a["reasons"]), a["reasons"])

    def test_the_structural_checks_do_not_weaken_the_digest_exit_status_outcome_and_run_id_checks(self):
        self.env(gen_s=2.0)
        self.pilot()
        run = self.run_dir()
        conf_path = os.path.join(run, T.SEAL_FILE)
        original = open(conf_path).read()
        self.addCleanup(lambda: open(conf_path, "w").write(original))
        for key, bad, needle in (("summary_sha256", "0" * 64, "differs from the one the seal confirmed"), ("view_sha256", "0" * 64, "differs from the one the seal confirmed"),
                                 ("exit_code", 1, "normal completion is not confirmed"), ("outcome", "STOPPED", "outcome differs"),
                                 ("run_id", "other-run", "run identity differs"), ("sealed", False, "does not say sealed")):
            with self.subTest(key=key):
                conf = json.loads(original)
                conf[key] = bad
                with open(conf_path, "w") as f:
                    json.dump(conf, f)
                a = T.evidence_acceptance(run, 0)
                self.assertFalse(a["sealed"] or a["supports_verdicts"])
                self.assertTrue(any(needle in r for r in a["reasons"]), a["reasons"])
        with open(conf_path, "w") as f:
            f.write(original)
        self.assertEqual(self.accept(0), {"sealed": True, "supports_verdicts": True, "reasons": []})

    def test_a_tampered_or_contradictory_report_is_not_accepted(self):
        self.env(gen_s=2.0)
        self.pilot()
        view_path = os.path.join(self.run_dir(), "summary-committed-view.json")
        original = open(view_path).read()
        view = json.loads(original)
        view["outcome"] = "STOPPED"
        with open(view_path, "w") as f:
            json.dump(view, f)
        a = self.accept(0)
        self.assertFalse(a["sealed"])
        self.assertTrue(any("differs" in r for r in a["reasons"]))
        with open(view_path, "w") as f:
            f.write(original)
        self.assertTrue(self.accept(0)["supports_verdicts"])
        raw = os.path.join(self.run_dir(), "series.jsonl")
        with open(raw, "a") as f:
            f.write("{}\n")
        a = self.accept(0)
        self.assertTrue(a["sealed"] and not a["supports_verdicts"])  # the sealed pair is intact, a raw artifact is not what it listed

    def test_a_failure_after_a_published_success_file_leaves_no_confirmation_and_no_accepted_evidence(self):
        self.env(gen_s=2.0)
        ev = threading.Event()

        def after_first_write(real):
            calls = {"n": 0}

            def inner(*a, **k):
                calls["n"] += 1
                if calls["n"] > 1:
                    raise OSError("synthetic rewrite failure")   # every rewrite fails, including the best-effort one
                out = real(*a, **k)
                ev.set()   # the first pass has just published a SUCCESS report; an interrupt is accepted right after
                return out
            return inner
        self.patch(D, "write_report", after_first_write)
        res = self.pilot(interrupted=ev)
        on_disk = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertEqual(on_disk["outcome"], "PILOT_COMPLETED")  # the stale success file is still on disk ...
        self.assertFalse(os.path.exists(os.path.join(self.run_dir(), T.SEAL_FILE)))
        a = self.accept()
        self.assertFalse(a["sealed"] or a["supports_verdicts"], a)  # ... and is not accepted
        self.assertEqual(res["exit_code"], 1)
        self.assertEqual(res["finalize_error"], "OSError")
        self.assertIn("S11", [s["id"] for s in res["stops"]])  # the pending interrupt is reconciled on the error return
        for k in T.VERDICT_ROWS:
            self.assertEqual(res["rows"]["rows"][k], "INCONCLUSIVE", k)  # supporting rows are withheld on the error path
        self.assertNotEqual(res["outcome"], "PILOT_COMPLETED")

    def test_an_interrupt_accepted_while_the_first_write_fails_is_reconciled_on_the_error_return(self):
        self.env(gen_s=2.0)
        ev = threading.Event()

        def interrupt_then_fail(real):
            calls = {"n": 0}

            def inner(*a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    ev.set()   # accepted after the verdict and the settle, then the write itself fails
                    raise OSError("synthetic write failure")
                return real(*a, **k)   # the best-effort rewrite of the failed (unconfirmed) report
            return inner
        self.patch(D, "write_report", interrupt_then_fail)
        res = self.pilot(interrupted=ev)
        self.assertIn("S11", [s["id"] for s in res["stops"]])
        for k in T.VERDICT_ROWS:
            self.assertEqual(res["rows"]["rows"][k], "INCONCLUSIVE", k)
        on_disk = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertIn("S11", [s["id"] for s in on_disk["stops"]])
        self.assertEqual((on_disk["finalize_error"], on_disk["seal"]), ("OSError", {"interrupt_seen": True, "sealed": False, "passes": 1}))
        self.assertEqual(res["exit_code"], 1)
        self.assertFalse(self.accept()["sealed"])

    def test_the_best_effort_rewrite_marks_the_report_failed_but_still_unconfirmed(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        self.patch(D, "write_seal_confirmation", lambda real: (lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic confirmation failure"))))
        res = self.pilot()
        self.assertEqual((res["outcome"], res["exit_code"], res["outcome_unsealed"]), ("FINALIZE_ERROR", 1, "PILOT_COMPLETED"))
        on_disk = json.load(open(os.path.join(self.run_dir(), "summary.json")))
        self.assertEqual((on_disk["outcome"], on_disk["finalize_error"], on_disk["seal"]["sealed"]), ("FINALIZE_ERROR", "OSError", False))
        for k in T.VERDICT_ROWS:
            self.assertEqual(on_disk["rows"]["rows"][k], "INCONCLUSIVE", k)
        self.assertFalse(self.accept()["sealed"])

    def test_a_non_success_outcome_is_kept_when_finalization_fails(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        ev.set()   # accepted before the verdict: STOPPED
        self.patch(D, "write_report", self.failing_after(0))
        res = self.pilot(interrupted=ev)
        self.assertEqual((res["outcome"], res["finalize_error"], res["exit_code"]), ("INTERRUPTED", "OSError", 1))   # the outcome is NOT rewritten to FINALIZE_ERROR
        self.assertFalse(self.accept()["sealed"])

    def test_a_report_that_cannot_be_written_at_all_is_never_accepted(self):
        self.env(gen_s=2.0)
        self.patch(D, "write_report", self.failing_after(0))
        res = self.pilot()
        self.assertEqual((res["outcome"], res["exit_code"]), ("FINALIZE_ERROR", 1))
        a = self.accept()
        self.assertFalse(a["sealed"] or a["supports_verdicts"])
        self.assertTrue(any("missing" in r or "no seal" in r for r in a["reasons"]))

    def test_the_confirmation_is_removed_before_a_rewrite(self):
        self.env(gen_s=2.0)
        ev = threading.Event()
        seen = {}

        def probe(real):
            calls = {"n": 0}

            def inner(run_dir, *a, **k):
                calls["n"] += 1
                seen[calls["n"]] = os.path.exists(os.path.join(run_dir, T.SEAL_FILE))
                out = real(run_dir, *a, **k)
                if calls["n"] == 1:
                    ev.set()
                return out
            return inner
        self.patch(D, "write_report", probe)
        res = self.pilot(interrupted=ev)
        self.assertEqual(seen, {1: False, 2: False})
        self.assertTrue(self.accept(1)["sealed"])   # sealed after the second pass, with its exit code 1
        self.assertFalse(self.accept(1)["supports_verdicts"])


class TestF4KillingStopAttribution(Scenario):
    """Finding 4: the exit attribution uses the actual killing-or-quarantining stop state, not the record's quarantine flag."""

    HANG = [sys.executable, "-B", "-c", "import time;time.sleep(300)"]

    def test_a_non_quarantining_immediate_stop_with_a_refused_signal_and_a_vanished_runtime_is_undetermined(self):
        self.env(mode="exit_after_gen", gen_s=1.5)
        probes = StubProbes()
        held = []
        self.addCleanup(lambda: [h.stop() for h in held])

        def stop_then_refuse():
            wait_until(lambda: any(s["who"] == "driver" and s["sent"] for s in self.live_signals()), 60)
            run = os.path.join(self.root, "runs", os.listdir(os.path.join(self.root, "runs"))[0])
            held.append(Holder(os.path.join(run, "signals.lock"), 2.5))  # the monitor's emergency kill cannot get the ledger lock
            probes.pressure_v = 4  # S1: immediate, NOT a quarantine
        threading.Thread(target=stop_then_refuse, daemon=True).start()
        res = self.pilot(probes=probes, monitor_interval=0.2, monitor_slow_every=2,
                         bounds=dict(BT, lock_timeout_s=0.4, orphan_max_s=3.0, backstop_s=8.0, reader_deadline_s=30.0), successor_cmd=self.HANG)
        self.assertIn("S1", [s["id"] for s in res["stops"]], res["stops"])
        rec = self.record()
        self.assertFalse(rec.get("owner_review_required"))  # the flag is NOT set: this is the case the old basis could not see
        self.assertEqual(rec["e3"]["killing_stop"], True)
        self.assertEqual(rec["e3"]["killing_stop_ids"], ["S1"])
        self.assertEqual([s for s in self.signals() if s["sent"] and s["pid"] == rec["pid"]], [])  # nothing was delivered to the runtime
        for name, d in (("record", rec), ("raw", json.load(open(os.path.join(self.run_dir(), "summary.json")))), ("view", self.view())):
            if name != "record":
                d = d["exit"]
            self.assertEqual(d["exit_cause"], T.UNDETERMINED, name)
            self.assertEqual(d["terminated_by"], "undetermined", name)
        self.assertIs(self.view()["orphan"]["exited_by_itself"], None)  # unknown stays unknown
        self.assertEqual(self.view()["orphan"]["exit_cause"]["cause"], T.UNDETERMINED)
        self.assertIs(self.view()["exit"]["attribution_consistent"], True)
        # finding 5 on the same run: the refused attempt is counted although it could not be written to the ledger
        acc = self.view()["signals"]["driver-monitor"]
        self.assertGreaterEqual(acc["unrecorded"], 1)
        self.assertGreaterEqual(acc["refused"]["ledger_lock_timeout"], acc["unrecorded"])
        self.assertEqual(acc["delivered"], 0)
        self.assertIn("lower bound", self.view()["signals_basis"])

    def live_signals(self):
        out = []
        runs = os.path.join(self.root, "runs")
        for d in os.listdir(runs) if os.path.isdir(runs) else []:
            out += T.SignalLedger(os.path.join(runs, d)).entries()
        return out

    def test_the_same_run_without_the_stop_is_still_a_self_exit(self):
        self.env(mode="exit_after_gen", gen_s=1.5)
        res = self.pilot(bounds=dict(BT, orphan_max_s=3.0, backstop_s=8.0, reader_deadline_s=30.0), successor_cmd=self.HANG)
        self.assertEqual(res["outcome"], "PILOT_COMPLETED_BACKSTOP", res["stops"])
        self.assertEqual(self.record()["terminated_by"], "self_exit")
        self.assertIs(self.view()["orphan"]["exited_by_itself"], True)
        self.assertNotIn("killing_stop", {k for k, v in self.record()["e3"].items() if v})

    def successor_record(self, rid, **extra):
        """A BOUND record of a runtime that is already gone, for the Successor process itself (called in-process)."""
        rs = T.LockedRecords(self.root)
        p = subprocess.Popen(["/bin/sleep", "60"], preexec_fn=lambda: os.setpgid(0, 0))  # its own group, empty once it is gone
        ident = L.identity(p.pid)
        p.kill()
        p.wait(5)
        rec = rs.create({"v": 1, "run_id": rid, "state": "INTENT", "tag": "no-such-tag-" + rid, "port": 59, "boottime": E.HostProbes().boottime()})
        rs.advance(rec, "SPAWNED", pid=p.pid, start=ident["start"], pgid=ident["pgid"], binding_verified=False, descendants=[])
        rs.advance(rec, "BOUND", binding_verified=True)
        e3 = dict({"scope": T.SCOPE, "bounds": json.loads(json.dumps(BT, default=list)), "t0_up": T.uptime() - 0.05}, **extra)
        rs.annotate(rec, e3=e3)
        os.makedirs(os.path.join(self.root, "runs", rid), exist_ok=True)
        return rs, os.path.join(rs.dir, rid + ".json")

    def run_successor(self, path):
        import contextlib
        import io
        import e3_successor as S
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.main(path)
        return rc, [json.loads(l) for l in out.getvalue().splitlines() if l.startswith("{")]

    def test_the_successor_reads_the_published_stop_state_not_only_the_flag(self):
        self.env()
        for name, extra, flag, want in (("plain", {}, False, "self_exit"),
                                        ("killing", {"killing_stop": True, "killing_stop_ids": ["S1"]}, False, "undetermined"),
                                        ("flag", {}, True, "undetermined")):
            with self.subTest(name):
                rs, path = self.successor_record("succ-" + name, **extra)
                if flag:
                    rs.annotate(rs.read("succ-" + name), owner_review_required=True, owner_review_reason="unit test")
                rc, msgs = self.run_successor(path)
                final = [m for m in msgs if m["e"] == "FINAL"][0]
                self.assertEqual(final["terminated_by"], want, final)
                self.assertEqual(rs.read("succ-" + name)["terminated_by"], want)
                self.assertEqual(final["self_exit"], want == "self_exit")
                if want == "undetermined":
                    self.assertEqual(final["exit_cause"]["cause"], T.UNDETERMINED)

    def test_record_stop_state(self):
        self.assertEqual(T.record_stop_state({}), [])
        self.assertEqual(T.record_stop_state({"e3": {"killing_stop": False}}), [])
        self.assertEqual(T.record_stop_state({"e3": {"killing_stop": True}}), [{"immediate": True}])
        self.assertEqual(T.record_stop_state({"owner_review_required": True}), [{"quarantine": True}])


class TestF5SignalAttemptAccounting(Base):
    def test_lock_timeouts_are_retained_without_pids_and_counted_but_never_as_delivered(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        ledger = T.SignalLedger(run, lock_timeout_s=0.2)
        h = Holder(ledger.lock)
        self.addCleanup(h.stop)
        for _ in range(3):
            self.assertEqual(ledger.send("driver-monitor", 1, [1, 1], signal.SIGKILL)["why"], "ledger_lock_timeout")
        self.assertEqual(ledger.entries(), [])  # nothing could be written
        self.assertEqual(ledger.unrecorded_total, 3)
        self.assertEqual(ledger.unrecorded, [{"who": "driver-monitor", "sig": int(signal.SIGKILL), "why": "ledger_lock_timeout"}] * 3)
        self.assertNotIn("pid", json.dumps(ledger.unrecorded))

    def test_the_retained_list_is_bounded(self):
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        ledger = T.SignalLedger(run, lock_timeout_s=0.0)
        h = Holder(ledger.lock)
        self.addCleanup(h.stop)
        for _ in range(T.SignalLedger.UNRECORDED_KEEP + 5):
            ledger.send("x", 1, [1, 1], signal.SIGKILL)
        self.assertEqual((len(ledger.unrecorded), ledger.unrecorded_total), (T.SignalLedger.UNRECORDED_KEEP, T.SignalLedger.UNRECORDED_KEEP + 5))

    def test_accounting_adds_reported_refusals_and_keeps_the_old_shape_without_them(self):
        entries = [{"who": "a", "sent": True, "pid": 1}, {"who": "a", "sent": False, "why": "gone", "pid": 1}]
        self.assertEqual(T.signal_accounting(entries), {"a": {"attempted": 2, "delivered": 1, "refused": {"gone": 1}}})
        acc = T.signal_accounting(entries, {"a": 2, "b": 1, "c": 0})
        self.assertEqual(acc["a"], {"attempted": 4, "delivered": 1, "refused": {"gone": 1, "ledger_lock_timeout": 2}, "unrecorded": 2})
        self.assertEqual(acc["b"], {"attempted": 1, "delivered": 0, "refused": {"ledger_lock_timeout": 1}, "unrecorded": 1})
        self.assertNotIn("c", acc)

    def test_the_basis_statement_is_part_of_the_committed_view(self):
        v = T.committed_view({"signals": {}, "signals_basis": T.SIGNAL_ACCOUNTING_BASIS})
        self.assertIn("lower bound", v["signals_basis"])

    def test_a_signal_delivered_by_a_signaller_that_died_before_the_append_is_in_no_ledger(self):
        # the ledger entry follows kill(2): the delivery counts are recorded deliveries, a lower bound, not "exact"
        run = os.path.join(self.tmp, "run")
        os.makedirs(run)
        ledger = T.SignalLedger(run)
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait(5)))

        class Died(BaseException):
            pass

        def die(*a, **k):
            raise Died()
        real = T.json
        T.json = types.SimpleNamespace(dumps=die, loads=real.loads, load=real.load, dump=real.dump)  # the signaller dies at the append
        try:
            with self.assertRaises(Died):
                ledger.send("successor", p.pid, L.identity(p.pid)["start"], signal.SIGKILL, "test")
        finally:
            T.json = real
        self.assertEqual(p.wait(5), -int(signal.SIGKILL))  # the signal WAS delivered ...
        self.assertEqual(ledger.entries(), [])  # ... and no ledger knows it
        self.assertEqual(T.signal_accounting(ledger.entries()), {})
        self.assertIn("RECORDED deliveries", T.SIGNAL_ACCOUNTING_BASIS)
        self.assertIn("delivered is a lower bound too", T.SIGNAL_ACCOUNTING_BASIS)
        self.assertNotIn("exact for delivery", T.SIGNAL_ACCOUNTING_BASIS)
        self.assertNotIn("always in the ledger", T.SIGNAL_ACCOUNTING_BASIS)


class TestF6FirstObservationLabel(Base):
    def finalize(self, rid, seen_alive):
        self.root = os.path.join(self.tmp, "e3root")
        rs = T.LockedRecords(self.root)
        run_dir = os.path.join(self.root, "runs", rid)
        os.makedirs(run_dir)
        p = subprocess.Popen(["/bin/sleep", "60"], preexec_fn=lambda: os.setpgid(0, 0))
        i = L.identity(p.pid)
        p.kill()
        p.wait(5)  # the runtime is gone before the finalizer's first look
        rec = rs.create({"v": 1, "run_id": rid, "state": "INTENT", "tag": "zz-" + rid, "port": 59, "boottime": E.HostProbes().boottime()})
        rs.advance(rec, "SPAWNED", pid=p.pid, start=i["start"], pgid=i["pgid"], binding_verified=False, descendants=[])
        rs.advance(rec, "BOUND", binding_verified=True)
        pilot = D.Pilot.__new__(D.Pilot)
        pilot.records, pilot.run_id, pilot.b, pilot.summary = rs, rid, BT, {}
        pilot.ledger, pilot.inst, pilot.stops = T.SignalLedger(run_dir), None, []
        pilot.runtime_seen_alive = seen_alive
        pilot.finalize_nonparent("driver_backstop")
        return rs.read(rid), pilot.summary["finalize"]

    def test_a_runtime_the_driver_never_saw_alive_from_the_kill_instant_is_absent_at_first_observation_in_that_scope(self):
        rec, fin = self.finalize("f6a", False)
        self.assertEqual((rec["state"], rec["exit_event"]), ("EXIT_VERIFIED", T.EXIT_UNOBSERVED))
        self.assertEqual((fin["alive_at_first_look"], fin["driver_saw_alive_from_kill_instant"]), (False, False))
        self.assertEqual(fin["first_observation_scope"], T.FIRST_OBSERVATION_SCOPE)  # the label's scope is in the report, not implied
        self.assertIn("pre-trigger monitor samples are not consulted", fin["first_observation_scope"])

    def test_a_runtime_the_driver_saw_alive_from_the_kill_instant_never_gets_that_label(self):
        rec, fin = self.finalize("f6b", True)
        self.assertEqual((rec["state"], rec["exit_event"]), ("EXIT_VERIFIED", T.EXIT_NO_NOTIFICATION))
        self.assertEqual((fin["alive_at_first_look"], fin["driver_saw_alive_from_kill_instant"]), (False, True))


class TestF7TestCleanupOrdering(unittest.TestCase):
    def test_processes_are_killed_and_verified_gone_before_the_records_that_identify_them_are_removed(self):
        import io
        victims = {}

        class Leak(Base):
            def runTest(self_):
                p = subprocess.Popen(["/bin/sleep", "60"])
                victims["p"], victims["tmp"] = p, self_.tmp
                rec = os.path.join(self_.tmp, "bench", "e3", "records")
                os.makedirs(rec)
                with open(os.path.join(rec, "x.json"), "w") as f:
                    json.dump({"run_id": "x", "state": "BOUND", "pid": p.pid, "start": L.identity(p.pid)["start"], "tag": "no-such-tag"}, f)
        self.addCleanup(lambda: victims["p"].poll() is None and victims["p"].kill())
        result = unittest.TextTestRunner(stream=io.StringIO()).run(Leak())
        self.assertTrue(result.wasSuccessful())
        # The cleanup killed it (with the old ordering the records were deleted first and this process lived on). The wait below is
        # THE TEST's own wait on its own child: it is what reaps the process, and its return code is the proof of the kill.
        try:
            rc = victims["p"].wait(5)
        except subprocess.TimeoutExpired:
            self.fail("the cleanup left the process running: the records were removed before the killer used them")
        self.assertEqual(rc, -int(signal.SIGKILL))
        self.assertFalse(os.path.exists(victims["tmp"]))

    def test_the_helper_counts_a_killed_unwaited_child_as_gone_without_reaping_it(self):
        tmp = tempfile.mkdtemp(prefix="e3-test-")
        records = os.path.join(tmp, "bench", "e3", "records")
        os.makedirs(records)
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait(5), subprocess.run(["rm", "-rf", tmp])))
        with open(os.path.join(records, "x.json"), "w") as f:
            json.dump({"run_id": "x", "state": "BOUND", "pid": p.pid, "start": L.identity(p.pid)["start"], "tag": "no-such-tag"}, f)

        def table_state():  # the process table, not the helper's view: 'Z' = exited and not yet waited for
            return subprocess.run(["ps", "-o", "stat=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(kill_recorded_and_verify_gone(os.path.join(tmp, "bench", "e3")), [])  # identity disappearance
        self.assertIsNone(L.identity(p.pid))  # the available inspection no longer sees it ...
        self.assertTrue(table_state().startswith("Z"), table_state())  # ... but it is a zombie: nothing was reaped
        self.assertIsNone(p.returncode)  # and the parent has not waited
        self.assertEqual(p.wait(5), -int(signal.SIGKILL))  # wait/reap completion is the parent's own wait
        self.assertEqual(table_state(), "")

    def test_a_surviving_process_keeps_the_bench_and_reports_it(self):
        import io
        tmp = tempfile.mkdtemp(prefix="e3-test-")
        records = os.path.join(tmp, "bench", "e3", "records")
        os.makedirs(records)
        p = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait(5), subprocess.run(["rm", "-rf", tmp])))
        with open(os.path.join(records, "x.json"), "w") as f:
            json.dump({"run_id": "x", "state": "BOUND", "pid": p.pid, "start": L.identity(p.pid)["start"], "tag": "no-such-tag"}, f)
        real_kill, real_helper = L.safe_kill, kill_recorded_and_verify_gone
        L.safe_kill = lambda *a, **k: False  # a process that cannot be signalled
        globals()["kill_recorded_and_verify_gone"] = lambda root: real_helper(root, timeout=0.5)
        err, real_err = io.StringIO(), sys.stderr
        base = Base("setUp")
        base.tmp = tmp
        sys.stderr = err
        try:
            base._cleanup_bench()
        finally:
            sys.stderr = real_err
            L.safe_kill = real_kill
            globals()["kill_recorded_and_verify_gone"] = real_helper
        self.assertTrue(os.path.isdir(tmp), "the bench is kept when a survivor remains")
        self.assertIn("survived the kill-and-verify cleanup", err.getvalue())
        self.assertIn("runtime", err.getvalue())
        self.assertIn(tmp, err.getvalue())
        self.assertNotIn("reaper", Base._cleanup_bench.__doc__.lower().replace("reaped", ""))


class TestMutations(Scenario):
    """Each test re-introduces one defect in memory and requires a safety property test to notice it."""

    def test_removing_the_sticky_refresh_loses_a_concurrent_flag(self):
        orig = T.LockedRecords._refresh
        T.LockedRecords._refresh = lambda self, rec: None
        try:
            rs = T.LockedRecords(os.path.join(self.tmp, "root"))
            rec = rs.create({"v": 1, "run_id": "r1", "state": "INTENT"})
            other = rs.read("r1")
            rs.annotate(other, owner_review_required=True)
            rs.advance(rec, "SPAWNED", pid=5, start=[1, 2])
            self.assertFalse(rs.read("r1").get("owner_review_required"))  # the defect: the flag is lost
        finally:
            T.LockedRecords._refresh = orig

    def test_a_ledger_without_the_identity_check_would_signal_a_reused_pid(self):
        p = subprocess.Popen(["/bin/sleep", "30"])
        self.addCleanup(p.kill)
        real = T.L.same_identity
        T.L.same_identity = lambda *a, **k: True
        try:
            r = T.SignalLedger(self.tmp).send("t", p.pid, [1, 1], signal.SIGKILL)
            self.assertTrue(r["sent"])  # the defect is real and this is what the identity check prevents
        finally:
            T.L.same_identity = real
        p.wait(5)

    def test_a_trigger_that_ignores_reader_completion_would_fire_late(self):
        t = T.Trigger(dict(T.BOUNDS))
        t.request_sent(0.0)
        for k in range(5):
            t.poll(2.0 + k * 0.1, True, True)
        t.reader_completed(2.2)
        t.reader_done_up = None  # the defect
        self.assertEqual(t.decide(2.6), T.FIRE)
        t.reader_done_up = 2.2
        self.assertEqual(t.decide(2.6), T.MISSED)


def driver_main(spec_json):
    spec = json.loads(spec_json)
    cfg = cfg3(spec)
    D.run_pilot(cfg, StubProbes(), 3, True, e3pins=spec["e3pins"], bounds=spec["bounds"], faults=spec.get("faults"), gate_n=3,
                interval=0.2, top_cmd=TOP4, post_delay=0, post_sample_s=0, install_signals=True, baseline_n=3, baseline_interval=0.1)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--driver":
        driver_main(sys.argv[2])
    else:
        unittest.main(verbosity=2)
