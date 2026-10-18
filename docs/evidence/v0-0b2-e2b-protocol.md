# Slice 0B-2 E2-B — protocol, evidence harness and readiness (macOS)

**Status:** protocol finalized for owner authorization; harness implemented and verified **only against synthetic or simulated runtimes**. The real model has not been loaded, `llama-server` has not been run for E2-B (not even `--version`), and no inference has occurred. E2-B has **not** been executed. Revised on 2026-10-17 after an independent static review (§16); the changes only add checks or stops and relax nothing.
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). **Preceding records:** [E1](v0-0b2-e1-process-ownership-termination.md), [E2 preflight](v0-0b2-e2-preflight-runtime-topology.md), [E2-A](v0-0b2-e2a-model-acquisition.md). **Accepted design:** [LD-04](../design/ld-04-execution-lifecycle.md) §1.3, §6, §14; ADR-0013.
**Harness:** [tools/evidence/runtime/](../../tools/evidence/runtime/) — `e2b_lib.py` (decision logic, records, recovery), `e2b_harness.py` (phases, CLI), `e2b_pins.json` (hashes and versions only), `e2b_fake_runtime.py` and `test_e2b.py` (synthetic runtime and tests).

This document adds checks to accepted criteria and relaxes none. Where a limit is new it is marked *new*; where it is inherited from the [baseline](v0-mac-client-runtime-baseline.md) J1 or the [feasibility record](v0-mac-local-model-runtime-feasibility.md) it is marked *inherited*.

## 1. Scope

One server lifetime, loopback only, `llama-server` b11440 in single-model mode, the pinned verified model, synthetic data. **Excluded** and not implemented: request cancel, client disconnect and late-delivery tests (Option C); any A/B control lifetime; E3 runtime crash recovery; the baseline's J-series throughput workloads. Either excluded item needs its own authorization and its own accounting. The word "Phase 1 gate" in the earlier plan note means the Load Gate of §3.

Phases: **1** Load Gate (host and artifacts); **2** containment controls (no model); **3** one server lifetime with inference; **4** shutdown, verification and a post-unload sample. Phase 3 cannot be separated from its shutdown; `--through 3` skips only the 60 s post-unload sample.

## 2. Authorization binding

The harness refuses to run without `<bench>/e2b/AUTHORIZATION.json` created by the owner. It must name `"scope": "base"`, the authorized `phases`, an `expires_epoch`, and the SHA-256 of **this document** as it stands when execution starts, so any later edit invalidates the authorization. It also requires `--attended`, an exclusive run lock, and no unresolved execution record (§9).

## 3. Phase 1 — Load Gate

A 61-sample window at 1 Hz. Spawn must start within 120 s of the window's end or the gate is repeated (*new*); the pre-spawn steps of §5 are inside that bound. The model, binary and runtime-tree hashes are computed **before** the window starts so that their I/O cannot affect it.

| # | Check | Pass criterion | Origin | Method |
|---|---|---|---|---|
| G1 | AC | 'AC Power' in 61/61 | inherited | `pmset -g batt` |
| G2 | Pressure | level 1 in 61/61 | inherited (10-06 gate) | `sysctl kern.memorystatus_vm_pressure_level` |
| G3 | Swap | no sample more than 64 MiB above the first | new, stricter than S3 | `sysctl vm.swapusage` |
| G4 | Paging | `Pageouts` Δ = 0 **and** `Swapouts` Δ = 0, last sample vs first | inherited, literal ("no additional pageouts or swapouts") | `vm_stat` counters. No tolerance exists |
| G5 | Free memory | ≥ 30% in every sample | new | `memory_pressure -Q` |
| G6 | CPU | exactly 61 usable `top` samples over **the same window**; mean idle ≥ 70%; minimum recorded | new | `top -l 62 -s 1 -n 0` started with the window; the first (since-boot) sample is dropped |
| G7 | Thermal | no warning recorded; fail-closed parse | inherited | `pmset -g therm` |
| G8 | Competing runtimes | no llama, ollama, mlx, `caffeinate` or `sandbox-exec` process | new | `ps` |
| G9 | Disk | ≥ 50 GiB free | inherited | `shutil.disk_usage` |
| G10 | Attendance | `--attended` given **and** operator input ≤ 120 s ago **and** the display-awake assertion held by powerd (§8) | new | `ioreg -c IOHIDSystem` (`HIDIdleTime`), `pmset -g assertions` |
| G11 | Artifacts | model size and SHA-256 equal the pins; `llama-server` SHA-256 equals the pin; **every file and symlink of the extracted runtime directory equals the pinned tree** (42 files, 18 links, no extra, missing or changed entry, including every `lib*.dylib` the launcher loads) | E2-A; tree *new* | streamed SHA-256; `e2b_pins.json` `runtime.tree`, equal member-by-member to the pinned archive |
| G12 | Clean state | no process carrying the tag variable; port 18080 free; **no unresolved execution record** | E1 | `KERN_PROCARGS2`, `lsof`, record store |
| CONT | Window continuity | every consecutive pair of samples obeys the S6 rules: both clocks advance, no gap above 3 s, no wall/awake skew above 2 s (a sleep or DarkWake inside the window fails it) | *new* | `wall` and `CLOCK_UPTIME_RAW` stamps of each sample |

