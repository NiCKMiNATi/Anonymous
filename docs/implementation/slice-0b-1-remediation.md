# Slice 0B-1 — concurrency and transaction-boundary remediation (implementation record)

**Status:** implemented and tested locally, 2026-10-11, on top of `ecef413`. Design (LD-04 revision 3.1) and ADR-0013/0014 are unchanged and remain **Proposed**. Scope: the four findings of the 0B-1 static review (worker tracking, pending admission, SQLite COMMIT boundaries, test accuracy). No 0B-2 work, no external runtime, no design change.

## 1. Root causes and fixes

### Finding 1 (HIGH) — worker tracking / B4

*Root cause.* `ThreadRegistry.spawn` appended the thread to its list **before** `Thread.start()`. Every `spawn()` and `alive()` call rebuilt the list as "threads that `is_alive()`", and `is_alive()` is false until the OS thread has actually begun. A second spawn, a poll, or `join_all` therefore forgot a registered-but-not-yet-running worker; `shutdown()` reported quiescence, the instance guard was released, and the worker then started and ran against the dataset with no owner. This broke the premise of B4 (a later boot holding the guard proves the earlier process's workers ended).

*Fix* (`application/supervisor.py`). The registry counts **reservations**, not threads, and never consults `is_alive()`:

- `reserve()` counts a unit of work before anything can start; `Reservation.start()` runs the thread through a wrapper that ends the reservation only when the target returns; `release()` is valid only for something that never started (an inline activity, a refused admission, or a start that failed with a *proven* non-start).
- A failed `Thread.start()` releases only when non-start is established: `RuntimeError` (the OS could not create the thread) → state back to *reserved*, the caller finishes its own cleanup and then releases. Any other exception (e.g. an interrupt) proves nothing → the reservation stays outstanding (`UNRESOLVED`), shutdown reports *incomplete*, ownership is kept.
- `begin_shutdown()` refuses new top-level reservations; `join_all()` waits for every outstanding reservation (started or not). A unit that is still running may spawn a **child** (the deadline watchdog) during shutdown; it is counted by the parent's reservation, so quiescence cannot be observed between them. After the parent ends it can no longer spawn.
- Request-path activity (an admission, an explicit reconcile) holds a reservation too, so a request thread that is mid-commit or mid-reconcile also blocks "quiescent".
- `Application.shutdown` releases the guard only if `outstanding()` is empty.

### Finding 2 (MEDIUM) — pending admission race

*Root cause.* Admission committed the `pending` run, returned, and only then marked the worker live. A concurrent reconcile (a request that touches unresolved work, or an explicit one) listed pending runs, saw none with a live worker, and settled the live admission as `interrupted_before_dispatch` (B1). Initial submissions and retries shared the defect.

*Fix* (`application/execution.py`, `reconcile.py`, `supervisor.py`). One path, `_admit_and_start`, serves submissions and retries: **reserve → (under the admission gate) commit the pending run and mark it live → start the worker on the reservation.** Orphan detection of pending runs holds the same gate across *list → liveness check → settle*. Holding the gate, a pending run without a live mark cannot be a live admission; a pending run left by a dead process (no mark, no admission in progress) is still settled, as at startup and as on the next request. `Reconciler.startup()` now uses the same rule instead of the bulk store call. If the worker thread cannot be started (proven), the run is settled B1 while the reservation is still held.

### Finding 3 (MEDIUM) — SQLite COMMIT boundaries

Coverage was restored through the real connection (§4). It exposed two real weaknesses, both fixed:

- **A settlement whose commit outcome was unknown was not resolved.** `RunSettler.apply_evidence` let `StorageOutcomeUnknown` escape. The B3 evidence (the bound instance delivered) was in hand and lost with the worker: a write that did land surfaced to the user as an error although the run was settled; a write that did not land left the run `in_flight` with no worker, and it was later quarantined on a guess-free but avoidable path. Now an unknown outcome is resolved by reading the run again and, if it did not land, applying the *same* evidence again (same source predicate and `expected_version`, so it can land at most once), bounded by `republish_attempts`. Applies to T5 and T7.
- **One run's storage fault aborted reconcile and startup.** `Reconciler.reconcile` now contains `StorageFailure`/`StorageOutcomeUnknown` per run: that run stays as stored (counted unresolved, generation stays blocked by it) and the others are still reconciled.

### Finding 4 (LOW) — test accuracy

- Migration/legacy tests took their "before" snapshot after the operations (`snapshot(path) == snapshot(path)`), or compared only statuses. They now capture the true before state (after migration, before any attempt; before startup) and compare a full dump / every column.
- Tests that used `sleep` to assume a competing operation had arrived now wait for an event that proves it: `closure_waiting_for_gate` (closer reached the handoff gate, which is asserted still locked), `waiting_for_slot` (second worker found the slot busy), `AdmissionGate.waiting()` (reconcile is parked on the admission gate), `write_begin_attempted` (a writer reached `BEGIN IMMEDIATE`). The remaining `time.sleep` calls are polling loops bounded by a deadline on a condition, or inside the runtime double.

## 2. Synchronization rules (lock order is total, outermost first)

| # | Lock | Held across | Never held across |
| --- | --- | --- | --- |
| 1 | `AdmissionGate` (process-wide) | admission commit + live mark; orphan scan of pending runs (list → check → settle) | a thread start, a runtime call, a wait, any lock below except the SQLite write lock and the leaf locks |
| 2 | per-run handoff gate, settle lock | as before (worker/settler) | database transactions across an external call |
| 3 | SQLite write transaction | one short transaction | any lock 1, 2, 4, 5 acquisition |
| 4 | `ControlRegistry` lock (leaf) | set/dict update | anything |
| 5 | `ThreadRegistry` condition (leaf) | state update, wait for quiescence | store calls, runtime calls, gates, checkpoints |

Rules: (R1) a unit of work is counted *before* it can begin and released *after* it has certainly ended; (R2) "not alive yet" is never "ended"; (R3) after `begin_shutdown` only a running unit's child may be reserved; (R4) a run is marked live atomically with its admission commit; (R5) a pending run is orphaned only if it is neither live nor between commit and live mark.

Audit: the admission gate is taken by the request thread (admission) and by the reconcile caller (orphan scan); neither takes a lock of rank 2 or 5 while holding it, and no code path acquires the gate while holding a rank 2–5 lock. SQLite's write lock is only ever the innermost lock. Registry methods call the checkpoint outside their lock. The 3-reconciler × 8-submitter stress test (`test_many_submitters_and_reconcilers…`) would deadlock on an inversion; it finishes in ~1.5 s.

## 3. Concrete before/after reproductions

[`docs/evidence/ld-04-0b1-remediation-race-repro.py`](../evidence/ld-04-0b1-remediation-race-repro.py) uses only API common to both trees (worktree at `ecef413` vs. the remediated tree):

| | `ecef413` | remediated |
| --- | --- | --- |
| **F1:** worker registered, `Thread.start()` parked, `shutdown(0.2)` | returns **True**, guard **released**, the worker then starts | returns **False**, guard **held**; worker starts, sees shutdown, settles its own never-dispatched run |
| **F2:** reconcile started between the admission commit and the live mark | reconcile **finishes inside the window**, settles the run (`pending_settled = 1`); run `failed / interrupted_before_dispatch`, no response | reconcile **parked on the admission gate** (`waiting()==1`), settles nothing; run `succeeded` with its response |

Mutation checks of the maintained tests: restoring an `is_alive()` filter in the registry fails 6 tests; removing the gate from the orphan scan fails 3 (including the stress test); removing the unknown-outcome retry or the per-run containment fails 7 of the COMMIT tests.

## 4. SQLite COMMIT-boundary coverage

`tests/commit_faults.py` replaces `store.connect` with a proxy over the **real** connection and fires on the store operation that is executing (stack-based, independent of SQL text and transaction count): `statement` (raises before a statement; known rollback), `before_commit` (the real `COMMIT` is not issued; unknown, not durable), `after_commit` (the real `COMMIT` succeeds, the acknowledgment is lost; unknown, durable).

`tests/application/test_commit_boundaries.py` (27 tests; each asserts durable state, no unsafe re-invocation, no duplicate message, instants/provenance as first committed, slot only released on a durable settlement):

| Write | before COMMIT | after COMMIT | statement fails |
| --- | --- | --- | --- |
| Admission (T1) | nothing saved; same submission id re-sent runs normally | durable pending preserved; replay returns the original (same message id and instant); recovered by next request **and** by restart; no duplicate | each of `messages`, `model_runs`, `submissions` rolls back everything |
| Dispatch (T3) | run stays pending, slot not taken, runtime not called; reconcile settles B1 | recognized; `start` once; binding, provenance, boot id, slot as committed | known rollback → settled B1 `dispatch_not_recorded`, runtime untouched |
| Handoff marker (T3b) | `start` never called; B1 on durable `NONE` | recognized; `start` once | known rollback: `start` never called; run stays `in_flight` (authorized, `NONE`) until reconcile settles it B1 |
| Handoff outcome (T3c) | best effort: result unchanged, outcome stays unrecorded | recorded; result unchanged | — |
| Publication (T4) | re-published once (model not re-invoked) | Case A: success preserved | run-update failure: no orphan assistant message, B3 `response_not_saved` |
| Repeated unknown publication | three attempts, then B3 settlement; no second invocation; retry reuses the user message | | |
| Unknown + unreadable store (Case C) | | success stays durable; nothing re-run or rewritten by reconcile | |
| Failure settlement (T5) | retried once; `state_version` equals the fault-free baseline | recognized, not repeated | — |
| Settlement never lands | `in_flight`; busy; same boot → quarantined (no guess); later boot guard → B4 settle; slot freed only then | | |
| Quarantine (T6) | contained in reconcile/startup; slot not released; converges | same | |
| T7 | applied once; slot released once | recognized; idempotent | never lands: stays quarantined, then a later reconcile settles |

## 5. Historical review-probe coverage

`server/review_tests/test_slice0a_review.py` (Codex's Slice 0A probes) calls the removed 0A API (`ExecutionCoordinator(store, builder, model)`, `recover_unsettled_runs`, `record_dispatch`). **15 of its 18 tests fail with `TypeError`/`AttributeError` for that reason alone; 3 pass.** It is not part of the suite and was not modified. Each historical invariant has a maintained test against the current API:

| Probe | Maintained regression test(s) |
| --- | --- |
| concurrent identical / conflicting HTTP submissions (R2/R3) | `tests/api/test_concurrent_submissions.py` (new; 8 threads, barrier); `test_execution.py::test_simultaneous_sends_admit_exactly_one` |
| unknown commit × {admission, dispatch, publication, settlement} × {before, after} + replay + restart | `test_commit_boundaries.py` (admission ×3, dispatch ×3, handoff ×5, publication ×3, settlement ×3, T6/T7 ×7); restart: `[restart]` variant, `test_failure_settlement_that_never_lands…`, `test_ownership_and_crash.py::test_crash_and_restart…` |
| each admission statement failure rolls back all facts | `test_commit_boundaries.py::test_a_failing_admission_statement…[messages|model_runs|submissions]` |
| publication second-statement failure | `test_commit_boundaries.py::test_publication_statement_failure…`; `test_store_behavior.py::test_publish_is_atomic_when_the_run_update_fails`; `test_execution.py::test_save_failure_after_generation…` |
| real-process SIGKILL during inference, then replay | `test_process_restart.py::test_sigkill_during_generation_is_settled_on_restart…` (HTTP, real process; new); `test_ownership_and_crash.py` (four checkpoints). *Semantics changed on purpose:* the 0A probe expected `indeterminate`; 0B-1 settles an `owning_process` orphan by B4 and keeps external bindings quarantined |
| startup settles a durable pending run without inference | `test_process_restart.py::test_a_durable_pending_run_is_settled_at_startup…` (real process; new); `test_commit_boundaries.py::…durable_is_preserved…[restart]` |
| IPv6 same-origin | `tests/api/test_http.py::test_ipv6_loopback_origin_is_accepted_when_served_on_ipv6` (the probe itself still passes) |
| delayed commit / timestamp approximation | `tests/persistence/test_commit_time.py` (FR-15 contract; its two lock-wait tests now prove the writer reached the lock) |

## 6. Validation (2026-10-11, macOS, Python 3.12, Node 24.21)

| Check | Result |
| --- | --- |
| `server`: `pytest` | **296 passed** (249 at `ecef413`; +47) |
| `server`: `ruff check`, `ruff format --check` | clean (80 files) |
| `server`: strict `mypy` | no issues in 79 files |
| `server`: concurrency/process subset (`tests/application`, `tests/integration`, concurrent HTTP, commit-time) repeated | 15 runs, all passed |
| `server`: registry/admission/commit-boundary/handoff/commit-time/integration subset repeated | 20 runs, all passed; then registry + admission + commit-boundary + concurrent-HTTP subset 10 more runs on the final tree, all passed |
| `client`: `npm test` | 53 passed (4 files) |
| `client`: `tsc --noEmit` / `npm run build` | pass; 24 modules, built |
| `client`: review suite (`review-tests`) | 7 passed (the Slice 0A frontend findings were fixed earlier) |
| `server/review_tests` (historical, obsolete API) | 15 failed, 3 passed — **obsolete, not a regression**; mapped in §5 |
| local server smoke (real process, fake model) | health open; send 201; replay 200; history `user, assistant`; one `succeeded` run; SIGTERM → clean exit |

Not run: Windows, any external runtime, Safari/browser rendering.

## 7. Remaining limitations

- Scripted/in-process only; B4 by guard applies only to `owning_process` bindings; external bindings stay quarantined (0B-2).
- A `Thread.start()` failure that does not prove non-start (e.g. an interrupt) keeps the reservation forever: shutdown reports *incomplete* and the process must exit. That is conservative by design and untestable without a real OS fault (simulated here).
- Request-path writes that are not run executions — conversation creation and configuration adoption in `ConversationService` — hold no reservation, so the registry does not account for them at shutdown (uvicorn stops serving before the lifespan shutdown, but that is not enforced here). Reads are harmless. Candidate follow-up if single-process ownership must cover every write.
- U-1/U-2/U-3, single slot, poll-based slot wait, legacy dataset behavior and the UI/route gaps are unchanged ([slice-0b-1.md](slice-0b-1.md)).
- The settlement retry is bounded by `republish_attempts`; when it is exhausted the run stays as stored and is resolved by reconcile (quarantine unless admissible evidence exists).
