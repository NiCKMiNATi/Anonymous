# Slice 0A independent review

Status: Complete. Review only; no product fixes authorized or implemented.

## Purpose and repository context

Independently verify the implemented persistent-chat fake-model slice against the
[project definition](../../docs/00-project-definition.md),
[domain model](../../docs/01-domain-model.md), requirements, scope, architecture,
logical data model, security baseline, accepted ADRs 0001–0012, and the
[implementation plan](2026-10-07-v0-slice-0a-persistent-chat-fake-model.md).
The user requests a report and permits clearly separated review-only tests.

## Requirements and acceptance criteria

Run documented checks; inspect all server/client responsibilities; independently
exercise concurrency, replay, commit uncertainty, restart, ordering and UI races.
Deliver severity-ranked evidence, one exact slice verdict, Claude fix order,
re-verification checklist, and a self-contained CHATGPT HANDOFF SUMMARY in
`docs/reviews/slice-0a-codex-review.md`.

## Constraints and open questions

Do not edit implementation or original tests. Use synthetic temporary databases.
Preserve provisional SQLite status and recorded development-only deviations.
Do not resolve LD-04, implement authentication, or add real inference/features.
The repository is entirely untracked at review start; compare file hashes rather
than treating git diff as a reliable change inventory. No separate CODEX REVIEW
HANDOFF was found by filename/content search.

## Components and approach

Read-only inspection of server/client and existing tests; review artifacts under
`docs/reviews/`. Tests can inject failures through review-local doubles. No ADR
is planned because this task makes no architecture decision.

## Work sequence and validation

1. Read authoritative and requested documentation fully.
2. Run README checks with existing installed toolchains; record exact outcomes.
3. Trace every persistence transaction and execution transition; inspect API/UI.
4. Add and run isolated adversarial tests where they improve evidence.
5. Write report, check links and changed-file hashes, record final results.

## Progress

- [x] 2026-10-07 Required documents and specialist guidance read.
- [x] 2026-10-07 Scope and original-file hash inventory recorded.
- [x] 2026-10-07 Baseline execution and code inspection.
- [x] 2026-10-07 Adversarial verification: 18 backend and 7 frontend cases.
- [x] 2026-10-07 Report, local links and original-file hashes validated.

## Discoveries

Node/npm are installed through fnm but absent from the login shell PATH. Use the
existing Node installation without installing or updating dependencies.

Baseline: 95 backend tests and 19 frontend tests pass; mypy, ruff, TypeScript and
build pass. Review-only backend suite: 17 pass / 1 fail. Frontend: 2 pass / 5 fail.
Six assertions reproduce five bugs, including two stale-response cases for R1.
Real COMMIT-boundary and active-inference SIGKILL checks passed. Browser access
was unavailable/pending Computer Use permissions; real HTTP serving/API smoke
passed, without claiming rendered-browser verification. Original files are
unchanged by SHA-256 comparison.

## Decision log

2026-10-07: Review stays within the deliberately limited slice, distinguishing
bugs from design/test gaps and deferred scope. No product or ADR changes.

## Final outcome

Delivered [the independent report](../../docs/reviews/slice-0a-codex-review.md)
with verdict **PASS_WITH_REQUIRED_FIXES**, five bounded bugs, the LD-04 design
gate and the FR-15 delayed-commit evidence gap. Includes exact validation results,
transaction/crash matrices, fix order, re-verification checklist and CHATGPT
HANDOFF SUMMARY. Only this plan, report and opt-in review test artifacts were
created. No production fix, new feature, dependency update or ADR change. The
temporary smoke server was stopped. Next work is Claude's accepted bounded fixes,
then independent re-verification, minimal LD-04 resolution and separately
authorized Slice 0B.
