# Execution plans

An **ExecPlan** is a living design/implementation plan for a complex feature, substantial refactor, or change spanning multiple architectural areas. Write one before starting substantial work; small, bounded documentation edits and routine fixes do not require one.

Store plans at `.agent/plans/YYYY-MM-DD-short-topic.md`. Each plan must let an agent unfamiliar with earlier chats understand and continue the work using the repository and plan alone. Link relevant source documents, describe the needed context in the plan, and never rely on an unstated chat decision.

Read `AGENTS.md` and the two authoritative design documents first. A plan does not authorize implementation beyond the current task, finalize an open question implicitly, or replace an ADR. Keep undecided proposals clearly separate from accepted decisions.

## Required contents

Use these sections, marking genuinely inapplicable sections with a brief explanation:

1. **Title, status, and purpose:** State the problem, intended user-visible outcome, and whether work is proposed, active, blocked, or complete.
2. **Repository context:** Explain relevant existing behavior, terminology, paths, source documents, and prerequisite knowledge. Describe what exists versus what is proposed.
3. **Requirements and acceptance criteria:** Define observable success, scope, and non-goals. Preserve the source documents' provisional status where applicable.
4. **Constraints and open questions:** Identify domain invariants, privacy/trust boundaries, task limits, dependencies, and unresolved questions. Identify what each blocker prevents without inventing answers.
5. **Affected components and intended approach:** Explain ownership, interfaces, data flow, and anticipated file changes. Cover source versus derived data and migration/recovery implications when relevant.
6. **Work sequence:** Give bounded milestones and actionable steps with working directories and commands when known. Explain safe retry/recovery for state-changing steps. Label unverified commands as proposed.
7. **Validation strategy:** Map acceptance criteria to checks, tests, or review evidence and expected outcomes. Include relevant failure, regression, privacy, provenance, and non-destructive history cases; documentation work may use structural and consistency checks.
8. **Progress:** Maintain dated checkboxes for completed and remaining work, including partial milestones and blockers.
9. **Discoveries:** Record unexpected behavior, evidence, and implications for the remaining work. Sanitize sensitive output.
10. **Decision log:** Record dates, rationale, alternatives, and decision status. Link architectural decisions to `docs/adr/`; do not claim acceptance without evidence.
11. **Final outcome:** Explain what changed, validation actually performed and its results, deviations, remaining limitations, and follow-up work. Do not mark incomplete acceptance criteria as complete.

## Maintenance

Update the plan as work proceeds and whenever scope, findings, decisions, or blockers change. Make the next action clear for a handoff. Preserve useful decision history while rewriting outdated instructions so the plan remains executable. At completion, reconcile progress and the outcome with actual repository state. Keep completed plans for future context.
