# V0 Mac Local Model Runtime Feasibility Experiment v0.1

**Status:** Resumed preparation complete; inference is blocked pending recovery of the previously authorized numeric model-download cap. **The experiment is not complete.**  
**Date:** 2026-10-06, Asia/Tokyo.  
**Readiness:** **NOT_READY_FOR_VERTICAL_SLICE_0** — required runtime measurements have not run; this is not evidence that the Mac or candidate model is unsuitable.  
**Plan:** [ExecPlan](../../.agent/plans/2026-10-06-v0-mac-local-model-runtime-feasibility.md).

## Scope and authority

This resumes the authorized Mac experiment after resource-only stops. It preserves the [Mac baseline J–L](v0-mac-client-runtime-baseline.md), [runtime procedure](runtime-feasibility-plan.md), [project definition](../00-project-definition.md), [domain model](../01-domain-model.md), [V0 scope](../03-v0-scope.md), [architecture](../04-architecture.md), [logical model](../05-data-model.md) and [runtime security requirements](../evaluations/v0-access-security-mechanisms.md#10-service-exposure-and-runtime-containment).

Windows remains the intended authoritative V0 server. This task neither changes the production runtime nor creates Anonymous frontend/backend, storage, API or integration code. Completed persistence experiments were not repeated. Mac feasibility cannot substitute for Windows runtime/security or multi-device acceptance.

## Repeated host gate

The same read-only commands as the earlier attempt were used: `uname`, `sw_vers`, selected hardware `sysctl` fields, `df -k /System/Volumes/Data`, `pmset -g batt`, `pmset -g custom`, `kern.memorystatus_vm_pressure_level`, `vm.swapusage`, `vm_stat` and `memory_pressure -Q`. Sampling ran once per second for 60 seconds, retaining a transcript summary rather than claiming a saved raw series for this initial gate.

| Observation | Verified result, 2026-10-06 22:14:07–22:15:07 JST |
| --- | --- |
| Host | Darwin / native ARM64; MacBookPro18,3; Apple M1 Pro; 8 physical/logical cores |
| Unified memory | 17,179,869,184 bytes = 16 GiB |
| OS | macOS 27.0.1, build 26A434 |
| Storage available | 387,986,944 KiB, approximately 370.01 GiB; exceeds 50 GiB reserve |
| AC | Recognized before and after sampling; battery 99% |
| Pressure | Level 1 (normal) in all 61 samples over 60.032 seconds |
| Swap | 1,246.81 → 1,238.81 MiB; range 1,238.81–1,246.81; delta −8 MiB |
| Physical compressor occupancy | 3.132 → 3.120 GiB; range 3.120–3.132 GiB |
| VM counters | No additional pageouts or swapouts; 32 swapins and 1,669 pageins |
| Power configuration | One-minute idle sleep; low-power mode off; observed without changes |

**Host gate passed.** Unlike earlier observations, pressure was no longer sustained warning and AC was attached. Existing used swap was not treated as a failure or required to reach zero. This is baseline evidence, not reserved model headroom. Repeat the 60-second idle check immediately before loading.

## Runtime evaluation and experimental choice

Current official documentation and release metadata were inspected on 2026-10-06. Only one runtime was acquired/executed; there is no comparative speed claim.

| Candidate | Relevant evidence | Experiment disposition |
| --- | --- | --- |
| Ollama, release v0.35.1 | Managed loading/unloading and streaming measurements; documented loopback binding, local-only mode and configurable model directory. Those controls do not independently prove authenticated caller restriction or OS egress isolation. [Official FAQ](https://docs.ollama.com/faq), [release](https://github.com/ollama/ollama/releases/tag/v0.35.1). | Evaluated, not installed. Additional lifecycle management is convenient, but direct control and native authentication favor llama.cpp for this bounded evidence task. |
| llama.cpp, build b11440 | Explicit GGUF path, context, Metal offload, tokenizer/template endpoints, native timing counters and API-key-file authentication. Actual pinned help verified offline mode, cache controls and disabling web UI/agent features. [Pinned server reference](https://github.com/ggml-org/llama.cpp/blob/b11440/tools/server/README.md), [release](https://github.com/ggml-org/llama.cpp/releases/tag/b11440). | **The one selected experimental runtime.** Portable native ARM64 build verified. No production adoption or new architectural ADR. |
| MLX / MLX-LM, release v0.31.3 | Apple Silicon-oriented Python execution with its own model format and measurement path. Upstream server documentation explicitly warns that its security checks are basic and advises against production use. [Project](https://github.com/ml-explore/mlx-lm), [server reference](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md). | Evaluated, not installed. Python/model-format setup and separate security work add scope without improving this experiment's immediate observability. No incompatibility or inferior-performance claim. |

The semantic llama.cpp release v0.6.0 has no portable assets; the official b11440 build release supplies the chosen binary. This was resolved by inspecting the official release list, not by using an unofficial package.

| Installed experimental artifact | Verified value |
| --- | --- |
| Archive | `llama-b11440-bin-macos-arm64.tar.gz` |
| Official source | `https://github.com/ggml-org/llama.cpp/releases/download/b11440/llama-b11440-bin-macos-arm64.tar.gz` |
| Download size | 11,970,453 bytes, runtime software only |
| SHA-256 | `822ea9475f9704da68905fc0735354840331e701136a36c1ad19360b283703e6`; matched published GitHub asset digest |
| Binary version | `0.6.0-dev (build 11440, commit 1a3011cc0)` |
| Architecture | Mach-O 64-bit ARM64; built with AppleClang 21.0.0.21000101 for Darwin arm64 |
| Execution performed | `--version` and `--help`, both exit 0; no inference server launched |
| Installation scope | Extracted portable archive in external experiment folder; no package manager, global install, login item or persistent service |

## Bounded model candidate and unresolved acquisition limit

No model artifact has been downloaded. The original numeric authorization is not present in this chat or recovered repository records. Baseline L proposes 30 GiB, explicitly as a proposed control, so it is not silently treated as the earlier authorization. An asynchronous clarification asks for the already authorized cap; this does not request authorization for a second experiment.

Prepared first candidate:

| Field | Value |
| --- | --- |
| Publisher repository | [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) |
| Immutable revision | `bc640142c66e1fdd12af0bd68f40445458f3869b` |
| Artifact | `Qwen3-4B-Q4_K_M.gguf` |
| Expected bytes | 2,497,280,256, approximately 2.326 GiB |
| Expected SHA-256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` from publisher LFS metadata; local artifact verification remains pending |
| License and lineage | Publisher metadata declares Apache-2.0 and Qwen/Qwen3-4B; pinned card/license retained locally |
| Mode | Proposed non-thinking template configuration, 2K first, maximum 256 output tokens, temperature 0/seed 42 per baseline; exact effective behavior unverified |
| Count/budget | 0 of at most 2 model artifacts acquired; **0 model bytes downloaded** |

A queried `Qwen/Qwen3-4B-Instruct-2507-GGUF` endpoint returned HTTP 401; no access bypass, sign-in or download was attempted. The public Qwen3-4B GGUF candidate above has verified public metadata. This is candidate evaluation, not a failed inference attempt. No second model is selected; it would need budget and measured headroom.

## Measurement preparation and limitations

Raw preparation artifacts live at `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01`, outside the repository and standard cloud-sync roots, created with a private umask. No inspection claims are made about arbitrary third-party whole-host backup software. The directory contains manifest, fixtures, telemetry, trials, summary, tools, models, cache and scratch areas. Its `models` directory is empty.

The original standard-library request recorder from the existing runtime procedure was preserved. An external harness adds per-trial native chat timings/usage, rendered-template token checks, synthetic J fixtures, one-second VM/pressure/swap/RSS/CPU, five-second aggregate GPU/socket/thermal sampling, separate startup timing, independent deadline timers, resource-stop handling and owned-process cleanup. Intended operation is one model/slot on IPv4 loopback with an ephemeral API-key file, no web UI/agent/MCP proxy, offline mode, disabled prefix/cache-RAM reuse and no context shifting. Those flags are supported by the pinned help; **they have not yet been verified with a loaded model**.

An isolated synthetic HTTP instrumentation check passed: empty role events did not count as answer text, first nonempty Unicode answer text set TTFT, a trailing usage/timing event was retained, and native tokens/duration arithmetic was correct. The mock rate is not a model benchmark and must never enter inference summaries. Python syntax checks passed. No runtime dependency was installed for these scripts.

Computer-use permission was unavailable on two Activity Monitor attempts. GUI Memory Pressure/GPU History, whole-system Memory Used as displayed by Activity Monitor, and subjective responsiveness observations are unavailable. Kernel pressure and physical compressor counters remain measurable; IORegistry exposes aggregate GPU utilization, which must not be labeled per-runtime utilization or independent VRAM. `pmset -g therm` reported no recorded thermal/performance warning during preparation. A scoped process check found neither Safari nor VS Code running, so browser/editor coexistence requires a later actual profile. No unrelated app was closed or launched.

## Results and remaining gates

| Required experiment evidence | Status |
| --- | --- |
| Host resource gate | PASS for recorded observation window |
| Runtime alternatives and exactly one portable runtime | DONE; native help/version verified |
| Pinned model integrity, actual load, Metal acceleration | NOT RUN; no model downloaded |
| SHORT CHAT, 2K, 4K, conditional 8K | NOT RUN |
| TTFT, prefill, decode throughput, load and request latency | NOT MEASURED |
| Runtime memory/swap trends and repeated generation | NOT MEASURED |
| Browser/editor development coexistence | NOT TESTED; applications absent in scoped process check |
| Actual Anonymous server coexistence | NOT TESTED; application is not implemented by this task |
| Actual listener/auth/cache/log/privacy/failure behavior | NOT TESTED; documented controls reviewed only |
| Restricted principal and enforced runtime egress/filesystem denial | NOT DEMONSTRATED; no PRIVATE payload is eligible |
| Windows runtime feasibility and client acceptance | REMAIN SEPARATE GATES |

There are no inference success/failure trials to summarize. Missing measurements are not zero values or passes. No source-history preservation claim is derived from synthetic recorder testing; preservation here means original repository files are retained unchanged.

Preparation validation passed: the before/after hash manifest found no modified or deleted original repository file and exactly two added Markdown files (this evidence and its ExecPlan). All 17 relative links in those files resolved; Markdown fences were balanced; external Python syntax passed; the models directory was empty and no process from the experiment runtime directory remained running. No application tests or inference acceptance are claimed.

## CHATGPT HANDOFF SUMMARY

- **Verdict:** **NOT_READY_FOR_VERTICAL_SLICE_0**. Experiment incomplete because the original numeric download cap is missing; runtime suitability remains unmeasured.
- **Completed:** Passed repeated AC/resource gate; reviewed prerequisite boundaries; created ExecPlan; evaluated three runtime candidates; acquired and verified only llama.cpp b11440; prepared external measurement tooling and verified its stream accounting with synthetic HTTP events.
- **Changes:** New ExecPlan and this evidence file; external portable runtime/docs/scripts only. No model weights, application code/dependencies, persistence reruns, production settings, trust/network configuration or authoritative-server changes.
- **Next action:** Recover the previously authorized total model-download limit, verify the proposed 2.326 GiB artifact fits, then acquire/hash it and repeat the idle gate immediately before load. Continue this plan and folder rather than restarting. Obtain actual browser/editor coexistence observations and label GUI instrumentation gaps honestly.
- **Boundary:** Windows remains the intended authoritative V0 server. A future positive Mac benchmark would not establish production security, Windows readiness or implemented vertical-slice acceptance.
