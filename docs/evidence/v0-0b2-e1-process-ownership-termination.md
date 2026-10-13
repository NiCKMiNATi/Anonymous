# Slice 0B-2 E1 — external process ownership and termination evidence (macOS)

**Status:** E1 executed 2026-10-12 on the macOS development host. **Evidence only.** No model was downloaded or loaded, nothing left loopback, no production or `server/`/`client/` code changed, accepted 0B-1 semantics are untouched. E2 and E3 are **not** started and not authorized.
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md) §6 (E1). **Authorization:** owner instruction 2026-10-12 (E1 approved; later model-based evidence needs a separate download authorization).
**Verdict in one line:** a *conditional* B4 (process-exit) basis is feasible on macOS for a **single-process, non-detaching runtime that Anonymous spawned and recorded**; it is **not** feasible, and the classifier correctly stays `INDETERMINATE`, for ambiguous listener bindings, missing records, and unverifiable wrappers; and a **detached, environment-scrubbing descendant spawned after binding is undetectable** by any OS-visible attribute we found, so that residual needs a runtime guarantee or containment, not more cleverness.

## 1. What was run

| Item | Value |
| --- | --- |
| Trials | **772** (S1 50, S2 40, S3 100, S4 80, S5 302, S6 100, S7 100); 20 per variant (S1 wrapper-sh 10; S5 real pid reuse 2). **0 failed checks, 0 harness errors, 0 trials with processes remaining after cleanup**; final audit found no process carrying the run marker. |
| Host | Apple M1 Pro, 16 GiB, macOS 27.0.1 (26A434), Python 3.9.6 (standard library only), user-level, no root |
| Run | 2026-10-12 ~12:03–12:21 UTC; harness marker `e1-f1dc255a90` |
| Subject | A disposable loopback stand-in (`e1_standin.py`). **It is not llama.cpp.** It proves OS and process-control facts only. |
| Raw artifacts | Outside the repository (bench folder, private umask); sanitized copies committed in [v0-0b2-e1/](v0-0b2-e1/): `trials.jsonl` (all 772 trials, every observation and cleanup record), `summary.json`, `llama-probe-no-model.json`, `e0-gate.txt` |
| Scripts | [tools/evidence/runtime/](../../tools/evidence/runtime/): `e1_lib.py` (libproc identity, kqueue, lsof, classifier), `e1_standin.py`, `e1_owner.py`, `e1_harness.py`, `e1_report.py`, `e1_llama_probe.py`. SHA-256 of the versions that produced these results: harness `f0000ccf…59b2`, lib `6190a975…2e4e`, owner `8e389e97…048a`, stand-in `18275a03…2b22`; `e1_report.py` was extended after the run (reporting only) and the probe was written during the run and executed afterwards. Re-run: `python3 -B tools/evidence/runtime/e1_harness.py --out DIR --trials 20 --reuse-real 2`. |

