# V0 local runtime feasibility planning

## 1. Title, status, and purpose

Status: complete, 2026-10-03 (documentation task only). Produce a reproducible hardware experiment plan, not benchmark results or a runtime selection. Deliver `docs/evidence/runtime-feasibility-plan.md` and a ChatGPT handoff footer.

## 2. Repository context

Read [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md), [requirements](../../docs/02-requirements.md), [V0 scope](../../docs/03-v0-scope.md), and [architecture](../../docs/04-architecture.md). The server and clients do not exist. Windows hardware is user-reported, not verified: Ryzen 7 5700X, RTX 3070 8 GB, 32 GB RAM, 1 TB NVMe. Optional Mac comparison: M1 Pro, 16 GB unified memory. C05/C06/C07/C10 need lifecycle, budgeting, and coexistence evidence before implementation. Backend, QA, and Security responsibilities inform author review; no subagents are requested.

## 3. Requirements and acceptance criteria

The document must distinguish mandatory Windows evidence from optional Mac/tuning work; define candidate selection and exact acquisition/pinning prerequisites, synthetic fixtures, measurement commands, repetitions, cold/warm conditions, context limits, offload, memory, timing, coexistence, failures, and reporting. Trace to V0-AC-01/02/06/07/08/09/11/12/14 and relevant requirements. No invented results or performance acceptance targets. No final runtime/model, database, API, or framework choice.

## 4. Constraints and open questions

Only documentation is authorized. Do not install, download models, run hardware benchmarks, change application code, or configure networking now. Execution commands are future operator instructions, not verified hardware results. Use synthetic inputs and loopback runtime endpoints; separate online acquisition from offline measurement. Exact OS/drivers, free resources, model artifacts, acceptable performance, and real server footprint remain unknown. Runtime concurrency does not implement Anonymous per-conversation admission. Surrogate load cannot prove actual server coexistence.

## 5. Affected components and intended approach

Create only the requested evidence-plan document and this ExecPlan. Keep existing baselines and ADRs unchanged. Describe C07 compatibility and C05/C10 lifecycle evidence without implementing adapters. Runtime outputs are experimental data, not authoritative conversation history or FR-15 commit timestamps. Preserve raw measurement artifacts outside the repository and publish sanitized summaries later.

## 6. Work sequence

1. Review source constraints and current official runtime/OS documentation.
2. Define a bounded exploratory matrix and promotion criteria; write reproducible Windows steps and optional Mac differences.
3. Include collection snippets within Markdown, definitions, failure classification, evidence templates, limits, and handoff.
4. Check links, required coverage, command syntax where possible without installation/execution, and changed-file scope. Reconcile this plan.

Commands in the deliverable are proposed execution procedures and must be checked against pinned binary help on the actual host. Retain failed trials; correct configuration under a new trial ID rather than overwriting evidence.

## 7. Validation strategy

Documentation review checks measurement units, true streamed content timing versus HTTP headers, actual token counts, prompt-cache effects, load versus process startup, machine versus process memory, input plus output capacity, and no false application-acceptance claims. Verify local Markdown targets and requirement/scenario IDs. Parse embedded Python snippets without running runtime requests; inspect PowerShell portability and bounded cleanup. Compare file hashes before/after.

## 8. Progress

- [x] 2026-10-03: Reviewed repository requirements, hardware, scope, architecture, and specialist concerns.
- [x] 2026-10-03: Started official-source verification for Ollama, llama.cpp, and measurement interfaces.
- [x] 2026-10-03: Wrote experiment plan with embedded collection commands, mandatory/optional evidence, candidate controls, result templates, and ChatGPT handoff.
- [x] 2026-10-03: Completed consistency, Python syntax, reference, scope, and author review; documented Windows/PowerShell execution limitations.

## 9. Discoveries

No runtime feasibility evidence exists in the repository. Candidate defaults and controls vary by version; binary/version/help and model hashes must accompany results. Required release guarantees include orphaned inference handling after application termination, not merely a throughput score.

PowerShell is unavailable in the preparation environment. WDDM per-process GPU memory can be unavailable; the plan provides total-device and Windows shared-memory observations without inventing zeros. Runtime-cold does not mean OS disk-cache-cold. Review corrected per-launch logs to avoid overwriting evidence and added recorder PIDs for targeted interruption probes.

## 10. Decision log

- 2026-10-03: Use Ollama and llama.cpp as test candidates, not selected dependencies. Compare identical model bytes where supported; otherwise label runtime/model comparisons as confounded.
- 2026-10-03: Keep initial resource-reserve experiments explicitly synthetic. Actual server coexistence and per-conversation refusal remain later integration gates. No architectural ADR is created because no architecture choice is being finalized.

## 11. Final outcome

Created [runtime-feasibility-plan.md](../../docs/evidence/runtime-feasibility-plan.md), including eight mandatory evidence groups, a staged two-runtime/model-size/quantization matrix, Windows inventory and memory/GPU sampling, four embedded standard-library Python helpers, cold/warm/context/offload/coexistence/lifecycle/offline procedures, optional Mac steps, and pending-result templates. All proposed numbers are experiment controls rather than invented results or product targets.

Validation passed: four embedded Python programs parse; all local links and referenced requirement/scenario IDs resolve; Markdown fences and whitespace are consistent; requested measurements and eight evidence groups are present. Backend, QA and Security concerns were reviewed by the author, not independent agents. File hashes show no changes to pre-existing baselines/ADRs/application areas. The only task artifacts are this ExecPlan and the requested document.

No dependencies, models, runtimes, services or networks were installed/configured; no runtime requests, Windows commands or benchmarks were executed. No candidate is selected and no ADR is warranted yet. Next action is operator execution of the mandatory Windows procedure on actual hardware, followed by sanitized evidence review and explicit acceptance targets; actual server integration and security/data/API design remain later gates.
