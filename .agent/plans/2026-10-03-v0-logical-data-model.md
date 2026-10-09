# V0 logical data model and persistence semantics

## 1. Title, status, and purpose

Status: complete, 2026-10-03. Replaced the data-model placeholder with a technology-independent V0 logical model, under Data & Memory ownership and Architect coordination, followed by five focused author review passes. No application implementation is authorized. The completion report ends with a self-contained CHATGPT HANDOFF SUMMARY.

## 2. Repository context

Read [AGENTS.md](../../AGENTS.md), [Project Definition](../../docs/00-project-definition.md), [Domain Model](../../docs/01-domain-model.md), [Requirements](../../docs/02-requirements.md), [V0 Scope](../../docs/03-v0-scope.md), [Architecture](../../docs/04-architecture.md), accepted ADR-0001–ADR-0005, and [specialist guidance](../../docs/agents/README.md). Sources were read in full in this conversation and the accepted ADRs/current architecture reviewed before drafting. Existing requirements include FR-15; V0 has 37 selected subsets and 15 acceptance scenarios. The [runtime feasibility plan](../../docs/evidence/runtime-feasibility-plan.md) exists but contains no hardware results. No runnable application or detailed security/API design exists.

## 3. Requirements and acceptance criteria

Define stable persistent identities, five data classes, non-destructive message semantics, independent authoritative order and commit instant, historical state boundaries, generation/correlation/retry/recovery, coherent persistence boundaries, multi-client access, provenance, and future branch/merge/Memory compatibility. Cover every selected persistence-relevant V0 behavior, with objective future checks. Include at least six textual diagrams and finish the model with the exact heading `Persistence Technology Requirements`. Each open decision must have a reason, owner/phase, and implementation-planning impact. Only meaningful logical decisions receive ADRs.

## 4. Constraints and open questions

Preserve all INV-001–INV-015, V0-D01–V0-D06, and ADR-0001–ADR-0005. Do not change source requirements, scope, or architecture to simplify persistence. No physical schemas/datatypes, ordering algorithms, indexes, database/ORM/SQL-family choices, concrete API/authentication/transport, dependencies, runtime configuration or benchmarking. Keep Memory/security/API placeholders untouched. No user cancellation or historical regeneration feature is introduced. Uncertain execution must reconcile before retry; runtime lifecycle mechanisms remain gated on evidence. Future edit/Branch/state-boundary physical representation remains open.

## 5. Affected components and intended approach

Change README project status only, this ExecPlan, `docs/05-data-model.md`, and warranted logical-data ADRs. C03 owns access truth; C04/C05 application semantics; C06 source selection; C07 runtime evidence; C08 durability; C09 rules; C10 restart readiness. Distinguish runtime outcome from committed-response outcome and knowledge of either. Model conceptual historical boundaries without requiring a snapshot entity. Define semantic coherence groups, not physical transactions. Source/generated history is preserved; derived rebuilding never re-infers historical output.

## 6. Work sequence

1. Correct stale README project-status paragraph and create this plan before substantive drafting.
2. Draft the logical model, concept/data-class tables, coherence guarantees and six or more textual diagrams.
3. Record any durable new logical decision with alternatives and consequences; preserve existing ADRs.
4. Review independently by concern (Architect, Backend, Security, QA, Data & Memory) as author passes. Record concrete corrections and unresolved gates without claiming independent agents.
5. Validate references, diagrams, IDs/coverage, scope and preservation with local read-only scripts; finalize README status, plan and report. Stop at this phase.

## 7. Validation strategy

Use requirement/scenario and invariant maps, semantic fault walkthroughs (save acknowledgment loss, dispatch ambiguity, orphan inference, final-save uncertainty, stale/duplicate clients, revocation and equal/non-monotonic timestamps), and logical cardinality checks. Text diagrams use a documented arrow legend and are checked for consistency with tables; no new renderer/dependencies are needed. Validate local Markdown links/anchors, unique IDs and final heading. Hash existing files to prove only the allowed files changed. These are documentation checks, not executed application tests.