**Deviations and caveats (recorded, not hidden).**
- **E0 gate.** The plan inherited the feasibility experiment's "abort on memory pressure or no AC power" rule. At the gate the Mac was **on battery (70%)** and `kern.memorystatus_vm_pressure_level` was **2 (warning)**; both were unchanged at the end of the run. That rule exists to protect model loads; E1 used a few small processes, so the run proceeded and this is the deviation. Timing numbers below were therefore taken under warning pressure on battery.
- **Two design iterations after a 2-trial smoke run** (smoke data not preserved): (1) `ps -axeww` does not print environments on this macOS, so the tag scan was rebuilt on `KERN_PROCARGS2` (finding F10); (2) the expectation for a descendant that inherits the listening socket was changed after the smoke run showed the listener binding becomes ambiguous (finding F7). Two harness bugs (a consumed kqueue event; argparse swallowing a child flag) were also fixed before the full run. Expectations for all other variants were written before any run and not changed.
- **Ground truth.** "Terminated" is established by a kernel `NOTE_EXIT` event (kqueue) on every real identity, independent of the identity call under test. "Alive" is by construction (the harness had not signalled it). The classifier and harness were written by the same author; independent review was not requested for this task.
- **Reproducibility re-run: partial only.** A second full run was attempted and **could not be completed**: the Mac repeatedly entered sleep/DarkWake on battery (the power log shows it, and it continued under `caffeinate -i`), stalling the harness for 25 s to 15 minutes between trials. Both interrupted re-runs were stopped, swept by marker (one in-flight stand-in killed by verified identity) and are preserved as [rerun-a](v0-0b2-e1/rerun-a-aborted-system-sleep-trials.jsonl) (192 trials: S1, S2, S3 complete, 2 S4) and [rerun-b](v0-0b2-e1/rerun-b-partial-host-sleep-trials.jsonl) (111 trials). In every variant that completed (S1 all, S2 all, S3 all five variants in rerun-a) the pass counts and verdict distributions were **identical to the main run** (e.g. S2 kqueue exit p50 56.6 ms vs 57.2 ms); no failure, error or leak occurred. **S4–S7 (including all of S5, S6, S7) were not reproduced**, and the stall means the elapsed-time statistics from these partial runs are not comparable. **Update 2026-10-13: a clean full re-run completed** (marker `e1-5b43fb4229`, same script hashes, run under `caffeinate -dimsu`, host stayed awake) and is preserved as [rerun-c trials](v0-0b2-e1/rerun-c-clean-full-trials.jsonl) and [summary](v0-0b2-e1/rerun-c-clean-full-summary.json): **772 trials, 0 failed checks, 0 errors, 0 leaks, final marker audit clean, both real pid-reuse trials obtained (99,299 and 99,304 forks)**. The 40 variants have exactly the main run's trial and pass counts and the 16 S5 (variant, verdict) groups are identical, including the designed unsound residuals (F6). S2 kqueue exit p50 59.8 ms, max 64.9 ms (main: 57.2 / 62.0). Total harness time 1033 s versus 1015 s. **Caveats:** the host was still **on battery (~55%)** and at memory-pressure level 2, so the plan's AC-power condition was not met; this establishes reproducibility of verdicts on the same host, build and author, not behavior under AC or normal pressure. The earlier sleep-interrupted partials remain as recorded.
- Same user, same host, loopback, no Windows, no sandbox-restricted environment, no real runtime. One OS build.

## 2. Classification rules under test

