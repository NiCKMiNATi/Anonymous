# V0 Mac Local Model Runtime Feasibility Experiment v0.1

## Title, status, and purpose

**Status:** Active, resumed 2026-10-06 after the owner recovered the acquisition authorization. Existing preparation is retained; repeat the resource gate before acquisition/load. Continue the previously authorized bounded synthetic experiment, not a new architecture or application task. Produce measured Mac feasibility and a CHATGPT HANDOFF SUMMARY with READY_FOR_VERTICAL_SLICE_0 or NOT_READY_FOR_VERTICAL_SLICE_0. Readiness is limited to the evidence actually obtained; Windows remains the intended authoritative V0 server.

## Repository context

Read AGENTS.md, [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md), [requirements](../../docs/02-requirements.md), [scope](../../docs/03-v0-scope.md), [architecture](../../docs/04-architecture.md), and relevant logical-data/security contracts. Follow the [Mac baseline, especially J–L](../../docs/evidence/v0-mac-client-runtime-baseline.md) and [runtime procedure](../../docs/evidence/runtime-feasibility-plan.md). ADR-0003 owns context/model separation; ADR-0011 requires authenticated contained runtime access; ADR-0012 forbids implicit authority transfer. Completed SQLite experiments are evidence, not work to repeat. Existing repository files are untracked; preserve them using a before/after hash manifest rather than interpreting git status as this task's changes.

## Requirements and acceptance criteria

Evaluate Ollama, llama.cpp and MLX/MLX-LM from current primary sources; install exactly one experimental runtime. Acquire at most two pinned bounded model artifacts within the user's earlier total model-download cap. Start with one 3B–4B Q4 artifact. Record version, hashes, license, template, exact input counts, backend and settings. Run baseline J's SHORT CHAT (3 process-cold + 5 warm), medium 2K (5 warm), pressure 2K/4K (3 per step), conditional 8K (3), repeated generation (10 or 15 minutes), plus browser/editor coexistence and bounded runtime failure/privacy probes. All requests cap at 256 output tokens and 120 seconds. Mark skipped/stopped/missing evidence explicitly. Never equate benchmark time with FR-15 commit time or runtime serialization with C05 admission.

## Constraints and open questions

Synthetic data only; no Anonymous frontend/backend, frameworks, persistence reruns, private context, cloud inference, global services, trust/firewall/sleep changes, memory purging, swap disabling or wired-limit increases. Keep at least 50 GiB storage free and plan at least 6 GiB for OS/development. One model loaded and one generation at a time. AC required. Stop owned work on red pressure, warning for 10 seconds, swap growth over 512 MiB lasting 10 seconds, lost AC, thermal warning, responsiveness loss, wrong bind or unexpected egress/download. No escalation after a resource stop. Preserve failures and confirm process exit.

The owner recovered the original authorization: approximately 12 GB of total new model downloads and at most two model artifacts. Use a conservative hard accounting ceiling of 12,000,000,000 bytes; runtime software is separately authorized. Download only the prepared first candidate initially. A second artifact requires a specific experimental reason plus exact identity, size, quantization and cumulative-budget verification before acquisition. Proposed first artifact is Qwen/Qwen3-4B-GGUF, revision bc640142c66e1fdd12af0bd68f40445458f3869b, Qwen3-4B-Q4_K_M.gguf, 2,497,280,256 bytes (about 2.33 GiB), Apache-2.0. A second artifact is optional and depends on measured headroom and budget. GUI Activity Monitor access is pending OS computer-use permissions; command-line pressure/VM sampling works. Missing GUI/GPU observations must remain explicit if access stays unavailable.

## Affected components and intended approach

Only this plan and sanitized evidence under docs/evidence are intended repository changes. Raw evidence and standard-library benchmark scripts live outside the repository at `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01`, with private directory permissions and manifest/fixtures/telemetry/trials/summary/tools/models/cache/scratch subdirectories. This local resolved path is outside standard cloud-sync roots; third-party whole-host backups are not claimed inspected. No production data or canonical store is created.

## Work sequence

1. Repeat read-only host preflight before any acquisition. Completed below.
2. Review prerequisites and runtime alternatives; freeze one official native ARM64 runtime and artifact manifest. Confirm acquisition cap before weights download.
3. Retain pinned help/version; implement external synthetic recorder, one-second sampler and independent hard deadline/resource watchdog. Bind only 127.0.0.1; use ephemeral native authentication without logging its secret. Disable tools/download modes and prompt disk cache. Inspect process-owned listeners.
4. Recheck a 60-second idle baseline, then run bounded small-model fixtures. Count rendered prompts with the pinned runtime tokenizer. Record cache reuse independently from model residency. No silent truncation.
5. Grow only through safe context steps. Run repetition/coexistence and bounded negative/lifecycle probes. Actual Anonymous server coexistence and Windows runtime evidence remain NOT TESTED.
6. Stop runtime, verify no owned workers/listeners, sample 60 seconds after unload, summarize all attempted/skipped profiles, validate documentation and source preservation. Stop after experiment.

