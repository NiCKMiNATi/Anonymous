# V0 SQLite capability experiment

## 1. Status and purpose

Complete, 2026-10-04. Gathered bounded synthetic technology-level SQLite evidence on the available Mac. No final selection, production physical design or application implementation.

## 2. Repository context

The authoritative definition/domain, requirements/scope/architecture/logical/security models, accepted ADRs 0001–0012, environment baselines, specialist guidance and persistence evaluation were fully read in this conversation. Hash verification confirms unchanged prior source documents; the preceding evaluation is the newly read recommendation. [Evaluation](../../docs/evaluations/v0-persistence-technology-evaluation.md) recommends SQLite but requires Windows evidence. [Logical model](../../docs/05-data-model.md) defines CB-01–CB-07 and FR-15. [ADR-0012](../../docs/adr/0012-v0-local-storage-and-authority-transfer.md) preserves server-local single authority.

## 3. Requirements and acceptance criteria

Create `docs/evidence/v0-sqlite-capability-experiment.md`, evidence-only reproducible scripts and small structured results. Cover A–V: actual environment, atomicity, run/response/provenance, retries/integrity/JSON, WAL/concurrency/admission, safe owned-child interruption, uncertain work, timestamps/frontiers, bounded growth/microtimings, backup/integrity/resources, requirement mapping and Windows delta. Six author review passes and self-contained handoff.

## 4. Constraints and open questions

Execution host returned Darwin before edits. Existing default Python 3.9.6 links SQLite 3.54.0; CLI reports vendor build 3.54.0; existing managed Python 3.12.14 links 3.53.1. Use the latter for the main experiment; no installs/upgrades. All SQLite fixture files live in a fresh temporary directory outside the repository. Scripts marked EXPERIMENTAL / NON-PRODUCTION / NOT ANONYMOUS PHYSICAL SCHEMA. Only synthetic data; terminate only subprocesses created by the harness. No network/configuration/real inference or production data.

## 5. Components and approach

Standalone standard-library harness under `tools/evidence/sqlite/`, not C08/application code. Disposable fixtures model logical operation classes, not future representations. Bounded transactions, controlled thread barriers and owned child processes; explicitly separate same-operation replay, explicit generation retry and unknown outcome. Store sanitized JSON results and environment metadata, never database files, in evidence. No ADR expected.

## 6. Work sequence

1. Host/version gate and pre-edit manifest (done).
2. Build/read-review evidence harness with finite workload and time/space limits.
3. Execute once on managed Python; inspect assertions/raw outcomes and repair genuine harness errors before rerunning affected work.
4. Write observed results/limits, requirement mapping and host-sensitive Windows checklist.
5. Six reviews; check results against report, links and changed-file scope; complete handoff and stop.

## 7. Validation strategy

Meaningful assertions on independent connections and reopened databases; reference/uniqueness rejection; deterministic coordination rather than unbounded contention; committed-versus-uncommitted process-kill stages; backup content digests and integrity checks. Record version/compile flags, timeout/error codes, repetitions/data sizes/timings/resources and script hash. No performance pass threshold or Windows inference. Validate documentation/raw-results consistency and scope.

## 8. Progress

- [x] macOS/existing SQLite gate and source continuity.
- [x] Harness and compile/capability inventory.
- [x] Bounded experiment and structured outcomes: final revised harness PASS at 2026-10-04 12:49:29–12:49:30 UTC.
- [x] Evidence report, six author review passes, validation and handoff prepared.

## 9. Discoveries

Default Python and CLI report a vendor SQLite 3.54.0 build; managed Python reports 3.53.1. Record literal observations without assuming identical builds. Thread-safety module values differ and require interpretation alongside compile options. Windows remains unavailable.

Managed build has THREADSAFE=1 / Python threadsafety=3; PATH build has THREADSAFE=2 / Python threadsafety=1. Fresh foreign-key settings were off. A 150 ms busy timeout returned SQLITE_BUSY after 176.869375 ms. Pinned-reader PASSIVE checkpoint returned [0,10,0], so zero busy indicator is not completion. Disabling automatic checkpoints for observation produced 19,462,912 WAL bytes before truncation for the 10,000-message growth fixture. These are operational considerations, not capability blockers.

Timestamp checks verify atomic representation/preservation of an absolute value, not exact engine commit-clock assignment. Fixture timestamps are sampled before COMMIT; production binding remains open. Parent RSS counters are process-lifetime peaks, not current usage or SQLite-only memory. No Windows capacity/coexistence or hardware-power-loss evidence was obtained.

## 10. Decision log

2026-10-04: Choose already available managed Python only as an experiment executor, not a production driver/backend choice. No database selection or new architecture decision.

2026-10-04: Retain final revised-run measurements only as the report's numerical source. An initial run passed; review strengthened explicit instant/constraint/reopen checks and recorded actual PRAGMAs, then reran the suite. This was harness verification, not a statistically repeated performance study. No ADR warranted.

## 11. Final outcome

Created [report](../../docs/evidence/v0-sqlite-capability-experiment.md), [32,051-byte raw result](../../docs/evidence/v0-sqlite-capability-results-mac.json), and [evidence harness](../../tools/evidence/sqlite/run_experiment.py), plus this plan. Reproduce from repository root using the existing managed Python path and new output filename documented in report §3; no dependency resolution/install required.

Final harness PASS covers atomic user/response rollback, idempotent replay and contention, relation/JSON checks, at-most-one admission, WAL/checkpoints, owned child interruptions, incomplete-run recognition, FR-15/order/frontier separation, 10,000-message growth, backup/restore and header-corruption detection. Growth: 122.381292 ms insertion, 5,439,488 bytes after checkpoint; simple-commit median 0.052333 ms, multi-record admission median 0.1419795 ms. Backup restored all-table content digest and integrity. All owned databases were removed. Details and limits are in report §§4–8.

Validation performed: full final harness execution; source-hash/result consistency; syntax parse without bytecode; recomputation of all four 200-sample timing summaries; report numerical cross-checks; relative-link resolution; pre/post SHA-256 manifest proves exactly four new task files and no changes/deletions to existing files; no database/WAL/shared-memory/bytecode artifacts retained in repository. Six author review passes recorded, not independent approvals. No application tests or implementation claims.

SQLite remains RECOMMENDED_V0 / REQUIRES_MORE_EVIDENCE. G-01–G-03 require actual Windows inventory, supported build and predeclared bounded hardware evidence; later full application/recovery/authority semantics remain G-04–G-06 work. No final engine/physical representation/driver choice, installation, application code, network changes or AI inference. Stop after the experiment. Next separately authorized task: read-only intended Windows host/storage inventory when available.