`PROVEN_ALIVE` — positive evidence: the recorded (pid, kernel start time) is live, **or** a recorded descendant is live, **or** a live process carries the instance tag, **or** the recorded port answers with the recorded nonce.
`PROVEN_TERMINATED` — requires **all** of: a complete record with a **verified listener binding** (at spawn the listener's pid equalled the recorded pid, uniquely, and the instance reported the same pid and kernel start time); the kernel reports no live process with the recorded (pid, start) (absent, zombie, or a different start time); no recorded descendant alive; no unrecorded live member in the recorded process group; and, in classifier **v2**, no live process carrying the instance tag. Classifier **v1** is the same without the tag scan.
`INDETERMINATE` — everything else. Pid absence, absence of a listener, a missing or foreign nonce answer, or a reused pid are **never sufficient alone**. A foreign listener on the recorded port is neither ownership nor termination evidence (it is only flagged).
Successor classification always ran in a **fresh process that had only the persisted record file**.

## 3. Results for the seven scenarios

| # | Scenario | Trials | Result (all expectations met unless noted) |
| --- | --- | --- | --- |
| **S1** | Process identity | 20 direct, 20 with grandchild, 10 via a shell wrapper | Kernel (pid, start µs) via `proc_pidinfo`: 40/40 tuples distinct, stable over repeated reads, equal to the instance's self-reported start time; listener binding verified 40/40 (sole listener pid == spawned pid). **Wrapper trap detected 10/10**: when the spawned pid is a shell and the listener its child, binding verification fails and the real listener is found only as a descendant. |
| **S2** | Graceful termination observed independently | 20 + 20 | SIGTERM → exit status 0 in 40/40. Three independent observers agree: kqueue exit event (p50 57 ms, max 62 ms), `waitpid`, and post-exit checks (identity gone, no listener, nonce probe `NO_ANSWER`). Successor verdict `TERMINATED` 40/40. **The exited-but-unreaped process is already invisible to `proc_pidinfo` (40/40 `None`)**; exit is observable at the moment of exit only by an observer that was watching (kqueue) or that is the parent. |
| **S3** | SIGTERM→SIGKILL escalation and cleanup | 20 × 5 variants | Ignored SIGTERM: process still live and verdict `ALIVE` after a 0.5 s grace (100/100); SIGKILL reaped in ~1.3 ms with status −9 (100/100). Grandchild in same group: a **main-pid-only SIGKILL leaves the grandchild alive (20/20)**, verdict stays `ALIVE`, then `killpg` → `TERMINATED` (20/20); direct `killpg` removes all (20/20). **Escaped grandchild (own session) survives `killpg` 20/20** and is `ALIVE` until killed by verified identity. Grandchild inheriting the listening socket keeps the port listening after the main process is dead (20/20); after everything is killed the verdict is `INDETERMINATE` 20/20 because the listener binding was ambiguous (two holders) — see F7. |
| **S4** | Child after owner SIGKILL | 20 × 4 variants | **Child survives owner SIGKILL 40/40** (own session and same group alike) and is reparented to pid 1 (40/40); nothing cascades. With an inherited **pipe-EOF watchdog** the child exits 40/40 (also when it ignores SIGTERM), p50 2–4 ms, max 4.2 ms. Successor verdicts matched truth 80/80. |
| **S5** | Successor recovery from the persisted record | 15 variants × 20 + 2 real reuse | See table below. **Unsound verdicts: 0** except the two designed residual cases (F6). |
| **S6** | Listener ownership | 20 × 5 variants | `lsof` port-centric and pid-centric queries agree (100/100 steady-state queries); all 200 port queries took ≤ 46 ms, including under CPU load; after a main-process death with an fd-inheriting descendant the listener is the descendant (20/20) and the port accepts but nobody serves it (`NO_ANSWER` 20/20); after exit a foreign listener appears as a different pid and answers a different nonce (20/20); with `SO_REUSEPORT` both listeners are listed (20/20) but **0 of 240 nonce probes reached ours — all 240 were answered by the other listener**. |
| **S7** | Bounded control and termination | 20 × 5 variants | A **SIGSTOPped process ignores SIGTERM** (alive 0.5 s later 20/20; SIGTERM is delivered only after SIGCONT, ~6 ms) while **SIGKILL ends it in ≤ 6 ms (20/20)**; identity calls ≤ 0.1 ms; with a request in flight, `/identity` is still served (20/20) and SIGTERM exits in ≤ 71 ms; a CPU-spinning child that ignores SIGTERM is gone at 0.506 s total (the 0.5 s grace plus ~6 ms); a probe to a listener nobody serves returns `NO_ANSWER` at 0.50 s (the probe timeout). |

### S5 detail (successor, fresh process, record only)

| Variant (truth) | Trials | v1 (no tag) | v2 (tag) |
| --- | --- | --- | --- |
| Alive after owner death (alive) | 20 | ALIVE 20 | ALIVE 20 |
| Dead, graceful (terminated) | 20 | TERMINATED 20 | TERMINATED 20 |
| Dead, killed after owner death (terminated) | 20 | TERMINATED 20 | TERMINATED 20 |
| **Real pid reuse** (original dead, same pid handed to a new process; start time differs) | **2** | TERMINATED 2 | TERMINATED 2 |
| Simulated pid reuse, original dead (record pid names an unrelated live `sleep`) | 20 | TERMINATED 20 | TERMINATED 20 (unrelated process never signalled, 20/20) |
| Simulated pid reuse, original **alive** (record pid tampered) | 20 | ALIVE 20 | ALIVE 20 |
| Port reused by an unrelated listener, original dead (terminated) | 20 | TERMINATED 20 (foreign listener flagged 20/20) | same |
| SIGSTOPped, unresponsive (alive) | 20 | ALIVE 20 | ALIVE 20 |
| Wrapper pid, binding unverified, truly dead | 20 | **INDETERMINATE 20** | **INDETERMINATE 20** |
| Wrapper pid, real child still alive | 20 | ALIVE 20 | ALIVE 20 |
| Late grandchild, same group, main killed (alive) | 20 | INDETERMINATE 20 | ALIVE 20 |
| Late **escaped** grandchild, tag inherited, main killed (alive) | 20 | **TERMINATED 20 — unsound** | ALIVE 20 |
| Late escaped grandchild, **tag scrubbed**, main killed (alive) | 20 | **TERMINATED 20 — unsound** | **TERMINATED 20 — unsound** |
| Record missing start time, truly dead | 20 | INDETERMINATE 20 | INDETERMINATE 20 |
| Nonce-only record, alive | 20 | ALIVE 20 | ALIVE 20 |
| Nonce-only record, truly dead | 20 | INDETERMINATE 20 | INDETERMINATE 20 |

Real pid reuse took 98,847 and 98,839 forks (~121 s each, ~0.8 k forks/s including per-fork pipe setup) to wrap the pid space; the reused pid was a different process with a different kernel start time, and the unmodified record classified correctly.

## 4. Findings

- **F1 Kernel identity works.** (pid, start time with microseconds) from `proc_pidinfo` is unique and stable (40/40) and distinguishes a *real* reused pid (2/2) and a simulated one (40/40). A pid alone is not an identity.
- **F2 Exit is positively observable only by a watcher.** kqueue `NOTE_EXIT` gives a kernel-issued exit event within ~60 ms of SIGTERM, before the parent reaps. After the fact, a successor can only see *absence* (and an unreaped zombie is already invisible), so successor-side proof must be a conjunction, never absence alone.
- **F3 Owner death does not stop the child.** Children survive owner SIGKILL (40/40) and become orphans of launchd, whether in their own session or the owner's group. An inherited pipe whose write end the owner holds gives immediate, reliable child-side termination (≤ 4.2 ms, 40/40) — **but it needs code in the child (or a shim between owner and runtime)**; an unmodified runtime would not have it.
- **F4 SIGKILL by verified identity is the only unconditional stop.** SIGTERM can be ignored (S3) or left pending on a stopped process (S7); SIGKILL worked in every trial, including stopped and CPU-spinning processes. Killing the main pid alone leaves group members and escaped descendants (S3), so `killpg` is needed and still cannot reach a descendant that changed session.
- **F5 The wrapper-pid trap is real and detectable.** If the recorded pid is a launcher, pid-death says nothing about the listener. Requiring "sole listener pid == recorded pid, and the instance reports the same pid and start time" catches it 10/10 and forces `INDETERMINATE` (S5, 20/20 for the dead case — conservative incompleteness, not unsoundness).
- **F6 Residual unsoundness (designed cases).** A descendant spawned **after** binding, in its own session, is invisible to identity, group and listener checks: classifier v1 declared a live instance `TERMINATED` 20/20. The **inherited environment tag** (finding F10) closes it 20/20 for descendants that keep their environment, but a descendant that scrubs it is `TERMINATED`-misclassified 20/20 by both. No OS-visible attribute we tested recovers it. This is the one place where the classifier is unsound, and it is a property of the *threat model* (a runtime that detaches helpers and scrubs its environment), not a bug.
- **F7 Shared listening sockets break the listener binding.** A descendant holding the listening fd (S3/S6) means two listeners at bind time, so the binding is unverifiable and a truly dead instance stays `INDETERMINATE` (20/20). The port also stays listening (accepts, nobody serves) after the main process dies. "No listener" and "listener present" are both weak evidence.
- **F8 Nonce and port are weak.** A nonce `MATCH` is alive evidence; `NO_ANSWER` (stopped process, no-one-serving listener) and `OTHER` (foreign listener, `SO_REUSEPORT`: 0/240 probes reached ours) prove nothing about the bound instance. Foreign listeners must be flagged, never reinterpreted as ownership.
- **F9 All operations are bounded.** Identity ≤ 0.1 ms; `lsof` ≤ 46 ms in all 200 port queries (including under CPU load); a fresh-process classification p50 51 ms, p95 0.58 s, max 0.61 s (under warning memory pressure on battery); probes bounded by their timeout (0.50 s); SIGKILL → reaped ~1.3 ms. Caveat: `lsof` could not be made to time out here, so its timeout path was not exercised.
- **F10 Tooling finding.** `ps -axeww` does **not** show process environments on macOS 27, `ps eww -p PID` does, and the per-pid `sysctl(KERN_PROCARGS2)` works for same-user processes (not for pid 1 or other users). The tag scan therefore walks `proc_listpids` and reads each same-user process; it is blind to other users' processes.

## 5. B4 evidence feasibility assessment (design §14: "instance and process identity and exit verification")

| Question | Assessment on this Mac |
| --- | --- |
| Can a *watching owner* prove exit? | **Yes.** kqueue `NOTE_EXIT` on the verified identity plus `waitpid` (40/40, ≤ 62 ms). `SUPPORTS`. |
| Can a *successor* prove exit from persisted facts? | **Yes, conditionally.** `PROVEN_TERMINATED` is sound (0 violations) when the record has: a verified exclusive listener binding, the kernel start time, the recorded descendants and process group, and the instance tag; **and** the runtime is single-process or its helpers do not detach and scrub. 0 unsound verdicts in the 262 other S5 trials, and the S2 and S4 verdicts (120 trials) also matched truth. `SUPPORTS (conditional)`. |
| Can pid or port reuse fool it? | **No**, for pid (2 real, 40 simulated) and for port (20): start-time mismatch and flagged foreign listeners. `SUPPORTS`. |
| Where does it stay `INDETERMINATE` (quarantine unchanged)? | Missing or incomplete record (20/20); unverified or ambiguous listener binding, including wrapper pids and fd-sharing descendants (40/40 dead cases); unrecorded live group members without a tag (20/20); nonce-only records (20/20). These must quarantine; E1 found no basis to relax any quarantine rule. |
| What can still be wrong? | A detached, tag-scrubbing descendant spawned after binding (F6). Also anything outside the user's visibility (other users' processes). Not closable by Anonymous-side checks alone. |
| Is "owner is dead, runtime alive" recoverable? | **Yes, by adopt-or-kill with verified identity**: a successor can kill a surviving instance by (pid, start) and then require the same terminated conjunction before releasing the slot. The kill is an action, not evidence; release still needs the proof. |

