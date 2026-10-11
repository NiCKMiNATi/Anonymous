# Slice 0B-1 — supervised execution lifecycle against a scripted runtime (implementation record)

**Status:** implemented and tested locally, 2026-10-11. Design: [LD-04 design](../design/ld-04-execution-lifecycle.md) revision 3.1 (PROPOSED); [ADR-0013](../adr/0013-execution-attempt-lifecycle-and-release-evidence.md) and [ADR-0014](../adr/0014-execution-configuration-provenance-and-continuity.md) remain **Proposed**. ExecPlan: [2026-10-11-slice-0b1-supervised-execution.md](../../.agent/plans/2026-10-11-slice-0b1-supervised-execution.md).

**Scope.** The lifecycle, ordering, ownership, evidence, retry and configuration contract of LD-04 against a *controlled, scripted, in-process* runtime. There is no llama.cpp, no external runtime, no broker, launcher or transport, no cloud, no Memory or persona subsystem, and no authentication. Nothing here is evidence about any external runtime.

## What exists

| Concern | Where |
| --- | --- |
| Migration 0002 (legacy preserved, stop-safe pre-flight, triggers) | `server/src/anonymous/adapters/persistence/sqlite/versions/0002_ld04_execution_ownership.sql` |
| Arbiter: per-transition conditional writes (T1–T7, T3b/T3c) | `adapters/persistence/sqlite/store.py`, port in `application/ports/persistence.py` |
| Evidence bases and admissibility (pure) | `domain/evidence.py` (the SQL trigger enforces the same table; a test compares them for every combination) |
| Provenance (label / identity / verification) | `domain/provenance.py` |
| Configuration manifests, catalog, golden self-test, binding service | `domain/configuration.py`, `application/configuration.py`, packaged fixture `application/golden/` |
| Runtime port (`prepare/start/await_result/stop/probe`) | `application/ports/model.py` |
| Control router (persisted binding only, bounded, guard-based B4) | `application/control.py` |
| Supervised worker, handoff gate, single-use invocation right | `application/worker.py`, `application/supervisor.py` |
| Closure, stop, verification, late delivery (single gated closure path) | `application/settling.py` |
| Reconciliation (startup, touching requests, explicit) | `application/reconcile.py` |
| Coordinator (admission, retry, shutdown) | `application/execution.py` |
| Dataset identity and ownership guard | `adapters/persistence/sqlite/instance_guard.py` |
| Scripted / in-process runtimes | `adapters/model/scripted.py`, `adapters/model/inprocess.py` |
| Wiring, shutdown that never releases ownership while a worker lives | `composition.py`, `api/app.py`, `__main__.py` |

## Results (2026-10-11, macOS, Python 3.12)

`ruff check` and `ruff format --check`: clean. `mypy` (strict, sources and tests): no issues in 75 files. `pytest tests`: **249 passed** (110 before 0B-1; the 0A tests were adapted to the new contract, not weakened). The concurrency and process tests were repeated 15 times with no failure. Real-process tests: a second OS process refused through symlink, directory-symlink, `..` and relative aliases; `SIGKILL` at four checkpoints followed by restart; a hung worker keeping ownership through an incomplete shutdown.

| Required scenario | Tests |
| --- | --- |
| stop versus start; paused invocation handoff | `test_handoff_protocol.py`: paused invoker with a waiting closer; closure first ⇒ `start` never called; stop cannot overlap start; at most one `start` ever |
| stop versus publication | publication wins / closure wins (both forced with checkpoints); `test_run_arbiter.py` store-level orderings |
| late result after closure | watchdog closure → quarantine → late delivery settles by B3 (T7); output discarded |
| uncertain invocation | T3 / T3b unknown (durable or not), unreadable store, `start` returning `UNKNOWN`/raising, lost handoff-outcome write, `NOT_STARTED` |
| uncertain publication | Cases A (durable, unknown), B (not landed → settle on evidence), C (unreadable → unchanged) |
| crash / restart recovery | `test_ownership_and_crash.py`: `SIGKILL` before the gate, after T3b, before await, before publish; external runtime stays quarantined across restarts |
| hung worker during shutdown | shutdown reports incomplete, guard still held, second process refused until the worker ends |
| second-process contention; path aliases | real second process; symlink, dir-symlink, `..`, relative, hard link (refused), special names, case variant (skipped on case-sensitive filesystems) |
| multiple legacy unresolved runs | `test_migration_0002.py`, `test_legacy_dataset.py`: preserved byte-for-byte, no slot, global block, no settlement path, stop-safe migration |
| T7 and idempotent release | `test_run_arbiter.py`, `test_reconcile.py`: own source predicate, stale version, repeated and four concurrent reconcilers (one write) |
| retry without duplicate messages | `test_retry.py`, `tests/api/test_retry_and_generation.py` |
| identity mismatch, replacement instance | output from another instance rejected and not evidence; control never reaches a replacement |
| configuration continuity | `test_configuration.py`: upgrade never rebinds, adoption, unavailable pinned configuration, legacy binding only after the golden replay, all 7 golden fixtures through the real store |

## Known limitations

- Scripted/in-process only. The B4 evidence that settles a restart (the exclusive guard held by a later boot) applies **only** to bindings recorded with `lifetime_scope = owning_process`; any external runtime remains quarantined until a verified producer exists (0B-2).
- U-1 (delayed delivery after an `UNKNOWN` handoff), U-2 (hung handoff: a closer that cannot take the gate commits nothing) and U-3 (single-process assumption, backed by the development `InstanceGuard`, which is not the ADR-0011 mechanism; local filesystems only) are contained, not eliminated. U-2 is covered by a test that asserts nothing is claimed.
- Existing 0A datasets with unresolved runs cannot dispatch (no evidence producer exists for binding-less runs); history stays readable. Use the default fresh `anonymous-0b1-dev.sqlite3`.
- Single execution slot; slot waiting is a bounded poll.
- The client UI is unchanged: new refusal codes (`runtime_quarantined`, `generation_blocked_legacy_unresolved`, `configuration_*`, `retry_not_eligible`, `execution_unresolved`) are returned as 409 with sanitized messages but have no dedicated presentation. No adoption or reconcile HTTP route; no authentication.
- `server/review_tests/` (Codex's 0A probes) target the removed 0A API and are not part of the suite.
- Not run: the client test suite (untouched); Windows.

## 0B-2 prerequisites (unchanged from the design, §14–15)

Runtime-evidence task on the Mac host (control during generation; per-attempt registration; bounded `start` that abandons sends; `late_delivery_excluded`; instance and process identity and exit verification; idle/per-attempt status; disconnect behavior; faithful input and `finish_reason`; version and artifact-digest reporting); whether Anonymous can own the runtime process; a legacy-capable evidence producer if legacy datasets must be resolved; the owner's model-download authorization and size cap; synthetic data and loopback only until SD-08/ADR-0011 containment; the ADR-0011 exclusive-instance mechanism behind assumption A-1; independent review of this implementation.
