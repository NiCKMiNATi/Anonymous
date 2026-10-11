# Slice 0B-1 remediation — Codex static diff-review handoff

**Status:** prepared 2026-10-11. **No independent review of this diff has been performed.** Static review only (do not run tests or edit files). Review **only** `git diff ecef413..HEAD` (the commit that contains this file; nothing is pushed) and the four original findings. Report findings with severity, file:line and a concrete failure scenario. Record: [slice-0b-1-remediation.md](../implementation/slice-0b-1-remediation.md).

## Original findings and where they were fixed

| # | Finding | Fix |
| --- | --- | --- |
| 1 HIGH | worker registered before `Thread.start()`; `is_alive()` filtering forgot it; shutdown could release the guard | `application/supervisor.py` (`ThreadRegistry`, `Reservation`), `application/execution.py` (`shutdown`, `_start_worker`), `composition.py` (`outstanding()`) |
| 2 MEDIUM | pending admission committed before the worker was live; reconcile settled it as abandoned | `AdmissionGate` + `ControlRegistry` (`supervisor.py`), `execution.py::_admit_and_start`, `reconcile.py::_settle_abandoned_pending` |
| 3 MEDIUM | no COMMIT-boundary failure coverage on the 0B-1 API | `tests/commit_faults.py`, `tests/application/test_commit_boundaries.py`; two product fixes it exposed: `settling.py::apply_evidence` (unknown outcome → read, re-apply same evidence, bounded) and `reconcile.py` (per-run fault containment) |
| 4 LOW | snapshots taken after operations; sleep-based "it is blocked" assertions | `test_migration_0002.py`, `test_legacy_dataset.py`, `test_handoff_protocol.py`, `test_commit_time.py`; new checkpoints `closure_waiting_for_gate`, `waiting_for_slot`, `orphan_scan_*` |

## Read in this order

1. `supervisor.py` — the registry state machine (`RESERVED → STARTING → RUNNING → ENDED`, plus `UNRESOLVED`), `start`, `_wrap`, `join_all`, child spawn.
2. `execution.py` — `_admit_and_start` (reserve → gate{admit, mark live} → start) and the `SpawnFailed` path; `shutdown`.
3. `reconcile.py` — the gate around *list → liveness → settle*; per-run containment.
4. `settling.py::apply_evidence` — the unknown-outcome loop and `unknown` counter.
5. Tests as evidence: `tests/application/test_registry_and_admission.py`, `test_commit_boundaries.py`, `tests/commit_faults.py`.

## Claims to challenge

1. **No path forgets a reservation.** Any state where `join_all` returns `True` while a thread started through `Reservation.start` has not finished its target; any use of `is_alive()` left in a decision; the `RuntimeError` ⇒ "never started" inference in `_start`; the `UNRESOLVED` path (if the wrapper later runs, it removes the entry — is that sound?).
2. **Shutdown cannot lose a unit.** Between `reserve` and `start`, between admission commit and `start`, and in `_admit_and_start`'s exception path (`reservation.release()` after an unknown admission commit). Child spawning after `begin_shutdown` (`_spawn_child` requires the parent in `STARTING/RUNNING`): can a child be reserved by a parent that is about to end such that the count transiently reaches zero?
3. **Lock order and deadlock.** The order in the module docstring and remediation record §2; any code that takes the admission gate while holding a handoff gate, settle lock, registry condition or an open SQLite write transaction; the checkpoint calls made while holding the admission gate (`admission_gate_held`, `admission_committed`, `orphan_scan_entered`) — safe outside tests?
4. **The admission gate really closes the window.** A path that commits a pending run without going through `_admit_and_start`; a `mark_worker_live` that can be skipped (exception between commit and mark inside the gate); a path where `mark_worker_done` runs before the run leaves `pending`; startup now uses the same rule (`Reconciler.startup` no longer calls `recover_pending_runs`) — is legitimate crash recovery of a pending run still reachable in every case (including a pending run whose admission commit was unknown and whose request thread already returned)?
5. **Repeated settlement is safe.** `apply_evidence` re-applies the same basis after an unknown outcome: can the second application observe a *different* state (e.g. closed by another actor) and apply evidence that was admissible for the first state only? `expected_version` is re-read each iteration.
6. **Containment in reconcile.** Catching `StorageFailure/StorageOutcomeUnknown` per run leaves the run as stored: confirm that startup then cannot report readiness with a run it half-settled, and that generation stays blocked by it.
7. **Fault-injection harness validity.** `commit_faults._store_operation` picks the first public store method on the stack: can a rule fire on the wrong operation (e.g. nested store calls)? Do `before_commit` and `after_commit` really correspond to "not durable" / "durable" (the proxy issues the real `COMMIT` or rolls back)? Tests that pass for the wrong reason (each of the 27 was also run against a mutated implementation — see the record §3).
8. **Test synchronization.** Any remaining assertion that depends on elapsed time rather than an observed event.

## Known limitations (not defects)

Scripted/in-process only; request-path writes outside run execution (conversation creation, configuration adoption) hold no reservation; a `Thread.start()` failure that does not prove non-start keeps ownership forever (conservative); `server/review_tests/` target the removed 0A API (mapped in the record §5); everything in [slice-0b-1.md](../implementation/slice-0b-1.md).

## Second pass (three fixes, commit after `bdd1afa`)

Review only that diff. (1) `supervisor.py`: `_start` claim/abandon protocol (`ABANDONED`, wrapper returns when not `STARTING/UNRESOLVED`), `_spawn_child` releases on `SpawnFailed`, idempotent `release()`; challenge: can the starter abandon while the wrapper is between its claim and `target()`; can an `UNRESOLVED` reservation be claimed by a wrapper twice; does `release()` of `ABANDONED` after a *later* real start leave a running thread uncounted (it runs nothing). (2) `commit_faults.py` `hits/verify/disarm` and the `faults.fired(...) == n` assertions in `test_commit_boundaries.py`: any armed rule that can fire on a different transaction of the same operation. (3) `test_process_restart.py::test_sigkill_during_generation…` and `durable_handoff`: `LIMIT 1` is safe only because that dataset holds one run.
