# Slice 0B-2 — runtime-evidence plan (Mac development host)

## 1. Title, status, and purpose

**Status: ACTIVE — E1 executed 2026-10-12 (owner-authorized); E2 and E3 NOT authorized and not started.** The owner approved E1 only: no model download or loading, loopback only, synthetic data. Model-based evidence (E2/E3) needs a separate authorization with the download cap; the owner's proposed cap is 3 GiB for one official Qwen3-4B-Q4_K_M GGUF artifact shared with the feasibility experiment, **not yet an authorization to download**. E1 evidence: [report](../../docs/evidence/v0-0b2-e1-process-ownership-termination.md).

**Problem.** Slice 0B-1 is closed against a *scripted, in-process* runtime. Every release basis that matters for a real runtime (B3 terminal result from the bound instance, B4 verified process exit, B5 instance-reported end, `late_delivery_excluded`) has no real producer, and the design says so ([LD-04 design §14](../../docs/design/ld-04-execution-lifecycle.md) rows `BLOCKED_BY_RUNTIME_EVIDENCE`). Until measured, an external runtime that cannot be shown to have stopped keeps the single slot quarantined (O1, ratified).

**Outcome wanted.** A small set of *measured, reproducible evidence records* on the Mac development host that say, per design §14 row, whether a real external runtime can supply the evidence, and whether Anonymous can own the runtime process well enough to produce B4. The outcome is knowledge and an informed 0B-2 implementation plan, not a feature.

## 2. Repository context

Exists: closed 0B-1 (scripted/in-process; `ModelPort` split `prepare/start/await_result/stop/probe`, binding with `lifetime_scope`, evidence bases B1–B5, arbiter, handoff gate, guard-based B4 only for `owning_process` bindings); ADR-0013/0014 Accepted for 0B-1 scope; design §14 evidence rows; [acceptance handoff](../../docs/reviews/slice-0b-1-acceptance-handoff.md). Also exists, **incomplete**: the [Mac local-model runtime feasibility experiment](../../docs/evidence/v0-mac-local-model-runtime-feasibility.md) — host gate passed (Apple M1 Pro, 16 GiB, macOS 27.0.1), llama.cpp **b11440** portable arm64 binary acquired and hash-verified (runtime only, ~12 MB, `--version`/`--help` run, no server launched), measurement tooling prepared under `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01` (outside the repository), **no model downloaded** because the original numeric download cap could not be recovered. Prerequisite reading: AGENTS.md, [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md), [LD-04 design](../../docs/design/ld-04-execution-lifecycle.md) §§4.7, 4.8, 6, 14, ADR-0013, ADR-0003.

Proposed (not existing): new evidence records under `docs/evidence/` and, if scripts are needed, `tools/evidence/runtime/` (following the existing `tools/evidence/sqlite/` convention). No change under `server/` or `client/`.

## 3. Requirements and acceptance criteria

In scope (evidence only): (a) **process ownership** — can Anonymous start and own a runtime process so that a later boot can tell, from persisted facts alone, that it is gone; (b) **termination evidence** — what verifies exit (child reaping, process identity = pid + start time, listener-port ownership), including pid reuse; (c) **cancellation** — what `stop`/request-level cancel actually does mid-generation, and whether `probe`/`stop` are served *during* generation; (d) **late-delivery handling** — after an `UNKNOWN` handoff or a disconnect, can output still arrive, and can `late_delivery_excluded` ever be declared; (e) **recovery constraints** — behavior when the owner is `SIGKILL`ed mid-generation (orphan survival, reparenting), restart reconciliation inputs, and adopt-versus-kill policy options; (f) the remaining §14 rows that are cheap to observe in the same runs (instance identity and version/artifact reporting, faithful input, `finish_reason`, idle/slot status, behavior on requester disconnect).

Done when: each experiment has an evidence record stating the question, exact environment (runtime build and hash, macOS build), method, raw-result location, counts over repeated trials, and a per-row verdict `SUPPORTS` / `DOES_NOT_SUPPORT` / `INCONCLUSIVE` against design §14; a short synthesis states what B3/B4/B5 can and cannot be produced and recommends (not decides) an adapter/controller shape; unsupported or inconclusive results are reported as such and leave the row `BLOCKED_BY_RUNTIME_EVIDENCE`.

**Non-goals:** any adapter, controller, broker, launcher or transport code; real-model product integration; streaming, cancel UI, multi-slot, persona/Memory; throughput/latency benchmarking (that belongs to the incomplete feasibility experiment); Windows (separate gate, `REQUIRED_BEFORE_FULL_V0`); authentication, access containment, ADR-0011 exclusive-instance mechanism; any weakening of CB-05 or any force release (would need its own ADR).

