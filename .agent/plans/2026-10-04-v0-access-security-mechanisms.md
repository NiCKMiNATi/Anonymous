# V0 access and security mechanism evaluation

## 1. Status and purpose

Complete, 2026-10-04. Select evidence-supported V0 access mechanisms one level below the completed threat model. Deliver a reviewable evaluation and ADRs, not implementation.

## 2. Repository context

Anonymous is a local-first, single-owner, multi-client system in architecture/design. Read [project definition](../../docs/00-project-definition.md), [domain](../../docs/01-domain-model.md), requirements, scope, architecture, logical model, [security](../../docs/07-security.md), accepted ADRs 0001–0007 and specialist guidance. C03 owns access authority; C02 guards delivery; C08 owns persistence. Windows hosting confers no client authority.

## 3. Requirements and acceptance criteria

Create `docs/evaluations/v0-access-security-mechanisms.md` with client gate, realistic network comparison, concrete credential/enrollment/bootstrap/recovery/session/transport/storage/exposure decisions, trust diagrams, all 14 requested failure flows, all SD-01–SD-10 dispositions, threat/control coverage, future tests and six focused review passes. Record only finalized architectural choices in ADRs. Finish with a self-contained ChatGPT handoff.

## 4. Constraints and open questions

Preserve INV-001–INV-015, V0-D01–D06, ADR-0007 non-revival and CB-07 coherence. No code, schemas, physical database, API routes, framework, live keys, configuration, installs, benchmarks or Memory design. Actual OS/browser/runtime capabilities are unverified. Recovery-key custody preference was asked asynchronously; absent a choice, record a deployment prerequisite rather than invented user agreement. No private infrastructure is inspected or configured.

## 5. Components and approach

Evaluate browser clients C01, ingress C02, access C03, application admission C04/C05, runtime boundary C07, security persistence C08 and deployment C10. Preserve all history and provenance. Add evaluation, this plan and numbered ADRs only unless genuine baseline contradiction requires a documented correction. Consult current primary sources for product-specific claims; separate documented capability from local test evidence.

## 6. Work sequence

1. Finish full baseline reads and source research.
2. Resolve client form and compare practical private networks.
3. Specify credentials, lifecycle, protected delivery, TLS and local outage path.
4. Classify every security gate; write selected-choice ADRs.
5. Perform Security, Architect, Backend, Frontend, Data & Memory and QA author reviews; validate links, coverage and scope.
6. Reconcile this plan and provide completion/handoff. No deployment follows.

All work runs in `/Users/user/Desktop/Codes/Anonymous`. Changes are additive documentation; inspect existing paths before writing. A pre-task hash manifest is retained outside the repo to verify scope.

## 7. Validation strategy

Check relative links, unique IDs, 14 failure flows, SD-01–SD-10, TH-01–TH-12 and SG-01–SG-12 coverage, six reviews and future test coverage. Walk through enrollment replay, lost acknowledgments, restart, expiry, offline local access and recovery failure. Review sources against actual claims. Compare file hashes to prove no application/configuration/baseline edits. These are documentation checks, not passing hardware or security tests.

## 8. Progress

- [x] 2026-10-04: Read request, repository guidance and principal baselines; captured scope manifest.
- [x] 2026-10-04: Completed required baseline reads and consulted official Tailscale, WireGuard, OWASP, Mozilla, Microsoft and Apple sources.
- [x] 2026-10-04: Wrote evaluation and accepted design ADRs 0008–0011; configuration/evidence prerequisites remain explicitly classified.
- [x] 2026-10-04: Completed all six author reviews and structural/link/coverage/scope validation; no implementation test claim.
- [x] 2026-10-04: Recorded completion boundary, remaining gates and self-contained handoff state for the final response.

## 9. Discoveries

Responsive browser access is supported by the project direction; native mobile is outside V0. A network-provider-only HTTPS ingress could couple local access to provider availability. Browser device proof must not be mislabeled as hardware identity. Recovery custody is an unanswered operational preference. Official pricing currently supports this personal three-device deployment; eligibility is still a deployment check. Review found persistent credential-age regression and authentication-load starvation risks; the final design adds a durable security-time floor and a reserved bounded management lane. Corrected the client-principles citation to Project Definition §9.

## 10. Decision log

2026-10-04: Mechanism selection is expressly authorized by the attached request; implementation is not. Finalized design choices:

- [ADR-0008](../../docs/adr/0008-v0-private-network-and-browser-origin.md): responsive browsers, Tailscale remote reachability and independent private-CA HTTPS/local loopback origin. Plain WireGuard lacks a verified reachable endpoint in this environment.
- [ADR-0009](../../docs/adr/0009-v0-browser-device-and-session-credentials.md): local owner passphrase, separate approved browser credentials and opaque server-side sessions; no cloud app identity or self-contained-token shortcut.
- [ADR-0010](../../docs/adr/0010-v0-owner-bootstrap-and-recovery.md): controlled new-dataset ceremony and host-admin-plus-offline-proof recovery, preserving identity/history. Custody method remains an explicit owner configuration gate.
- [ADR-0011](../../docs/adr/0011-v0-access-coordinator-and-delivery.md): serialized access coordinator and durable invalidation/release protocol. Runtime caller authentication is required; actual mechanism is blocked on candidate evidence.

No existing ADR was changed. Numeric values are bounded V0 policy choices, not measured performance or universal security thresholds.

## 11. Final outcome

Created the [evaluation](../../docs/evaluations/v0-access-security-mechanisms.md), four ADRs and this plan. All 10 SD groups have explicit disposition across 19 matrix rows. The document contains 14 required failure flows, 14 future test groups, all 12 threat/control mappings, three trust/mechanism diagrams and six focused author reviews.

Validation passed on 2026-10-04: local Markdown links/fences; sequential sections and expected unique flow/test/threat IDs; full SD/SG coverage; valid classifications; review and ADR structure. Before/after SHA-256 manifests show exactly these six new Markdown files and no changes to existing files. Manual lifecycle reviews covered replay after revocation, selective logout, device-wide invalidation, clock/restart, closed partial bootstrap/recovery, lost acknowledgments, buffered delivery and offline local access. No application/security/hardware tests were run, no keys created and no infrastructure configured.

Remaining prerequisites: owner recovery/CA/disk-key custody, actual OS/browser/encryption/sync configuration, origin/certificate/network policy acceptance, storage/transport/exclusive-instance bindings, and runtime authentication/containment/capacity evidence. No client-form blocker remains. Detailed representation, runtime/model, framework, database, API and Memory decisions remain outside this task.

Recommended next bounded task is an access-environment and recovery-custody readiness record using actual device facts and owner choices, without implementation or live changes. Separately authorized runtime feasibility must collect containment/authentication evidence. Stop here; do not begin API design or implementation.
