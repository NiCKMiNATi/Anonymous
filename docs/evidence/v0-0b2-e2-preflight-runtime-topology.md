# Slice 0B-2 E2 preflight — llama-server b11440 topology, F6 boundary, partial model file (macOS)

**Status:** executed 2026-10-14 on the macOS development host. **Evidence only.** No model was downloaded, opened or loaded; nothing left loopback; no `server/` or `client/` code, no accepted 0B-1 semantics, no design document or ADR was changed. E2 inference and E3 are **not** started and remain gated. E1 was not repeated ([E1 report](v0-0b2-e1-process-ownership-termination.md), commit `deeedbb`).
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). **Raw data:** [v0-0b2-e2pre/topology-trials.jsonl](v0-0b2-e2pre/topology-trials.jsonl) (sanitized; 140 trials). **Script:** [tools/evidence/runtime/e2pre_topology_probe.py](../../tools/evidence/runtime/e2pre_topology_probe.py) (SHA-256 `6f27fd15…24dc`; data file `ade89ace…ec19`).

**Verdict in one line:** use **single-model mode** for the first real inference test, spawned directly by Anonymous under a kernel-enforced no-fork sandbox profile; router mode is demonstrated to create ordinary same-group, environment-inheriting children (so E1's classifier handles it), but its owner-death linkage starts only after a model has loaded, so it should wait for its own experiment. The F6 gap can be closed **by construction** (the runtime cannot create processes), not by better observation.

## 1. Method and environment

| Item | Value |
| --- | --- |
| Binary | llama.cpp **b11440** (`version: 0.6.0-dev (build 11440, commit 1a3011cc0)`), portable arm64 archive SHA-256 `822ea947…03e6` (matches the published digest, re-verified), `llama-server` SHA-256 `1bf5602a…6b41` |
| Host | Apple M1 Pro, 16 GiB, macOS 27.0.1, Python 3.9.6 stdlib only, same-user, no root; on battery, memory-pressure level 2 (unchanged from E1; irrelevant to model-less runs) |
| Safety | loopback `127.0.0.1` only; `--offline`; empty temp `LLAMA_CACHE` (empty after every trial); **no** `-hf`/`--hf-repo`, **no** `POST /models` (the download endpoint), **no** real model path (the only model path ever passed does not exist); best-effort sandbox profile denying non-loopback outbound (effect not verified, as in E1); every signal sent to a process whose kernel identity (pid, start) the script recorded; leftovers swept by an environment tag; all 140 trials ended with zero leftover processes and an empty cache |
| Technique | Router mode with a preset whose only model is a **non-existent path**, then `POST /models/load`: the router spawns a model-instance child, which fails to load (nothing to load) and exits after ~0.15 s. During that window the child's identity, group, session, environment and sockets are observed. Single-model mode (`-m` on the missing path) is observed the same way. No model bytes are touched. |
| Source reading | The b11440 tag files `tools/server/server-models.cpp`, `server.cpp`, `server-models.h` and `vendor/sheredom/subprocess.h`, plus the local README/help. Line numbers below refer to those files as fetched 2026-10-14. Source-derived statements are labelled **[source]**; they are not measurements. |

## 2. Task 1 — runtime topology

### 2.1 Modes **[source, confirmed by run]**
- **Router mode** iff no `-m`/`--model`, no `--hf-repo` and no docker repo is given (`server.cpp:151`). It "never loads a model and must not touch the GPU". README: "do not expose router mode to untrusted environments". Control endpoints: `/models`, `/models/load`, `/models/unload`, `/models/sse`, and **`POST /models` which starts a download child** (`LLAMA_SERVER_CHILD_MODE=download`, `LLAMA_ARG_HF_REPO`).
- **Single-model mode** (`-m path`): one server process serving one model. It spawns children **only** if MCP servers (`--mcp-servers-config`/`--mcp-servers-json`) or tool runtimes (`--tools`, `--tools-runtime`) are configured (README; not exercised).
- Model sources/launch paths that can **download**: `-hf`/`--hf-repo`, env `LLAMA_ARG_HF_REPO`, `POST /models`, a preset using `hf-repo`. `--offline` is passed in every run here; whether it blocks every one of these paths was not tested.

### 2.2 When router mode creates subprocesses
| Fact | Basis |
| --- | --- |
| No child exists after startup (idle router: 0 descendants before the load request, 100/100 router trials) | measured |
| A child is created on first need for a model: `POST /models/load`, a request naming the model (autoload, disable with `--no-models-autoload`), or a preset's `load-on-startup`; at most `--models-max` (default 4) | source (`server-models.cpp` load path), `/models/load` spawned a child 80/80 (and 0/20 under the no-fork profile, §3.1) |
| The child appears ~1.5 ms after the load request (max 1.9 ms) | measured, 80 spawn trials |
| Children are spawned with `subprocess.h` (`fork`+`exec` or `posix_spawn`); **no `setsid`/`setpgid`/`PDEATHSIG`** anywhere in `server-models.cpp` or `subprocess.h` | source (grep) |
| Child gets a **fresh free port** chosen by probing and releasing a port (`common_http_get_free_port`), bound to `127.0.0.1`; the router proxies requests | source (TOCTOU between choosing and binding is possible; not exercised) |

### 2.3 Child process properties (measured, router trials with a child: 80/80 for process facts, 20/20 for sockets)
- **Parent, group, session:** ppid = router pid, **same process group and same session as the router** (80/80). Children **do not detach**.
- **Environment inheritance:** the full environment is inherited (`base_env` + `LLAMA_SERVER_ROUTER_PORT`); our per-instance tag was present in the child 80/80, and `LLAMA_SERVER_ROUTER_PORT` 80/80. README: "model instances inherit both command line arguments and environment variables".
- **Listeners:** the router's listening socket is **not** held by the child (0/20 with the child frozen and inspected by `lsof`); the router stayed the sole holder of its port (100% of router trials). The child had no listening socket yet (it exits during startup), so *steady-state* child listeners are unmeasured.
- **Router SIGTERM** (child alive and loading): router gone ≤ 61 ms, child gone at the same time, 0 leftovers (20/20). **[source]** a *loading* child is force-killed; a *ready* child gets an exit command on its stdin and is force-killed after `stop-timeout` (default 10 s).
- **Router SIGKILL**: the child **survives** and is reparented to launchd (alive immediately after router death 40/40; ppid 1 in 36/40, the other 4 sampled while the dying router was still its parent). **The child then exits ~72 ms later, which is its own load-failure time, so this does not show that an owner-death link works** (confounded; see 2.4). With the child SIGSTOPped, it is still alive 0.5 s after router death (20/20) and exits only after SIGCONT, again within its own failure time.
- **E1 classifier against the real router (the F6 question for this binary):** record = router only (the child did not exist when it was written), router SIGKILLed, child frozen alive (20/20). Classifier v1 (no tag): **INDETERMINATE** (live unrecorded member in the recorded group) 20/20; v2 (tag): **PROVEN_ALIVE** 20/20; after the child is gone, both **PROVEN_TERMINATED** 20/20. So this binary's router children are the "late same-group descendant, tag inherited" case, which E1 classified soundly.

### 2.4 What is the owner-death link, and when does it exist **[source]**
Each child's stdin is a pipe from the router. A watcher thread treats **EOF on stdin as "router died or was killed" and calls `exit(1)`**, and the exit command is `cmd_router_to_child:exit` (`server-models.cpp:45-53, 1841-1851`). **The watcher is started only after the model has loaded and the HTTP server is ready** (`server.cpp:549-550`, inside the post-load branch). Consequence: **while a child is still loading its model it has no owner-death linkage**; after SIGKILL of the router it keeps loading and exits only after load completes (and the watcher then sees EOF). Real model loads take seconds, so the orphan window is expected to be seconds, holding memory. This is source-derived and **unverified** (it needs a model that loads).

### 2.5 Single-model mode, no model (measured)
`-m <missing file>`: exits with code 1 in ~87 ms (20/20), logs `failed to load model`, **never listened**, **0 descendants** (20/20). Identical outcome (exit 1, same final log line, 0 descendants, same lifetime) under the no-fork profile (20/20).

### 2.6 What can and cannot be shown without a model
| Property | Without a model |
| --- | --- |
| Modes and mode selection, spawn trigger, group/session/env inheritance, router listener not inherited, router SIGTERM/SIGKILL effect on a loading child, classifier verdicts | **Demonstrated** (this record) |
| A kernel-enforced no-spawn profile prevents router children (§3) | **Demonstrated** |
| Steady-state child: listening socket, `/health`, readiness, whether `listen` and the router's proxy coexist | Unverified |
| Owner-death link (stdin-EOF watcher) behaviour and its timing; orphan duration during load; whether an orphan can still serve | Unverified |
| Whether a **ready** child honours the exit command and how it ends under SIGTERM/SIGKILL of the router | Unverified |
| Whether single-model mode listens and returns 503 *during* model load | Unverified (the missing-file run fails before listening) |
| Whether inference under the no-fork profile works (Metal/GPU path, helper threads, any launchd/XPC use) | **Unverified; the main E2 risk for the recommended containment** |
| GPU work and memory after process death; late delivery; cancel; `finish_reason` | Unverified |
| Router `readiness`: **0.21 s** here (max 0.21) versus **~6.7 s** in the E1 probe (no preset) | Unexplained discrepancy; E2 must keep bounded waits for both |

## 3. Task 2 — the F6 evidence boundary

**F6 (E1):** a descendant that is spawned after binding, detaches into its own session and scrubs its environment is invisible to every OS-visible check we have; the classifier then reports `TERMINATED` for a live instance. Observation cannot close this. What can: making sure no such descendant can exist, or refusing to produce B4.

### 3.1 New measured control: a kernel-enforced no-spawn profile
Same router, same load request, under the sandbox profile plus `(deny process-fork)`: **the router stays alive and the spawn fails** — HTTP **500 "failed to spawn server instance"**, **0 children observed and 0 descendants after 0.5 s, 20/20**, router logs the failure 20/20. The positive control is the identical router **without** that rule, which spawned a child **80/80** (§2.2). `sandbox-exec` applies the profile and then execs the target in place (pid unchanged; E1 showed the spawned pid is the sole listener), and a macOS sandbox profile is designed to be irrevocable for the confined process (taken from the sandbox's design, not tested here). Single-model startup is unaffected up to the model load (§2.5).

Limits (stated, not hidden): it blocks `fork`/`posix_spawn` **by the runtime process**; it does not stop the runtime from asking a system service (launchd/XPC) to start something for it, and `sandbox-exec` is a deprecated interface. For this pinned binary, source reading found child creation only through `subprocess.h` in the router and MCP paths. Whether a Metal inference run works under the rule is **not** known.

### 3.2 Minimum conditions before Anonymous may rely on B4 for an `external` binding
These are **admission conditions for a future B4 producer** (recommendations; none is implemented). All must hold; otherwise the outcome stays `INDETERMINATE` and the slot stays quarantined, exactly as now.

1. **Direct, recorded spawn.** Anonymous itself spawns the process that serves requests (no launcher, shell wrapper or router in between; E1 F5: a wrapper pid forces `INDETERMINATE`). Before the **first** request it durably records: pid, kernel start time, process group, session, a per-instance environment tag, port, argv digest, binary SHA-256, and a **verified sole-listener binding** (listener pid == recorded pid and the instance reports the same identity). A missing or partial record ⇒ `INDETERMINATE` (E1 S5, 20/20).
2. **Declared topology = single process, enforced at spawn.** Preferred: a kernel-enforced no-new-process profile (§3.1), recorded in the binding and re-verified for each runtime build by a positive/negative probe. If the process is not so contained, B4 is **not** available for that binding, because detach-and-scrub cannot be excluded by observation (F6).
3. **Pinned, constrained launch.** Pinned binary hash; fixed argv with **no router mode, no MCP/tool options, no `--hf-repo`**; environment built from an **allow-list** (drop all `LLAMA_ARG_*`, `HF_*` and any inherited tool/MCP settings; add only the tag), because environment variables can change mode and trigger downloads.
4. **Topology monitored for violations.** Zero descendants and zero other tagged processes at dispatch, at every probe and at closure. Any unexpected descendant or tagged process ⇒ the binding is marked topology-violated ⇒ **no B4 for it** (the descendant is recorded and killed by verified identity as an *action*, never as evidence).
5. **Exit proof by conjunction, never one signal.** While the owner lives: kqueue `NOTE_EXIT` on the verified identity plus `waitpid`. For a successor: E1's conjunction — the kernel reports no live process with the recorded (pid, start); no recorded descendant alive; no unrecorded live member in the recorded group; no live process carrying the tag; verified listener binding. **PID disappearance, process-group termination or listener disappearance, alone or in any pair, is not sufficient** (E1: grandchild keeps the port 20/20; pid reuse 2 real/40 simulated; group-only checks missed escaped descendants 20/20).
6. **Same-user visibility.** The tag scan and `lsof` see only the same user's processes; the runtime must run as that user, and a different-user process is out of scope ⇒ `INDETERMINATE`.
7. **Owner-death linkage is a recovery aid, not evidence.** A pipe/stdin-EOF link shortens orphan life but is not B4; and per §2.4 it does not exist during model load for llama.cpp's own router children.
8. **Unsupported topologies stay quarantined:** router mode (until its own experiment shows the conditions above for every child), MCP/tools enabled, any wrapper or launcher, un-contained runtimes, missing records, unverified bindings, other users' processes.

### 3.3 Relation to accepted 0B-1 and scope of any change
- Nothing here weakens or alters accepted 0B-1 semantics; every condition only **adds** cases that remain `INDETERMINATE`. B4 text in the [LD-04 design](../design/ld-04-execution-lifecycle.md) §1.3 ("the specific process named by the binding has exited, verified against a launch identity") is consistent, but it does not state that the named process must be the **only** execution unit; conditions 2 and 4 supply that, and without them B4 on a router pid would be unsound for its child's work (§2.3).
- **I did not implement or edit anything in the execution-ownership boundary.** If these conditions are adopted for 0B-2, the affected documents are: the LD-04 design §1.3/§14 (B4 producer obligations for `external` bindings), ADR-0013 (consequences), and a new ADR for the controller-spawned, sandbox-contained runtime shape (O1's open branch / ExecPlan Q3). That is a documentation-and-ADR change plus a 0B-2 adapter, not a change to 0B-1 code.

## 4. Task 3 — the existing partial model file (read-only inspection)

| Item | Finding |
| --- | --- |
| Location / name | `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01/models/Qwen3-4B-Q4_K_M.gguf.partial` |
| Size | **1,786,773,504 bytes = exactly 1704 MiB** (71.55 % of 2,497,280,256); fully allocated on disk (not sparse, not pre-allocated: `du` 1,744,896 KiB; non-zero data at the tail and in a mid sample) |
| Times | created 2026-10-06 22:36:26, last modified 22:38:49 (≈ 2 m 23 s of writing, ~12 MB/s); unchanged by this inspection. Created **24 s after** the AC host gate passed (22:36:02) and about a minute after the authorization record (22:35:22) |
| Open by a process | none (`lsof` empty); no downloader found in the bench tooling, telemetry or the home cache; the file has only `com.apple.provenance`. **Which tool wrote it is unknown.** The `.partial` suffix is not Hugging Face Hub's `.incomplete` |
| Header (first 32 bytes only) | `GGUF`, version 3, tensor count 398, metadata KV count 28. 398 = 36 blocks × 11 tensors + token-embedding + output-norm, which is **consistent with** Qwen3-4B (tied embeddings); this is arithmetic plausibility, not verification |
| SHA-256 of the partial (fingerprint, 2026-10-14) | `328707193716194cbe598ad599629c4f2de18c99250c671aeddc198ca42549c9` |
| Apparent source / intended model | the pinned candidate in the bench manifest: `Qwen/Qwen3-4B-GGUF`, revision `bc640142c66e1fdd12af0bd68f40445458f3869b`, `Qwen3-4B-Q4_K_M.gguf`, Apache-2.0, base `Qwen/Qwen3-4B` |
| Contradiction | the feasibility evidence states "0 model bytes downloaded" and an empty `models/`; the file contradicts that (also recorded in the ExecPlan discoveries). The evidence file was **not** edited. |

**Official metadata comparison (queried 2026-10-14; metadata only, no file bytes):** Hugging Face API tree at the pinned revision lists `Qwen3-4B-Q4_K_M.gguf` size **2,497,280,256**, LFS SHA-256 **`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`**; a `HEAD` on the resolve URL returns `x-repo-commit` = the same revision, `x-linked-size` 2,497,280,256, `x-linked-etag` = the same SHA-256, `accept-ranges: bytes` (redirects to a CDN; range support **at the CDN** is not verified). The pinned revision is still the head of `main` (last modified 2025-05-21). All three match the bench manifest.

**Is there a trustworthy resume procedure?** Resumption is *possible* (byte ranges are advertised), but the **prefix cannot be verified before completion**: the publisher gives only a whole-file SHA-256 (no per-chunk hash that we can use without a Xet client), and the writer of the file is unknown. Trust can therefore only be established **after the fact** by the whole-file SHA-256. I did **not** fetch sample ranges to compare the prefix: that would download model bytes, which is gated.

**Recommendation (not a decision):** treat the partial as *unverified provenance*. If the owner authorizes the download, prefer **safe resumption with a hard gate**: (1) resume into an APFS clone (`cp -c`), keeping the original and its recorded fingerprint untouched; (2) request `Range: bytes=1786773504-` with the ETag as `If-Range`, accept only `206` with a matching `Content-Range`, count all transferred bytes; (3) accept the artifact **only** if size is 2,497,280,256 and SHA-256 equals the publisher value, before any load; (4) on mismatch, quarantine both files and do one fresh full download. Worst-case new bytes: 710,506,752 + 2,497,280,256 = **3,207,787,008 B = 2.9875 GiB**, under the owner's proposed 3 GiB cap **only if the cap counts newly transferred bytes**; if the owner counts bytes on disk, one artifact at a time still fits. Replacement from scratch (2.326 GiB) is the cleaner-provenance choice and costs ~1.66 GiB more transfer; both fit. Do not reuse the file as a model without the hash gate under any option.

## 5. Task 4 — E2 readiness

1. **Observed topology and behavior:** §2. Router children are same-group, same-session, environment-inheriting, own their ports, do not hold the router's listener, survive router SIGKILL, and die with the router on SIGTERM (loading). Owner-death linkage exists only after load **[source]**.
2. **F6 containment requirements:** §3.2 (eight conditions); the load-bearing ones are a direct recorded spawn, kernel-enforced single-process containment, a pinned/constrained launch with an allow-listed environment, and the E1 conjunction for exit proof.
3. **Partial-file disposition:** §4 — do not touch now; if authorized, safe resumption into a clone with a whole-file SHA-256 gate and fresh-download fallback.
4. **Outstanding model-download prerequisites (all the owner's):** explicit download authorization for **one** artifact (`Qwen3-4B-Q4_K_M.gguf` at the pinned revision) with the stated cap and whether it counts transferred or on-disk bytes; the partial-file decision; AC power and the 60-second idle/memory gate immediately before any load (the host has been on battery at memory-pressure level 2 in every E1 and preflight run, so the plan's own gate would **fail today**); allowed download hosts (`huggingface.co` and its CDN `*.hf.co`) for outbound HTTPS, no token; free disk is ample (368 GiB). Integrity (hash) is not safety: loading runs llama.cpp's GGUF parser on a file from outside, so keep the first load model-agnostic and bounded.
5. **Genuinely blocking defect:** **none** for starting E2. Open items that are not defects but must be handled: the unverified viability of inference under the no-fork profile (the first E2 trial must test it and must be willing to report `DOES_NOT_SUPPORT`), the unexplained router-readiness variance (0.21 s vs 6.7 s), and the pre-existing contradiction in the feasibility evidence.
6. **Smallest safe next execution task:** **E2-A — authorized acquisition and hash verification only, no load.** Once the owner authorizes the download and decides the partial, perform the acquisition exactly as §4, verify size and SHA-256, record transferred bytes, and stop. Then E2-B: one bounded single-model start (`-m`, `-np 1`, `--no-webui`, `--host 127.0.0.1`, no router, no tools/MCP, allow-listed environment) **under the no-fork profile**, a few synthetic prompts, with the E1 record/classify protocol around it. If the no-fork profile breaks inference, report that and decide containment before anything else; do not drop it silently.

**Recommendation on mode:** the first inference test should use **single-model mode**. It has one process and no spawn trigger, so it satisfies conditions 1–5 directly; router mode adds a spawn-on-demand tree, a download endpoint and a post-load-only owner-death link, and is justified only if a multi-model need appears (then its own experiment: record each child by identity before dispatch, run the E1 protocol on the whole tree, and measure the stdin-EOF link with a real model).

## 6. Limitations
Stand-in-free but model-free: nothing here shows how a loaded runtime behaves. One host, one macOS build, one user, one llama.cpp build. The sandbox profile's outbound-network effect and `(deny process-fork)` on a real inference path are unverified; the `lsof` timeout path is still unexercised. Source line numbers refer to files fetched on the day and are not pinned by hash. The author of the probe, the classifier and this analysis is the same; no independent review was requested, as instructed.