**Minimum control changes this implies for 0B-2** (recommendations, not decisions; any architectural consequence needs an ADR):
1. **Controller-spawned, persisted record** before the first request: pid, kernel start time, process group/session, verified sole-listener binding, per-instance tag in the environment, recorded descendants — written durably before any invocation.
2. **Owner-death linkage**: a pipe-EOF watchdog (a small supervising shim whose parent is the owner, or runtime support) so owner death implies runtime death; without it an owner crash leaves a live runtime until a successor kills it.
3. **Successor policy**: classify; if `ALIVE`, kill by verified identity (group first, then recorded descendants), then re-classify; release only on the terminated conjunction.
4. **Runtime constraint**: a runtime that spawns detached or env-scrubbing helpers cannot reach B4 here; require single-process (or non-detaching) operation, or treat it as permanently quarantining.
Quarantine rules are **not weakened**: nothing here releases a slot on weaker evidence than 0B-1's B4.

## 6. Observations of the already-acquired llama-server b11440 without a model (kept separate)

[Raw record](v0-0b2-e1/llama-probe-no-model.json). Bounded to 8 s, loopback, `--offline`, empty cache dir, best-effort sandbox profile denying non-loopback outbound (**whether it took effect was not verified**; no external address was contacted to test it). No model was loaded; the router reported "no models found on the system", and the empty cache directory stayed empty.