Acquisition is explicit and separate from inference. No automatic retries; partial downloads and failed attempts remain recorded. Resume only verified task-owned files. No unrelated process termination or broad cache cleanup.

## Validation strategy

Compare one-second pressure/swap/compression/RSS/CPU with phase baselines; retain UTC and monotonic clocks, page size and units. TTFT is dispatch to first nonempty answer text; native decode tokens/time supplies throughput. Record startup readiness separately if pure load is unavailable. Keep cold/warm and cache modes separate. Check ORCHID and record endpoints in medium/pressure output; correctness does not prove full input accounting. Test absent/wrong authentication, listener binding, logs/caches, oversize input, unavailable runtime, interrupted request and owned runtime death where resource gates allow. No real secrets/private files as probes. Validate new links, required plan sections, evidence consistency and before/after hashes; no application tests apply.

## Progress

- [x] 2026-10-06 22:14–22:15 JST: Host gate passed: M1 Pro/16 GiB, approximately 370 GiB free, AC before/after, 61 normal-pressure samples over 60.032 seconds. Swap 1,246.81 → 1,238.81 MiB; physical compressor 3.132 → 3.120 GiB; no new swapouts/pageouts.
- [x] Read both authoritative starting documents fully and reviewed requirements, scope, architecture and relevant data/security/runtime contracts.
- [x] Created external evidence directory and pre-change repository hash manifest.
- [x] Selected only llama.cpp b11440 (0.6.0-dev, commit 1a3011cc0); acquired its 11,970,453-byte official portable ARM64 archive, verified SHA-256, inspected native help/version. No package-manager/global service installation.
- [x] Prepared external standard-library harness and retained original recorder. Synthetic HTTP instrumentation self-check verifies empty role-event handling, visible TTFT, trailing usage/timings and native throughput arithmetic; it is not an inference benchmark.
- [x] Owner recovered acquisition cap: approximately 12 GB, at most two models; first candidate explicitly within budget.
- [ ] Acquire and verify prepared first model after repeated resource gate.
- [ ] Run synthetic workloads, coexistence and failure/privacy observations.
- [ ] Stop/unload, validate evidence and provide exact readiness verdict.
- [x] Preparation handoff: no owned runtime remains running; zero model artifacts; original repository files unchanged; two new documentation files only; 17 relative links resolve; external Python syntax passes. Inference acceptance remains incomplete.

## Discoveries

The latest GitHub semantic llama.cpp release v0.6.0 has no portable binaries. Official build releases do: b11440 has an 11,970,453-byte macOS ARM64 archive. Its SHA-256 is 822ea9475f9704da68905fc0735354840331e701136a36c1ad19360b283703e6. Runtime candidate evaluation favors llama.cpp's explicit tokenizer/context/timing controls and native API-key support. GUI permission was unavailable on two attempts. Use kernel pressure counters and five-second IORegistry aggregate GPU utilization as explicitly labeled instrumentation alternatives; Activity Monitor charts and subjective responsiveness remain unobserved. Neither Safari nor VS Code was found running in the scoped process-name check, so an actual browser/editor coexistence profile will need those apps open. No model download has occurred.

## Decision log

- 2026-10-06: Preserve the existing Mac J workload/guardrails; no persistence reruns, architecture redesign, production runtime selection or server-role change.
- 2026-10-06: Use an external isolated portable runtime instead of a package-manager/global service install. Experimental runtime choice does not require an architectural ADR unless later adopted for production.
- 2026-10-06: Select exactly one experimental runtime, llama.cpp b11440. Ollama v0.35.1 offers managed lifecycle and local-only configuration, but native caller restriction needs further design. MLX-LM v0.31.3 suits Apple Silicon yet adds a Python/model-format dependency surface and its server documentation warns against production use. Neither alternative is installed or benchmarked; no speed ranking is asserted.

## Final outcome

**Current continuation:** Budget blocker resolved; previous handoff below is historical. Acquisition and inference now proceed only after fresh resource checks.

See [preparation evidence and handoff](../../docs/evidence/v0-mac-local-model-runtime-feasibility.md). NOT_READY_FOR_VERTICAL_SLICE_0 because the required measurements remain unexecuted. The host gate passed and exactly one portable runtime was prepared. The explicit user limit cannot be recovered from available records, so weights acquisition waits for the pending clarification. No model/benchmark failure is inferred. GUI instrumentation and real browser/editor profile remain observational gaps. Validation found no modified/deleted original file, exactly this plan and the evidence file added, 17 resolving relative links, valid Python syntax and no owned runtime process. Resume with the pinned first artifact and the existing external harness after the cap is supplied; recheck idle conditions before loading.