## 4. Constraints and open questions

Constraints: synthetic data only (no PRIVATE or real private data, prompts and logs included); loopback `127.0.0.1` only, no LAN or public exposure; **no model download without the owner's separate authorization and a stated total size cap**; no new dependencies in `server/` or `client/`; the runtime must be disposable and run from the external bench folder, no login item, no persistent service, no global install; the experimenter kills only processes it spawned and verifies none remain; raw artifacts stay outside the repository, only sanitized summaries are committed; no secrets recorded. Domain invariants and ADR-0013/0014 are not reopened.

Open questions (each blocks only what is stated): **Q1** which model and what size cap the owner authorizes (blocks E2–E3 only; the previously noted candidate `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 bytes ≈ 2.326 GiB at a pinned revision with publisher SHA-256, is a *candidate*; the earlier proposed 30 GiB figure was only a proposal and is not an authorization). **Q2** whether this work and the incomplete feasibility experiment share one model artifact and bench folder or stay separate (affects budget only). **Q3** whether the owner prefers a controller-owned runtime process if E1 shows external-process ownership is weak (this is O1's open branch; deciding it needs an ADR if architecture changes). **Q4** exact experiment-script location (`tools/evidence/runtime/` proposed). **Q5** what the owner wants done with the feasibility experiment's unresolved cap in the meantime.

## 5. Affected components and intended approach

Evidence only; source versus derived: raw logs and timelines are transient external artifacts, committed records are sanitized derived summaries that cite them; no 0B-1 facts are touched. Approach: smallest experiment first, each building on the last, stop on any resource or safety trigger.

- **E0 — gate (no download).** Repeat the host resource gate; re-verify the b11440 archive hash and `--version`; create a fresh dated bench folder (private umask); record the build and OS. Abort on memory pressure or no AC power as in the feasibility plan.
- **E1 — owned-process and termination-evidence primitives (no model, no download). *First experiment.*** See section 6.
- **E2 — real runtime control and cancellation (needs authorized model).** Start `llama-server` b11440 loopback-only with the pinned model and a synthetic prompt set; measure: `stop`/`probe`/health/slot status *during* generation; request-level cancel and what happens on client disconnect; per-attempt registration (can an unknown attempt be distinguished); instance identity, build and model-artifact digest reporting; `finish_reason` and faithful input; `start` boundedness and abandonment; late output after disconnect and after an uncertain handoff (inject a stalled/lost response path with a local loopback proxy).
- **E3 — crash and recovery (needs authorized model).** `SIGKILL` the owner mid-generation; observe orphan survival and reparenting; define restart reconciliation from persisted facts only; compare adopt-versus-kill policies; confirm B4 inputs hold across pid reuse; confirm nothing can publish from an orphan.
- **Synthesis.** An evidence summary and a recommendation for the 0B-2 implementation plan (separate task, separate authorization).

Anticipated files: `docs/evidence/v0-0b2-<experiment>.md` per experiment (+ a sanitized machine-readable results file if useful), `tools/evidence/runtime/*.py` (stdlib only), updates to this plan, and — only if a result changes a documented design position — an ADR proposal. Migration/recovery implications: none (no persistence change).

## 6. Work sequence

Working directory for all steps: the repository root; raw outputs in the external bench folder. Every step is re-runnable; each trial records its own timestamp and spawned PIDs; cleanup is by explicit PID/process-group of what the harness started, verified afterwards. Commands are **proposed and unverified** until run.

### E1 — proposed first experiment (no model, no download)

**Question.** On macOS, can an owner process start a loopback runtime-like child and later (including after its own crash) establish, from persisted facts alone, that the child is gone — without mistaking another process for it (pid reuse or port reuse) — and what behavior must the design assume when it cannot?

**Subject.** A small stand-in child (stdlib Python, loopback HTTP, controllable behaviors: immediate reply, slow reply, stalled reply, ignores SIGTERM, spawns a grandchild) — *explicitly a stand-in*: it proves OS and process-control facts only and says nothing about llama.cpp behavior. As a bounded real-binary probe, also observe whether the b11440 `llama-server` binary starts, listens or exits when launched without a model (record only what happens; no assumption is made beforehand; if it needs a model it simply stops).

**Scenarios (each repeated at least 20 times, counts recorded):**

1. Owner spawns child; records `(pid, start time from the kernel, listening port, a per-instance nonce the child reports over loopback)`. Verify the record uniquely identifies the process, and that a *different* process reusing the pid or port is distinguishable.
2. Graceful stop: SIGTERM → exit; verify exit via child reaping (`waitpid`) and via a second independent observer (kernel exit notification such as kqueue `NOTE_EXIT`, and a pid/start-time re-check).
3. Child ignores SIGTERM; escalate to SIGKILL after a budget; verify no zombie, no grandchild left (process group / session behavior).
4. **Owner `SIGKILL`ed while child runs.** Does the child survive and reparent? With and without a new session/process group? Does a child-side watchdog (EOF on an inherited pipe) reliably terminate it, and how fast?
5. **New owner after crash** with only the persisted record: classify each case as *proven gone*, *proven alive* or *unknowable*; try adversarial cases (pid reused by an unrelated process; port reused by an unrelated listener; clock change).
6. Port and listener ownership: can the listener's owning pid be read reliably and is it stable under races?
7. Resource bounds: confirm `stop` and observation calls remain bounded while the child is blocked.

**Stop conditions.** Any process not started by the harness is never touched; abort and clean up on unexpected child count, memory-pressure warning, or a trial that cannot verify cleanup.

**Evidence record E1 answers (feeds design §14 "instance and process identity and exit verification", "can Anonymous own the runtime process", O1):** which identity tuple is sufficient on macOS; whether exit is verifiable by an owner and by a successor; whether orphan survival can be prevented or must be assumed; the exact conditions that must map to quarantine.

Why first: needs no model, no download and no network beyond loopback; it answers the highest-leverage unknown (whether external-runtime B4 is achievable and what ownership shape it needs) before any weights are acquired; and its result changes what E2–E3 must test.

### E2–E3
Proceed only after E1's record is reviewed and the owner authorizes the model with an explicit size cap (Q1). Reuse the verified runtime and bench folder; repeat the 60-second idle gate before each model load.

## 7. Validation strategy

Per acceptance criterion: each verdict cites trial counts and raw-artifact hashes; any scenario with an unexplained failure is reported as `INCONCLUSIVE`, never rounded up; E1 is re-run once on a clean boot of the bench folder to check reproducibility; cleanup is verified (no stray process, no listener, bench folder contents inventoried); a final consistency pass checks that no committed file contains prompts, paths of private data, secrets or non-loopback addresses and that every link resolves. Failure and privacy cases: orphan outliving its owner; pid/port reuse; late output after closure (must never be treated as publishable, see ADR-0013); disconnect during generation. Documentation-only review rules (AGENTS.md) apply to the evidence records; no repository tests are added by evidence work.

## 8. Progress

- [x] 2026-10-12 Plan written (this file).
- [x] 2026-10-12 Owner answered Q1/Q2/Q5 in part: shared artifact and budget with the feasibility experiment; proposed cap 3 GiB, one artifact; the earlier unknown cap superseded prospectively; actual download still needs separate authorization. Q3 (controller-owned process) and Q4 (script location: `tools/evidence/runtime/`, used) remain open for the owner.
- [x] 2026-10-12 E0 gate read: battery 70%, memory pressure level 2 (deviation from the plan's abort rule, recorded; E1 used only small processes).
- [x] 2026-10-12 E1 executed: 772 trials, 0 failed checks, clean final audit; real pid reuse obtained twice; llama-server b11440 probed without a model (kept separate).
- [x] 2026-10-12 E1 evidence record written. Independent review not requested (owner: not needed unless a high-risk architectural issue emerges; none did, but see the residual in report F6).
- [x] 2026-10-12 Reproducibility re-run attempted twice; interrupted by host sleep on battery (both partials preserved); S1–S3 reproduced identically, S4–S7 **not** reproduced.
- [x] 2026-10-13 Clean full E1 re-run completed with the host awake: 772 trials, 0 failed, verdicts identical to the main run, real pid reuse obtained twice (report §1). Still on battery and memory-pressure level 2, so AC-power behavior remains unmeasured.
- [x] 2026-10-14 E2 preflight (model-free, no download): llama-server b11440 router/single-model topology measured (140 trials, 0 leftovers), F6 minimum B4 conditions stated, partial model file inspected read-only against official metadata. Record: [E2 preflight](../../docs/evidence/v0-0b2-e2-preflight-runtime-topology.md). Recommendation: first inference test in single-model mode under a kernel-enforced no-fork sandbox profile.
- [x] 2026-10-14 E2-A (acquisition and hash verification only, no load): one fresh `Qwen3-4B-Q4_K_M.gguf` at the pinned revision acquired, 2,497,280,256 B, SHA-256 matches the manifest; 2,497,280,256 B transferred of the 3 GiB cumulative cap; the partial file untouched. Record: [E2-A](../../docs/evidence/v0-0b2-e2a-model-acquisition.md). E2-B not started; needs AC power, the idle gate and owner authorization.
- [ ] 2026-10-14 E2-B authorized; **stopped at Phase 1 gate: host on battery power** (`pmset`: 'Battery Power', 100%, discharging; memory free 46%). Model re-verified (2,497,280,256 B, SHA-256 matches). No sandbox test, start, load or inference was attempted. Resume when the host is on AC power; the 60-second idle/memory gate must then pass immediately before load.
- [ ] Owner decision on the partial model file and the discovery items (report §8; preflight §4); owner authorization of the model download and size cap (separate; E2 blocked until then). Also needed before any load: AC power and the idle gate (host has been on battery at memory-pressure level 2 in every run so far).
- [ ] E2, E3.
- [ ] Synthesis and recommendation for a 0B-2 implementation plan.

## 9. Discoveries

- **Partial model file.** `models/Qwen3-4B-Q4_K_M.gguf.partial` (1,786,773,504 bytes, 2026-10-06 22:38) exists in the bench folder although the feasibility evidence says no model bytes were downloaded. Untouched, unverified. The bench manifest also holds a recovered authorization record (12,000,000,000-byte ceiling, ≤ 2 artifacts) that the repository evidence says was unrecoverable; the owner's 3 GiB / one-artifact decision supersedes it prospectively.
- **E1 headline.** A conditional B4 basis is feasible for a single-process, non-detaching runtime spawned and recorded by Anonymous; ambiguous or unverified bindings must stay `INDETERMINATE`; a detached, environment-scrubbing descendant spawned after binding cannot be detected (report F6).
- **Tooling facts.** Children survive owner SIGKILL (reparented to pid 1); a pipe-EOF watchdog stops them in ≤ 4.2 ms; SIGTERM is ignored by a SIGSTOPped process, SIGKILL is not; `ps -axeww` hides environments on macOS 27, `KERN_PROCARGS2` reads them.
- **E2 preflight (2026-10-14).** Router children are same-group/same-session, inherit the environment and own their ports (80/80); the router's listener is not inherited; router SIGKILL orphans them (reparented to pid 1). The child's stdin-EOF owner-death watcher starts only **after the model has loaded** (source, `server.cpp:549-550`), so loading children have no owner-death link (unverified with a real model). Under `(deny process-fork)` the router cannot spawn a child (HTTP 500, 20/20), a candidate way to close F6 by construction; its viability for real inference is unverified. `POST /models` and `-hf`/`LLAMA_ARG_HF_REPO` are download paths: scrub `LLAMA_ARG_*`/`HF_*` and never expose router control. The partial model file is exactly 1704 MiB (71.55 %), not sparse, GGUF v3 header valid, writer unknown, SHA-256 fingerprint recorded, official size/SHA-256/revision re-confirmed; no prefix verification without downloading.
- **llama-server b11440 without a model** starts in router mode (`role: router`, `max_instances: 4`), needs ~6.7 s to listen, is one process when idle, and exits on SIGTERM in ~11 ms. Whether router mode's per-model children detach or inherit the environment is the key E2 question.

## 10. Decision log

2026-10-12 — Owner approved E1; run the model-free E1 first. Rationale: it is independent of runtime internals, needs no authorization beyond loopback execution of a disposable child, and decides whether the O1 branch "controller-owned process" is needed. Alternative considered: start with the real runtime and model (rejected: blocked by the download authorization and would test control and ownership together, making results hard to attribute). Status: proposal. No ADR is created or implied; any architectural consequence goes through an ADR after the evidence exists.

## 11. Final outcome

**Partial (E1 complete; E2, E3 and synthesis outstanding).** E1 ran as planned and is recorded in the [E1 report](../../docs/evidence/v0-0b2-e1-process-ownership-termination.md) with sanitized raw data under `docs/evidence/v0-0b2-e1/` and scripts under `tools/evidence/runtime/`. Deviations: battery power and memory-pressure level 2 at the E0 gate (recorded); two design iterations after a smoke run (report §1). No model was downloaded or loaded, nothing left loopback, no application code or accepted 0B-1 semantics changed. Remaining limitations: stand-in only (llama.cpp behavior unmeasured beyond the model-less probe), macOS only, same-user visibility, residual F6, `lsof` timeout path unexercised, sandbox effectiveness unverified. Next: owner decisions (report §7–8), then a separately authorized E2.
