# Slice 0B-1 — Codex static code-review handoff

**Status:** prepared 2026-10-11. **No independent review has been performed.** Static review only: do not run tests, do not edit files; report findings with severity, file:line and a concrete failure scenario. Base `01e9f46`; head is the local commit that contains this file (`git log -1`; nothing is pushed). The LD-04 design (revision 3.1), ADR-0013/0014 (Proposed) and their review handoff are in the same commit.

## Read in this order

1. `server/src/anonymous/application/worker.py` (supervisor: T3, handoff under the gate, delivery handling, publication cases) and `application/settling.py` (closure, stop, verification, late delivery).
2. `server/src/anonymous/adapters/persistence/sqlite/versions/0002_ld04_execution_ownership.sql` and `store.py` (arbiter predicates; triggers as backstop).
3. `domain/evidence.py` (admissible bases), `application/control.py` (router, guard-based B4), `adapters/persistence/sqlite/instance_guard.py`, `composition.py` (shutdown/ownership).
4. `application/reconcile.py`, `application/execution.py`, `application/configuration.py`.
5. Tests as evidence: `tests/application/test_handoff_protocol.py`, `tests/persistence/test_run_arbiter.py`, `tests/integration/test_ownership_and_crash.py`, `tests/persistence/test_migration_0002.py`.

## Implementation-relevant guarantees to check

- `start` has exactly one call site (`worker._handoff`), reached only after `mark_handoff_started` confirmed, while holding the per-run gate; `close_run` and `settle_in_flight` each have one call site (`settling.py`); an architecture test pins this.
- A closure of an open fence is committed only under the gate; a closer that cannot take the gate commits nothing (U-2).
- T3b requires an open fence and `NONE→STARTED` once; publication requires an open fence, `STARTED` and epoch `0b`; settlement requires a basis admissible for the durable handoff state; B1 only for `NONE`/`NOT_CALLED`; B5 after an `UNKNOWN`/unrecorded handoff only with `late_delivery_excluded`.
- Control addresses the persisted binding only; mismatching output is rejected, fences the run and is never evidence; a model mismatch from the verified instance is B3.
- The slot is `slot_id` on the run, unique among `in_flight`/`indeterminate`; `pending` holds none; quarantine blocks all dispatch; reconcile never acquires it.
- Legacy rows are untouched by migration; no settlement path exists for binding-less runs; the migration stops safely only on structural inconsistency.
- The guard is released only when no supervised reservation is outstanding (started or not); shutdown reports incomplete otherwise and `__main__` exits the process. *(Corrected after review: the original wording "no thread alive" was the defect; see [the remediation record](../implementation/slice-0b-1-remediation.md).)*

## Claims to challenge

1. **Guard-based B4 (control.py `_owner_is_gone`, design §4.8):** is a later boot's exclusive guard sufficient proof that an `owning_process` runtime's workers ended? Look for a path where the router returns B4 for a binding that is not process-bound, or while another process could hold the dataset (alias, hard link, WAL files, bind mounts, `fork`).
2. **The handoff proof (design §4.6) against the code:** any interleaving, exception path or early return in `worker._handoff` / `RunSettler.close_and_verify` where `start` is called after a closure commits, twice, or without T3b; any lock-order inversion between `settle_lock`, the handoff gate and database writes.
3. **Trigger versus store parity and NULL logic (0002):** remaining `=`-on-nullable traps; transitions the Python checks forbid but the triggers allow (or vice versa); the legacy-epoch exclusions; `state_version` handling in `_update_run`.
4. **Publication cases (worker `_publish`):** Case B settles with B3 after repeated unknown outcomes — is "closure + settlement in one write" really proof that no commit can land later? Case C leaves the run unresolved and raises.
5. **Shutdown (`execution.shutdown`, `composition.Application.shutdown`):** can ownership be released while a watchdog or worker thread is alive? Is `join_all` racy with threads spawned during shutdown?
6. **Stranded pending and reconcile triggers:** can `reconcile` settle a `pending` run whose worker is merely slow to start (`mark_worker_live` ordering)?
7. **Golden baseline (`configuration.py`):** does the startup replay really exercise the shipped builder rather than a copy; is binding of legacy conversations only after success airtight; fixture digest pinning.
8. **Privacy and diagnostics:** nothing logs prompts, outputs, runtime text, paths or binding payloads; failure messages are bounded and sanitized; the configuration manifest holds only application-shipped text.
9. **Test quality:** tests that pass for the wrong reason; scheduling that is effectively sleep-based; missing failure-injection points.

## Known limitations (not defects)

Scripted/in-process runtime only; U-1/U-2/U-3 contained not eliminated; single slot; legacy datasets with unresolved runs stay blocked; no UI work for the new refusal codes; no adoption/reconcile routes; `server/review_tests/` target the removed 0A API. See [implementation record](../implementation/slice-0b-1.md).
