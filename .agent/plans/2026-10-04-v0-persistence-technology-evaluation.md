# V0 persistence technology evaluation

## 1. Status and purpose

Complete, 2026-10-04. Evaluated SQLite, PostgreSQL and MongoDB against Anonymous's established V0 semantics. SQLite is the requirement-level recommendation; final selection is deferred under the existing actual-host evidence gate. No persistence implementation or physical design.

## 2. Repository context

The project is architecture/design only. The project definition, domain, requirements, scope, architecture, logical model, security baseline, mechanism evaluation, environment baselines and accepted ADRs 0001–0012 were fully read in this conversation. Unchanged reads were reused after hash verification; logical/transaction boundaries, ADRs and specialist guidance were refreshed. The only changed older evidence document was the Mac follow-up authored/read in the preceding task. [ADR-0004](../../docs/adr/0004-persistence-port-boundary.md) owns replaceable persistence contracts; [ADR-0012](../../docs/adr/0012-v0-local-storage-and-authority-transfer.md) excludes network/synced primary storage and automatic authority transfer. Mac facts do not verify Windows deployment.

## 3. Requirements and acceptance criteria

Create `docs/evaluations/v0-persistence-technology-evaluation.md`, with ranked comparison, eight operation-level atomicity assessments, V0 versus future concurrency, relationships/metadata/evolution/security/operations/Python/search evaluation, migrations and explicit recommendation or evidence blocker. Create a selection ADR only if justified. Record six author review passes and a self-contained ChatGPT handoff.

## 4. Constraints and open questions

Preserve INV-001–INV-015, FR-15 identity/order/absolute-commit-time separation, CB-01–CB-07, one active/uncertain generation per conversation and durable revocation. No client database access, multi-writer authority or migration while old authority is uncertain. No installs, database creation, SQL, physical tables/columns/collections/keys/index design, ORM selection, migration files, API/code or configuration. Windows hardware is REPORTED_NOT_VERIFIED; filesystem/encryption/OS/storage/permissions remain host gates.

## 5. Components and approach

C08 technology behind Anonymous-owned ports; C03/C04/C05 depend on outcome/consistency contracts, not database products. Candidate evidence from official database/driver documentation, with dates and limits. Actual changes: the evaluation and this plan only. No selection ADR or authoritative-baseline changes because the actual-host gate is unclosed. Source history remains authoritative; derived search/memory stores remain future/rebuildable.

## 6. Work sequence

1. Snapshot repository, verify prior full-read sources and refresh relevant logical/security material.
2. Research primary sources for candidate atomicity/concurrency/platform/driver/backup capabilities.
3. Derive mandatory criteria and future compatibility; compare operations, costs and migration risks.
4. Decide whether requirement-level selection is justified separately from host verification; document ADR only if so.
5. Perform six author reviews, links/scope/semantic/exclusion checks, complete plan and handoff; stop.

## 7. Validation strategy

Check source links, logical CB/invariant/requirement coverage, 19 comparison criteria, eight operation cases, all requested migration paths and evidence classifications. Audit for unverified Windows readiness, exactly-once inference claims, physical design leakage or implicit backup/Memory/ORM decisions. Use before/after hashes to bound edits; documentation checks only.

## 8. Progress

- [x] Request, repository guidance and source-read continuity checked; pre-edit manifest saved.
- [x] Official candidate evidence and logical criteria, 2026-10-04.
- [x] Evaluation/recommendation and explicit no-selection/no-ADR disposition, 2026-10-04.
- [x] Six author reviews, documentation validation and prepared handoff, 2026-10-04.

## 9. Discoveries

The logical model's final Operational practicality requirement explicitly requires actual-hardware resource/capability validation before selection. Windows remains unverified; preserve the gate while completing a substantive technology recommendation. No permission question was necessary because this task authorizes a recommendation/no-selection outcome and excludes database experiments.

SQLite's official WAL documentation identifies a corruption fix in 3.51.3 and specified backports; verify the driver-linked library if WAL is later proposed. MongoDB standalone deployments do not provide multi-document transactions; the current production guide requires a replica-set topology, whose release-specific requirements need verification. Current self-managed MongoDB search has native Linux constraints, not a proven native Windows vector advantage. Python tooling is available for all candidates without selecting an ORM or driver.

## 10. Decision log

2026-10-04: User authorizes technology selection if sufficient evidence, but explicitly excludes physical design/implementation. No selection made at plan creation.

2026-10-04: Requirement-level rank SQLite, PostgreSQL, MongoDB. Recommend SQLite as a prospective replaceable V0 choice; retain PostgreSQL as viable alternative/future migration target and do not recommend MongoDB for this workload. Final selection/ADR deferred until G-01–G-03 actual-host/build/resource evidence. No existing requirement or decision overridden.

## 11. Final outcome

Created `docs/evaluations/v0-persistence-technology-evaluation.md` with 13 derived criteria, eight coherent-operation comparisons, 19 ranked matrix criteria, future growth/search compatibility, four migration paths, six evidence gates and six author reviews. No ADR created; all accepted decisions and source documents remain unchanged.

Validation passed: before/after hashes show exactly two new Markdown files and no deletions; 18 local links and the logical-model anchor resolve; required classifications, numbered criteria/operations/gates, six reviews and migration paths are present; no executable code blocks or physical designs introduced. Manual reviews verified preservation/FR-15/CB-01–CB-07, unknown outcome and revocation semantics, candidate-source applicability, host evidence limits and recommendation versus selection wording. No database, application or runtime tests ran.

Next bounded task: read-only Windows inventory with actual host access and owner-designated storage/admin context, then separately authorize bounded synthetic SQLite capability/resource evidence before a selection ADR. Physical schema, driver/ORM/migration tooling, transaction/durability settings, backup design, APIs and implementation remain separate future tasks. Stop after this evaluation.