Any failure fails the gate; the gate may be re-run and no tolerance is added.

## 4. Phase 2 — containment controls (no model), budget 80 s

Profile: `SANDBOX_NOFORK` of [e2pre_topology_probe.py](../../tools/evidence/runtime/e2pre_topology_probe.py) (asserted equal by a test). Budget 80 s total so that spawn stays within the 120 s staleness bound (*derived, not a relaxation*).

- **C1 (5+5):** `os.fork()` under the profile fails with `EPERM`; without the fork deny it succeeds.
- **C2, scoped to what can be established without sending a packet (5+5+5+1 informational):**
  - **C2a** an IPv4 **UDP `connect()`** (route lookup only, nothing transmitted) from a sandboxed probe to the RFC 5737 documentation address 192.0.2.1 is denied (`EPERM`);
  - **C2b** the same call without the profile succeeds (the probe and route work);
  - **C2c** a TCP connect to a harness-owned loopback listener under the profile succeeds;
  - **C2d** (informational, not a pass criterion): a TCP connect to this host's own non-loopback address under the profile.
  - **C2 establishes only** that the recorded profile's outbound rule is in effect for an IPv4 UDP `connect()` to a non-local address. It does **not** establish absence of external TCP egress, DNS, IPv6, or any behaviour of `llama-server` itself. During Phase 3, egress is only *observed* (S9, 5 s `lsof` polls, which can miss short-lived sockets).
- **C3, version and Metal are separate checks, each 3× unconfined and 3× under the profile:**
  - **C3a** `llama-server --version` exits 0 and prints the pinned version string (`0.6.0-dev (build 11440, commit 1a3011cc0)`);
  - **C3b** `llama-server --list-devices` exits 0 and its output matches a Metal device pattern. The real output format is unverified; an unmatched format fails closed and is recorded as such.
  - A result differing between unconfined and under-profile is reported as such and is not by itself an attribution.

Any Phase 2 failure ends E2-B as `INCONCLUSIVE` with no server launched. Invocation counts: C1 10, C2 16, C3 12.

## 5. Phase 3 — launch, limits, accounting

```
/usr/bin/sandbox-exec -p "$SANDBOX_NOFORK" llama-server -m <model> --host 127.0.0.1 --port 18080 \
  -c 2048 -np 1 -ngl all -t 6 -b 512 -ub 128 -fit off --perf --no-webui --offline \
  --api-key-file <0600 file> --no-cache-prompt --cache-ram 0 --no-context-shift -to 120 \
  --log-timestamps --chat-template-kwargs '{"enable_thinking":false}'
```

Flags are present in the stored b11440 help; their effect is unverified until read from the log. The environment is an allow-list (`HOME`, `USER`, `LOGNAME`, `TMPDIR`, `LANG`, `LC_ALL`, `__CF_USER_TEXT_ENCODING` if set; fixed `PATH`; an empty `LLAMA_CACHE`; `HF_HUB_OFFLINE=1`; the instance tag). No `LLAMA_ARG_*` or `HF_*` is passed. Whether this allow-list suffices for Metal initialisation is unverified.

| Step | Limit | Worst case |
|---|---|---|
| Readiness (`/health`, unauthenticated) | 120 s | 120 s |
| Stage checks (26 calls × 2 s) | 60 s | 60 s |
| P1 ×3 | 30 s each | 90 s |
| P2 ×2 | 90 s each | 180 s |
| P3, P4 | 30 s each | 60 s |
| Shutdown (10 s TERM, 5 s KILL, 10 s verify) | 25 s | 25 s |
| **Lifetime, monitored (S11)** | **600 s, enforced by the monitor** (§11), measured from when the launch returns (after the process is created and its record is persisted) | **535 s** summed limits, including the 25 s shutdown (plus bookkeeping of roughly 30 s: per-trial `/slots` reads, poller joins, binding). The monitor is stopped before the shutdown starts, so the shutdown is bounded by its own limits, not by S11. |

The 600 s equals the recorder's existing trial observation limit; no accepted ceiling (120 s per request, 5 min startup) is exceeded. A test asserts the worst-case sum of the per-step limits (535 s). **What enforces the 600 s.** Each request and wait has its own wall-clock deadline in the harness, independent of socket timeouts (the recorder's 600 s check is not a hard watchdog, [baseline](v0-mac-client-runtime-baseline.md) §J2). The aggregate 600 s is checked **only by the 1 Hz monitor**, which compares uptime since the spawn mark with the limit on each tick (strictly greater than 600 s fires S11), and only until the harness halts the monitor at the end of Phase 3 or at a stop. There is no second, independent lifetime clock. Consequences: a breach is detected up to one tick (about 1 s) late; the monitored interval ends when the monitor is halted, before the shutdown; and the shutdown that follows an S11 stop adds up to its own 25 s. Spawn to verified exit can therefore reach roughly 626 s in the worst case (derived from the limits, not measured), so the 600 s is a monitor-enforced stop threshold for the runtime's activity, not a hard bound on spawn → verified exit. With the per-step limits summing to 535 s plus about 30 s of bookkeeping, S11 on lifetime is expected not to be the first stop.

