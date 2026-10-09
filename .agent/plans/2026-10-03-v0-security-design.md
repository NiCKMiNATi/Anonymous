# V0 security design and threat model

## 1. Title, status, and purpose

Status: complete, 2026-10-03. The user asked to continue after the logical-model completion report recommended Security design. This was treated as authorization for the next documentation task, not implementation or hardware benchmarking. Replaced `docs/07-security.md` with a substantive V0 security design/threat model, with explicit enforcement outcomes, evidence gates and unresolved mechanism decisions. The completion report includes a CHATGPT HANDOFF SUMMARY.

## 2. Repository context

Read [repository guidance](../../AGENTS.md), [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md), [requirements](../../docs/02-requirements.md), [V0 scope](../../docs/03-v0-scope.md), [architecture](../../docs/04-architecture.md), [logical data model](../../docs/05-data-model.md), ADR-0001–0006 and [specialist guidance](../../docs/agents/README.md). The earlier phases define stable identity, PRIVATE-only operation, controlled owner provisioning, finite sessions, device-wide revocation, current delivery guards, durable history and restart reconciliation. No application exists; the security document is a placeholder. Hardware/software configuration and runtime feasibility are unmeasured. Memory and API design remain pending.

## 3. Requirements and acceptance criteria

Produce a bounded threat model, assets/actors/trust boundaries, owner/device/session lifecycle, operation/resource authorization, provisioning/recovery requirements, revocation races, client and runtime privacy enforcement, secrets/diagnostics and local/network protections. Map selected SEC/PRIV requirements and relevant V0 scenarios to objective future checks. Separate existing decisions, new logical design decisions and unresolved mechanism proposals. Include reasons/owners/deadlines for open issues and make readiness limits explicit. Read current primary security guidance for relevant controls; no claim of certification or implementation testing.

## 4. Constraints and open questions

Preserve source documents 00–05, existing ADRs, INV-001–015 and V0-D01–06. No code, physical data design, API routes, frameworks, dependencies, live configuration, secrets, private datasets or benchmark results. Do not finalize Tailscale, a runtime, authentication technology, privacy taxonomy or arbitrary session durations without evidence. Credential/device proof, deployment origins, actual client support, bootstrap/recovery and session/transport parameters need specific later decisions before an access-capable build. This task can complete the design/threat-model artifact while clearly leaving those implementation gates open.

## 5. Affected components and intended approach

C03 owns access policy and lifecycle; C02 enforces ingress and current delivery; C04/C05 enforce operation ownership/admission; C06/C07 constrain context/runtime use; C08 preserves access/recovery evidence; C01 renders safely; C10 supplies protected deployment and diagnostics. Expected files: this plan, `docs/07-security.md`, README status only, and a warranted logical security ADR if the work introduces an independently significant decision. Leave Memory/API placeholders untouched. Hash all prior files before edits to verify scope.

## 6. Work sequence

1. Review baselines, accepted ADRs, role concerns and current primary security references; create plan before drafting.
2. Draft the threat model and operation/lifecycle controls with explicit failure handling and design gates.
3. Evaluate any durable new policy for an ADR, with alternatives and consequences; do not manufacture a mechanism selection.
4. Conduct focused author passes for Architect, Security, Backend, Frontend, Data & Memory and QA. Record corrections and remaining risks honestly.
5. Check traceability, local links, IDs, diagrams, open-decision ownership and allowed-file hashes; finalize README, plan and handoff. Stop before API/implementation/benchmarking.

## 7. Validation strategy

Use documentation-only scripts and manual threat/failure walkthroughs. Check every selected SEC/PRIV ID maps to controls and future cases, each threat has an owner/mitigation/test, and each unresolved gate has rationale and deadline. Walk through unknown LAN peer, stale/replayed authority, two sessions per device, lost acknowledgment, simultaneous revocation/delivery, bootstrap/recovery races, offline local use, hostile rendered output, diagnostic leakage, and startup uncertainty. Text diagrams must match authoritative ownership. Verify local links and final file-hash scope; external references are reviewed guidance, not release evidence.

## 8. Progress

