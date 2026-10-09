# Architecture Baseline v0.1 execution plan

## Status and purpose

**Status:** Complete. **Date:** 2026-10-03.

Create a high-level architecture satisfying the selected Anonymous V0 boundary while preserving domain invariants. Stop before detailed data/API/security mechanisms, Memory algorithms, technology initialization, or application implementation.

## Repository context

Read fully: `AGENTS.md`, `docs/00-project-definition.md` (PD), `docs/01-domain-model.md` (DM), `docs/02-requirements.md` (RB), `docs/03-v0-scope.md` (V0), `.agent/PLANS.md`, and all specialist responsibility documents. V0 selects 25 required and 11 partial requirements, defers 11, and marks 4 inapplicable. It defines 15 release scenarios and six product-decision profiles. At task start, `docs/04-architecture.md` was a placeholder and the ADR directory contained only its marker. Initial file hashes were captured to protect previous work. The baseline and five ADRs now exist.

## Requirements and acceptance criteria

Replace the architecture placeholder with Architecture Baseline v0.1 covering eight requested views: context, deployment, logical components, dependency direction, trust, main request, failure paths, and evolution. Give every one of the 36 selected requirement subsets an architectural home, account for excluded requirements, and map all 15 release scenarios. Record only actual architectural decisions in numbered ADRs with status/context/decision/alternatives/consequences. Review Security, Data & Memory, Backend, Frontend, and QA concerns and report remaining gates honestly.

## Constraints and questions

PD/DM intent, RB semantics, and V0 selections remain unchanged. Do not edit `docs/05-data-model.md` or later placeholders. No schema, migration, concrete route, OpenAPI, Memory algorithm, UI design, dependency, framework, model/network installation, or application code. The user-reported hardware is available in V0; software versions, capacity, and runtime measurements remain unverified. No technology requires finalization to define the architecture boundaries; retain candidates and explicit later evidence gates.

## Affected areas and intended approach

Change only `docs/04-architecture.md`, this plan, and ADRs for decisions made here. Evaluate a single authoritative V0 application instance, modular internal responsibilities, equal clients, server-owned canonical state, explicit Context Builder, Anonymous-owned model/persistence ports, and layered private access. Keep compile-time dependency direction distinct from runtime call flow. Define persistence/authorization checkpoints as guarantees, not transaction or credential designs. Use repository-native text diagrams and tables; no external design artifact is needed.

## Work sequence

1. Read required material and snapshot repository file hashes.
2. Draft the eight architecture views, ownership/dependencies, failure behavior, traceability, and later decision gates.
3. Write cohesive ADRs for actual topology, modularity, model/context, persistence, and access-boundary choices; link them to the baseline.
4. Perform five author review passes and repair ambiguity, uncovered cases, or conflicting ownership.
5. Run inline read-only documentation checks from the repository root: coverage, classification consistency, references, diagrams/fences, links, ADR structure/status, and file-hash scope. Reconcile the plan and report completion without proceeding into data modeling.

Resume from the current plan/document if interrupted, preserving unrelated edits. No operational migration, rollback, or runtime test is involved.

## Validation strategy

Cross-check the architecture against V0-D01–V0-D06, all 36 selected requirement IDs, all 15 V0-AC scenarios, and INV-001–INV-015. Ensure no deferred feature is introduced by an extension boundary and no selected security/failure behavior is orphaned. Review saving before inference, complete output plus provenance before success, unknown outcomes, one active generation per conversation, revocation at ingress and delivery, and runtime work surviving a server restart. Check that domain/application code depends on owned contracts, not adapters. Compare hashes so PD/DM/RB/V0, role guidance, and all downstream placeholders stay unchanged. Passing these checks validates documentation only.

## Progress

- [x] 2026-10-03: Read all required documents and responsibilities; inspected placeholder/ADR directory and captured initial hashes.
- [x] 2026-10-03: Drafted Architecture Baseline v0.1 with eight views, ten named responsibilities, and five cohesive ADRs.
- [x] 2026-10-03: Completed Security, Data & Memory, Backend, Frontend, and QA author review passes; findings recorded in architecture §13.
- [x] 2026-10-03: Completed structural/scope verification and prepared completion report.

