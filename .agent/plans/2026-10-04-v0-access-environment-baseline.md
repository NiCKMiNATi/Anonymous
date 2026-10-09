# V0 access environment and security operations baseline

## 1. Status and purpose

Complete, 2026-10-04. Collect safely observable environment facts and separate owner choices, deployment values and later evidence dependencies. Deliver a baseline and owner questionnaire; do not deploy or implement.

## 2. Repository context

Anonymous remains in architecture/design. The [definition](../../docs/00-project-definition.md), [domain](../../docs/01-domain-model.md), requirements, V0 scope, architecture, logical model, security baseline and accepted ADRs 0001–0011 govern this work. Their full reads from the preceding evaluation remain available in this conversation; verify unchanged files and reread affected passages. Read repository/plan/specialist guidance and the completed [mechanism evaluation](../../docs/evaluations/v0-access-security-mechanisms.md). Tailscale, private-CA HTTPS, browser credentials, opaque sessions and coordinated invalidation are already selected, not candidates to reopen.

## 3. Requirements and acceptance criteria

Create `docs/evidence/v0-access-environment-baseline.md`, titled “V0 Access Environment & Security Operations Baseline v0.1”. Include structured environment facts, safely labeled verification steps, custody alternatives and owner questions, certificate/hostname inputs, operational-limit classifications, exclusive-instance and storage requirements, official Tailscale/browser facts, every remaining security gate with separate API/implementation consequences, five author reviews and completion evidence. End the document with “Owner Input Required”. Supply a self-contained ChatGPT handoff.

## 4. Constraints and open questions

No live configuration, keys, certificates, trust-store edits, network/firewall/router changes, encryption changes, installs, app code, API routes, database selection or benchmarks. Do not publish private addresses, account names, serials or credentials. Local execution access does not establish access to Windows/iPhone or identify the intended Mac uniquely. Unknown facts stay NEEDS_LIVE_VERIFICATION; actual owner choices stay NEEDS_OWNER_INPUT. No answer is not approval. Preserve ADR-0007–0011 and source-history semantics.

## 5. Components and approach

Document C10 operational prerequisites, C01 browser evidence, C03 access/custody and C08 ownership/storage obligations without physical representation choices. Only this plan and the new evidence document are anticipated. Add an ADR only for a genuinely new durable decision; prefer recording already-established requirements and explicitly gated recommendations. Capture a pre-task file-hash manifest outside the repository.

## 6. Work sequence

1. Confirm source state and create plan.
2. Ask a few essential owner custody choices while progressing independently.
3. Safely inspect minimal local OS/browser/storage facts, with no device/network scanning; distinguish the execution host from intended deployment devices.
4. Check current official vendor documentation and prepare read-only checklists for inaccessible devices.
5. Write inventory, policies, limits, gate matrix and final owner questionnaire.
6. Perform Security, Architect, Backend/Operations, Frontend and QA author reviews; validate links, complete gate coverage and change scope.
7. Record outcome and handoff, then stop.

Working directory: `/Users/user/Desktop/Codes/Anonymous`. Read-only commands require neither installation nor state changes; permission-denied observations remain unknown. No remote access is inferred or configured.

## 7. Validation strategy

Trace all 19 mechanism-evaluation decision rows and every remaining configurable gate. Check fact provenance, observation timestamps, no invented Windows/iPhone data, safe action labels, custody option/consequence completeness, separate API versus implementation deadlines, local links, document structure and five review records. Compare before/after hashes; distinguish documentation validation from future deployment/security tests.

## 8. Progress

- [x] Read attached request and refreshed repository/plan/specialist instructions; captured file manifest.
- [x] 2026-10-04: Confirmed prior fully read starting baselines/ADRs unchanged by hashes; refreshed relevant passages and current official Tailscale/Microsoft/Apple/Mozilla/WebKit evidence. Recorded five bounded Mac observation groups.
- [x] 2026-10-04: No substantive owner answers received. Kept custody/uptime choices unresolved and ended baseline with eight decision-oriented questions.
- [x] 2026-10-04: Created baseline and ADR-0012; completed Security, Architect, Backend/Operations, Frontend and QA author reviews.
- [x] 2026-10-04: Validated structure, links, labels, counts, full gate mapping and change scope; recorded final outcome and handoff state.

## 9. Discoveries

The prior task left owner custody unanswered. Its accepted choices intentionally do not establish installed OS/browser versions, actual encryption state or deployment readiness.

Read-only execution-host evidence: Apple M1 Pro/16 GiB, macOS 27.0.1 build 26A434, installed Safari 27.0.1 build 22625.1.29.11.28, FileVault On. These observations do not establish maintenance currency or intended-client identity uniquely. Tailscale/Edge were not observed at standard Mac app locations; alternate installation remains unknown. A workspace-volume query returned no usable fact. No Windows/iPhone/account/network inspection occurred.

Reviews identified that an Edge About page may initiate updates, so the checklist uses the version page; a missing iPhone root-trust toggle need not mean unsupported CA trust; a local lock cannot fence independent host copies; replacing a leaf certificate does not by itself invalidate a stolen prior chain. These distinctions are explicit in the final baseline.

## 10. Decision log

2026-10-04: The user authorizes observation and design inputs only. No custody proposal became an owner-approved choice.

[ADR-0012](../../docs/adr/0012-v0-local-storage-and-authority-transfer.md) accepts one warranted operational restriction: V0 primary data is protected server-local storage, excluding network-mounted/cloud-synced primary paths; copied/restored data cannot automatically become authoritative while the original writer might live. It records the distinction between provable local exclusion and trusted operational transfer, without database/lock selection or a new backup feature. ADRs 0001–0011 remain unchanged.

CA hierarchy/lifetime and key-copy recommendations remain explicit owner/PKI inputs; no ADR is created for machine facts, versions or unchosen deployment values.

## 11. Final outcome

Created the [evidence baseline](../../docs/evidence/v0-access-environment-baseline.md), this plan and ADR-0012. The baseline has 32 fact inventory rows, 24 safely labeled verification steps, seven custody decisions, 19 operational-limit classifications, 28 gate rows mapping all 19 ME decisions, eight final owner questions and five author reviews.

Validation passed: local links/references, allowed statuses/action labels, full sequential fact/check/limit/question coverage, original ME-row coverage, populated supplier/deadline/API/implementation columns, required final heading, and ADR/plan structure. A hash comparison confirmed exactly three new Markdown files and all existing documents unchanged. Manual review checked safe observation boundaries, sensitive-output minimization, missing facts, no implicit custody approval, single-instance/storage failure, TLS replacement and browser limitations. Only bounded Mac OS/app metadata and FileVault queries ran; no application/acceptance tests or benchmarks.

Owner choices, Windows/iPhone/designated-Mac verification and final deployment values remain pending. Persistence/reconciliation/exclusivity and transport release evidence block finalizing affected API contracts; runtime containment/capacity blocks execution promises and implementation. Custody and real-device support block their respective provisioning/integration/private-use stages. Deferred features remain deferred.

No installs, live configuration, credentials/certificates, API endpoints, app code, physical database, runtime/model/framework selection or backup design occurred. Next bounded task: obtain the actual owner choices and safely inspect unverified intended devices under legitimate access, returning sanitized facts. Stop here; no persistence selection, API design, runtime benchmark or implementation begins.