- [x] 2026-10-03: Read current repository context and relevant source/security requirements; captured before-edit hashes.
- [x] 2026-10-03: Created ExecPlan and started primary-source security guidance review.
- [x] 2026-10-03: Drafted security baseline and ADR-0007 for durable logical access-lifecycle decisions.
- [x] 2026-10-03: Completed Architect, Security, Backend, Frontend, Data & Memory and QA author reviews; incorporated corrections.
- [x] 2026-10-03: Passed structural/scope checks; finalized README, plan and completion/handoff content. No subsequent phase begun.

## 9. Discoveries

Existing ADR-0005 already decides layered private access and revocation enforcement. This task must make controls reviewable without presenting those decisions as new or equating local/overlay reachability with authentication. The logical model separates original commit timestamps from security expiry and requires current authority even for duplicate-result reconciliation.

Review clarified that transport bytes released before invalidation may arrive afterward; the test must observe server release/admission ordering, not rely only on receipt time. A separate runtime process is not proof of file/network containment. Device proof is not necessarily hardware binding. Application-managed secrets must not leak, but this is not automatic detection/redaction of arbitrary user-pasted source content. Missing access state cannot establish a fresh installation. No conflict requiring changes to source baselines was found.

## 10. Decision log

- 2026-10-03: Continue with Security design as the immediately recommended next task. Keep benchmark execution separate because no actual hardware evidence or explicit benchmark instruction was supplied.
- 2026-10-03: Use plain-text diagrams and documentation-only checks; no rendering dependencies or application tooling.
- 2026-10-03: Accepted [ADR-0007](../../docs/adr/0007-access-invalidation-and-owner-recovery.md): invalidated sessions do not revive after device restoration; first-owner setup requires positively new-dataset status and controlled proof; approval replay cannot undo later revocation. Current admission/delivery remains coordinated with invalidation. Mechanisms stay open.
- 2026-10-03: Recorded 10 decision groups SD-01–10. SD-01–09 block applicable access/execution implementation or private use until concrete decisions/evidence exist; SD-10 covers deferred features. No arbitrary validity durations or technology defaults were inferred.
- 2026-10-03: Used seven primary OWASP references for authorization, authentication, session management, TLS, CSRF, XSS and logging, linked beside the relevant controls. They inform design, not a compliance or tested-security claim.

## 11. Final outcome

Delivered `docs/07-security.md` with 16 sections, seven asset groups, six trust boundaries, 12 mapped threats, 12 logical controls, three text diagrams, an operation-authority matrix, mechanism alternatives, 10 assigned decision gates and 18 objective future tests. Created one warranted logical ADR and changed README's status paragraph only. Existing documents 00–05, ADR-0001–0006, Memory/API placeholders, runtime feasibility plan and other files were preserved.

Six focused author reviews completed. Architect confirmed dependency/scope preservation; Security clarified credential/theft limits and session fixation; Backend clarified admission versus receipt and durable revocation versus uncertainty; Frontend covered rendering/forgery/cache/relogin; Data & Memory confirmed history and credential/source distinctions; QA checked traceability and race/failure observability. These were not independent agent approvals or an external audit.

Validation passed through local read-only checks: exact coverage of all 11 selected SEC/PRIV requirement subsets; unique complete TH/SG/SD/ST IDs; slash/range references within defined IDs; all threats mapped to controls/owners/tests; all decision rows complete; 16 ordered sections; three balanced text diagrams; local Markdown links. Seven external primary guidance pages were opened and relevant passages reviewed. Manual walkthroughs covered unknown peers, stolen/invalid authority, first-owner/recovery races, old approval replay, lost acknowledgments, current delivery, clock/restart uncertainty, local offline access, hostile rendering/runtime input, diagnostic leakage and resource pressure. A file-hash comparison found exactly the intended four files changed; README diff was status-only.

No application code/tests, physical schema/API design, dependencies, configuration, network probes, runtime selection, benchmarks or live security testing occurred. Concrete proof/recovery policy, session values, client/origin/transport configuration, custody, runtime containment and race-enforcement mechanisms remain unresolved by design and explicitly block dependent work. The completed artifact is a logical security/threat baseline, not an implementation-ready authentication/deployment specification.

Next recommended separately authorized task: select and document concrete V0 access/provisioning/recovery/session/deployment mechanisms using actual OS/browser configurations and owner recovery-custody preferences, with ADRs and dependent API/persistence contracts. Actual-hardware runtime feasibility/containment evidence is separate. Do not proceed automatically to implementation, Memory, API or benchmarking from this plan.
