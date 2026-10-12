#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. Aggregate E1 raw trials into sanitized tables.

Run: python3 -B e1_report.py RUN_DIR [--sanitized-out FILE.jsonl]
Prints per-variant counts, failed checks, verdict distributions, soundness counts and timing
statistics. The sanitized output keeps every trial (including failures) but drops absolute
paths and the per-trial record file names."""

import json
import statistics
import sys
from collections import Counter, defaultdict


def stats(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"n": len(xs), "min": round(xs[0], 4), "p50": round(statistics.median(xs), 4),
            "p95": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 4), "max": round(xs[-1], 4)}


def main():
    run = sys.argv[1]
    rows = [json.loads(l) for l in open(run + "/trials.jsonl")]
    by = defaultdict(list)
    for r in rows:
        by[(r["scenario"], r["variant"])].append(r)
    print(f"total trials: {len(rows)}; ok: {sum(r['ok'] for r in rows)}; "
          f"errors: {sum(1 for r in rows if r['error'])}; trials with leaks after cleanup: {sum(r['leak'] for r in rows)}")
    leaked_expected = Counter()
    for r in rows:
        if r["cleanup"]["leaked_after_trial"] or r["cleanup"]["swept_unrecorded"]:
            leaked_expected[(r["scenario"], r["variant"])] += 1
    print()
    print("| Scenario / variant | trials | checks passed | verdicts v1 (no tag) | verdicts v2 (tag) | unsound v1 / v2 | survivors reaped by harness cleanup |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for (sid, var), rs in sorted(by.items()):
        v1, v2 = Counter(), Counter()
        for r in rs:
            o = r["obs"]
            for key, c in (("verdict_v1", v1), ("verdict_v2", v2)):
                if o.get(key):
                    c[o[key].replace("PROVEN_", "")] += 1
        u1 = sum(1 for r in rs if r["obs"].get("unsound_v1"))
        u2 = sum(1 for r in rs if r["obs"].get("unsound_v2"))
        failed = Counter()
        for r in rs:
            for c, v in r["checks"].items():
                if not v:
                    failed[c] += 1
        sv = leaked_expected.get((sid, var), 0)
        print(f"| {sid} {var} | {len(rs)} | {sum(r['ok'] for r in rs)}/{len(rs)}"
              + (f" (failed: {dict(failed)})" if failed else "") + f" | {dict(v1) or '-'} | {dict(v2) or '-'} | {u1} / {u2} | {sv} |")
    print()
    timing = {
        "S2 SIGTERM->kqueue exit (s)": [r["obs"].get("t_kqueue_exit_s") for r in rows if r["scenario"] == "S2"],
        "S3 SIGKILL->reaped (s)": [r["obs"].get("t_sigkill_to_reap_s") for r in rows if r["scenario"] == "S3"],
        "S4 watchdog child exit after owner SIGKILL (s)": [r["obs"].get("child_exit_after_owner_sigkill_s") for r in rows if r["scenario"] == "S4" and "watchdog" in r["variant"]],
        "S5 classify call, fresh process (s)": [r["obs"].get("classify_seconds") for r in rows if r["scenario"] == "S5"],
        "S6 lsof port query (s)": [x for r in rows if r["scenario"] == "S6" for x in (r["obs"].get("port_query_seconds") or r["obs"].get("lsof_seconds") or [])],
        "S6 identity() call max per trial (s)": [r["obs"].get("identity_call_max_s") for r in rows if r["scenario"] == "S6"],
        "S7 SIGKILL of stopped process -> exit (s)": [r["obs"].get("sigkill_exit_s") for r in rows if r["scenario"] == "S7"],
        "S7 escalation total, CPU-spinning child (s)": [r["obs"].get("total_escalation_s") for r in rows if r["scenario"] == "S7"],
        "S7 SIGTERM exit with request in flight (s)": [r["obs"].get("sigterm_exit_s") for r in rows if r["scenario"] == "S7"],
        "S7 probe with nobody serving (s)": [r["obs"].get("probe_seconds") for r in rows if r["scenario"] == "S7" and r["variant"].startswith("probe")],
    }
    print("| Timing | n | min | p50 | p95 | max |")
    print("| --- | --- | --- | --- | --- | --- |")
    for k, xs in timing.items():
        s = stats(xs)
        if s:
            print(f"| {k} | {s['n']} | {s['min']} | {s['p50']} | {s['p95']} | {s['max']} |")
    print()
    tuples = [tuple(r["obs"]["tuple"]) for r in rows if r["scenario"] == "S1" and r["obs"].get("tuple")]
    print(f"S1 identity tuples: {len(tuples)} observed, {len(set(tuples))} distinct")
    print("S2 identity between exit notification and reap:", Counter(r["obs"].get("identity_between_exit_and_reap") for r in rows if r["scenario"] == "S2"))
    print("S4 reparent ppid after owner death:", Counter(r["obs"].get("child_ppid_after_owner_death") for r in rows if r["scenario"] == "S4"))
    rp = [r for r in rows if r["variant"] == "pid-reuse-real"]
    for r in rp:
        print("pid-reuse-real:", {k: r["obs"].get(k) for k in ("forks", "seconds", "reused", "original_confirmed_dead", "reused_identity_start_differs", "verdict_v1", "verdict_v2")}, "ok", r["ok"])
    probes = [(r["obs"].get("probe_match_count"), r["obs"].get("probe_other_count")) for r in rows if r["variant"] == "reuseport-two-listeners"]
    print("S6 reuseport MATCH/OTHER per 12 probes per trial:", Counter(probes))
    print("S6 reuseport lsof lists both:", Counter(r["checks"].get("lsof_lists_both") for r in rows if r["variant"] == "reuseport-two-listeners"))
    print("S7 stopped: SIGTERM pending (alive 0.5s later):", Counter(r["obs"].get("alive_0_5s_after_sigterm") for r in rows if r["variant"] == "sigstopped-sigterm-pending"))
    print("S5 foreign-listener flagged:", Counter(r["obs"].get("foreign_listener_flag") for r in rows if r["variant"] == "port-reuse-foreign-listener"))
    print("S4 owner-group: child pgid == owner pgid:", Counter(r["obs"].get("child_pgid_equals_owner_pgid") for r in rows if r["scenario"] == "S4"))

    print()
    print("DETAIL")
    def cnt(sel, key):
        return dict(Counter(json.dumps(r["obs"].get(key)) for r in rows if sel(r)))
    for var in ("plain", "gc-same-pid-kill", "gc-same-group-kill", "gc-escaped", "gc-inherit-listener"):
        sel = lambda r, v=var: r["scenario"] == "S3" and r["variant"] == v
        print(f"S3 {var}: alive after ignored SIGTERM {cnt(sel,'alive_after_sigterm_grace')}; verdict_v2 after ignored SIGTERM {cnt(sel,'verdict_after_sigterm_v2')}; "
              f"returncode {cnt(sel,'returncode')}; verdict v1/v2 after main SIGKILL {cnt(sel,'verdict_after_kill_v1')}/{cnt(sel,'verdict_after_kill_v2')}; "
              f"descendant survivors after main kill {cnt(sel,'descendant_survivors_after_main_kill')}; verdict_v2 after group kill {cnt(sel,'verdict_after_group_kill_v2')}; "
              f"escaped survives group kill {cnt(sel,'escaped_descendant_survives_group_kill')}; binding_verified {cnt(sel,'binding_verified_at_record')}")
    for var in ("direct", "with-grandchild", "wrapper-sh"):
        sel = lambda r, v=var: r["scenario"] == "S1" and r["variant"] == v
        print(f"S1 {var}: binding_verified {cnt(sel,'binding_verified')}; wrapper_detected {cnt(sel,'wrapper_detected')}")
    for var in ("plain", "with-grandchild"):
        sel = lambda r, v=var: r["scenario"] == "S2" and r["variant"] == v
        print(f"S2 {var}: returncode {cnt(sel,'returncode')}; probe_after {cnt(sel,'probe_after')}; listeners_after {dict(Counter(str(r['obs'].get('listeners_after')) for r in rows if sel(r)))}")
    for var in ("own-session", "owner-group", "watchdog-pipe", "watchdog-ignores-sigterm"):
        sel = lambda r, v=var: r["scenario"] == "S4" and r["variant"] == v
        print(f"S4 {var}: child survived 1.5s {cnt(sel,'child_survived_1_5s')}; ppid {cnt(sel,'child_ppid_after_owner_death')}; "
              f"exit latency {stats([r['obs'].get('child_exit_after_owner_sigkill_s') for r in rows if sel(r)])}")
    for var in ("steady-state", "listener-persists-after-owner-process-death", "foreign-listener-after-exit", "reuseport-two-listeners", "queries-under-cpu-load"):
        sel = lambda r, v=var: r["scenario"] == "S6" and r["variant"] == v
        print(f"S6 {var}: failed checks {dict(Counter(c for r in rows if sel(r) for c, v2 in r['checks'].items() if not v2))}; probe {cnt(sel,'probe')}")
    print("failed/errored trials:", [(r['scenario'], r['variant'], r['trial'], r['error']) for r in rows if not r['ok']])
    if len(sys.argv) > 3 and sys.argv[2] == "--sanitized-out":
        with open(sys.argv[3], "w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str, sort_keys=True).replace(run, "<run>") + "\n")


if __name__ == "__main__":
    main()
