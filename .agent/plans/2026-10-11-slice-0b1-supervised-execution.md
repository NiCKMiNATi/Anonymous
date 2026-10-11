# Slice 0B-1 — supervised execution lifecycle against a scripted runtime

## 1. Title, status, and purpose

**Status:** Complete for scope (implementation and local validation); awaiting independent code review. Implements the corrected LD-04 contract (design revision 3.1, ADR-0013/0014 **Proposed**) with a deterministic, scripted, in-process runtime and no external broker, launcher or surviving process. Outcome: a lifecycle that cannot publish after closure, cannot invoke after a winning closure, releases the single execution slot only on admissible evidence, preserves legacy executions untouched, supports explicit retry on the same user message, and keeps each conversation's configuration pinned.

## 2. Repository context

Base: `01e9f46` (Slice 0A) plus the uncommitted LD-04 design documents (committed together with this work). Existing: synchronous `ModelPort`, coordinator that settled any exception as failure, startup that turned every `in_flight` run `indeterminate`, no way out of `indeterminate`, no retry, run identity of two labels. Proposed and now implemented: see [implementation record](../../docs/implementation/slice-0b-1.md). Authoritative inputs: AGENTS.md, `docs/00`, `docs/01`, the LD-04 design, ADR-0013/0014, `docs/05` §§7–12, architecture §§8–9.

## 3. Requirements and acceptance criteria

Done when: migration 0002 preserves legacy facts and stops safely only on structural inconsistency; every transition has its own source predicate enforced in code and by triggers; `start` is called once, under the handoff gate, after T3b, and never after a closure commits; settlement requires an admissible basis; the guard stays held until all supervised workers end; retry creates no duplicate user message; configuration binding, provenance and the golden baseline behave as designed; and the required scenario tests pass with lint and strict type checks clean. **Non-goals:** real llama.cpp or any external runtime, broker/launcher/transport safety, Memory, persona, cloud, authentication, UI work, production deployment, submission fencing.

## 4. Constraints and open questions

Domain invariants, FR-15 and V0-D03/D04/D06 preserved; PRIVATE data never leaves; no secrets. Open (unchanged, design §14): runtime evidence rows, owner items O1–O6, independent review. No genuine safety contradiction prevented any feature. One defect was found and fixed during implementation (a NULL-comparison hole in the settlement trigger, found by the SQL/domain parity test).

## 5. Affected components and intended approach

C05 (worker, settler, reconciler, coordinator), C07 (port split, scripted/in-process adapters, control router), C08 (arbiter, migration, triggers, configuration/binding/retry tables), C10 (composition, boot id, guard lifecycle), C04 (retry, adoption), C02 (retry route, health). Source versus derived: unpublished output is transient; run facts, bindings, provenance and manifests are source facts and never relabeled; legacy rows are never rewritten.

## 6. Work sequence

1. (done) Design corrections 3.1: B6 removed, ownership concrete, legacy settlement via declared lifetime withdrawn, separate clean database.
2. (done) Domain types → migration 0002 → port → store → adapters → application layer → composition/API.
3. (done) Adapt the 0A tests; add arbiter, migration, protocol, reconcile, retry, configuration, ownership/crash and legacy tests.
4. (done) `ruff`, `ruff format --check`, `mypy`, `pytest` (repeated for flakiness).
5. (next, separate authorization) Independent static code review → owner decisions O1–O6 → runtime-evidence task → 0B-2.
Commands (from `server/`): `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy`, `.venv/bin/python -m pytest tests`. Safe retry: all steps are re-runnable; the migration is forward-only and checksummed.

## 7. Validation strategy

Behavior tests tied to acceptance criteria with relevant failure, preservation and privacy cases: controlled scheduling with named checkpoints and gates (no sleeps as proof), fault injection at store operations, real processes for contention and `SIGKILL`, SQL-versus-domain parity for the admissibility table, structural tests that `start`, `mark_handoff_started`, `close_run` and `settle_in_flight` have exactly one gated caller.

## 8. Progress

- [x] 2026-10-11 Design corrections 3.1 (design, ADR-0013, ExecPlan statement removed).
- [x] 2026-10-11 Implementation of 0B-1 (all listed items).
- [x] 2026-10-11 Validation: 249 tests pass; lint, format, strict types clean; 15 repeated runs of the concurrency/process tests without failure.
- [x] Local commit (not pushed).
- [x] Independent static code review (Codex): four findings (worker tracking HIGH; pending-admission race MEDIUM; missing COMMIT-boundary coverage MEDIUM; test accuracy LOW).
- [x] 2026-10-11 Remediation of the four findings ([record](../../docs/implementation/slice-0b-1-remediation.md)): reservation-based thread registry, admission gate, COMMIT-boundary fault tests (27), settlement retry on unknown outcome, per-run reconcile containment, event-based test synchronization. 296 server tests; client 53 + review suite 7; lint/format/strict types/tsc/build clean. Committed locally; not pushed.
- [ ] Independent re-review of the remediation diff only.
- [ ] Owner confirmation of O1–O6; ADR-0013/0014 acceptance (they stay Proposed).
- [ ] 0B-2 (not started; needs runtime evidence and the owner's model-download authorization).

## 9. Discoveries

- (Review) A registry that decides "quiescent" from `Thread.is_alive()` forgets a worker that is registered but not yet running; ownership accounting must count reservations (see remediation record §1).
- (Review) An admission is visible in the database before it is visible in memory; orphan detection must treat the gap as one atomic step with the commit.
- (Remediation) Injecting faults at the real COMMIT showed that an unknown settlement outcome was not retried and that one run's storage fault aborted reconcile; both fixed.
- The settlement trigger's first version accepted every basis for an unrecorded handoff outcome (SQL three-valued logic); caught by the parity test, fixed with `IS` comparisons.
- Ordering runs by `requested_at` made a retry appear before the run it retried when the clock restarted; ordering is now insertion order.
- In-process runtimes make two true statements that external runtimes do not: a returned call has ended, and a later boot holding the exclusive guard proves the owning process and its workers are gone. Both are scoped to the `owning_process` binding recorded at dispatch.
- Closing the fence while holding the handoff gate is what lets a closer treat "handoff never started" (`NONE`) as durable proof of non-invocation with no external action at all.
- A stranded `pending` run (T3 unconfirmed) needs a reconcile trigger of its own; startup alone left its conversation closed until the next restart.

## 10. Decision log

All design decisions remain **proposed** in ADR-0013/0014 and the design; implementation choices: poll-based slot waiting; one shipped configuration; startup self-test covers FX-01…FX-06 and tests cover FX-07; retry route and health `generation` block added, adoption/reconcile routes not; default dataset file renamed to `anonymous-0b1-dev.sqlite3` so execution never runs against a legacy database.

## 11. Final outcome

Implemented as scoped. Validation actually run: lint, format check, strict mypy, 249 tests, 15 repeated concurrency/process runs. Not run: client tests, Windows, any external runtime. Deviations from the design are listed in design §17. Remaining limitations and 0B-2 prerequisites: [implementation record](../../docs/implementation/slice-0b-1.md).