## Discoveries

- V0 has multiple concurrent client sessions despite one user; a client connection cannot own durable conversation or execution state.
- V0-D04 already fixes persistence confirmation/retry behavior; the architecture needs responsible components and boundaries, not new retry policy.
- Model runtime separation means server-process restart does not prove inference stopped. Recovery needs explicit responsibility without silently replaying uncertain work.
- Canonical persistent ownership and derived canonical/compressed state are different; the latter is not a V0 feature.
- Source inspection confirmed all 36 selected requirement classifications and all 15 release scenarios. No authoritative-source conflict was found.
- Resolved local-link filenames against the actual repository: downstream files are `06-memory-design.md`, `07-security.md`, and `08-api-design.md`; they remain untouched.

## Decision log

- 2026-10-03: Use five focused author review passes, not mandatory specialist-agent invocation.
- 2026-10-03: Preserve existing requirement/scope documents and record architectural decisions in new ADRs. Detailed technology decisions remain evidence-gated rather than falsely accepted.
- 2026-10-03: Use text diagrams to keep every view directly readable in the repository without rendering dependencies.
- 2026-10-03: Accepted [ADR-0001](../../docs/adr/0001-shared-server-and-canonical-ownership.md): shared client/server boundary and server canonical ownership. Rejected client-owned history/peer synchronization and local bypass because they conflict with V0 continuity or add excluded work.
- 2026-10-03: Accepted [ADR-0002](../../docs/adr/0002-modular-monolith-server.md): one active modular application instance with a separate private local runtime. Distributed services/instances are unnecessary for V0; recovery must account for runtime work surviving the app.
- 2026-10-03: Accepted [ADR-0003](../../docs/adr/0003-context-and-model-execution-boundary.md): explicit Context Builder and application-owned model contracts preserve privacy, actual input attribution, and runtime independence.
- 2026-10-03: Accepted [ADR-0004](../../docs/adr/0004-persistence-port-boundary.md): purpose-specific owned persistence contracts protect confirmation/reconciliation semantics without an engine/schema commitment.
- 2026-10-03: Accepted [ADR-0005](../../docs/adr/0005-layered-private-access.md): distinct network, device, session, resource, and delivery checks; no public service exposure or model-controlled private release.

These statuses record decisions made within the authorized architecture task, not independent specialist approvals. Framework/runtime/network/storage candidates remain provisional.

## Final outcome

Completed [Architecture Baseline v0.1](../../docs/04-architecture.md), five ADRs, and this plan. The baseline maps 25 required and 11 partial subsets, accounts for the 11 deferred and 4 inapplicable requirements, and assigns all 15 release scenarios to components. All 15 domain invariants remain represented. Seven text diagrams plus the logical ownership table provide the eight views.

Validation actually performed from the repository root using inline Python and source inspection:

- Parsed the V0 selection matrix and compared every selected architecture ID/classification: exact match, 36 unique rows (25 required / 11 partial).
- Compared scenario headings with architecture rows: 15 unique scenarios, all with owners; checked ten defined component IDs and all 15 invariant references.
- Checked requirement references against RB, five ADR status/structure records, all five review records, Markdown fence balance, local link destinations, obsolete naming, and trailing whitespace. All passed.
- Compared pre/post SHA-256 file inventories, including untracked files: only the architecture baseline, five new ADRs, and this new plan changed; no deletions or downstream/source edits.
- Performed semantic review of V0-D01–V0-D06, all scenarios, source/derived distinctions, dependency direction, private boundaries, client parity, and failure/recovery responsibilities. Findings and dispositions are in architecture §13.

No runtime tests or hardware benchmarks ran: this is documentation validation only. Exact software inventories, hardware performance/input limits, authentication/transport mechanisms, persistence/provenance/correlation representations, single-instance/recovery mechanisms, and detailed context selection remain explicit pre-implementation or pre-access gates in architecture §12. No technology was finalized; no schema, concrete API contract, dependency, framework, application code, or later design document was introduced. No substantive task deviation occurred. Stop here; data modeling requires a new task.