- Started and stayed up **without a model**: it runs in **router mode** (`/props` reports `"role":"router"`, `max_instances: 4`, models autoload on demand); output states "no models found on the system" and warns that router mode must not be exposed to untrusted environments.
- **Readiness took ~6.7 s** (no listener for the first six seconds).
- **Idle, one process, no descendants**; the spawned pid *was* the sole listener (consistent with `sandbox-exec` exec-ing the target), so the listener binding verified; `/health` returned 200.
- SIGTERM → exit observed in **10.7 ms**, clean shutdown logged; no descendants or tagged processes remained; classified `ALIVE` while running (its environment, carrying our tag, was readable through `KERN_PROCARGS2`) and `TERMINATED` afterwards.
- **Not learned:** whether router mode spawns child processes per model (it does by design), whether they detach, inherit the environment, hold the socket, or survive a router SIGKILL; single-model (`-m`) behavior; anything about generation, cancel, or late delivery.

## 7. Implications for E2 and E3, and recommendations

**E2 (needs the authorized model; not started).**
1. Test **both** launch modes: single-model (`-m`) and router mode. For router mode, trigger a model load and record the child processes it spawns: pids and start times, process group/session, listening sockets, environment tag inheritance, and whether children are reaped or orphaned when the router is SIGTERMed and SIGKILLed. This is the F6 question for the real runtime.
2. Run the same record/classify protocol against the real process; require the sole-listener binding to hold with real children present.
3. Measure `stop`/health/`/props` during generation, request-level cancel and what happens on client disconnect, per-attempt registration, and late output after disconnect (the §14 rows), using the E1 stalled/lost-response techniques on a loopback proxy.
4. Keep the stand-in harness as the control: any divergence between the stand-in and llama-server in the same scenario is a finding.
5. Expect ~7 s startup; handshakes must wait with a bound and treat "not yet listening" as `INDETERMINATE`.

