# V0 Mac client and alternate runtime evidence

## 1. Status and purpose

Complete, 2026-10-04. Verified the currently available intended Mac client's environment and documented optional development/alternate inference feasibility. Windows remains the initial authoritative server. No implementation or configuration.

## 2. Repository context

The definition, domain, requirements, scope, architecture, logical model, security baseline, mechanism evaluation, environment baseline and ADRs 0001–0012 were fully read in this conversation. Prior reads were reused after unchanged source hashes were checked; relevant runtime evidence and affected passages were refreshed. The [environment baseline](../../docs/evidence/v0-access-environment-baseline.md) contains the prior Mac observations; the new Mac baseline supplies expanded evidence. The [runtime feasibility plan](../../docs/evidence/runtime-feasibility-plan.md) defines Windows-first evidence. Repository/plan/specialist instructions apply. No Anonymous application is implemented, and runtime/security deployment gates remain open.

## 3. Requirements and acceptance criteria

Create `docs/evidence/v0-mac-client-runtime-baseline.md` with sanitized hardware/OS/tool inventory, browser/CA/Tailscale readiness, current primary-source comparison of Ollama/llama.cpp/MLX-LM, theoretical memory envelope, exact future benchmark procedure, client/development/alternate-runtime role separation, readiness/decision matrices and six author reviews. Update only newly verified Mac facts in the environment baseline. A benchmark may run only if exact runtime/model/quantization and safe bounded no-download execution are established.

## 4. Constraints and open questions

Host gate must be macOS before repository edits; `uname -s` returned Darwin. User now identifies this available Mac as the intended client. Read-only inspection only: no installs, updates, settings/trust/DNS/firewall changes, model downloads, credentials, app code or stress tests. Sanitize account/serial/UUID/address/SSID/key material before output. No inference migration or server-role change is authorized. Absence is limited to inspected locations/environments.

## 5. Components and approach

C01 client evidence; C10 OS/operations; C07 optional runtime capability; C03 trust prerequisites. Preserve C08 Windows-owned canonical history. Anticipated edits: this plan, new Mac baseline and narrow Mac evidence updates in existing environment baseline. No ADR for facts; architectural alternatives remain proposals.

## 6. Work sequence

1. Confirm macOS and snapshot file hashes (done).
2. Collect bounded filtered hardware/storage/security/power and installed-tool observations without settings changes.
3. Read official browser/network/runtime sources and classify facts versus hypotheses.
4. Check existing runtime/model opportunity; if any prerequisite missing, do not benchmark.
5. Draft reproducible future workloads, metrics, limits and role/security assessments.
6. Perform six author reviews, validate links/coverage/scope and complete handoff; stop.

## 7. Validation strategy

Check observation provenance and units; no hypothetical throughput. Verify all requested tools/candidate/runtime metrics and client scenarios are classified. Check no inferred Windows readiness or remote inference permission. Validate local links, source consistency, allowed change set and sanitization; no application test tooling.

## 8. Progress

- [x] macOS execution gate, instructions and scope manifest.
- [x] Read-only evidence and current official sources, 2026-10-04.
- [x] Runtime/model prerequisite assessment and future benchmark procedure, 2026-10-04.
- [x] Documents and six author review passes, 2026-10-04.
- [x] Final documentation validation and prepared handoff, 2026-10-04.

## 9. Discoveries

Prior inventory had no usable filesystem observation and only checked standard Tailscale application location. Bounded follow-up established internal APFS/SSD capacity and broadened tool discovery without searching arbitrary private environments. Verified M1 Pro, 8 CPU/14 GPU cores, 16 GiB, about 400.63 GB free, FileVault On, application firewall Off and one-minute configured idle sleep. Swap was already about 3,958 MiB used; this is not attributed to inference or a performance result.

An additional uv-managed Python 3.12.14 with pip 26.2.1 was found alongside default Python 3.9.6/pip 21.2.4. Neither inspected environment has MLX, MLX-LM or PyTorch. No supported runtime/exact local model/quantization combination was established; therefore no benchmark was permitted or attempted. PATH contains pnpm, but its version/usability remains unknown rather than invoking a possible bootstrap. Mac Tailscale remains not found in inspected locations, not globally proven absent.

## 10. Decision log

2026-10-04: User authorizes this Mac as client evidence target and optional runtime evaluation. Windows ownership remains unchanged. No new architecture decision.

2026-10-04: Keep Ollama, llama.cpp and MLX-LM as candidates only. Proposed 3B–4B then 7B–8B quantized screens are hypotheses; 12B–14B is conditional. A networked Mac inference node remains deferred because the accepted initial runtime is server-local. No ADR for machine facts.

## 11. Final outcome

Created `docs/evidence/v0-mac-client-runtime-baseline.md` with all A–N deliverables, six author reviews, four reproducible synthetic workloads, telemetry/metric definitions and explicit no-benchmark outcome. Updated only Mac facts and their follow-up provenance/checklist status in `docs/evidence/v0-access-environment-baseline.md`. No accepted decision, implementation, installation, download or configuration changed.

Validation: file-hash manifest identified exactly the three intended Markdown changes and no deletions; 32 relative links across those files passed; A–N sections, all 17 requested tool entries, required status vocabulary, four workloads/metric coverage, code fences and sensitive-path/UUID screening passed. Manual Operations/Security/Frontend/Runtime/Architect/QA reviews checked scopes and evidence claims. Corrected two GiB roundings and the logout/revocation acceptance reference. No runtime or browser test is claimed.

Remaining gates: Windows evidence and owner custody/naming/uptime choices; Mac Tailscale/CA configuration and Safari acceptance; exact runtime/model acquisition, measured capacity/coexistence and private-runtime containment. Recommended next bounded task is read-only inventory on the available intended Windows server, with owner-designated storage/admin context. An optional Mac experiment requires a separate authorized acquisition/benchmark task and the new baseline's safety bounds. Stop here; no implementation, persistence selection or authority migration.
