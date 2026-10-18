#!/usr/bin/env python3
"""Tests for the E2-B evidence harness. Standard library only (unittest); macOS (sandbox-exec,
libproc). Everything runs against synthetic or simulated runtime behaviour: the real model and the
real llama-server are never started. Test fixtures use their own synthetic strings, not the
approved experiment fixtures.

Run: python3 -B test_e2b.py            (all)      python3 -B test_e2b.py TestGate  (one class)
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e2b_harness as H  # noqa: E402
import e2b_lib as E  # noqa: E402

FAKE = os.path.join(HERE, "e2b_fake_runtime.py")


def PYSLEEP(n):
    return [sys.executable, "-I", "-c", f"import time; time.sleep({n})"]
TOP4 = [sys.executable, "-c", "for _ in range(4): print('CPU usage: 5.0% user, 5.0% sys, 90.0% idle')"]


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def alive(pid, start):
    i = L.identity(pid)
    return L.same_identity(pid, start, i) and i["status"] != "zombie"


class StubProbes(E.HostProbes):
    """Healthy synthetic host readings; tests flip attributes to simulate pressure etc."""

    def __init__(self):
        super().__init__()
        self.pressure_v, self.src, self.swap, self.free, self.sleep_jump = 1, "AC Power", 3000.0, 60, 0.0
        self.hid = 5.0
        self.n = 0
        self.fail_left, self.fail_always, self.jump_at, self.swap_seq = 0, False, None, None

    def sample(self):
        self.n += 1
        if self.jump_at is not None and self.n == self.jump_at:
            self.sleep_jump = 60.0  # the host "slept" between the previous sample and this one
        if self.fail_always or self.fail_left > 0:
            self.fail_left = max(0, self.fail_left - 1)
            raise RuntimeError("synthetic probe failure")
        return {"wall": time.time() + self.sleep_jump, "up": time.clock_gettime(time.CLOCK_UPTIME_RAW), "src": self.src,
                "press": self.pressure_v, "swap": self.swap, "free": self.free, "pageouts": 100, "swapouts": 50}

    def swap_mib(self):
        return self.swap_seq.pop(0) if self.swap_seq else self.swap

    def thermal_warn(self):
        return False

    def disk_gib(self, path=""):
        return 300.0

    def hid_idle_s(self):
        return self.hid

    def competing(self):
        return []

    def attendance(self):
        return {"hid_idle_s": self.hid, "display_awake_assertion": True, "ac_timers_min": {"displaysleep": 10, "sleep": 1}}


def make_env(tmp, mode="normal", extra_fake=()):
    """Bench folder with synthetic fixtures, a tiny 'model', a wrapper standing in for the binary,
    pins computed for them, and an owner authorization bound to a stand-in protocol document."""
    bench = os.path.join(tmp, "bench")
    for d in ("fixtures/e2b", "models", "tools"):
        os.makedirs(os.path.join(bench, d), exist_ok=True)
    pre = [{"role": "system", "content": "unit-test system alpha"}, {"role": "user", "content": "unit-test turn bravo"},
           {"role": "assistant", "content": "unit-test reply charlie"}]

    def body(u, n, stream=False):
        b = {"messages": pre + [{"role": "user", "content": u}], "max_tokens": n, "temperature": 0, "seed": 42,
             "stream": stream, "cache_prompt": False}
        if stream:
            b["stream_options"] = {"include_usage": True}
        return b

    files = {"P1": body("unit-test ask delta", 32), "P2": body("unit-test ask echo longer", 256),
             "P3": body("unit-test ask echo longer", 16), "P4": body("unit-test ask delta", 32, True),
             "AUTH": body("unit-test ask delta", 1), "meta": {"label": "unit-label-zulu"}}
    pins = {"runtime": {"version_string": "0.6.0-dev (build 11440, commit 1a3011cc0)"}, "port": free_port(),
            "fixtures": {}, "derived": {}, "model": {"filename": "m.gguf"}}
    for k, o in files.items():
        raw = E.canon(o)
        with open(os.path.join(bench, "fixtures/e2b", k + ".json"), "wb") as f:
            f.write(raw)
        spec = {"bytes": len(raw), "sha256": E.sha256_bytes(raw)}
        if k == "meta":
            pins["meta"] = spec
        else:
            pins["fixtures"][k] = spec
    for did, src in (("APPLY_P1", "P1"), ("APPLY_P2", "P2")):
        raw = E.canon({"messages": files[src]["messages"]})
        pins["derived"][did] = {"from": src, "bytes": len(raw), "sha256": E.sha256_bytes(raw)}
    model = os.path.join(bench, "models", "m.gguf")
    with open(model, "wb") as f:
        f.write(b"synthetic-model-bytes")
    wrapper = os.path.join(bench, "tools", "fake-llama-server")
    with open(wrapper, "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" -B "{FAKE}" --mode {mode} {" ".join(extra_fake)} "$@"\n')
    os.chmod(wrapper, 0o755)
    with open(os.path.join(bench, "tools", "libfake.dylib"), "wb") as f:
        f.write(b"synthetic-library-bytes")
    pins["model"].update(bytes=os.path.getsize(model), sha256=E.sha256_file(model))
    pins["runtime"]["binary_sha256"] = E.sha256_file(wrapper)
    tree = E.tree_manifest(os.path.join(bench, "tools"))
    pins["runtime"]["tree"] = {"files": tree["files"], "links": tree["links"]}
    doc = os.path.join(tmp, "protocol.md")
    with open(doc, "w") as f:
        f.write("stand-in protocol document\n")
    root = os.path.join(bench, "e2b")
    os.makedirs(root, mode=0o700, exist_ok=True)
    with open(os.path.join(root, "AUTHORIZATION.json"), "w") as f:
        json.dump({"scope": "base", "protocol_sha256": E.sha256_file(doc), "phases": [1, 2, 3, 4],
                   "expires_epoch": time.time() + 3600, "authorized_by": "unit test"}, f)
    return {"bench": bench, "pins": pins, "binary": wrapper, "model": model, "port": pins["port"], "doc": doc,
            "forbidden": E.forbidden_strings(*E.load_fixtures(os.path.join(bench, "fixtures/e2b"), pins))}


def cfg_from(spec, **kw):
    return H.Config(spec["bench"], pins=spec["pins"], binary=spec["binary"], model=spec["model"], port=spec["port"],
                    protocol_doc=spec["doc"], readiness_s=kw.pop("readiness_s", 15.0), control_runs=kw.pop("control_runs", 2),
                    control_c3_runs=kw.pop("control_c3_runs", 1), log_runner=lambda c: "", **kw)


def reap_all(root):
    """Test hygiene only: kill anything a test's records name, by recorded identity."""
    d = os.path.join(root, "records")
    for name in os.listdir(d) if os.path.isdir(d) else []:
        try:
            rec = json.load(open(os.path.join(d, name)))
        except (OSError, ValueError):
            continue
        if rec.get("pid") and rec.get("start"):
            L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL)
        for i in L.tag_scan(rec.get("tag", "none")):
            L.safe_kill(i["pid"], i["start"], signal.SIGKILL)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="e2b-test-")
        self.addCleanup(lambda: reap_all(os.path.join(self.tmp, "bench", "e2b")))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.tmp]))

    def env(self, mode="normal", **kw):
        self.spec = make_env(self.tmp, mode)
        self.cfg = cfg_from(self.spec, **kw)
        return self.cfg

    def run_all(self, through=4, probes=None, **kw):
        opts = dict(gate_n=3, interval=0.2, top_cmd=TOP4, post_delay=0, post_sample_s=0, install_signals=False,
                    baseline_n=3, baseline_interval=0.1)
        opts.update(kw)
        return H.run_all(self.cfg, probes or StubProbes(), through, True, **opts)

    def records(self):
        return E.Records(self.cfg.root)

    def when_state(self, state, fn, delay=1.5):
        """Run fn shortly after any record reaches ``state``."""
        def watch():
            d = os.path.join(self.cfg.root, "records")
            for _ in range(900):
                for n in os.listdir(d) if os.path.isdir(d) else []:
                    try:
                        if json.load(open(os.path.join(d, n))).get("state") == state:
                            time.sleep(delay)
                            return fn()
                    except (OSError, ValueError):
                        pass
                time.sleep(0.1)
        threading.Thread(target=watch, daemon=True).start()

    def when_bound(self, fn, delay=1.5):
        """Run fn shortly after any record reaches BOUND (i.e. mid Phase 3)."""
        self.when_state("BOUND", fn, delay)

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(lambda: setattr(obj, name, old))
        return old

    def only_record(self):
        rs = self.records()
        names = [n for n in os.listdir(rs.dir) if n.endswith(".json")]
        self.assertEqual(len(names), 1, names)
        return rs.read(names[0][:-5])


# --------------------------------------------------------------------------------------------
# pure logic


class TestFixturesAndPins(Base):
    def test_load_verifies_full_hashes_and_never_echoes_content(self):
        self.env()
        bodies, meta = E.load_fixtures(os.path.join(self.spec["bench"], "fixtures/e2b"), self.spec["pins"])
        self.assertEqual(set(bodies), {"P1", "P2", "P3", "P4", "AUTH"})
        path = os.path.join(self.spec["bench"], "fixtures/e2b/P2.json")
        raw = open(path, "rb").read()
        open(path, "wb").write(raw.replace(b"echo", b"ECHO"))
        with self.assertRaises(E.FixtureError) as cm:
            E.load_fixtures(os.path.join(self.spec["bench"], "fixtures/e2b"), self.spec["pins"])
        self.assertIn("P2", str(cm.exception))
        self.assertNotIn("unit-test", str(cm.exception))

    def test_noncanonical_bytes_rejected_even_with_matching_pin(self):
        self.env()
        d = os.path.join(self.spec["bench"], "fixtures/e2b")
        raw = json.dumps(json.load(open(os.path.join(d, "P1.json"))), indent=2).encode()
        open(os.path.join(d, "P1.json"), "wb").write(raw)
        pins = json.loads(json.dumps(self.spec["pins"]))
        pins["fixtures"]["P1"] = {"bytes": len(raw), "sha256": E.sha256_bytes(raw)}
        with self.assertRaises(E.FixtureError) as cm:
            E.load_fixtures(d, pins)
        self.assertIn("not canonical", str(cm.exception))

    def test_derived_apply_template_bodies_checked(self):
        self.env()
        pins = json.loads(json.dumps(self.spec["pins"]))
        pins["derived"]["APPLY_P1"]["sha256"] = "0" * 64
        with self.assertRaises(E.FixtureError):
            E.load_fixtures(os.path.join(self.spec["bench"], "fixtures/e2b"), pins)

    def test_scan_files_reports_index_not_text(self):
        self.env()
        p = os.path.join(self.tmp, "leak.md")
        with open(p, "w") as f:
            f.write("contains unit-label-zulu here")
        hits = E.scan_files([p], self.spec["forbidden"])
        self.assertTrue(hits and all(isinstance(i, int) for _, i in hits))

    def test_committed_pins_have_full_hashes_and_no_prompt_text(self):
        pins = E.load_pins()
        for spec in list(pins["fixtures"].values()) + list(pins["derived"].values()) + [pins["meta"]]:
            self.assertEqual(len(spec["sha256"]), 64)
        text = open(E.PINS_FILE).read()
        self.assertNotIn("messages", text)


class TestParsers(unittest.TestCase):
    def test_top_window_drops_first_since_boot_sample(self):
        text = "".join(f"CPU usage: 1.0% user, 1.0% sys, {v}% idle\n" for v in (10.0, 90.0, 92.5, 94.0))
        self.assertEqual(E.cpu_window(text, 3), [90.0, 92.5, 94.0])
        self.assertIsNone(E.cpu_window(text, 4))  # short window is not silently accepted

    def test_thermal_fails_closed(self):
        ok = "Note: No thermal warning level has been recorded\nNote: No performance warning level has been recorded\n"
        self.assertFalse(E.thermal_warning(ok))
        self.assertTrue(E.thermal_warning("CPU_Scheduler_Limit = 80\n"))
        self.assertTrue(E.thermal_warning(""))

    def test_power_swap_free_vm_hid_boot_timers(self):
        self.assertEqual(E.parse_pmset_batt("Now drawing from 'AC Power'\n -InternalBattery"), "AC Power")
        self.assertEqual(E.parse_swap_mib("total = 5120.00M  used = 3910.69M  free = 1.00M"), 3910.69)
        self.assertEqual(E.parse_swap_mib("total = 5.00G  used = 2.00G"), 2048.0)
        self.assertEqual(E.parse_free_pct("System-wide memory free percentage: 55%"), 55)
        vm = E.parse_vm_counters('Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPageouts:   12.\n"Translation faults":  5.\nSwapouts: 7.\n')
        self.assertEqual((vm["Pageouts"], vm["Swapouts"], vm["_page_size"]), (12, 7, 16384))
        self.assertAlmostEqual(E.parse_hid_idle_s('| |   "HIDIdleTime" = 213837577083'), 213.837577083)
        self.assertEqual(E.parse_boottime("{ sec = 1791976123, usec = 969207 } Wed"), [1791976123, 969207])
        custom = "Battery Power:\n sleep 1\n displaysleep 2\nAC Power:\n displaysleep 10\n sleep 1\n"
        self.assertEqual(E.parse_pm_timers(custom), {"displaysleep": 10, "sleep": 1})
        self.assertTrue(E.parse_display_awake_assertion("   PreventUserIdleSystemSleep     1\n"))
        self.assertFalse(E.parse_display_awake_assertion("   PreventUserIdleSystemSleep     0\n"))

    def test_procargs_parse(self):
        raw = (2).to_bytes(4, "little") + b"/bin/x\0\0\0/bin/x\0--a\0E=1\0"
        self.assertEqual(E.parse_procargs(raw), ("/bin/x", ["/bin/x", "--a"]))