**E3 (crash and recovery; not started).** Owner SIGKILL during real generation under both modes; verify orphan survival and what the router's children do; evaluate adopt-or-kill; confirm no orphan can publish (ADR-0013); repeat across pid reuse.

**Before E2:** the owner should (a) confirm the E1 control-change recommendations in section 5 as the intended direction (or reject the controller-owned option); (b) decide the discrepancy in section 8; (c) separately authorize the model download within the stated cap (1 artifact, ≤ 3 GiB).

## 8. Discoveries needing an owner decision (nothing was changed)

1. **A partial model file exists.** `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01/models/Qwen3-4B-Q4_K_M.gguf.partial`, **1,786,773,504 bytes**, last modified 2026-10-06 22:38. The feasibility evidence says no model bytes were downloaded and `models` was empty. It is unverified, not a usable artifact, and was **not opened, hashed, moved or loaded**. It is ~71.5 % of the 2,497,280,256-byte candidate. Decide whether to resume it, verify it, or delete it; any resumed download needs the separate authorization.
2. **A recovered-authorization record exists** in the bench manifest (`acquisition-authorization.json`): `model_download_byte_ceiling` 12,000,000,000 and `max_model_artifacts` 2, "Recovered explicitly by owner in continuation". The repository evidence says the original cap was unrecoverable. Your 2026-10-12 decision (3 GiB, one artifact, shared) supersedes it prospectively; this is recorded so the history is not lost.
3. The earlier feasibility host gate in that manifest recorded `ac_all: false` and `pass: false`.

## 9. Indeterminate and unproven items (summary)

Indeterminate by design (quarantine): incomplete record; unverified/ambiguous listener binding; wrapper pids; nonce-only records; unrecorded group members without the tag. Unproven: any behavior of a real inference runtime; llama-server router-mode children; Windows (kqueue, libproc, `lsof` and `KERN_PROCARGS2` are macOS-specific); other macOS builds; other users' processes; `lsof` timeout path; sandbox effectiveness; behavior under AC power and normal memory pressure.

## 10. Validation performed

Per-variant expectations asserted in the harness and checked over 772 trials (reproduced in part only, see section 1); failed trials and cleanup outcomes are in `trials.jsonl` (none failed); real pid reuse obtained twice; final marker audit clean; sanitized artifacts grepped for the home path (none); links in this document checked. Not run: the repository test suites (no repository code changed).