**Accounting (base experiment):** 1 lifetime; 7 authorized generation requests (fixtures P1×3, P2×2, P3, P4); 2 unauthenticated chat probes at `max_tokens` 1 that must be rejected before generation (if one generates it is an extra execution, triggers S10, and the hard ceiling is 9); non-generating calls bounded by the time limits; Phase 2 invocations as in §4. Option C: 0. A/B control lifetime: 0.

Order: **pre-spawn** (fixtures; artifact re-verification; swap baseline; staleness; monitor running) → readiness → identity and **exact-address** listener verification → non-chat authentication matrix → template and token checks → chat authentication probes → trials → shutdown.

**Pre-spawn, in this order, nothing spawned until all hold (*new*):**

1. Fixtures verified against the pins (§12).
2. **Artifact re-verification.** The runtime tree is re-hashed and the model must be the very file Phase 1 hashed: size, mtime, inode, ctime and device all equal (a replacement by rename changes the inode; a same-size rewrite changes mtime and ctime; ctime cannot be set by a user). Mismatch → `ARTIFACT_CHANGED`. The interval between this check and the runtime opening the model remains and is accepted (see §16).
3. **Swap baseline for S3**: ten 1 Hz `vm.swapusage` readings taken immediately before the spawn; the baseline is their median. A missing reading, or a spread above the G3 bound (64 MiB), → `BASELINE_FAILED`.
4. Staleness: spawn within 120 s of the end of the Phase 1 window.
5. **The monitor is started before the spawn** and its first tick must have produced every fast reading (pressure, swap, power); otherwise `MONITOR_NOT_READY`. A trigger on any tick before the spawn cancels it (`PRE_SPAWN_ABORT`).
6. Interrupt: an operator interrupt at any earlier point ends the run with nothing spawned. A final check runs inside the launch, after the `INTENT` record is written and with the catchable signals blocked, immediately before `Popen`.

**Binding.** The sole listener must be the recorded pid **and** exactly `127.0.0.1:18080` (one listening socket, nothing else) before any request carrying the key is sent. A wildcard or other-address listener is `S9` (immediate kill); an unreadable listener inventory fails the binding.

## 6. Authentication

| Class | Endpoints | Expected |
|---|---|---|
| Documented public | `GET /health` | 200 without a key |
| **Must enforce** | `POST /v1/chat/completions`, `/tokenize`, `/apply-template` | 401/403 for no or wrong key; 2xx with the key |
| Expected to enforce, undocumented | `GET /props`, `/slots`, `/v1/models` | 401/403 for no or wrong key |

- **S10** fires only for an **unauthorized success** on a must-enforce endpoint. A correct 401/403 rejection is `REJECTED_OK` and never triggers S10.
- A timeout, refusal or any other status for a no-key/wrong-key probe on a must-enforce endpoint is `INDETERMINATE`: the run stops, but unauthorized access is not claimed.
- A 401/403 for the **correct** key is `VALID_KEY_REJECTED`, a harness or key configuration stop, not S10.
- An expected-class endpoint that answers without a key is recorded as `AUTH_NOT_ENFORCED(endpoint)` and the run continues.
- Establishes this build's behaviour for these endpoints with these flags on loopback; **not** OS-level caller restriction ([feasibility record](v0-mac-local-model-runtime-feasibility.md)). The key is ephemeral, passed by file never by argv, deleted afterwards, never logged.

## 7. Template and token accounting (self-consistency only)

- **TT1** `POST /apply-template` for the two message sets (P1 and P2 families). Mandatory: every message content appears verbatim and in order, and the text ends with an assistant generation prefix. Expected (published Qwen3 template, unverified): an empty reasoning block follows the prefix. A miss on either aborts **before any generation** as `TEMPLATE_CHECK_FAILED`: a configuration result with no runtime verdict; choosing another template flag is an owner decision.
- **TT2** `/tokenize` of the rendered prompt with `add_special` false and true (`parse_special` true): N_t and N_t_bos.
- **TT3** `usage.prompt_tokens` N_u per trial (final stream event for P4). **TT4** `timings.cache_n` expected 0.

| Result | Label | Supports |
|---|---|---|
| N_u = N_t | `ACCOUNTING_CONSISTENT` | the server's count equals its own tokenizer applied to its own rendering |
| N_u = N_t_bos ≠ N_t | `ACCOUNTING_EXPLAINED_BOS` | same, with the special-token difference recorded |
| otherwise | `ACCOUNTING_UNEXPLAINED` | row `INCONCLUSIVE`; never `DOES_NOT_SUPPORT`, because the base run cannot isolate the cause |

