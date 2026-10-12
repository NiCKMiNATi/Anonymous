# Slice 0B-2 — runtime-evidence plan (Mac development host)

## 1. Title, status, and purpose

**Status: PROPOSED — plan only, not started, not authorized to execute.** Nothing here authorizes a model download, any application code, or execution beyond the owner's separate instruction.

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

- [x] 2026-10-12 Plan written (this file). Not started.
- [ ] Owner review of the plan; answers to Q1–Q5.
- [ ] E0 gate.
- [ ] E1 (first experiment).
- [ ] E1 evidence record and review.
- [ ] Owner authorization of model and size cap (separate).
- [ ] E2, E3.
- [ ] Synthesis and recommendation for a 0B-2 implementation plan.

## 9. Discoveries

None yet. Known going in: llama.cpp b11440 was acquired and verified but never launched as a server; no model weights exist locally; the feasibility experiment's download cap is unrecovered.

## 10. Decision log

2026-10-12 — Run the model-free E1 first. Rationale: it is independent of runtime internals, needs no authorization beyond loopback execution of a disposable child, and decides whether the O1 branch "controller-owned process" is needed. Alternative considered: start with the real runtime and model (rejected: blocked by the download authorization and would test control and ownership together, making results hard to attribute). Status: proposal. No ADR is created or implied; any architectural consequence goes through an ADR after the evidence exists.

## 11. Final outcome

Not applicable — plan only; nothing executed, no evidence gathered, no claim made about any external runtime.