def win(n=61, **over):
    base = {"src": "AC Power", "press": 1, "swap": 3000.0, "free": 55, "pageouts": 10, "swapouts": 5}
    out = []
    for i in range(n):
        s = dict(base, wall=1000.0 + i, up=500.0 + i)
        out.append(s)
    for k, v in over.items():
        for i, x in v.items():
            out[i][k] = x
    return out


CTX = {"thermal_warning": False, "competing": [], "disk_gib": 300.0, "attended_flag": True,
       "attendance": {"hid_idle_s": 5.0, "display_awake_assertion": True, "ac_timers_min": {"displaysleep": 10}},
       "artifacts": {"ok": True, "detail": "x"}, "clean_state": {"ok": True, "detail": "x"}}


class TestGate(unittest.TestCase):
    def check(self, w, cpu=None, ctx=None, expect_fail=()):
        g = E.evaluate_gate(w, cpu if cpu is not None else [90.0] * len(w), ctx or CTX)
        failed = {k for k, v in g.items() if not v["ok"]}
        self.assertEqual(failed, set(expect_fail), g)

    def test_pass(self):
        self.check(win())

    def test_g1_ac_loss_in_one_sample(self):
        self.check(win(src={30: "Battery Power"}), expect_fail={"G1"})

    def test_g2_pressure_two_in_one_sample(self):
        self.check(win(press={7: 2}), expect_fail={"G2"})

    def test_g3_swap_rise_over_64(self):
        self.check(win(swap={50: 3065.0}), expect_fail={"G3"})
        self.check(win(swap={50: 3064.0}))

    def test_g4_zero_pageouts_is_strict(self):
        """The accepted 10-06 wording is 'no additional pageouts or swapouts': even +1 fails."""
        self.check(win(pageouts={60: 11}), expect_fail={"G4"})
        self.check(win(swapouts={60: 6}), expect_fail={"G4"})
        self.check(win(pageouts={60: 9}), expect_fail={"G4"})  # a decreasing counter is also unusable

    def test_g5_free_below_30(self):
        self.check(win(free={3: 29}), expect_fail={"G5"})

    def test_g6_cpu_window_must_match_gate_window(self):
        self.check(win(), cpu=[90.0] * 60, expect_fail={"G6"})  # 60 CPU samples for 61 gate samples
        self.check(win(), cpu=[69.0] * 61, expect_fail={"G6"})
        g = E.evaluate_gate(win(), None, CTX)
        self.assertFalse(g["G6"]["ok"])

    def test_window_must_be_exactly_61(self):
        g = E.evaluate_gate(win(60), [90.0] * 60, CTX)
        self.assertFalse(g["WINDOW"]["ok"])
        self.assertFalse(E.gate_passed(g))

    def test_attendance_and_state_checks(self):
        c = dict(CTX, attendance=dict(CTX["attendance"], hid_idle_s=200.0))
        self.check(win(), ctx=c, expect_fail={"G10"})
        self.check(win(), ctx=dict(CTX, attended_flag=False), expect_fail={"G10"})
        self.check(win(), ctx=dict(CTX, competing=["123 llama-server"]), expect_fail={"G8"})
        self.check(win(), ctx=dict(CTX, thermal_warning=True), expect_fail={"G7"})
        self.check(win(), ctx=dict(CTX, disk_gib=49.0), expect_fail={"G9"})
        self.check(win(), ctx=dict(CTX, clean_state={"ok": False, "detail": "unresolved"}), expect_fail={"G12"})


def S(up, **kw):
    s = {"wall": 1000.0 + up, "up": up, "press": 1, "src": "AC Power", "swap": 3000.0}
    s.update(kw)
    return s


class TestStopEvaluator(unittest.TestCase):
    def ids(self, samples, base=3000.0):
        ev = E.StopEvaluator()
        ev.set_phase_baseline(base)
        out = []
        for s in samples:
            out += [t["id"] for t in ev.feed(s)]
        return out

    def test_s1_critical_immediately(self):
        self.assertEqual(self.ids([S(0), S(1, press=4)]), ["S1"])

    def test_s2_needs_ten_seconds_and_resets(self):
        self.assertEqual(self.ids([S(i, press=2) for i in range(10)]), [])  # 9 s
        self.assertEqual(self.ids([S(i, press=2) for i in range(11)]), ["S2"])
        mixed = [S(i, press=2) for i in range(8)] + [S(8, press=1)] + [S(i, press=2) for i in range(9, 18)]
        self.assertEqual(self.ids(mixed), [])

    def test_s3_swap_baseline_512_for_10s(self):
        self.assertEqual(self.ids([S(i, swap=3513.0) for i in range(12)]), ["S3"])
        self.assertEqual(self.ids([S(i, swap=3512.0) for i in range(12)]), [])
        self.assertEqual(self.ids([S(i, swap=3513.0) for i in range(9)]), [])

    def test_s4_power_loss(self):
        self.assertEqual(self.ids([S(0), S(1, src="Battery Power")]), ["S4"])

    def test_s5_thermal(self):
        self.assertEqual(self.ids([S(0, thermal_warn=False), S(1, thermal_warn=True)]), ["S5"])

    def test_s6_sampler_gap_and_sleep_skew(self):
        self.assertEqual(self.ids([S(0), S(4)]), ["S6"])
        slept = [S(0), dict(S(1), wall=1001.0 + 40.0)]  # wall clock advanced 40 s, awake clock 1 s
        self.assertEqual(self.ids(slept), ["S6"])
        self.assertEqual(self.ids([S(0), S(1), S(2)]), [])

    def test_s7_rss_cap(self):
        self.assertEqual(self.ids([S(0, rss=5121.0)]), ["S7"])
        self.assertEqual(self.ids([S(0, rss=5120.0)]), [])

    def test_s8_s9_and_actions(self):
        ev = E.StopEvaluator()
        t = ev.feed(S(0, tree=["descendant:1"], egress=["conn:x"]))
        by = {x["id"]: x for x in t}
        self.assertTrue(by["S8"]["immediate"] and by["S8"]["quarantine"])
        self.assertTrue(by["S9"]["immediate"] and by["S9"]["quarantine"])
        self.assertFalse(E.StopEvaluator().feed(S(0, listen_bad=["listen:*:1"]))[0]["quarantine"])

    def test_s11_lifetime_and_disk_s12_attendance(self):
        self.assertEqual(self.ids([S(0, life=601.0)]), ["S11"])
        self.assertEqual(self.ids([S(0, life=600.0)]), [])
        self.assertEqual(self.ids([S(0, disk_gib=49.0)]), ["S11"])
        self.assertEqual(self.ids([S(0, hid_idle_s=480.0, hid_ceiling_s=480.0)]), ["S12"])

    def test_each_stop_fires_once(self):
        self.assertEqual(self.ids([S(0, press=4), S(1, press=4)]), ["S1"])

    def test_limits_are_consistent_with_the_600s_lifetime(self):
        L_ = E.LIMITS
        worst = (L_["readiness_s"] + L_["stage_s"] + 3 * L_["short_s"] + 2 * L_["p2_s"] + 2 * L_["short_s"]
                 + L_["term_s"] + L_["kill_s"] + L_["verify_s"])
        self.assertEqual(worst, 535.0)
        self.assertLessEqual(worst, L_["lifetime_s"])
        self.assertEqual(L_["lifetime_s"], 600.0)
        self.assertLessEqual(L_["p2_s"], 120.0)  # accepted per-request ceiling
        self.assertLessEqual(L_["readiness_s"], 300.0)  # accepted startup ceiling


class TestAuthClassification(unittest.TestCase):
    def test_correct_rejection_is_not_s10(self):
        for klass in ("must", "expected", "public"):
            for cred in ("none", "wrong"):
                o = E.auth_outcome(klass, cred, 401)
                self.assertFalse(o["s10"], (klass, cred))
                self.assertFalse(o["stop"], (klass, cred)) if klass != "public" else None
        self.assertEqual(E.auth_outcome("must", "none", 401)["outcome"], "REJECTED_OK")

    def test_unauthorized_success_on_must_enforce_is_s10(self):
        for cred in ("none", "wrong"):
            o = E.auth_outcome("must", cred, 200)
            self.assertTrue(o["s10"] and o["stop"])

    def test_expected_class_success_is_a_finding_not_a_stop(self):
        o = E.auth_outcome("expected", "none", 200)
        self.assertEqual((o["s10"], o["stop"], o["finding"]), (False, False, "AUTH_NOT_ENFORCED"))

    def test_public_health_is_ok_without_key(self):
        self.assertEqual(E.auth_outcome("public", "none", 200)["outcome"], "PUBLIC_OK")

    def test_unusable_answer_is_indeterminate_not_claimed_unauthorized(self):
        for st in (None, 500, 404, 400):
            o = E.auth_outcome("must", "none", st)
            self.assertEqual(o["outcome"], "INDETERMINATE")
            self.assertTrue(o["stop"] and not o["s10"])

    def test_valid_key_rejected_is_a_configuration_stop_not_s10(self):
        o = E.auth_outcome("must", "correct", 401)
        self.assertTrue(o["stop"] and not o["s10"])
        self.assertEqual(o["outcome"], "VALID_KEY_REJECTED")
        self.assertEqual(E.auth_outcome("must", "correct", 200)["outcome"], "ACCEPTED_OK")


class TestTemplateAndAccounting(unittest.TestCase):
    MSGS = [{"role": "system", "content": "aa"}, {"role": "user", "content": "bb"}]

    def test_structural_checks(self):
        good = "<|im_start|>system\naa<|im_end|>\n<|im_start|>user\nbb<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        r = E.check_template(good, self.MSGS)
        self.assertTrue(r["mandatory_ok"] and r["empty_think_block"])
        no_think = good.replace("<think>\n\n</think>\n\n", "")
        r = E.check_template(no_think, self.MSGS)
        self.assertTrue(r["mandatory_ok"] and not r["empty_think_block"])
        self.assertFalse(E.check_template("bb then aa assistant\n", self.MSGS)["mandatory_ok"])  # order
        self.assertFalse(E.check_template("aa bb", self.MSGS)["mandatory_ok"])  # no assistant prefix

    def test_accounting_labels_do_not_overclaim(self):
        self.assertEqual(E.classify_accounting(50, 50, 51), "ACCOUNTING_CONSISTENT")
        self.assertEqual(E.classify_accounting(51, 50, 51), "ACCOUNTING_EXPLAINED_BOS")
        self.assertEqual(E.classify_accounting(60, 50, 51), "ACCOUNTING_UNEXPLAINED")
        self.assertEqual(E.classify_accounting(None, 50, 51), "ACCOUNTING_UNEXPLAINED")

    def test_stream_parse(self):
        raw = b'data: {"choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3}}\n\ndata: [DONE]\n\n'
        self.assertEqual(E.parse_stream(raw), ("a", "stop", {"prompt_tokens": 3}))