The best faithful-input verdict is "SUPPORTS (self-consistency only)": all three readings come from one server code path. A model reproducing the label is quality evidence only.

## 8. Attendance and sleep, without power assertions

`caffeinate` and any power assertion are prohibited ([baseline J1](v0-mac-client-runtime-baseline.md)); earlier use during acquisition and E1 stand-ins is a recorded historical deviation not carried forward. Observed timers on this host (AC): display sleep 10 min, system sleep 1 min; while the display is on, powerd holds the idle-sleep assertion, so system sleep follows display sleep by about a minute.

- **Gate (G10):** operator input within the last 120 s (measured, not merely asserted) and the display-awake assertion present.
- **During the run:** `HIDIdleTime` is sampled every 5 s. An advisory is printed at > 300 s without input (nothing synthesises input). **S12** (*new*) stops gracefully when idle time reaches *display-sleep minus 120 s* (480 s on this host), before the display can sleep.
- **Detection of actual sleep (S6):** the awake-time clock (`CLOCK_UPTIME_RAW`) excludes sleep and wall time includes it; a skew above 2 s, or a sampler gap above 3 s, is an environmental interruption.
- The total attended window can exceed 10 minutes in the worst case (gate 61 s + lifetime up to about 626 s including a late-detected S11 stop and its shutdown (§5) + post-sample 60 s), so the operator must give input at least once mid-run; this is stated in the authorization text of §14.

## 9. Execution ownership, interruption and recovery

No successor supervisor exists or is assumed. The harness persists one JSON record per instance under `<bench>/e2b/records/` (atomic write, fsync of file and directory): `INTENT` **before** the spawn (tag, argv, digests, boot time, harness identity), `SPAWNED` immediately after it (kernel pid, start time, pgid, sid), `BOUND` once the sole-listener binding is verified, `EXIT_VERIFIED` only on proof of exit, or `QUARANTINED`.

