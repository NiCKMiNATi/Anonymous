# Requirements Baseline v0.1

## Status and purpose

**Status:** Complete. **Date:** 2026-10-03.

Translate the established Anonymous project intent and domain concepts into traceable, testable product requirements. This task ends with a reviewed requirements baseline; it does not select V0 scope or authorize implementation.

## Repository context

The repository contains documentation and empty client/server layout directories. `docs/02-requirements.md` is a placeholder. `AGENTS.md`, `docs/00-project-definition.md` (PD), `docs/01-domain-model.md` (DM), `.agent/PLANS.md`, and all files under `docs/agents/` have been read fully. PD and DM are authoritative Draft v0.1 sources. PD already uses Anonymous throughout; the requested obsolete-name correction requires no change.

## Requirements and acceptance criteria

Produce the fourteen requested sections in `docs/02-requirements.md`. Give each normative product requirement a stable category ID, title, statement, source, acceptance criteria, and status. Cover all ten minimum scenarios and all fifteen DM §48 questions. Distinguish product requirements from V0 selection, source invariants from unresolved choices, and document verification from product testing.

## Constraints and open questions

Preserve all DM §46 invariants and the source documents' provisional status. Do not create application code, dependencies, schemas, API endpoints, technology commitments, designs, or V0 scope. Do not alter other design documents. Keep unanswered policy, capability, and representation questions explicit and classify their decision timing. No source ambiguity currently prevents stating the established minimum guarantees.

## Affected components and approach

Only `docs/02-requirements.md` and this plan are expected to change. Translate source intent into observable semantics, using PD/DM section references and scenario/requirement cross-references. Conditional requirements describe guarantees when a capability is offered, without making it a V0 commitment. No data migration or application recovery operation is involved.

## Work sequence

1. Read sources and role guidance; verify naming and capture existing file hashes.
2. Draft scenarios, requirement records, traceability, questions, decision timing, and completion criteria.
3. Conduct separate Architect, Security, Data & Memory, and QA review passes; revise gaps in place.
4. From the repository root, use read-only Python/`rg` checks to verify IDs, required fields, references, source sections, links, question coverage, counts, and scope against the initial file hashes. These checks were executed successfully as recorded below.
5. Reconcile this plan, report counts and unresolved limitations, and stop.

Edits are bounded Markdown replacements. If drafting is interrupted, read the current plan and requirements document, retain unrelated edits, and continue from the first unfinished milestone. No destructive rollback is needed.

## Validation strategy

Check each requirement for an observable pass/fail oracle, including relevant negative cases. Inspect each source reference for support rather than merely existence. Map INV-001–INV-015 and each minimum scenario to requirement IDs. Check that all DM §48 questions remain unresolved and explicitly classified. Review privacy in derived/context data, revocation, failure handling, and non-destructive history. Verify that only the expected two files change and both authoritative source documents remain byte-identical to their pre-task state. No runtime behavior can be tested because no application exists.

## Progress

- [x] 2026-10-03: Read all required sources and role guidance; confirmed name correction is already complete; captured pre-change hashes.
- [x] 2026-10-03: Drafted 51 requirements, 12 scenarios, invariant/source maps, and 24 classified questions.
- [x] 2026-10-03: Completed four author review passes; clarified context/rebuilding test oracles and replacement coverage. Recorded review findings in the baseline.
- [x] 2026-10-03: Completed structural/scope validation and prepared the completion report with counts, timing classifications, testability limits, and source ambiguities.

## Discoveries

- Source lists of attributes, statuses, privacy classes, and technology candidates are illustrative/provisional, not fixed schemas or selections.
- “Canonical state” is explicitly derived despite its name. Preserved history and future hard-deletion behavior require separate treatment.
- Source qualifiers such as “where practical” need explicit limitations or requirement questions rather than invented universal fidelity/retention guarantees.
- NFR-05 requires a supported-client test matrix and NFR-06 requires hardware/cost bounds before their acceptance contracts are fully executable. Other minimum semantic criteria do not resolve the separately listed capability-policy questions.

## Decision log

- 2026-10-03: Use the established name without modifying PD, since no obsolete name remains. This is a verified repository fact.
- 2026-10-03: Requirements will be marked source-derived draft baseline items, not implemented/validated or user-approved decisions. Capability inclusion remains for the next task.
- 2026-10-03: Perform the four review passes within this session. No specialist agents are required. No architectural decision is being made, so no ADR is needed.

## Final outcome

Replaced the placeholder with Requirements Baseline v0.1: 14 FR, 7 NFR, 8 SEC, 6 PRIV, 10 DATA, and 6 REC records (51 total), each with a title, statement, source, acceptance criteria, and status. Covered 12 scenarios, all 15 domain invariants, and all 15 original domain questions plus 9 additional gaps. The 24 questions classify as 14 blocking dependent requirements, 3 blocking V0 scope, 5 blocking architecture/design, and 2 deferred.

Completed the four author review passes and recorded their findings in the baseline. NFR-05 and NFR-06 retain explicit test-environment/resource-bound dependencies; complete capability-policy and quantitative quality criteria remain open rather than invented. Baseline draft completion does not imply product approval, implemented behavior, or complete release acceptance.

Validation: inline Python checks passed for the 14 sections, 51 unique/sequential IDs and required fields, all requirement/question references, scenario/invariant/question coverage, timing-table consistency, explicit source-section references, five local links, and whitespace. Pre/post SHA-256 inventories confirmed only this plan and `docs/02-requirements.md` changed; no files were deleted and authoritative sources remained identical. An initial validator regex incorrectly treated titles as multiline; restricting titles to one line corrected the checker, after which all checks passed. No validation tooling was added to the repository.

No application implementation, runtime dependencies, schemas, API design, technology finalization, ADR, or V0/architecture placeholder edits were introduced. No runtime tests ran. There were no scope deviations; implementation and V0 scoping await a new task.