class TestSocketsAndTreePolicy(unittest.TestCase):
    def test_classify_sockets(self):
        self.assertEqual(H.classify_sockets(["127.0.0.1:18080", "127.0.0.1:18080->127.0.0.1:50000"], 18080), ([], []))
        bad, eg = H.classify_sockets(["*:18080", "127.0.0.1:1->8.8.8.8:443"], 18080)
        self.assertTrue(bad and eg)
        self.assertTrue(H.classify_sockets(["0.0.0.0:18080"], 18080)[0])
        self.assertTrue(H.classify_sockets(["127.0.0.1:9999"], 18080)[0])  # wrong port

    def test_tree_policy_never_marks_strangers_killable(self):
        root = {"pid": 10, "start": [1, 1]}
        d = [{"pid": 11, "start": [2, 2]}]
        stranger = {"pid": 99, "start": [9, 9]}
        pol = E.tree_policy(root, d, [stranger], [stranger, dict(d[0])])
        killable = {t["pid"] for t in pol["killable"]}
        self.assertEqual(killable, {10, 11})
        self.assertEqual([s["pid"] for s in pol["strangers"]], [99])
        self.assertTrue(pol["violation"])
        self.assertFalse(E.tree_policy(root, [], [], [dict(root)])["violation"])

    def test_kill_identified_refuses_a_mismatched_start(self):
        p = subprocess.Popen(["/bin/sleep", "30"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        i = L.identity(p.pid)
        wrong = [i["start"][0] - 5, i["start"][1]]
        self.assertEqual(E.kill_identified([{"pid": p.pid, "start": wrong}]), {p.pid: False})
        time.sleep(0.1)
        self.assertIsNone(p.poll())  # still running
        self.assertEqual(E.kill_identified([{"pid": p.pid, "start": i["start"]}]), {p.pid: True})
        p.wait(5)


class TestDenialsAndAttribution(unittest.TestCase):
    LOG = ("2026-10-17 00:59:43.979 E  kernel[0:815df] (Sandbox) Sandbox: llama-server(4242) deny(1) process-fork\n"
           "2026-10-17 00:59:44.000 E  kernel[0:815df] (Sandbox) Sandbox: llama-server(4242) deny(1) process-fork\n"
           "2026-10-17 00:59:45.522 E  kernel[0:76074] (Sandbox) Sandbox: other(4243) deny(1) network-outbound\n"
           "2026-10-17 00:59:46.001 E  kernel[0:76074] (Sandbox) Sandbox: llama-server(4242) deny(1) network-outbound 8.8.8.8\n")

    def test_denial_counts_are_per_pid_operation_only(self):
        cfg = H.Config(E.DEFAULT_BENCH, pins=E.load_pins(), log_runner=lambda c: self.LOG)
        d = H.sandbox_denials(cfg, 4242, time.time() - 5)
        self.assertEqual(d, {"available": True, "ops": {"process-fork": 2, "network-outbound": 1}})
        self.assertNotIn("8.8.8.8", json.dumps(d))  # targets are not retained

    def test_attribution_never_declares_a_sandbox_cause_without_a_deny_line(self):
        self.assertEqual(H.attribute(False, {"available": True, "ops": {}}), "NONE")
        self.assertEqual(H.attribute(True, {"available": True, "ops": {}}), "INCONCLUSIVE_ATTRIBUTION")
        self.assertEqual(H.attribute(True, {"available": False}), "INCONCLUSIVE_ATTRIBUTION")
        self.assertEqual(H.attribute(True, {"available": True, "ops": {"file-read-data": 3}}), "INCONCLUSIVE_ATTRIBUTION")
        self.assertEqual(H.attribute(True, {"available": True, "ops": {"process-fork": 1}}), "FAIL_SANDBOX_CANDIDATE")


class TestRecordsAndAuthorization(Base):
    def rec(self, **kw):
        r = {"run_id": "r1", "state": "INTENT", "tag": "t" * 8}
        r.update(kw)
        return r

    def test_transitions_and_resolution(self):
        rs = E.Records(self.tmp)
        r = rs.create(self.rec())
        self.assertEqual([n for n, _ in rs.unresolved()], ["r1.json"])
        rs.advance(r, "SPAWNED", pid=1, start=[1, 1])
        with self.assertRaises(ValueError):
            rs.advance(r, "INTENT")
        rs.advance(r, "BOUND")
        rs.advance(r, "EXIT_VERIFIED")
        self.assertEqual(rs.unresolved(), [])
        with self.assertRaises(ValueError):
            rs.advance(r, "BOUND")

    def test_quarantine_only_clears_to_exit_verified(self):
        rs = E.Records(self.tmp)
        r = rs.create(self.rec())
        rs.advance(r, "QUARANTINED", reason="x")
        with self.assertRaises(ValueError):
            rs.advance(r, "SPAWNED")
        self.assertTrue(rs.unresolved())

    def test_unreadable_unknown_and_stray_files_are_unresolved(self):
        rs = E.Records(self.tmp)
        with open(os.path.join(rs.dir, "bad.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(rs.dir, "x.json.tmp.123"), "w") as f:
            f.write("{}")
        names = {n for n, _ in rs.unresolved()}
        self.assertEqual(names, {"bad.json", "x.json.tmp.123"})

    def test_authorization_checks(self):
        self.env()
        a = lambda ph=(1, 2, 3, 4), **kw: E.check_authorization(self.cfg.root, list(ph), kw.get("doc", self.spec["doc"]), kw.get("now"))
        self.assertTrue(a()[0])
        self.assertFalse(a(now=time.time() + 7200)[0])  # expired
        with open(self.spec["doc"], "a") as f:
            f.write("edited\n")
        self.assertFalse(a()[0])  # protocol changed after authorization
        os.unlink(os.path.join(self.cfg.root, "AUTHORIZATION.json"))
        self.assertFalse(a()[0])

    def test_authorization_scope_and_phases(self):
        self.env()
        p = os.path.join(self.cfg.root, "AUTHORIZATION.json")
        with open(p) as f:
            d = json.load(f)
        with open(p, "w") as f:
            json.dump(dict(d, phases=[1, 2]), f)
        self.assertFalse(E.check_authorization(self.cfg.root, [1, 2, 3], self.spec["doc"])[0])
        with open(p, "w") as f:
            json.dump(dict(d, scope="optionC"), f)
        self.assertFalse(E.check_authorization(self.cfg.root, [1], self.spec["doc"])[0])

    def test_run_lock_is_exclusive(self):
        with E.run_lock(self.tmp):
            with self.assertRaises(RuntimeError):
                with E.run_lock(self.tmp):
                    pass


class TestNoPromptLiteralsCommitted(unittest.TestCase):
    def test_changed_files_contain_no_approved_fixture_strings(self):
        """Uses the real external fixtures when present; skipped otherwise."""
        try:
            bodies, meta = E.load_fixtures(os.path.join(E.DEFAULT_BENCH, "fixtures", "e2b"), E.load_pins())
        except (E.FixtureError, OSError):
            self.skipTest("external approved fixtures not present")
        files = [os.path.join(HERE, n) for n in ("e2b_lib.py", "e2b_harness.py", "e2b_fake_runtime.py", "test_e2b.py", "e2b_pins.json")]
        files += [p for p in (E.PROTOCOL_DOC,) if os.path.exists(p)]
        self.assertEqual(E.scan_files(files, E.forbidden_strings(bodies, meta)), [])

    def test_sandbox_profile_matches_the_recorded_e2_preflight_profile(self):
        import e2pre_topology_probe as pre
        self.assertEqual((E.SANDBOX, E.SANDBOX_NOFORK), (pre.SANDBOX, pre.SANDBOX_NOFORK))


# --------------------------------------------------------------------------------------------
# synthetic-process tests: normal operation, interruption, cleanup failure, unresolved ownership


class TestNormalOperation(Base):
    def test_full_lifetime_completes_and_resolves_ownership(self):
        self.env("try_fork")
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED", json.dumps(res.get("stops")) + json.dumps(res.get("controls"), default=str)[:600])
        p3 = res["phase3"]
        self.assertTrue(p3["binding_verified"])
        self.assertEqual(len(p3["trials"]), 7)
        self.assertTrue(all(t["status"] == "PASS" for t in p3["trials"]))
        self.assertEqual({t["accounting"] for t in p3["trials"]}, {"ACCOUNTING_CONSISTENT"})
        rec = self.only_record()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertEqual(rec["exit_basis"], "owner_waitpid_and_conjunction")
        self.assertEqual([s["state"] for s in rec["history"]], ["INTENT", "SPAWNED", "BOUND", "EXIT_VERIFIED"])
        self.assertFalse(alive(rec["pid"], rec["start"]))
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(res["shutdown"]["e1_classify"], L.TERMINATED)
        self.assertTrue(res["shutdown"]["term_sent"] and not res["shutdown"]["kill_sent"])

    def test_auth_matrix_correct_rejections_do_not_stop_the_run(self):
        self.env()
        res = self.run_all()
        auth = res["phase3"]["auth"]
        self.assertTrue(any(a["outcome"] == "REJECTED_OK" for a in auth))
        self.assertFalse(any(a["s10"] for a in auth))
        self.assertEqual(next(a for a in auth if a["path"] == "/health" and a["cred"] == "none")["outcome"], "PUBLIC_OK")
        self.assertEqual(res["stops"], [])

    def test_sandbox_is_really_applied_to_the_runtime(self):
        self.env("try_fork")
        res = self.run_all()
        log = open(os.path.join(self.cfg.root, "runs", res["run_id"], "server.log")).read()
        self.assertIn("FORK_DENIED", log)
        self.assertNotIn("FORK_ALLOWED", log)

    def test_rows_and_committed_view_are_prompt_free(self):
        self.env()
        res = self.run_all()
        self.assertEqual(res["rows"]["B4_identity_and_exit"], "SUPPORTS (conditional; 1 lifetime; harness-owned; not reproduced)")
        self.assertEqual(res["rows"]["control_during_generation"], "SUPPORTS")
        self.assertEqual(res["rows"]["finish_reason"], "SUPPORTS")
        self.assertEqual(res["rows"]["input_accounting"], "SUPPORTS (self-consistency only)")
        self.assertEqual(res["rows"]["B3_cancel_disconnect_late_delivery_attempt_registration"], "NOT_TESTED")
        self.assertEqual(res["rows"]["inference_observed"], 7)
        view = json.dumps(H.committed_view(res))
        for s in self.spec["forbidden"]:
            self.assertNotIn(s, view)
        key = open(os.path.join(self.cfg.root, "runs", res["run_id"], "server.log")).read()
        self.assertFalse(os.path.exists(os.path.join(self.cfg.root, "runs", res["run_id"], "scratch", "api-key")))
        self.assertNotIn("api-key", view)

    def test_gate_failure_stops_before_any_process(self):
        self.env()
        probes = StubProbes()
        probes.src = "Battery Power"
        res = self.run_all(probes=probes)
        self.assertEqual(res["outcome"], "GATE_FAILED")
        self.assertFalse(res["gate"]["G1"]["ok"])
        self.assertEqual(os.listdir(self.records().dir), [])

    def test_refusals_without_attended_or_authorization(self):
        self.env()
        self.assertEqual(H.run_all(self.cfg, StubProbes(), 4, False, install_signals=False)["outcome"], "REFUSED")
        os.unlink(os.path.join(self.cfg.root, "AUTHORIZATION.json"))
        self.assertEqual(self.run_all()["outcome"], "REFUSED")

    def test_through_one_and_two_stop_early(self):
        self.env()
        self.assertEqual(self.run_all(through=1)["outcome"], "GATE_PASSED")
        self.assertEqual(os.listdir(self.records().dir), [])
        r2 = self.run_all(through=2)
        self.assertEqual(r2["outcome"], "CONTROLS_PASSED", json.dumps(r2.get("controls"), default=str)[:800])
        self.assertEqual(os.listdir(self.records().dir), [])

    def test_phase2_separates_version_from_metal_verification(self):
        self.env()
        c = H.controls(self.cfg, 1, 1)
        self.assertTrue(c["C3a_version_unconfined"]["ok"] and c["C3b_metal_devices_unconfined"]["ok"])
        self.assertTrue(c["C3a_version_under_profile"]["ok"] and c["C3b_metal_devices_under_profile"]["ok"])
        self.assertIn("no packet transmitted", c["C2_scope"])
        self.assertTrue(c["C2a_udp_connect_nonlocal_denied_under_profile"]["ok"])
        self.assertTrue(c["C2b_udp_connect_nonlocal_allowed_without_profile"]["ok"])
        self.assertTrue(c["C2c_loopback_tcp_allowed_under_profile"]["ok"])
        # the local-interface TCP result is recorded but is not a pass criterion (see controls())
        self.assertNotIn("ok", c.get("C2d_local_interface_tcp_observation", {}))
        bad = H.Config(self.spec["bench"], pins=self.spec["pins"], binary=self.spec["binary"], model=self.spec["model"],
                       version_string="9.9.9-not-this")
        c2 = H.controls(bad, 1, 1)
        self.assertFalse(c2["C3a_version_unconfined"]["ok"])
        self.assertTrue(c2["C3b_metal_devices_unconfined"]["ok"])  # metal result is independent of the version check
        self.assertFalse(c2["passed"])

    def test_launch_restores_signal_mask_and_persists_intent_before_spawn(self):
        self.env()
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "mask", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        seen = {}
        real_popen = subprocess.Popen

        def spy(*a, **k):
            if a and a[0] and a[0][0] == self.spec["binary"]:  # only the runtime spawn, not helper commands
                seen["state_at_spawn"] = rs.read("mask")["state"]
                seen["mask_at_spawn"] = signal.pthread_sigmask(signal.SIG_BLOCK, [])
            return real_popen(*a, **k)
        subprocess.Popen = spy
        try:
            inst.launch({})
        finally:
            subprocess.Popen = real_popen
        self.addCleanup(lambda: reap_all(self.cfg.root))
        self.assertEqual(seen["state_at_spawn"], "INTENT")  # durable intent exists before the process does
        self.assertTrue({signal.SIGINT, signal.SIGTERM, signal.SIGHUP} <= seen["mask_at_spawn"])
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, []), set())
        self.assertEqual(rs.read("mask")["state"], "SPAWNED")
        self.assertEqual(rs.read("mask")["pid"], inst.proc.pid)
        # the child must not inherit the blocked mask: SIGTERM has to work
        out = inst.shutdown()
        self.assertTrue(out["term_sent"] and not out["kill_sent"], out)


class TestStopsAndFailures(Base):
    def test_unauthorized_success_stops_quarantines_and_blocks_new_runs(self):
        self.env("no_auth_chat")
        res = self.run_all()
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertIn("S10", [s["id"] for s in res["stops"]])
        self.assertEqual(res["phase3"].get("trials"), [])
        rec = self.only_record()
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertTrue(rec["owner_review_required"])
        self.assertFalse(alive(rec["pid"], rec["start"]))
        self.assertEqual(self.run_all()["outcome"], "REFUSED_UNRESOLVED")
        rep = E.recover(self.records(), rec["run_id"], E.HostProbes().boottime(), kill=True, confirm=rec["run_id"])
        self.assertEqual(rep["verdict"], "QUARANTINE_OWNER_REVIEW")  # termination evidence does not lift policy quarantine
        self.assertEqual(self.records().read(rec["run_id"])["state"], "QUARANTINED")

    def test_expected_class_not_enforced_is_a_finding_only(self):
        self.env("no_auth_slots")
        res = self.run_all()
        self.assertEqual(res["stops"], [])
        self.assertTrue(any(a["outcome"] == "AUTH_NOT_ENFORCED" and a["path"] == "/slots" for a in res["phase3"]["auth"]))

    def test_template_failure_aborts_before_any_generation(self):
        self.env("wrong_template")
        res = self.run_all()
        self.assertEqual(res["stops"][0]["id"], "TEMPLATE_CHECK_FAILED")
        log = open(os.path.join(self.cfg.root, "runs", res["run_id"], "server.log")).read()
        self.assertNotIn("GEN request", log)
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_unexplained_token_mismatch_is_inconclusive_not_a_runtime_verdict(self):
        self.env("token_mismatch")
        res = self.run_all()
        self.assertEqual({t["accounting"] for t in res["phase3"]["trials"]}, {"ACCOUNTING_UNEXPLAINED"})
        self.assertEqual(res["rows"]["input_accounting"], "INCONCLUSIVE")
        self.assertEqual(res["rows"]["finish_reason"], "SUPPORTS")  # other rows unaffected

    def test_resource_stop_kills_immediately_and_stays_verified(self):
        self.env("slow_chat")
        probes = StubProbes()
        self.when_bound(lambda: setattr(probes, "pressure_v", 4))
        t0 = time.monotonic()
        res = self.run_all(probes=probes)
        self.assertIn("S1", [s["id"] for s in res["stops"]])
        self.assertLess(time.monotonic() - t0, 40)
        self.assertFalse(res["shutdown"]["term_sent"])  # S1 skips SIGTERM
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")
        self.assertEqual(res["rows"]["B4_identity_and_exit"], "INCONCLUSIVE")  # an environmental stop is never SUPPORTS
        self.assertEqual(res["interpretation"], "INTERRUPTED_ENVIRONMENT")

    def test_sleep_event_is_an_environmental_interruption(self):
        self.env("slow_chat")
        probes = StubProbes()
        self.when_bound(lambda: setattr(probes, "sleep_jump", 60.0))
        res = self.run_all(probes=probes)
        self.assertIn("S6", [s["id"] for s in res["stops"]])
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_trial_deadline_is_enforced_independently_of_socket_timeouts(self):
        self.env("slow_chat")
        t0 = time.monotonic()
        port = self.spec["port"]
        # direct client check: a 1 s wall deadline against a server that answers after 100 s
        p = subprocess.Popen([self.spec["binary"], "--port", str(port), "--startup-delay", "0"], stdout=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        for _ in range(50):
            if H.http_call(port, "GET", "/health", deadline=1.0)["status"] == 200:
                break
            time.sleep(0.1)
        r = H.http_call(port, "POST", "/v1/chat/completions", b"{}", None, deadline=1.0)
        self.assertTrue(r["timed_out"])
        self.assertLess(r["elapsed"], 2.0)

    def test_operator_interrupt_shuts_down_and_verifies(self):
        self.env("slow_chat")
        intr = threading.Event()
        self.when_bound(intr.set)
        t0 = time.monotonic()
        res = self.run_all(interrupted=intr)
        self.assertIn("S11", [s["id"] for s in res["stops"]])
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")
        self.assertLess(time.monotonic() - t0, 25)  # the 100 s request is cancelled, not waited out

    def test_readiness_timeout_is_bounded_and_resolved(self):
        self.env("never_ready")
        self.cfg.readiness_s = 3.0
        t0 = time.monotonic()
        res = self.run_all()
        self.assertEqual(res["stops"][0]["id"], "READINESS")
        self.assertLess(time.monotonic() - t0, 60)
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_runtime_that_exits_before_ready_is_resolved_by_owner_reaping(self):
        self.env("die_on_start")
        res = self.run_all()
        self.assertEqual(res["stops"][0]["id"], "READINESS")
        rec = self.only_record()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")  # exit proven by waitpid, although the listener was never bound
        self.assertFalse(rec["binding_verified"])

    def test_spawn_exception_is_recorded_and_resolved_when_nothing_exists(self):
        self.env()
        self.cfg.binary = self.spec["binary"]
        inst = H.Instance(self.cfg, self.records(), "spawnfail", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        self.cfg.binary = os.path.join(self.tmp, "does-not-exist")
        with self.assertRaises(H.StopRun):
            inst.launch({})
        self.assertEqual(self.records().read("spawnfail")["state"], "EXIT_VERIFIED")


class TestTopologyAndUnidentifiedProcesses(Base):
    def spawn_stranger(self, tag, argv):
        p = subprocess.Popen(argv, env={"PATH": "/usr/bin:/bin", E.TAG_ENV: tag}, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def test_s8_kills_identified_tree_but_never_a_tagged_stranger(self):
        self.env("fork_child")
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "topo", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        inst.launch({})
        self.addCleanup(lambda: reap_all(self.cfg.root))
        cancel = threading.Event()
        state, _ = inst.wait_ready(cancel, 15)
        self.assertEqual(state, "READY")
        inst.bind()
        # a non-platform process: the environment of Apple platform binaries (/bin/sleep, /bin/sh) is
        # invisible to KERN_PROCARGS2, so the tag scan cannot see them (recorded as a limitation)
        stranger = self.spawn_stranger(inst.tag, PYSLEEP(60))
        s_id = L.identity(stranger.pid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not [d for d in L.descendants(inst.proc.pid)]:
            time.sleep(0.2)
        obs = inst.observe()
        self.assertTrue(any(t.startswith("descendant:") for t in obs["tree"]))
        self.assertTrue(any(t == f"stranger:{stranger.pid}" for t in obs["tree"]))
        out = inst.shutdown()
        self.assertTrue(alive(stranger.pid, s_id["start"]), "a tagged stranger must never be signalled")
        self.assertEqual([s["pid"] for s in out["strangers_not_signalled"]], [stranger.pid])
        self.assertFalse(out["verified"])  # the stranger carries the tag, so ownership is not proven
        self.assertEqual(self.records().read("topo")["state"], "QUARANTINED")
        self.assertFalse(alive(inst.root["pid"], inst.root["start"]))
        self.assertFalse(out["checks"]["tag_scan_clear"])

    def test_policy_quarantine_requested_by_s8_survives_a_clean_exit(self):
        self.env("fork_child")
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "pol", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        inst.launch({})
        state, _ = inst.wait_ready(threading.Event(), 15)
        inst.bind()
        deadline = time.monotonic() + 10  # let the descendant appear so the snapshot contains it
        while time.monotonic() < deadline and not L.descendants(inst.proc.pid):
            time.sleep(0.2)
        out = inst.shutdown(policy_quarantine="owner review required: S8")
        rec = self.records().read("pol")
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertTrue(rec["owner_review_required"])
        self.assertTrue(out["verified"])


class TestPolicyQuarantineSurvivesUnverifiedExit(Base):
    def test_requested_policy_quarantine_is_kept_when_exit_cannot_be_verified(self):
        self.env("ignore_term")
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "pq", os.path.join(self.tmp, "rd"), wrap=False,
                          kill_fn=lambda targets, sig=signal.SIGKILL: {t["pid"]: False for t in targets})
        os.makedirs(inst.run_dir)
        inst.launch({})
        self.addCleanup(lambda: reap_all(self.cfg.root))
        inst.wait_ready(threading.Event(), 15)
        inst.bind()
        out = inst.shutdown(policy_quarantine="owner review required: S10")
        rec = rs.read("pq")
        self.assertFalse(out["verified"])
        self.assertEqual((rec["state"], rec["owner_review_required"]), ("QUARANTINED", True))
        L.safe_kill(rec["pid"], rec["start"], signal.SIGKILL)  # the process is now really gone
        time.sleep(0.5)
        rep = E.recover(rs, "pq", E.HostProbes().boottime())
        self.assertEqual(rep["verdict"], "QUARANTINE_OWNER_REVIEW")  # termination evidence cannot lift a policy quarantine


class TestInterruptedExecutionAndOwnership(Base):
    def driver(self, mode):
        spec = make_env(self.tmp, mode)
        self.spec, self.cfg = spec, cfg_from(spec)
        proc = subprocess.Popen([sys.executable, "-B", os.path.abspath(__file__), "--driver", json.dumps(
            {k: spec[k] for k in ("bench", "pins", "binary", "model", "port", "doc")})],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return proc

    def wait_state(self, state, limit=60):
        rs = self.records()
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit:
            for n in os.listdir(rs.dir) if os.path.isdir(rs.dir) else []:
                if n.endswith(".json"):
                    try:
                        r = rs.read(n[:-5])
                    except ValueError:
                        continue
                    if r["state"] == state:
                        return r
            time.sleep(0.1)
        self.fail(f"record never reached {state}")

    def test_harness_sigkill_leaves_an_orphan_that_blocks_new_runs_until_admissible_evidence(self):
        proc = self.driver("slow_chat")
        rec = self.wait_state("BOUND")
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
        self.addCleanup(lambda: reap_all(self.cfg.root))
        self.assertTrue(alive(rec["pid"], rec["start"]))  # E1 F3: owner death does not stop the child
        self.assertEqual(self.run_all()["outcome"], "REFUSED_UNRESOLVED")
        boot = E.HostProbes().boottime()
        ro = E.recover(self.records(), rec["run_id"], boot)  # read-only by default
        self.assertEqual(ro["verdict"], L.ALIVE)
        self.assertTrue(alive(rec["pid"], rec["start"]))
        self.assertEqual(self.records().read(rec["run_id"])["state"], "BOUND")
        wrong = E.recover(self.records(), rec["run_id"], boot, kill=True, confirm="not-the-run-id")
        self.assertEqual(wrong["verdict"], L.ALIVE)
        self.assertTrue(alive(rec["pid"], rec["start"]))  # kill requires an exact confirmation
        done = E.recover(self.records(), rec["run_id"], boot, kill=True, confirm=rec["run_id"])
        self.assertEqual(done["verdict"], L.TERMINATED, done)
        self.assertFalse(alive(rec["pid"], rec["start"]))
        self.assertEqual(self.records().read(rec["run_id"])["exit_basis"], "successor_classify")
        self.assertEqual(self.records().unresolved(), [])  # ownership now resolved by admissible evidence

    def test_intent_only_record_is_indeterminate_and_never_cleared_on_the_same_boot(self):
        self.env()
        rs = self.records()
        boot = E.HostProbes().boottime()
        rs.create({"run_id": "win", "state": "INTENT", "tag": "ab" * 16, "boottime": boot,
                   "argv_target": ["/bin/sleep", "60"], "argv_full": ["/usr/bin/sandbox-exec", "-p", "x", "/bin/sleep", "60"]})
        rep = E.recover(rs, "win", boot, kill=True, confirm="win")
        self.assertEqual(rep["verdict"], L.INDETERMINATE)
        self.assertEqual(rs.read("win")["state"], "INTENT")
        self.assertEqual(self.run_all()["outcome"], "REFUSED_UNRESOLVED")

    def test_intent_only_recovery_signals_only_a_tag_and_argv_matched_process(self):
        self.env()
        rs = self.records()
        boot = E.HostProbes().boottime()
        tag = "cd" * 16
        env = {"PATH": "/usr/bin:/bin", E.TAG_ENV: tag}
        match = subprocess.Popen(PYSLEEP(61), env=env, start_new_session=True)
        other = subprocess.Popen(PYSLEEP(62), env=env, start_new_session=True)
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in (match, other)])
        time.sleep(0.5)  # python re-execs itself: take the argv the kernel reports as the intended one
        _, kernel_argv = E.parse_procargs(L.procargs(match.pid))
        rs.create({"run_id": "win2", "state": "INTENT", "tag": tag, "boottime": boot, "argv_target": kernel_argv,
                   "argv_full": ["/usr/bin/sandbox-exec", "-p", "x"] + kernel_argv})
        io, jo = L.identity(match.pid), L.identity(other.pid)
        rep = E.recover(rs, "win2", boot)  # report only
        self.assertEqual({c["pid"]: c["argv_matches_intent"] for c in rep["candidates"]}, {match.pid: True, other.pid: False})
        self.assertTrue(alive(match.pid, io["start"]) and alive(other.pid, jo["start"]))
        rep = E.recover(rs, "win2", boot, kill=True, confirm="win2")
        match.wait(5)
        self.assertTrue(alive(other.pid, jo["start"]), "an unidentified (argv-mismatched) process must never be signalled")
        self.assertEqual(rep["unidentified_not_signalled"], [other.pid])
        self.assertEqual(rep["verdict"], L.INDETERMINATE)  # still not cleared: a tagged process remains
        self.assertEqual(rs.read("win2")["state"], "INTENT")

    def test_changed_boot_time_is_admissible_evidence_for_a_window_record(self):
        self.env()
        rs = self.records()
        rs.create({"run_id": "old", "state": "INTENT", "tag": "ef" * 16, "boottime": [1, 1]})
        rep = E.recover(rs, "old", E.HostProbes().boottime())
        self.assertEqual((rep["verdict"], rep["basis"]), (L.TERMINATED, "boot_time_changed"))
        self.assertEqual(rs.read("old")["state"], "EXIT_VERIFIED")

    def test_spawned_but_never_bound_record_stays_indeterminate(self):
        self.env()
        rs = self.records()
        p = subprocess.Popen(["/bin/sleep", "0.1"])
        i = L.identity(p.pid)
        p.wait()
        r = rs.create({"run_id": "sp", "state": "INTENT", "tag": "01" * 16, "boottime": E.HostProbes().boottime()})
        rs.advance(r, "SPAWNED", pid=p.pid, start=i["start"], pgid=i["pgid"], binding_verified=False, descendants=[])
        rep = E.recover(rs, "sp", E.HostProbes().boottime())
        self.assertEqual(rep["verdict"], L.INDETERMINATE)  # E1 rule: no verified listener binding, absence is not evidence

    def test_cleanup_failure_quarantines_and_blocks_until_real_evidence(self):
        self.env("ignore_term")
        noop = lambda targets, sig=signal.SIGKILL: {t["pid"]: False for t in targets}
        res = self.run_all(kill_fn=noop)
        self.addCleanup(lambda: reap_all(self.cfg.root))
        self.assertEqual(res["outcome"], "QUARANTINED")
        self.assertFalse(res["shutdown"]["verified"])
        rec = self.only_record()
        self.assertEqual(rec["state"], "QUARANTINED")
        self.assertTrue(alive(rec["pid"], rec["start"]))
        self.assertEqual(self.run_all()["outcome"], "REFUSED_UNRESOLVED")
        rep = E.recover(self.records(), rec["run_id"], E.HostProbes().boottime())
        self.assertEqual(rep["verdict"], L.ALIVE)
        self.assertEqual(self.records().read(rec["run_id"])["state"], "QUARANTINED")
        done = E.recover(self.records(), rec["run_id"], E.HostProbes().boottime(), kill=True, confirm=rec["run_id"])
        self.assertEqual(done["verdict"], L.TERMINATED, done)
        self.assertEqual(self.records().read(rec["run_id"])["state"], "EXIT_VERIFIED")

    def test_second_harness_is_refused_by_the_run_lock(self):
        self.env()
        with E.run_lock(self.cfg.root):
            self.assertEqual(self.run_all()["outcome"], "REFUSED")


# --------------------------------------------------------------------------------------------
# regressions for the independent static review (H1-H3, M1-M11)


class TestGateContinuity(unittest.TestCase):
    """M5: the Phase 1 window must be one uninterrupted observation."""

    def failed(self, w):
        g = E.evaluate_gate(w, [90.0] * len(w), CTX)
        return {k for k, v in g.items() if not v["ok"]}

    def test_contiguous_window_passes_with_jitter(self):
        w = win()
        for i in range(1, 61):
            w[i]["wall"] += 0.5 * (i % 2)  # sub-skew jitter
        self.assertEqual(self.failed(w), set())

    def test_sleep_inside_the_window_fails_it(self):
        w = win()
        for i in range(31, 61):
            w[i]["wall"] += 60.0  # wall clock ran on while the awake clock stood still
        self.assertEqual(self.failed(w), {"CONT"})

    def test_sampler_gap_stalled_clock_and_missing_timing_fail_it(self):
        w = win()
        for i in range(31, 61):
            w[i]["wall"] += 10.0
            w[i]["up"] += 10.0
        self.assertEqual(self.failed(w), {"CONT"})
        w = win()
        w[5]["up"] = w[4]["up"]
        self.assertEqual(self.failed(w), {"CONT"})
        w = win()
        del w[3]["wall"]
        self.assertEqual(self.failed(w), {"CONT"})

    def test_gate_rejects_a_window_the_host_slept_through(self):
        probes = StubProbes()
        probes.jump_at = 2
        tmp = tempfile.mkdtemp(prefix="e2b-test-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", tmp]))
        spec = make_env(tmp)
        cfg = cfg_from(spec)
        res = H.run_all(cfg, probes, 1, True, gate_n=3, interval=0.2, top_cmd=TOP4, install_signals=False)
        self.assertEqual(res["outcome"], "GATE_FAILED")
        self.assertEqual({k for k, v in res["gate"].items() if not v["ok"]}, {"CONT"})


class TestStopEvaluatorRemediation(unittest.TestCase):
    def test_s9_quarantine_escalates_and_is_never_downgraded(self):  # M1
        ev = E.StopEvaluator()
        first = ev.feed(S(0, listen_bad=["listen:x"]))
        later = ev.feed(S(1, egress=["conn:y"]))
        self.assertEqual([(t["id"], t["quarantine"]) for t in first + later], [("S9", False), ("S9", True)])
        self.assertEqual(ev.feed(S(2, listen_bad=["listen:x"], egress=["conn:y"])), [])
        ev = E.StopEvaluator()
        self.assertEqual([t["quarantine"] for t in ev.feed(S(0, egress=["conn:y"]))], [True])
        self.assertEqual(ev.feed(S(1, listen_bad=["listen:x"])), [])  # the weaker one adds nothing
        both = E.StopEvaluator().feed(S(0, listen_bad=["listen:x"], egress=["conn:y"]))
        self.assertEqual([(t["id"], t["quarantine"]) for t in both], [("S9", True)])

    def test_s3_is_armed_by_the_constructor_baseline(self):  # H3
        ev = E.StopEvaluator(swap_base=3000.0)
        ids = [t["id"] for i in range(12) for t in ev.feed(S(i, swap=3600.0))]
        self.assertEqual(ids, ["S3"])
        unarmed = E.StopEvaluator()
        self.assertEqual([t["id"] for i in range(12) for t in unarmed.feed(S(i, swap=9000.0))], [])  # no baseline: nothing to compare

    def ids(self, ev, s):
        return [t["id"] for t in ev.feed(s)]

    def test_missing_fast_readings_are_bounded_not_healthy(self):  # M4
        ev = E.StopEvaluator()
        self.assertEqual(self.ids(ev, S(0, press=None)), [])
        self.assertEqual(self.ids(ev, S(1, press=None)), [])
        self.assertEqual(self.ids(ev, S(2)), [])  # a good reading resets the count
        self.assertEqual(self.ids(ev, S(3, swap=None)), [])
        self.assertEqual(self.ids(ev, S(4, swap=None)), [])
        self.assertEqual(self.ids(ev, S(5, swap=None)), ["S13"])
        ev = E.StopEvaluator()
        self.assertEqual([self.ids(ev, S(i, src=None, expect_rss=True, rss=None)) for i in range(3)], [[], [], ["S13"]])

    def test_missing_slow_readings_and_topology_are_bounded(self):  # M4
        good = dict(slow=True, thermal_warn=False, disk_gib=100.0, hid_idle_s=1.0)
        ev = E.StopEvaluator()
        self.assertEqual(self.ids(ev, S(0, **dict(good, disk_gib=None))), [])
        self.assertEqual(self.ids(ev, S(1)), [])  # a fast-only tick neither counts nor resets
        self.assertEqual(self.ids(ev, S(2, **dict(good, disk_gib=None))), ["S13"])
        ev = E.StopEvaluator()
        blind = dict(good, expect_topology=True, observed=False)
        self.assertEqual([self.ids(ev, S(i, **blind)) for i in range(2)], [[], ["S13"]])
        ev = E.StopEvaluator()  # nothing expected (no live runtime): no complaint
        self.assertEqual([self.ids(ev, S(i, **dict(good, observed=False))) for i in range(3)], [[], [], []])
        self.assertEqual(self.ids(E.StopEvaluator(), S(0, **dict(good, hid_idle_s=None))), [])
        ev = E.StopEvaluator()
        self.assertEqual([self.ids(ev, S(i, **dict(good, thermal_warn=None))) for i in range(2)], [[], ["S13"]])


class TestRecordsRemediation(Base):
    def spawned(self, rs, run_id="r1"):
        r = rs.create({"run_id": run_id, "state": "INTENT", "tag": "t" * 8})
        return rs.advance(r, "SPAWNED", pid=1, start=[1, 1])

    def test_owner_review_is_sticky_and_not_cleared_by_this_code(self):
        rs = E.Records(self.tmp)
        r = self.spawned(rs)
        rs.annotate(r, owner_review_required=True, owner_review_reason="S10: x")
        rs.annotate(r, owner_review_required=False)
        self.assertTrue(r["owner_review_required"])
        with self.assertRaises(ValueError):
            rs.advance(r, "EXIT_VERIFIED")
        rs.advance(r, "QUARANTINED", owner_review_required=False)
        self.assertTrue(rs.read("r1")["owner_review_required"])
        with self.assertRaises(ValueError):
            rs.advance(r, "EXIT_VERIFIED")
        self.assertTrue(rs.unresolved())

    def test_failed_write_never_claims_state_but_keeps_the_review_flag(self):
        rs = E.Records(self.tmp)
        r = self.spawned(rs)
        real = E.atomic_write_json

        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        E.atomic_write_json = boom
        try:
            with self.assertRaises(OSError):
                rs.advance(r, "BOUND")
            self.assertEqual(r["state"], "SPAWNED")  # memory never runs ahead of disk
            with self.assertRaises(OSError):
                rs.annotate(r, owner_review_required=True)
            self.assertTrue(r["owner_review_required"])  # the requirement survives in memory
            self.assertNotIn("owner_review_required", rs.read("r1"))
        finally:
            E.atomic_write_json = real
        rs.advance(r, "QUARANTINED", reason="exit not verified")
        on_disk = rs.read("r1")
        self.assertEqual((on_disk["state"], on_disk["owner_review_required"]), ("QUARANTINED", True))

    def test_concurrent_writers_do_not_corrupt_or_collide(self):
        rs = E.Records(self.tmp)
        r = self.spawned(rs)
        errors = []

        def hammer(k):
            try:
                for i in range(40):
                    rs.annotate(r, **{f"f{k}": i})
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))
        ts = [threading.Thread(target=hammer, args=(k,)) for k in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        disk = rs.read("r1")
        self.assertEqual([disk[f"f{k}"] for k in range(8)], [39] * 8)
        self.assertEqual([n for n in os.listdir(rs.dir) if ".tmp." in n], [])


class TestRecoveryRemediation(Base):
    def wait_for_record(self, state, limit=90):
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit:
            for n in os.listdir(self.records().dir) if os.path.isdir(self.records().dir) else []:
                try:
                    r = self.records().read(n[:-5])
                except (OSError, ValueError):
                    continue
                if r["state"] == state:
                    return r
            time.sleep(0.1)
        self.fail(f"no record reached {state}")

    def test_recover_refuses_while_the_run_lock_is_held(self):  # M9
        self.env()
        rs, boot = self.records(), E.HostProbes().boottime()
        rs.create({"run_id": "old", "state": "INTENT", "tag": "ef" * 16, "boottime": [1, 1]})
        with E.run_lock(self.cfg.root):
            rep = E.recover(rs, "old", boot, kill=True, confirm="old")
        self.assertEqual(rep["verdict"], "REFUSED_RUN_LOCK_HELD")
        self.assertEqual(rs.read("old")["state"], "INTENT")  # nothing read-modified
        self.assertEqual(E.recover(rs, "old", boot)["verdict"], L.TERMINATED)  # lock free again

    def test_recovery_cannot_race_a_live_run(self):  # M9
        self.env("slow_chat")
        intr, out = threading.Event(), {}
        th = threading.Thread(target=lambda: out.update(res=self.run_all(interrupted=intr)))
        th.start()
        try:
            rec = self.wait_for_record("BOUND")
            rep = E.recover(self.records(), rec["run_id"], E.HostProbes().boottime(), kill=True, confirm=rec["run_id"])
            self.assertEqual(rep["verdict"], "REFUSED_RUN_LOCK_HELD")
            self.assertTrue(alive(rec["pid"], rec["start"]))  # the healthy runtime was not touched
        finally:
            intr.set()
            th.join(90)
        self.assertEqual(out["res"]["outcome"], "STOPPED")
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_policy_quarantined_record_lets_recover_terminate_identified_orphans(self):  # M3, recovery side
        self.env()
        rs, boot = self.records(), E.HostProbes().boottime()
        code = ("import subprocess,sys,time\n"
                "c=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(120)'])\n"
                "print(c.pid,flush=True)\ntime.sleep(120)\n")
        parent = subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
        child_pid = int(parent.stdout.readline())
        pi, ci = L.identity(parent.pid), L.identity(child_pid)
        self.addCleanup(lambda: (L.safe_kill(child_pid, ci["start"], signal.SIGKILL), parent.kill(), parent.wait()))
        r = rs.create({"run_id": "orph", "state": "INTENT", "tag": "9" * 16, "boottime": boot, "port": self.spec["port"]})
        rs.advance(r, "SPAWNED", pid=parent.pid, start=pi["start"], pgid=pi["pgid"], binding_verified=True, descendants=[ci])
        rs.annotate(r, owner_review_required=True, owner_review_reason="S8: test")
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait()
        self.assertTrue(alive(child_pid, ci["start"]))  # the root died; its child was re-parented and lives on
        ro = E.recover(rs, "orph", boot)
        self.assertEqual(ro["verdict"], "QUARANTINE_OWNER_REVIEW")
        self.assertTrue(alive(child_pid, ci["start"]))  # read-only by default
        rep = E.recover(rs, "orph", boot, kill=True, confirm="orph")
        for _ in range(50):
            if not alive(child_pid, ci["start"]):
                break
            time.sleep(0.1)
        self.assertFalse(alive(child_pid, ci["start"]))
        self.assertEqual(rep["verdict"], "QUARANTINE_OWNER_REVIEW")  # killed, but never released
        now = rs.read("orph")
        self.assertEqual((now["state"], now["owner_review_required"]), ("SPAWNED", True))
        self.assertTrue(rs.unresolved())


class TestArtifactIntegrity(Base):
    def lib(self):
        return os.path.join(self.spec["bench"], "tools", "libfake.dylib")

    def tamper_lib(self):
        raw = open(self.lib(), "rb").read()
        open(self.lib(), "wb").write(b"X" * len(raw))  # same size, different bytes

    def test_tree_pin_detects_changed_extra_missing_and_retargeted_entries(self):  # M6
        self.env()
        d, spec = os.path.join(self.spec["bench"], "tools"), self.spec["pins"]["runtime"]["tree"]
        self.assertTrue(E.verify_tree(d, spec)["ok"])
        raw = open(self.lib(), "rb").read()
        self.tamper_lib()
        self.assertIn("file changed: libfake.dylib", E.verify_tree(d, spec)["problems"])
        open(self.lib(), "wb").write(raw)
        extra = os.path.join(d, "libextra.dylib")
        open(extra, "wb").write(b"x")
        self.assertIn("file unpinned: libextra.dylib", E.verify_tree(d, spec)["problems"])
        os.unlink(extra)
        os.symlink("libfake.dylib", os.path.join(d, "libalias.dylib"))
        self.assertIn("link unpinned: libalias.dylib", E.verify_tree(d, spec)["problems"])
        os.unlink(os.path.join(d, "libalias.dylib"))
        os.unlink(self.lib())
        self.assertIn("file missing: libfake.dylib", E.verify_tree(d, spec)["problems"])
        self.assertFalse(E.verify_tree(d, None)["ok"])  # no pin is a failure, not a pass

    def test_tampered_library_fails_the_gate(self):  # M6
        self.env()
        self.tamper_lib()
        res = self.run_all(through=1)
        self.assertEqual(res["outcome"], "GATE_FAILED")
        self.assertFalse(res["gate"]["G11"]["ok"])

    def after_phase2(self, mutate):
        orig = H.controls

        def wrapped(*a, **k):
            r = orig(*a, **k)
            mutate()
            return r
        self.patch(H, "controls", wrapped)

    def test_library_swapped_between_gate_and_spawn_is_refused(self):  # M6
        self.env()
        self.after_phase2(self.tamper_lib)
        res = self.run_all()
        self.assertEqual(res["outcome"], "ARTIFACT_CHANGED")
        self.assertTrue(res["artifact_integrity"]["gate_check_ok"])
        self.assertFalse(res["artifact_integrity"]["prespawn"]["runtime_tree_ok"])
        self.assertEqual(os.listdir(self.records().dir), [])  # no INTENT, no process

    def test_model_replaced_by_a_same_size_file_is_refused(self):  # M7
        self.env()

        def replace():
            raw = open(self.cfg.model, "rb").read()
            new = self.cfg.model + ".new"
            open(new, "wb").write(b"Q" * len(raw))
            os.replace(new, self.cfg.model)  # same path, same size, different inode
        self.after_phase2(replace)
        res = self.run_all()
        self.assertEqual(res["outcome"], "ARTIFACT_CHANGED")
        self.assertFalse(res["artifact_integrity"]["prespawn"]["model_same_file"])
        self.assertEqual(os.listdir(self.records().dir), [])

    def test_model_rewritten_in_place_is_refused(self):  # M7
        self.env()

        def rewrite():
            with open(self.cfg.model, "r+b") as f:
                f.write(b"Z")
        self.after_phase2(rewrite)
        res = self.run_all()
        self.assertEqual(res["outcome"], "ARTIFACT_CHANGED")
        self.assertFalse(res["artifact_integrity"]["prespawn"]["model_same_file"])

    def test_untouched_artifacts_pass_the_whole_chain(self):
        self.env()
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED")
        self.assertTrue(res["artifact_integrity"]["prespawn"]["ok"])
        self.assertTrue(res["model_unchanged"])


class TestContainmentAfterFailures(Base):
    """H1: an exception after the spawn can never leave an unmanaged runtime or a false EXIT_VERIFIED."""

    def inst(self, name):
        rs = self.records()
        inst = H.Instance(self.cfg, rs, name, os.path.join(self.tmp, "rd-" + name), wrap=False)
        os.makedirs(inst.run_dir)
        self.addCleanup(lambda: reap_all(self.cfg.root))
        return rs, inst

    def test_failed_spawned_write_kills_by_identity_and_resolves_only_on_proof(self):
        self.env()
        rs, inst = self.inst("h1a")
        real = rs.advance

        def failing(rec, state, **kw):
            if state == "SPAWNED":
                raise OSError(28, "No space left on device")
            return real(rec, state, **kw)
        rs.advance = failing
        with self.assertRaises(H.StopRun) as cm:
            inst.launch({})
        self.assertEqual(cm.exception.sid, "LAUNCH")
        self.assertIsNotNone(inst.proc.poll())  # reaped by its owner: dead
        self.assertEqual(L.tag_scan(inst.tag), [])
        rec = rs.read("h1a")
        self.assertEqual((rec["state"], rec["exit_basis"]), ("EXIT_VERIFIED", "owner_waitpid_and_conjunction"))

    def test_when_nothing_can_be_written_the_record_stays_unresolved(self):
        self.env()
        rs, inst = self.inst("h1b")

        def failing(rec, state, **kw):
            raise OSError(28, "No space left on device")
        rs.advance = failing
        with self.assertRaises(H.StopRun):
            inst.launch({})
        self.assertIsNotNone(inst.proc.poll())  # still killed
        self.assertEqual(L.tag_scan(inst.tag), [])
        self.assertEqual(rs.read("h1b")["state"], "INTENT")  # no claim of termination was made
        self.assertEqual([n for n, _ in rs.unresolved()], ["h1b.json"])

    def test_a_failed_final_write_is_not_reported_as_verified(self):
        self.env()
        rs, inst = self.inst("h1d")
        inst.launch({})
        self.assertEqual(inst.wait_ready(threading.Event(), 15)[0], "READY")
        inst.bind()

        def failing(rec, state, **kw):
            raise OSError(5, "I/O error")
        rs.advance = failing
        out = inst.shutdown()
        self.assertFalse(out["verified"])
        self.assertFalse(out["record_written"])
        self.assertTrue(any(e.startswith("record:") for e in out["errors"]))
        self.assertEqual(rs.read("h1d")["state"], "BOUND")  # still unresolved on disk
        self.assertFalse(alive(inst.root["pid"], inst.root["start"]))  # but the process was terminated by identity

    def test_observation_failure_does_not_prevent_termination(self):
        self.env()
        rs, inst = self.inst("h1c")
        inst.launch({})
        self.assertEqual(inst.wait_ready(threading.Event(), 15)[0], "READY")
        inst.bind()

        def boom():
            raise RuntimeError("lsof exploded")
        inst.observe = boom
        out = inst.shutdown()
        self.assertTrue(out["verified"], out)
        self.assertTrue(any("pre-observation" in e for e in out["errors"]))
        self.assertEqual(rs.read("h1c")["state"], "EXIT_VERIFIED")
        self.assertFalse(alive(inst.root["pid"], inst.root["start"]))

    def test_exception_in_phase3_is_contained_and_verified(self):
        self.env()

        def boom(*a, **k):
            raise RuntimeError("synthetic harness bug")
        self.patch(H, "run_phase3", boom)
        res = self.run_all()
        self.assertIn("HARNESS_EXCEPTION", [s["id"] for s in res["stops"]])
        rec = self.only_record()
        self.assertEqual(rec["state"], "EXIT_VERIFIED")
        self.assertFalse(alive(rec["pid"], rec["start"]))
        self.assertEqual(L.tag_scan(rec["tag"]), [])
        self.assertEqual(res["outcome"], "STOPPED")

    def test_failed_verification_is_never_reported_as_termination(self):
        self.env()

        def boom(self_, out, policy):
            raise RuntimeError("verification exploded")
        self.patch(H.Instance, "_finalize", boom)
        res = self.run_all()
        self.addCleanup(lambda: reap_all(self.cfg.root))
        rec = self.only_record()
        self.assertNotEqual(rec["state"], "EXIT_VERIFIED")
        self.assertFalse(res["shutdown"]["verified"])
        self.assertEqual(res["outcome"], "QUARANTINED")
        self.assertFalse(alive(rec["pid"], rec["start"]))  # contained by identity all the same
        self.assertTrue(self.records().unresolved())


class TestOperatorInterrupt(Base):
    """H2: an interrupt is honoured in every phase and can never be followed by a spawn."""

    def no_ownership_created(self, res, outcome="INTERRUPTED"):
        self.assertEqual(res["outcome"], outcome, res.get("why"))
        self.assertEqual(os.listdir(self.records().dir), [])

    def test_before_phase_one(self):
        self.env()
        intr = threading.Event()
        intr.set()
        self.no_ownership_created(self.run_all(interrupted=intr))

    def test_during_phase_one(self):
        self.env()
        intr = threading.Event()

        class P(StubProbes):
            def sample(self_):
                if self_.n == 1:
                    intr.set()
                return super().sample()
        self.no_ownership_created(self.run_all(probes=P(), interrupted=intr))

    def test_during_phase_two(self):
        self.env()
        intr, orig = threading.Event(), H.controls

        def wrapped(*a, **k):
            intr.set()
            return orig(*a, **k)
        self.patch(H, "controls", wrapped)
        res = self.run_all(interrupted=intr)
        self.no_ownership_created(res)
        self.assertTrue(res["controls"]["cancelled"])
        self.assertEqual(res["controls"]["C1_fork_denied_under_profile"]["results"], ["CANCELLED"])  # no further control child was started
        self.assertLess(res["controls"]["elapsed_s"], 3.0)

    def test_during_the_pre_spawn_baseline(self):
        self.env()
        intr = threading.Event()

        class P(StubProbes):
            def swap_mib(self_):
                intr.set()
                return super().swap_mib()
        self.no_ownership_created(self.run_all(probes=P(), interrupted=intr))

    def test_in_the_last_instant_before_the_spawn_nothing_is_spawned(self):
        self.env()
        intr, orig = threading.Event(), E.Records.create

        def create_then_interrupt(self_, rec):
            r = orig(self_, rec)
            intr.set()  # arrives after the INTENT record, before Popen
            return r
        self.patch(E.Records, "create", create_then_interrupt)
        spawned = []
        real_popen = subprocess.Popen

        def spy(*a, **k):
            if a and self.spec["binary"] in a[0] and "--api-key-file" in a[0]:  # the server launch, not Phase 2's --version
                spawned.append(a[0])
            return real_popen(*a, **k)
        self.patch(subprocess, "Popen", spy)
        res = self.run_all(interrupted=intr)
        self.assertEqual(spawned, [])
        self.assertEqual(res["outcome"], "NOT_SPAWNED")
        rec = self.only_record()
        self.assertEqual((rec["state"], rec["exit_basis"]), ("EXIT_VERIFIED", "launch_aborted_before_spawn"))
        self.assertNotIn("pid", rec)
        self.assertEqual(os.path.getsize(os.path.join(self.cfg.root, "runs", res["run_id"], "server.log")), 0)

    def test_during_readiness(self):
        self.env("never_ready")
        self.cfg.readiness_s = 60.0
        intr = threading.Event()
        self.when_state("SPAWNED", intr.set, 0.5)
        t0 = time.monotonic()
        res = self.run_all(interrupted=intr)
        self.assertLess(time.monotonic() - t0, 30)  # not the 60 s readiness limit
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertIn("operator interrupt", res["stops"][0]["why"])
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_during_an_in_flight_request(self):
        self.env("slow_chat")
        intr = threading.Event()
        self.when_bound(intr.set, 4.0)
        t0 = time.monotonic()
        res = self.run_all(interrupted=intr)
        self.assertLess(time.monotonic() - t0, 30)  # the first trial's own limit is 30 s
        self.assertEqual(res["phase3"]["trials"], [])  # a cancelled request is not a trial result
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_a_real_sigterm_reaches_the_handler_and_the_handlers_are_restored(self):
        self.env("slow_chat")
        before = {sg: signal.getsignal(sg) for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}

        def deliver():
            if callable(signal.getsignal(signal.SIGTERM)):  # only while the harness' handler is installed
                os.kill(os.getpid(), signal.SIGTERM)
        self.when_bound(deliver, 4.0)
        t0 = time.monotonic()
        res = self.run_all(install_signals=True)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertIn("operator interrupt", res["stops"][0]["why"])
        self.assertEqual({sg: signal.getsignal(sg) for sg in before}, before)
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")


class TestSwapMonitoring(Base):
    def test_s3_is_armed_during_the_model_load(self):  # H3
        self.env("never_ready")  # the runtime never finishes "loading": everything happens before READY
        self.cfg.readiness_s = 45.0
        probes = StubProbes()
        self.when_state("SPAWNED", lambda: setattr(probes, "swap", probes.swap + 600.0), 0.3)
        t0 = time.monotonic()
        res = self.run_all(probes=probes)
        self.assertIn("S3", [s["id"] for s in res["stops"]])
        self.assertEqual(res["phase3"]["readiness"]["state"], "CANCELLED")  # stopped while still loading
        self.assertEqual(res["swap_baseline"]["median_mib"], 3000.0)  # taken before the spawn, not after the load
        self.assertLess(time.monotonic() - t0, 40)
        series = [json.loads(l) for l in open(os.path.join(self.cfg.root, "runs", res["run_id"], "series.jsonl"))]
        self.assertTrue(any("life" not in x for x in series) and any("life" in x for x in series))  # sampling began pre-spawn
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_unstable_or_unreadable_baseline_refuses_to_spawn(self):
        self.env()
        p = StubProbes()
        p.swap_seq = [3000.0, 3100.0, 3000.0]
        res = self.run_all(probes=p)
        self.assertEqual(res["outcome"], "BASELINE_FAILED")
        self.assertIn("not stable", res["why"])
        p = StubProbes()
        p.swap_seq = [3000.0, None, 3000.0]
        res = self.run_all(probes=p)
        self.assertEqual(res["outcome"], "BASELINE_FAILED")
        self.assertEqual(os.listdir(self.records().dir), [])


class TestMonitorBeforeSpawn(Base):
    def after_phase2(self, mutate):
        orig = H.controls

        def wrapped(*a, **k):
            r = orig(*a, **k)
            mutate()
            return r
        self.patch(H, "controls", wrapped)

    def test_a_host_trigger_before_the_spawn_prevents_it(self):
        self.env()
        probes = StubProbes()
        self.after_phase2(lambda: setattr(probes, "pressure_v", 4))  # critical pressure appears after the gate
        spawned, real_popen = [], subprocess.Popen

        def spy(*a, **k):
            if a and self.spec["binary"] in a[0] and "--api-key-file" in a[0]:  # the server launch, not Phase 2's --version
                spawned.append(a[0])
            return real_popen(*a, **k)
        self.patch(subprocess, "Popen", spy)
        res = self.run_all(probes=probes)
        self.assertEqual(spawned, [])
        self.assertEqual(res["outcome"], "NOT_SPAWNED")
        ids = [s["id"] for s in res["stops"]]
        self.assertIn("S1", ids)
        self.assertIn("PRE_SPAWN_ABORT", ids)
        self.assertEqual(self.only_record()["exit_basis"], "launch_aborted_before_spawn")

    def test_no_spawn_without_a_working_monitor(self):
        self.env()
        probes = StubProbes()
        self.after_phase2(lambda: setattr(probes, "fail_always", True))  # every monitor sample will fail
        res = self.run_all(probes=probes)
        self.assertEqual(res["outcome"], "MONITOR_NOT_READY")
        self.assertEqual(os.listdir(self.records().dir), [])


class TestProbeLossHandling(Base):
    """M4: a safety observation that stays unavailable is never read as healthy."""

    def test_a_crashed_monitor_stops_the_run(self):
        self.env("slow_chat")
        state, orig = {"boom": False}, E.StopEvaluator.feed

        def feed(self_, smp):
            if state["boom"]:
                raise RuntimeError("synthetic monitor bug")
            return orig(self_, smp)
        self.patch(E.StopEvaluator, "feed", feed)
        self.when_bound(lambda: state.update(boom=True), 0.5)
        t0 = time.monotonic()
        res = self.run_all(monitor_interval=0.3)
        s13 = [s for s in res["stops"] if s["id"] == "S13"]
        self.assertTrue(s13 and "monitor" in s13[0]["why"], res["stops"])
        self.assertLess(time.monotonic() - t0, 40)
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_a_monitor_that_fails_on_its_first_tick_prevents_the_spawn(self):
        self.env()

        def feed(self_, smp):
            raise RuntimeError("synthetic monitor bug")
        self.patch(E.StopEvaluator, "feed", feed)
        res = self.run_all()
        self.assertEqual(res["outcome"], "MONITOR_NOT_READY")
        self.assertEqual(os.listdir(self.records().dir), [])

    def run_blind(self, mode="slow_chat", **kw):
        return self.run_all(monitor_interval=0.3, monitor_slow_every=2, **kw)

    def test_sustained_probe_failure_stops_gracefully(self):
        self.env("slow_chat")
        probes = StubProbes()
        self.when_bound(lambda: setattr(probes, "fail_always", True), 0.5)
        res = self.run_blind(probes=probes)
        s13 = [s for s in res["stops"] if s["id"] == "S13"]
        self.assertTrue(s13, res["stops"])
        self.assertFalse(s13[0].get("immediate"))
        self.assertTrue(res["shutdown"]["term_sent"])  # graceful
        self.assertEqual(res["interpretation"], "INTERRUPTED_ENVIRONMENT")
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")
        series = open(os.path.join(self.cfg.root, "runs", res["run_id"], "series.jsonl")).read()
        self.assertIn("probe_error", series)  # the failure is recorded, not skipped

    def test_transient_probe_failure_is_tolerated(self):
        self.env()
        probes = StubProbes()
        self.when_bound(lambda: setattr(probes, "fail_left", 2), 0.5)
        res = self.run_blind(probes=probes)
        self.assertEqual(res["stops"], [], res["stops"])
        self.assertEqual(res["outcome"], "COMPLETED")

    def test_unavailable_or_empty_listener_inventory_is_not_a_healthy_reading(self):
        for answer in (None, []):
            self.env("slow_chat")
            real = H.lsof_names
            self.addCleanup(lambda r=real: setattr(H, "lsof_names", r))
            self.when_bound(lambda a=answer: setattr(H, "lsof_names", lambda pid: a), 0.5)
            res = self.run_blind()
            H.lsof_names = real
            self.assertIn("S13", [s["id"] for s in res["stops"]], (answer, res["stops"]))
            self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")
            subprocess.run(["rm", "-rf", os.path.join(self.tmp, "bench")])  # fresh bench for the next variant


class TestPolicyViolationHandling(Base):
    def test_s8_persists_review_before_shutdown_and_terminates_identified_descendants(self):  # M2 + M3
        self.env("fork_child")
        seen, stop, snap = [], threading.Event(), {}
        orig_kill = H.Instance.emergency_kill

        def spying_kill(self_):
            snap["rec"] = self_.records.read(self_.run_id)  # what is on disk at the instant of the kill
            return orig_kill(self_)
        self.patch(H.Instance, "emergency_kill", spying_kill)

        def watch():
            d = os.path.join(self.cfg.root, "records")
            while not stop.is_set():
                for n in os.listdir(d) if os.path.isdir(d) else []:
                    try:
                        r = json.load(open(os.path.join(d, n)))
                    except (OSError, ValueError):
                        continue
                    if r.get("owner_review_required") and r["state"] in ("SPAWNED", "BOUND"):
                        seen.append(r["state"])
                time.sleep(0.02)
        th = threading.Thread(target=watch, daemon=True)
        th.start()
        try:
            res = self.run_all(wrap=False, monitor_interval=0.3, monitor_slow_every=2)  # unwrapped: the no-fork profile would stop the child
        finally:
            stop.set()
            th.join(5)
        self.assertIn("S8", [s["id"] for s in res["stops"]])
        self.assertTrue(seen, "the review requirement was not durable before the final record write")
        self.assertTrue(snap["rec"].get("owner_review_required"), "the flag was not on disk when the kill was issued")
        self.assertIn(snap["rec"]["state"], ("SPAWNED", "BOUND"))
        rec = self.only_record()
        self.assertEqual((rec["state"], rec["owner_review_required"]), ("QUARANTINED", True))
        self.assertTrue(rec["descendants"])  # the identified child was persisted when first seen
        for d in rec["descendants"]:
            self.assertFalse(alive(d["pid"], d["start"]), d)  # killed after the root, by identity
        self.assertTrue(res["shutdown"]["verified"])  # every fact holds; only policy keeps it quarantined
        self.assertFalse(res["shutdown"]["term_sent"])

    def test_failed_flag_write_still_prevents_a_clean_resolution(self):  # M2 persistence failure
        self.env()
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "pf", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        inst.launch({})
        self.addCleanup(lambda: reap_all(self.cfg.root))
        inst.wait_ready(threading.Event(), 15)
        inst.bind()
        real = E.atomic_write_json

        def boom(*a, **k):
            raise OSError(5, "I/O error")
        E.atomic_write_json = boom
        try:
            self.assertFalse(inst.mark_owner_review("S10: test"))
        finally:
            E.atomic_write_json = real
        self.assertTrue(inst.persist_errors)
        self.assertNotIn("owner_review_required", rs.read("pf"))  # the write really failed
        out = inst.shutdown()  # no policy passed in: the flag lives in the record
        rec = rs.read("pf")
        self.assertEqual((rec["state"], rec["owner_review_required"]), ("QUARANTINED", True))
        self.assertTrue(out["verified"])

    def test_wildcard_listener_is_refused_before_any_credential_is_sent(self):  # M11
        self.env("listen_all")
        res = self.run_all()
        self.assertEqual(res["stops"][0]["id"], "S9")
        self.assertFalse(res["phase3"]["binding_verified"])
        self.assertEqual(res["phase3"]["auth"], [])
        log = open(os.path.join(self.cfg.root, "runs", res["run_id"], "server.log")).read()
        self.assertNotIn("BEARER_SEEN", log)  # no Authorization header ever reached the listener
        self.assertFalse(res["shutdown"]["term_sent"])  # immediate
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_bind_requires_the_exact_loopback_address_and_a_readable_inventory(self):  # M11
        self.env()
        rs = self.records()
        inst = H.Instance(self.cfg, rs, "bd", os.path.join(self.tmp, "rd"), wrap=False)
        os.makedirs(inst.run_dir)
        inst.launch({})
        self.addCleanup(lambda: reap_all(self.cfg.root))
        inst.wait_ready(threading.Event(), 15)
        real = H.lsof_names
        H.lsof_names = lambda pid: None
        try:
            self.assertFalse(inst.bind())
        finally:
            H.lsof_names = real
        self.assertFalse(inst.bind_detail["addr_ok"])
        self.assertEqual(rs.read("bd")["state"], "BOUND")
        self.assertFalse(rs.read("bd")["binding_verified"])


class TestEvidenceIntegrity(Base):
    def test_rows_follow_completed_trials_and_stops(self):  # M8
        import copy
        self.env()
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED")
        self.assertEqual(res["rows"]["row_counts"]["trials_completed"], 7)
        full = H.rows(res)
        self.assertEqual(full["slot_idle_consistency"], "SUPPORTS (consistency only)")

        partial = copy.deepcopy(res)
        partial["phase3"]["trials"] = partial["phase3"]["trials"][:3]
        r = H.rows(partial)
        for row in ("slot_idle_consistency", "input_accounting", "finish_reason"):
            self.assertEqual(r[row], "INCONCLUSIVE", row)
        self.assertEqual(r["row_counts"]["trials_completed"], 3)

        failed = copy.deepcopy(res)
        failed["phase3"]["trials"][2]["status"] = "FAIL_RUNTIME"
        self.assertEqual(H.rows(failed)["input_accounting"], "INCONCLUSIVE")
        self.assertEqual(H.rows(failed)["inference_observed"], 6)

        for stop in ({"id": "S6", "why": "system slept"}, {"id": "S3", "why": "swap"}, {"id": "S11", "why": "operator interrupt"},
                     {"id": "S12", "why": "attendance lapse"}, {"id": "S13", "why": "probe loss"}):
            s = copy.deepcopy(res)
            s["stops"] = [stop]
            self.assertEqual(H.rows(s)["B4_identity_and_exit"], "INCONCLUSIVE", stop)
            self.assertTrue(H.is_environmental(stop), stop)

        noctl = copy.deepcopy(res)
        noctl["phase3"]["trials"][3]["polls"] = [p for p in noctl["phase3"]["trials"][3]["polls"] if p["path"] != "/slots"]
        self.assertEqual(H.rows(noctl)["control_during_generation"], "INCONCLUSIVE")

    def test_version_and_digest_row_is_evidence_based(self):  # M8
        base = {"phase3": {"reported": {"/props": {"build_info": "b11440-1a3011cc0"}, "/v1/models": {"data": [{"id": "m"}]}}},
                "version_tokens": ["11440", "1a3011cc0"], "model_sha256": "ab" * 32}
        self.assertIn("DOES_NOT_SUPPORT (scoped", H.rows(base)["version_artifact_reporting"])
        withdigest = json.loads(json.dumps(base))
        withdigest["phase3"]["reported"]["/v1/models"]["data"][0]["id"] = ("AB" * 32)  # case-insensitive
        self.assertEqual(H.rows(withdigest)["version_artifact_reporting"], "version info present; digest reported")
        noversion = json.loads(json.dumps(base))
        noversion["phase3"]["reported"]["/props"] = {"x": 1}
        self.assertTrue(H.rows(noversion)["version_artifact_reporting"].startswith("INCONCLUSIVE"))
        self.assertEqual(H.rows({"phase3": {"reported": {"/props": {}}}})["version_artifact_reporting"], "INCONCLUSIVE")

    VERDICT_ROWS = ("B4_identity_and_exit", "control_during_generation", "slot_idle_consistency", "finish_reason",
                    "input_accounting", "version_artifact_reporting")

    def assert_no_verdict(self, rows):
        for name in self.VERDICT_ROWS:
            self.assertEqual(rows[name], "INCONCLUSIVE", name)
        self.assertEqual(rows["B3_cancel_disconnect_late_delivery_attempt_registration"], "NOT_TESTED")

    def test_interrupt_after_all_seven_trials_withholds_every_verdict(self):  # D1
        self.env()
        orig = H.run_phase3

        def interrupted_after_trials(*a, **k):
            out = orig(*a, **k)  # all seven trials, the P2 polls and the version queries complete
            raise H.StopRun("S11", "operator interrupt")
        self.patch(H, "run_phase3", interrupted_after_trials)
        res = self.run_all()
        self.assertEqual(res["outcome"], "STOPPED")
        self.assertEqual(res["interpretation"], "INTERRUPTED_ENVIRONMENT")
        self.assertEqual([t["status"] for t in res["phase3"]["trials"]], ["PASS"] * 7)
        self.assert_no_verdict(res["rows"])
        # the observations survive; only the verdicts are withheld
        self.assertEqual(res["rows"]["inference_observed"], 7)
        self.assertEqual(res["rows"]["row_counts"]["trials_completed"], 7)
        self.assertEqual(res["rows"]["row_counts"]["p2_trials"], 2)
        self.assertGreater(res["rows"]["row_counts"]["p2_polls"], 0)
        self.assertEqual(res["rows"]["row_counts"]["verdicts_withheld_by_stops"], ["S11"])
        self.assertTrue(res["phase3"]["reported"]["/props"])
        # without the stop the same observations would have produced the verdicts (the stop is the only cause)
        clean = H.rows(dict(res, stops=[]))
        self.assertEqual(clean["control_during_generation"], "SUPPORTS")
        self.assertEqual(clean["finish_reason"], "SUPPORTS")
        self.assertEqual(clean["slot_idle_consistency"], "SUPPORTS (consistency only)")
        self.assertIn("DOES_NOT_SUPPORT (scoped", clean["version_artifact_reporting"])
        view = json.load(open(os.path.join(self.cfg.root, "runs", res["run_id"], "summary-committed-view.json")))
        self.assertEqual(view["interpretation"], "INTERRUPTED_ENVIRONMENT")
        self.assert_no_verdict(view["rows"])
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_every_kind_of_stop_withholds_every_verdict(self):  # D1
        self.env()
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED")
        for stop in ({"id": "S3", "why": "swap"}, {"id": "S13", "why": "probe loss"}, {"id": "S10", "why": "unauthorized success", "quarantine": True},
                     {"id": "S11", "why": "trial P4 exceeded 30 s"}, {"id": "HARNESS_EXCEPTION", "why": "RuntimeError"},
                     {"id": "TEMPLATE_CHECK_FAILED", "why": "x"}):
            self.assert_no_verdict(H.rows(dict(res, stops=[stop])))

    def test_template_failure_asserts_no_runtime_verdict_after_version_queries(self):  # D1
        self.env("wrong_template")
        res = self.run_all()
        self.assertEqual(res["stops"][0]["id"], "TEMPLATE_CHECK_FAILED")
        self.assertEqual(res["phase3"]["trials"], [])  # no generation was attempted
        # the version queries had succeeded before the abort: without the stop a verdict would have been derived
        self.assertTrue(res["phase3"]["reported"]["/props"] and res["phase3"]["reported"]["/v1/models"])
        self.assertIn("DOES_NOT_SUPPORT", H.rows(dict(res, stops=[]))["version_artifact_reporting"])
        self.assert_no_verdict(res["rows"])
        self.assertEqual(res["rows"]["inference_observed"], 0)
        self.assertEqual(res["rows"]["row_counts"]["verdicts_withheld_by_stops"], ["TEMPLATE_CHECK_FAILED"])
        self.assertNotIn("DOES_NOT_SUPPORT", json.dumps(res["rows"]))
        view = json.load(open(os.path.join(self.cfg.root, "runs", res["run_id"], "summary-committed-view.json")))
        self.assert_no_verdict(view["rows"])
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_completed_run_keeps_its_legitimate_verdicts(self):  # D1 (unchanged behaviour)
        self.env()
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED")
        self.assertEqual(res["stops"], [])
        self.assertIsNone(res.get("interpretation"))
        r = res["rows"]
        self.assertEqual(r["B4_identity_and_exit"], "SUPPORTS (conditional; 1 lifetime; harness-owned; not reproduced)")
        self.assertEqual(r["control_during_generation"], "SUPPORTS")
        self.assertEqual(r["slot_idle_consistency"], "SUPPORTS (consistency only)")
        self.assertEqual(r["finish_reason"], "SUPPORTS")
        self.assertEqual(r["input_accounting"], "SUPPORTS (self-consistency only)")
        self.assertTrue(r["version_artifact_reporting"].startswith("version info present; digest DOES_NOT_SUPPORT (scoped"))
        self.assertEqual(r["B3_cancel_disconnect_late_delivery_attempt_registration"], "NOT_TESTED")
        self.assertEqual(r["inference_observed"], 7)
        self.assertNotIn("verdicts_withheld_by_stops", r["row_counts"])

    def test_failed_trials_are_not_reported_as_completed_and_get_an_attribution_candidate_slot(self):  # M8
        self.env("chat_error")
        res = self.run_all()
        self.assertEqual(res["outcome"], "COMPLETED_WITH_TRIAL_FAILURES")
        self.assertEqual(res["exit_code"], 1)
        self.assertEqual(res["rows"]["inference_observed"], 0)
        self.assertEqual(res["rows"]["input_accounting"], "INCONCLUSIVE")
        self.assertEqual(res["attribution"], "INCONCLUSIVE_ATTRIBUTION")  # not "NONE"
        self.assertEqual(self.only_record()["state"], "EXIT_VERIFIED")

    def test_committed_view_is_bound_to_raw_artifacts_and_tool_identities(self):  # M10
        self.env()
        res = self.run_all()
        run_dir = os.path.join(self.cfg.root, "runs", res["run_id"])
        view = json.load(open(os.path.join(run_dir, "summary-committed-view.json")))
        self.assertEqual(view["raw_artifacts"], res["raw_artifacts"])
        for name in ("events.jsonl", "gate-window.jsonl", "gate-context.json", "series.jsonl", "post-unload.jsonl", "server.log", "summary.json"):
            spec = view["raw_artifacts"][name]
            self.assertEqual(spec["sha256"], E.sha256_file(os.path.join(run_dir, name)), name)
            self.assertEqual(spec["bytes"], os.path.getsize(os.path.join(run_dir, name)))
        ids = view["identities"]
        self.assertEqual(ids["protocol_sha256"], E.sha256_file(self.spec["doc"]))
        self.assertEqual(ids["e2b_harness_py"], E.sha256_file(H.__file__))
        self.assertEqual(ids["e2b_lib_py"], E.sha256_file(E.__file__))
        self.assertEqual(ids["e2b_pins_json"], E.sha256_file(E.PINS_FILE))
        self.assertEqual(ids["pins_in_use_canonical"], E.sha256_bytes(E.canon(self.cfg.pins)))
        self.assertIn("G3", view["gate_measured"])  # measured values, not only booleans
        self.assertIn("competing process(es)", view["gate_measured"]["G8"])
        self.assertEqual(view["ownership"], {"record_state": "EXIT_VERIFIED", "owner_review_required": False, "persist_errors": 0})
        text = json.dumps(view)
        for s in self.spec["forbidden"]:
            self.assertNotIn(s, text)
        tampered = os.path.join(run_dir, "server.log")
        open(tampered, "a").write("x")
        self.assertNotEqual(E.sha256_file(tampered), view["raw_artifacts"]["server.log"]["sha256"])  # detectable

    def test_committed_stop_reasons_never_carry_socket_endpoints(self):
        stop = {"id": "S9", "why": "non-loopback socket: conn:127.0.0.1:5->203.0.113.9:443"}
        self.assertEqual(H.committed_why(stop), "non-loopback socket")
        self.assertEqual(H.committed_why({"id": "S3", "why": "swap > phase baseline + 512 MiB for >= 10 s"}),
                         "swap > phase baseline + 512 MiB for >= 10 s")


def driver_main(spec_json):
    spec = json.loads(spec_json)
    cfg = cfg_from(spec)
    H.run_all(cfg, StubProbes(), 4, True, gate_n=3, interval=0.2, top_cmd=TOP4, post_delay=0, post_sample_s=0, install_signals=False,
              baseline_n=3, baseline_interval=0.1)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--driver":
        driver_main(sys.argv[2])
    else:
        unittest.main(verbosity=2)