- **Identity-binding window.** SIGINT, SIGTERM and SIGHUP are blocked from before `Popen` until `SPAWNED` is persisted, and the child starts with an empty mask (a test caught the inherited blocked mask making the runtime ignore SIGTERM). SIGKILL cannot be blocked: an `INTENT`-only record has no pid or start time, so it is **`INDETERMINATE` and is never cleared on the same boot**. A `SPAWNED` record whose listener binding was never verified is likewise `INDETERMINATE` under the E1 classifier.
- **Refusal.** `run` refuses (`REFUSED_UNRESOLVED`) while any record is not `EXIT_VERIFIED`, including unreadable, unknown or stray files (fail closed). An exclusive `flock` prevents a second harness.
- **Recovery is a manual, owner-directed step** (`recover RUN_ID`). It is read-only by default. With `--kill --confirm RUN_ID` it signals only (a) the recorded root and recorded or same-observation descendants, each re-verified by (pid, start) immediately before the signal, or (b) for an `INTENT`-only record, a process that carries the unique tag **and** whose kernel argv equals the intended argv. It never uses process-group signals and never signals an unidentified process.
- **Admissible evidence for clearing a record:** (i) the boot time differs from the recorded one and no tagged process exists; (ii) the E1 `classify()` returns `PROVEN_TERMINATED` for a `SPAWNED`/`BOUND` record; (iii) the harness reaped its own child by `waitpid` and the conjunction of §10 holds. Nothing else clears a record; there is no attestation.
- **Policy quarantine.** A stop that requires owner review (S8 topology, a non-loopback socket, S10) leaves the record `QUARANTINED` with `owner_review_required`, even after a verified exit; `recover` reports `QUARANTINE_OWNER_REVIEW` and never lifts it. Lifting it is outside the harness (the owner archives the record by hand after review and notes it in the ExecPlan).
- **Durability of policy violations (*new*).** The owner-review requirement is written to the record **at detection**, before any slower action (S8, a non-loopback socket, S10), and is **sticky**: it cannot be unset, and a record carrying it is never advanced to `EXIT_VERIFIED` by this code. If that write fails, the requirement stays in the in-memory record so every later write carries it, the failure is counted in the summary, and a clean `EXIT_VERIFIED` is impossible; with every write failing the record simply remains unresolved. A failed write never leaves the in-memory record claiming a state that was not persisted.
- **Descendant identities (*new*).** Every descendant is recorded with its kernel identity when first observed (a root's children are re-parented the moment it dies and can no longer be found by parent pid). `recover --kill --confirm RUN_ID` terminates the recorded root and these descendants (each re-verified by pid and start time) **also for a policy-quarantined record**, so an orphan is not left running; it still never lifts the quarantine.
- **Recovery takes the run lock (*new*).** `recover`, in every mode, holds the exclusive run lock; while a harness holds it, `recover` reports `REFUSED_RUN_LOCK_HELD` and reads or changes nothing, so recovery cannot race a live run or kill a healthy runtime.
- **Failures after the spawn (*new*).** Every exit from the lifetime passes through shutdown; if shutdown itself fails, the harness kills the recorded root and remembered descendants by verified identity (a direct child whose identity could not be read is signalled through its own process handle: its pid cannot be reused while it is unreaped) and then verifies by the same conjunction. A record is `EXIT_VERIFIED` only when the conjunction holds; if verification or the record write fails, the record stays unresolved (and a runtime that could not be killed is `QUARANTINED`). A post-spawn bookkeeping failure (for example the `SPAWNED` write) takes the same path.
- **Not claimed:** this is evidence-harness handling. It is not a design of Anonymous's successor policy (E3 and the 0B-2 implementation own that).

## 10. Shutdown and verification (Phase 4)

SIGTERM by verified identity (skipped for S1, S7, S8, S9), wait 10 s, SIGKILL by verified identity, wait 5 s, reap. An immediate kill first captures the live tree with identities, then kills the root, then every remembered descendant; descendants observed at **any** earlier time (persisted in the record) are killed by identity after the root, also when the root was already killed by the monitor. **Tagged strangers and group members outside the tree are reported, never signalled** and keep the exit unverified. Exit is verified by the conjunction: child reaped; recorded (pid, start) gone; recorded descendants dead; no extra process-group member; no tagged process; port 18080 free (retry up to 10 s). Unverified exit → `QUARANTINED`. Then: sandbox deny lines for the runtime pid (operation names and counts only), model size/mtime unchanged, key file deleted, and a 60 s post-unload sample (Phase 4 only).

## 11. Stop conditions

| ID | Trigger | Action |
|---|---|---|
| S1 | pressure level 4 | SIGKILL immediately (inherited) |
| S2 | level 2 for ≥ 10 s | graceful stop (inherited) |
| S3 | swap > baseline + 512 MiB for ≥ 10 s; baseline = median of ten readings taken just before the spawn (§5); **armed from the first monitor tick, so it covers the model load** | stop (inherited; baseline definition *new*) |
| S4 | AC lost | stop (inherited) |
| S5 | thermal or performance warning (5 s poll) | stop (inherited) |
| S6 | sampler gap > 3 s, or sleep skew > 2 s | stop; `INTERRUPTED_ENVIRONMENT` (*new*) |
| S7 | runtime RSS > 5 GiB | SIGKILL (*new*; ≈1.4–1.7× the expected 3.0–3.6 GiB, 31% of RAM) |
| S8 | any descendant, extra group member or tagged stranger (5 s and each stage) | SIGKILL of the root by recorded identity, then every descendant remembered with its identity; policy quarantine, persisted at detection; **no unidentified process is ever signalled** (*new*) |
| S9 | listener other than 127.0.0.1:18080, a non-loopback socket, or a non-empty cache dir | SIGKILL; a non-loopback socket also quarantines (*new*). Quarantine **escalates**: a later quarantining trigger of the same id is never swallowed by an earlier non-quarantining one |
| S10 | unauthorized **success** on a must-enforce endpoint (§6) | stop; policy quarantine (*new*) |
| S11 | lifetime > 600 s; trial over its limit; disk < 50 GiB; response body > 64 KiB; operator interrupt; harness exception | stop (*new*; disk inherited) |
| S12 | operator idle ≥ display-sleep − 120 s | graceful stop (*new*) |
| S13 | a safety observation stays unavailable: pressure, swap or power for 3 consecutive 1 Hz ticks (the S6 bound); thermal, disk, operator-input or the listener/topology inventory for 2 consecutive 5 s ticks (a runtime's `lsof` answer that is unavailable, or empty after binding, counts as unavailable); also a monitor thread that fails or stops | graceful stop; environmental (*new*) |

A missing reading is never a healthy reading: a single missing reading is tolerated, a sustained loss is S13. An operator interrupt (SIGINT, SIGTERM, SIGHUP) is honoured in every phase: it ends Phase 1, Phase 2 and the baseline, cancels readiness waits and in-flight requests, and can never be followed by a spawn; during shutdown it changes nothing, which always runs to its own bounds.

After a stop there is no retry and no escalation.

## 12. Evidence handling

- **Fixtures** are canonical JSON (sorted keys, compact separators, UTF-8, no trailing newline) kept **outside the repository** in `<bench>/fixtures/e2b/`. The harness verifies each file's exact length and **full** SHA-256 against [e2b_pins.json](../../tools/evidence/runtime/e2b_pins.json), requires the bytes to equal the canonical encoding of what they parse to, and verifies the derived template-request bodies. A mismatch aborts naming only the fixture id. Hashes of the approved set were reproduced on 2026-10-17 from the owner-reviewed values.
- **No prompt literal exists in any committed 0B-2 file.** `scan-committed` greps files for every fixture message and the label token (reporting only an index, never the text); a test applies it to the harness, tests and pins. Because the approved system and example wording is already public in the baseline's J3, the rule is applied to files added or changed by 0B-2 evidence.
- **Raw artifacts** (requests, outputs, rendered prompts, server log, 1 Hz series, sandbox excerpts, profile text) stay outside the repository in `<bench>/e2b/runs/<run>/`. **Committed** evidence is the generated `summary-committed-view.json` class only: ids, byte lengths, hashes, token counts, booleans, timings, verdict labels, exit codes, deny-operation counts, and hashes of raw artifacts. Never committed: prompts, outputs, logs, the key, home paths, the local interface address. The committed view also carries the **measured gate values** (not only pass/fail; the competing-process names stay raw), the **SHA-256 and length of every raw artifact** (`events`, `gate-window`, `gate-context`, `series`, `post-unload`, `server.log`, raw `summary.json`), and the **identities of the tools that produced it**: the SHA-256 of this protocol, `e2b_harness.py`, `e2b_lib.py`, `e1_lib.py`, `e2b_pins.json`, and the canonical hash of the pins in use. The authorization binds to this document's hash only; binding it to the harness hash as well is an owner decision (§16).

## 13. Classification and the LD-04 distinction

Row verdicts are `SUPPORTS`, `DOES_NOT_SUPPORT` or `INCONCLUSIVE`, each with n and lifetime count (ExecPlan §3). **LD-04 register classes and B1–B5 are untouched; every row stays `BLOCKED_BY_RUNTIME_EVIDENCE`.** A completed generation is tagged `INFERENCE_OBSERVED` and supports no LD-04 row by itself.

| Row | Best verdict from the base run | Not established |
|---|---|---|
| B4 identity and exit | "SUPPORTS (conditional; 1 lifetime; harness-owned; not reproduced)" | any Anonymous adapter behaviour |
| Control during generation | `SUPPORTS` if `/health` and `/slots` answered within 2 s at every 0.5 s poll during both P2 runs and `is_processing` was seen true | B5 reliability |
| Slot-idle signal | "SUPPORTS (consistency only)" | B5 qualification |
| `finish_reason` | `SUPPORTS` if P2 reports `stop` and P3 `length` | |
| Input accounting | "SUPPORTS (self-consistency only)" | faithful input |
| Version / artifact reporting | version present; digest absent from `/props` and `/v1/models` → `DOES_NOT_SUPPORT` scoped to those endpoints | |
| B3, cancel, disconnect, late delivery, attempt registration | `NOT_TESTED` | |

**Rows are derived from the trials that actually completed.** Each row carries its counts (`row_counts`: trials expected and completed, P2 trials and polls, observations). B4 is `SUPPORTS` only when **no stop of any kind** occurred, the binding was verified, the exit was verified and the E1 classifier says terminated. Control-during-generation needs both P2 trials to pass, with `/health` and `/slots` polled, answered 200 within 2 s, and `is_processing` seen true in each. Slot-idle and input accounting need all seven trials to pass. `finish_reason` needs both P2 trials `stop` and P3 `length`. Version reporting requires the pinned build number or commit to be found in `/props` or `/v1/models`; the digest `DOES_NOT_SUPPORT` is scoped to the exact 64-hex SHA-256 (case-insensitive) being absent from those two endpoints. A run with failed trials is `COMPLETED_WITH_TRIAL_FAILURES`, never `COMPLETED`, and its attribution is evaluated.

With one lifetime a behavioural `DOES_NOT_SUPPORT` is unreachable (`INCONCLUSIVE` instead). A sandbox cause is `FAIL_SANDBOX_CANDIDATE` only when a `process-fork` or `network-outbound` deny line exists for the runtime pid; without one it is `INCONCLUSIVE_ATTRIBUTION`. Environmental stops (S1–S7, S12, S13, and S11 for an operator interrupt or low disk) set `interpretation: INTERRUPTED_ENVIRONMENT` and make every row `INCONCLUSIVE`. A failure under the no-fork profile is never a universal verdict, and no A/B control is available to isolate it in the base run.

## 14. Authorization text required to run

The owner must (a) place `AUTHORIZATION.json` as in §2 and (b) state, in the task, an explicit start authorization of this form:

> "I authorize executing E2-B Phases 1–4 as specified in `docs/evidence/v0-0b2-e2b-protocol.md` at its current commit hash, base scope only (one server lifetime; seven generation requests; no Option C; no A/B control), with `--attended`. I will be at the machine on AC power for the whole window, will give input at least once mid-run, will not use `caffeinate` or change power settings, and accept that the first load of the verified model runs llama.cpp's GGUF parser on a file from outside. The partial model file and its cap treatment remain untouched and unresolved."

Phases may be authorized separately (`--through 1`, `2`, `3`, `4`).

## 15. Implementation record (2026-10-17)

**Tested (synthetic or simulated only):** pure decision logic (gate, stop conditions, authentication classification, template and accounting classification, parsers, record transitions, authorization, limits arithmetic); synthetic-runtime lifetimes under the **real** `sandbox-exec` profile: normal completion, ownership resolution, interrupt, resource stop (S1), sleep (S6), template abort, token mismatch, unauthorized success (S10) with policy quarantine, readiness timeout, runtime exit before ready, spawn exception, cleanup failure, harness SIGKILL with orphan recovery, `INTENT`-only window records, boot-time evidence, tagged-stranger and unidentified-process non-signalling, exclusive lock. Real-host read-only checks: `host-probe` parsing, fixture verification against the real external files, authorization refusal. Test counts and results are in the handoff of the task that produced this record.

**Not tested:** any invocation of the real `llama-server` or the real model (so the `--list-devices` output format and Metal initialisation under `(deny process-fork)` are unverified); a real 61-sample Phase 1 window through the harness; the allow-listed environment's sufficiency for the real runtime; a real SIGINT/SIGTERM delivered to the harness (the interrupt flag was injected); a real sleep event; the real `log show` deny query against a real denial (parser tested on the observed line format only); behaviour at real memory pressure; recovery's argv match against the real binary's kernel argv (a Python stand-in re-execs itself, so the test takes the kernel-reported argv).

**Discoveries made while implementing (evidence, none changes an accepted decision):**
1. **The recorded profile allows connects to the host's own interface address.** `(deny network-outbound)` alone denies a TCP connect to this host's own LAN address, but the recorded `(allow network-outbound (remote ip "localhost:*"))` permits it (observed: refused, not denied). The earlier-proposed C2 expectation was therefore wrong for the recorded profile; C2 now uses a zero-transmission UDP `connect()` and records the local-interface result only as information.
2. **A blocked signal mask is inherited across `exec`.** Blocking SIGINT/SIGTERM/SIGHUP around the spawn made the child ignore SIGTERM; the child's mask is now reset (tested).
3. **`KERN_PROCARGS2` does not expose the environment of Apple platform binaries** (`/bin/sleep`, `/bin/sh`: argv and ppid visible, environment not), so the E1 tag scan cannot see a descendant that is such a binary. Ppid and process-group checks still can. This sharpens E1's F6 residual; it does not affect a single-process, non-forking `llama-server`.
4. The Python framework stand-in re-execs itself, changing `argv[0]`; recovery's exact argv match is fail-safe (a mismatch means "unidentified, not signalled").

**Limitations that remain:** macOS-specific; same-user visibility only; the pageout/swapout gate may fail repeatedly under background activity and is not relaxed; policy quarantine can only be lifted by hand outside the harness; an `INTENT`-only record can be cleared only by a reboot (admissible evidence) — by design; one author wrote the harness, the tests and this record, and the independent static review that followed (§16) read the code but ran nothing.

## 16. Independent static review and remediation (2026-10-17)

A reviewer read the uncommitted harness without running anything and returned **BLOCKED** (three HIGH, eleven MEDIUM findings). Each finding was re-checked against the code, this protocol and the accepted invariants before it was fixed; none required relaxing an accepted gate or stop. Everything below is verified **against synthetic runtimes only**; nothing here says anything about llama.cpp.

| Finding | Defect | Disposition |
|---|---|---|
| H1 | An exception after the spawn left a live runtime with no kill path; `shutdown` began with a fallible observation | Every exit passes through `shutdown`, which is best-effort around observation and records only what the conjunction proves; `contain` kills by verified identity if shutdown itself fails; post-spawn bookkeeping failures take the same path (§9) |
| H2 | Interrupt flag read only between calls; no check before the spawn; readiness and in-flight requests ran to their own limits | One interrupt ends every phase promptly (§11); final check inside the launch before `Popen`; real SIGTERM delivery tested |
| H3 | S3 had no baseline until after the load, and then took a single post-load reading | Baseline taken before the spawn and the monitor running and verified before it (§5, §11) |
| M1 | A later quarantining S9 trigger was dropped by id-only de-duplication | De-duplication per (id, quarantine) (§11) |
| M2 | Owner-review requirement written only inside `shutdown` | Written at detection; sticky; failure-tolerant (§9) |
| M3 | An immediate kill left identified descendants alive; `recover --kill` refused for policy quarantine | Descendants remembered with identity and persisted; killed after the root; `recover --kill` terminates them without lifting quarantine (§9, §10) |
| M4 | Missing readings treated as healthy | S13 (§11) |
| M5 | Window contiguity unchecked | Gate row CONT (§3) |
| M6 | Only the 49,984-byte launcher was pinned | The whole extracted runtime tree is pinned and checked at Phase 1 and again before the spawn (§3, §5) |
| M7 | Model replacement window | Identity tuple compared across Phase 1, the spawn and the end of the run (§5) |
| M8 | Row, outcome and attribution overclaims | Rows derived from completed trials with counts (§13) |
| M9 | `recover` ignored the run lock | `recover` takes it (§9) |
| M10 | Committed view not tied to raw artifacts or tools | Raw-artifact hashes, measured gate values and tool identities (§12) |
| M11 | Listener address unchecked before the key was sent | Exact `127.0.0.1:18080` required first (§5) |

**D1 — verdicts surviving a stop (found after the remediation above; corrected the same day).** *Defect:* row verdicts other than B4 were derived from the observations alone. A stop that arrived after the observations they need had completed left `SUPPORTS` or `DOES_NOT_SUPPORT` in the rows of a stopped run: an operator interrupt after all seven trials, or a `TEMPLATE_CHECK_FAILED` abort after the version queries had answered (no generation attempted, yet the version row could still read `DOES_NOT_SUPPORT`). That contradicted the rule that a stopped run leaves no runtime-evidence verdict (§11, §13). *Correction:* `rows()` in `e2b_harness.py` now sets all six verdict rows (B4, control during generation, slot idle, `finish_reason`, input accounting, version/artifact reporting) to `INCONCLUSIVE` whenever **any** stop is recorded, whatever its kind (environmental, policy, template or configuration abort, trial limit, harness exception), and lists the stop ids in `row_counts.verdicts_withheld_by_stops`. The observations are kept as observed: `inference_observed`, the trial and poll counts, and the reported fields; B3 stays `NOT_TESTED`. §13's sentence on environmental stops is a subset of this rule. A completed run with no stop is unchanged. *Regression tests* (`TestEvidenceIntegrity`, each marked `# D1`):

1. `test_interrupt_after_all_seven_trials_withholds_every_verdict` — all seven trials pass, then an S11 interrupt; every verdict row is `INCONCLUSIVE`, the seven observations and the poll counts survive, the same data without the stop would have produced the verdicts, and the committed view carries the same withheld rows.
2. `test_every_kind_of_stop_withholds_every_verdict` — S3, S13, S10 (quarantining), S11, `HARNESS_EXCEPTION` and `TEMPLATE_CHECK_FAILED` applied to an otherwise complete run.
3. `test_template_failure_asserts_no_runtime_verdict_after_version_queries` — a template abort after successful version queries, no generation, no `DOES_NOT_SUPPORT` anywhere in the rows or the committed view.
4. `test_completed_run_keeps_its_legitimate_verdicts` — a stop-free run keeps every legitimate verdict and gains no `verdicts_withheld_by_stops`.

The test file now defines 137 tests (133 + these four). The results in the verification paragraph below are those of the 133-test run; they predate D1 and are synthetic only.

**Accepted residuals, flagged for owner decision before real inference:**

1. **Model replaced after the pre-spawn check.** The check is a stat identity, not a content hash, and the runtime opens the file some milliseconds to seconds later. Closing it fully would need either a re-hash immediately before the spawn (2.5 GB of reads between the gate and the load, and the window would remain) or passing a verified file descriptor, which is unverified for this runtime. Decision needed: accept, or authorize a re-hash.
2. **Runtime libraries are checked by content at Phase 1 and before the spawn, not at load time**, and macOS code-signature validity is not examined. The same window exists for them.
3. **Authorization binds to this document's hash only.** The harness, pins and library hashes are recorded in every committed view but not enforced at start. Decision needed: bind `AUTHORIZATION.json` to the harness hash as well, or accept the record-only identity.
4. **S13 thresholds** (3 fast ticks, 2 slow ticks) and the **ten-sample swap baseline** with its 64 MiB stability bound are new values. They only stop earlier or refuse; a real host that fails them repeatedly is a finding, not a reason to relax them silently.
5. **A crash during a record write leaves a `*.tmp.*` file.** It blocks new runs, as does any unreadable file in `records/`, and `recover` cannot take it (it needs a run id). The owner inspects and removes it by hand.
6. **The 600 s lifetime is checked only by the 1 Hz monitor, and only until it is halted before the 25 s shutdown**; the shutdown is bounded by its own limits, so spawn → verified exit can reach roughly 626 s (§5).
7. Unchanged and speculative, not fixed: `kern.boottime` could shift on a wall-clock step (mitigated by the empty tag scan only for processes whose environment is visible); G10 checks the system-wide idle-sleep assertion, not specifically powerd's; `/apply-template` may omit the generation prompt or ignore the kwargs (fails safe as `TEMPLATE_CHECK_FAILED`); the real `lsof` listener format is assumed to match the synthetic and E1/E2-preflight observations.

**Verification of the remediation (synthetic only, 2026-10-17, Mac dev host).** `python3 -B test_e2b.py`: **133 tests, all pass** (81 before; 52 added, one per confirmed defect plus failure-mode variants), about 286 s. Targeted regressions include a real SIGTERM delivered to the harness, a halted-write and a crashed-verification path after the spawn, interrupts at six different points (none followed by a spawn), S3 firing while the synthetic runtime was still "loading", a sleep inside the gate window, and `recover` refused while a live run holds the lock. **Mutation check:** each of 25 re-introduced defects (on a throwaway copy) was caught by at least one targeted test; one initially survived (a failed final write reported as verified) and led to an added test. Static: byte-compile, `-X dev -W error` import, no unused imports or undefined names; `scan-committed` over the seven changed files found no fixture text; the external fixtures still verify against the pins. No process, bench record or temporary directory was left behind. These tests establish the harness's own logic against a synthetic runtime; they say nothing about llama.cpp.

**Not tested, as before:** the real `llama-server` and model, a real 61-sample window through the harness, behaviour at real memory pressure, the real `log show` deny query against a real denial, a real sleep event.