## 8. Progress

- [x] 2026-10-03: Read user attachment, existing source baselines, ADRs and specialist guidance; confirmed data-model placeholder and stale README status.
- [x] 2026-10-03: Corrected stale README status and created ExecPlan before drafting.
- [x] 2026-10-03: Drafted the substantive logical model and ADR-0006.
- [x] 2026-10-03: Completed all five author review passes and applied corrections; findings recorded in model section 17.
- [x] 2026-10-03: Validated artifacts, finalized README phase status, and prepared the completion report/handoff. Work stops at this phase.

## 9. Discoveries

The README still described completed baselines as pending. Runtime survival after server death and lost write acknowledgment require more than a single successful/failed flag. The user's mention of retrying uncertain generation must be interpreted consistently with V0-D04: reconcile uncertainty first, not launch another run while it remains unresolved. No source change is needed for that distinction.

Review corrections: prepared input references do not prove dispatch; observed runtime completion must survive a failed publication; failure/reconciliation labels cannot settle admission until their durable outcome is confirmed. Historical boundaries describe history, not current access authority. Future manual Memory may be source information rather than derived state. Session invalidation does not imply permanent full access-log retention. No unresolved source-baseline conflict was found; concrete implementation feasibility remains unproven.

## 10. Decision log

- 2026-10-03: Use plain-text diagrams to keep the model version-control-friendly without renderer installation.
- 2026-10-03: Treat requested/pending work as a logical intent, not proof of runtime dispatch. Separate run outcome, committed publication, and uncertainty; this refines established guarantees without selecting storage or transport.
- 2026-10-03: Accepted [ADR-0006](../../docs/adr/0006-preserved-message-facts-and-historical-boundaries.md): preserve prior committed message facts and fixed historical history boundaries, separately from selected/actual contributions. No mandatory snapshot, event sourcing, sequence, boundary entity, Branch/Merge entity or physical representation.
- 2026-10-03: Retained 13 open-decision groups with reasons, later ownership and implementation-planning gates. Runtime lifecycle capability, detailed persistence/contracts and security remain unresolved; no next phase is started.

## 11. Final outcome

Delivered the logical baseline, one warranted logical ADR, README status correction and this completed plan. The model contains 16 conceptual entries, five data classes, seven logical guarantees, seven consistency boundaries, seven text diagrams, 13 open-decision groups and 14 objective future validation cases. It ends with the exact requested technology-requirements heading and 14 implementation-neutral capability obligations.

Architect review confirmed ownership/dependency consistency and bounded the new ADR. Backend review corrected invocation/publication/settlement distinctions and preserved recovery gates. Security review confirmed current authorization, separate identities and bounded retention. QA review checked traceability, objective failure cases and diagram cardinalities. Data & Memory review confirmed source/generated/derived separation and deferred-feature compatibility. These were focused author reviews, not independent specialist-agent approvals.

Validation passed: a local read-only script compared the traceability table to V0 scope (all 37 selected requirement subsets and 15 scenarios), checked unique LM/CB/LD/test IDs, all 13 open-decision rows, seven fenced text diagrams, ordered sections and required final heading, and resolved local Markdown links. Manual walkthroughs covered uncertain dispatch/save, orphan runtime, lost acknowledgment, explicit retries, concurrency, current revocation, equal/backward timestamps and future source preservation. A before/after file-hash comparison found exactly the four intended changed/new files. README diff was limited to its stale status paragraph. Source documents 00–04, accepted ADR-0001–0005, later design placeholders, runtime feasibility plan and all other files remained unchanged.

No application tests, benchmarks, dependency installs, runtime/network configuration, physical schema/API/security implementation or technology selection occurred. The 14 cases are future acceptance scenarios, not executed runtime results. Recommend a separately authorized Security design task before any access-capable build, with separately authorized actual-hardware runtime evidence informing lifecycle design; detailed persistence/API contracts must resolve their listed gates before implementation. Do not begin those tasks here.
