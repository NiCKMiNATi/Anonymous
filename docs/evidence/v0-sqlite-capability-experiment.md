# V0 SQLite Capability Experiment v0.1

Date: 2026-10-04. Status: **complete — bounded Mac capability evidence only**.

**SQLite remains RECOMMENDED_V0 and REQUIRES_MORE_EVIDENCE. It is not finally selected.** This experiment found no blocker in the exercised capabilities. Windows host/build/resource evidence remains missing, so the selection gate stays open. No database-selection ADR or other architectural decision was made.

## 1. Scope, authority and evidence

Anonymous remains in architecture/design. This task tests SQLite technology with generated synthetic data, not an Anonymous database or persistence implementation. It follows the [logical model](../05-data-model.md), [persistence evaluation](../evaluations/v0-persistence-technology-evaluation.md), [architecture](../04-architecture.md), [security baseline](../07-security.md), [ADR-0004](../adr/0004-persistence-port-boundary.md) and [ADR-0012](../adr/0012-v0-local-storage-and-authority-transfer.md). The [ExecPlan](../../.agent/plans/2026-10-04-v0-sqlite-capability-experiment.md) records scope and execution.

Evidence artifacts:

- [Reproducible standard-library harness](../../tools/evidence/sqlite/run_experiment.py): **EXPERIMENTAL / NON-PRODUCTION / NOT ANONYMOUS PHYSICAL SCHEMA**.
- [Structured Mac results](v0-sqlite-capability-results-mac.json): 32,051 bytes, including every timing sample, observed settings, build options, failure codes, counts and content digests.
- Final recorded run: **2026-10-04 12:49:29.062040–12:49:30.116500 UTC**, status `PASS`; measured parent wall interval **1,056.874167 ms** includes setup/inventory/cleanup and differs slightly from timestamp endpoints.
- Harness SHA-256: `e57b32bac79d3f0ca5a442cd9ec4f0463ef2d295f25de979030a0c12f1c15543`.

`VERIFIED_ON_MAC` means observed by this harness/environment inspection. `DOCUMENTED_SQLITE_CAPABILITY` means supported by cited vendor documentation but not exhaustively proven here. `REQUIRES_WINDOWS_VERIFICATION` means this Mac result cannot establish the intended Windows server's behavior. All measurements here are **MAC_EXPERIMENT_EVIDENCE**, never **WINDOWS_V0_CAPACITY**. A passing fixture assertion is not proof that Anonymous implements the corresponding requirement.

An initial run passed. Author review then added explicit user/assistant instant checks, missing-run/duplicate-position/duplicate-response rejection, observed PRAGMAs and orderly-reopen verification. The complete revised harness passed once; this report and the retained result describe that final run. The initial run is not used to select favorable timings or claim statistical repeatability. Each micro-measurement has 200 samples within the final run; this is not a prolonged stability study.

## 2. A — actual environment and configuration

Read-only host verification returned **Darwin** before substantive changes. The harness observed **arm64, Darwin release 27.0.0**. This kernel release is distinct from the macOS product version. The earlier [Mac baseline](v0-mac-client-runtime-baseline.md) records M1 Pro, 16 GiB RAM and macOS 27.0.1; those hardware facts were not remeasured here. Windows was unavailable.

| Existing execution surface | Exact observed version/build | Interpretation |
| --- | --- | --- |
| Main experiment: existing managed Python | Python **3.12.14**, linked SQLite **3.53.1**; source ID `2026-05-05 10:34:17 c88b22011a54b4f6fbd149e9f8e4de77658ce58143a1af0e3785e4e6475127e9` | All capability and timing results below use this combination. Experiment executor only; no production driver choice. |
| Existing PATH Python | Python **3.9.6**, linked SQLite **3.54.0**; source ID `2026-04-09 12:25:13 8fa8248e303219400c646a885e36dfc52eae33d83f4412e3f369b2be5373aapl` | Inventory only, not a second execution of the capability suite. |
| Existing sqlite3 CLI | `3.54.0 2026-04-09 12:25:13 8fa8248e303219400c646a885e36dfc52eae33d83f4412e3f369b2be5373aapl (64-bit)` | Version command succeeded. Do not infer identical options merely because source ID matches PATH Python. |

Record these vendor/build strings literally; version-number/date differences between bundled builds are not evidence that they are interchangeable. No SQLite, Python, package or other dependency was installed or upgraded.

Main build options include `THREADSAFE=1`, `MUTEX_PTHREADS`, `COMPILER=clang-22.1.3`, `DEFAULT_PAGE_SIZE=4096`, `DEFAULT_WAL_AUTOCHECKPOINT=1000`, `DEFAULT_SYNCHRONOUS=2`, `DEFAULT_WAL_SYNCHRONOUS=2`, `TEMP_STORE=1`, `MAX_VARIABLE_NUMBER=32766` and `MAX_FUNCTION_ARG=1000`. Full observed option lists for both Python-linked builds are in the JSON; listed limits were not stress-tested.

Main Python reports `sqlite3.threadsafety=3`; its compile setting represents SQLite serialized mode. PATH Python reports `threadsafety=1` and `THREADSAFE=2`. Python before 3.11 did not dynamically derive this module value, so inspect the linked build too. Every test thread owns its own connection; connection sharing across threads was not tested. [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html#sqlite3.threadsafety).

| Capability or setting | VERIFIED_ON_MAC | Limit |
| --- | --- | --- |
| Transactions, constraints and foreign keys | Commit/rollback, CHECK, UNIQUE and FK rejection exercised | Foreign keys initially **off** on fresh connections; explicitly enabled on every harness connection |
| JSON | `json_extract`, nested filter, `json_set`, `json_valid`; optional `jsonb('{}')` returns a blob | No production JSON validation/index/encoding decision |
| WAL/checkpoints | Reported `wal`; PASSIVE and TRUNCATE exercised | No rollback-journal comparison, RESTART/FULL checkpoint experiment or network filesystem test |
| Backup/integrity | Python `Connection.backup`, `integrity_check`, `foreign_key_check` exercised | No production backup/recovery guarantee |
| Actual main connection settings | `synchronous=2` (FULL), `foreign_keys=1`, `busy_timeout=1000`, `wal_autocheckpoint=0`, `page_size=4096`, `locking_mode=normal` | Fixture settings, not deployment recommendations |
| Flush settings | `fullfsync=0`, `checkpoint_fullfsync=0` | No hard reboot, power-loss or storage-controller durability claim |

Automatic WAL checkpointing was intentionally disabled **on fixture connections only** to make growth and checkpoint behavior observable. This changes measured costs and sizes. It does not propose that production disable automatic checkpointing. SQLite documents a default automatic checkpoint threshold and the effect of readers on progress. [SQLite WAL documentation](https://www.sqlite.org/wal.html).

All build, driver, filesystem, timing and resource conclusions require Windows verification. Compiled codec-related flags in the PATH Python inventory are not proof that these unencrypted fixtures or a future Anonymous database have database-level encryption.

## 3. B — disposable harness and reproducibility

The script creates a fresh owned temporary directory outside the repository and deletes it on normal completion. It uses separate logical, process-interruption, growth and micro-measurement databases plus owned backup/restored/corrupt copies. No runtime database file is retained in the repository. The recorded final run confirms directory removal and logical WAL/shared-memory sidecar removal after the last connection closed.

Fixture concepts are conversation, message, position, illustrative absolute instant, run, request correlation, provenance, fixed prefix, access epoch/denial and JSON metadata. Their concrete fields, labels, constraints and indexes exist only to exercise capabilities. They omit real user/device/session/security models and comprehensive cross-conversation relationship rules. They are not a suggested production schema, migration, adapter or API. Fixture model/runtime names explicitly denote synthetic work; no inference occurs.

Bounds: 20 growth conversations, 10,000 growth messages, 5,000 each of runs/provenance/request associations; 200 repetitions for each of four micro-measurements; four reader threads; two competing submissions per race; three contention cases; two owned child interruptions. Connections normally have a 1,000 ms busy timeout, child readiness has an 8-second limit, child waiting has a 15-second fallback and backup progress has a 5-second deadline. Worker coordination waits are bounded. These are experiment limits, not production deadlines or a hard whole-process watchdog.

To reproduce on this Mac, from the repository root, use the **already installed** interpreter below. Do not invoke a package manager or a command that resolves/downloads dependencies:

```sh
"$HOME/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/bin/python3" -B tools/evidence/sqlite/run_experiment.py --inventory
sqlite3 --version
"$HOME/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/bin/python3" -B tools/evidence/sqlite/run_experiment.py --output docs/evidence/v0-sqlite-capability-results-mac-repeat.json
```

Choose a **new** output filename for every run: the script refuses to overwrite existing results. If that interpreter is absent on another host, identify an existing usable Python/SQLite first; do not install automatically. `--inventory` creates only an in-memory database. The experiment uses the interpreter that launches it for its owned child processes. The extra PATH Python inventory may describe a different library.

Success prints `status: PASS` with elapsed time and cleanup status; then inspect the new JSON. An assertion/error or absence of a completed result is a failed/incomplete experiment, not success. Do not manually invoke the internal child options or point them at existing data. Ordinary exceptions clean the owned directory; abrupt termination of the parent may leave that run's temporary directory. Any later cleanup must identify that exact experiment directory rather than remove other temporary files.

Do not expect identical timings, generated instants, digests or the identity of a winning race participant. Expect the same assertions, counts and outcome classes. The final raw artifact's script hash allows an exact script-version comparison. There is no performance pass threshold; these measurements characterize the fixture and cannot establish production acceptability.

## 4. C–G — commit, response, replay and integrity

| Test | Observed result | Interpretation / remaining limit |
| --- | --- | --- |
| C: user admission transaction | User identity/body, position **1**, UTC instant, accepted-request correlation, pending run and aggregate update committed together; independent connection observed coherent effects | Representative CB-02/03 support. Failure injected after inserting user but before remaining effects left the complete pre-operation digest unchanged |
| D: run/assistant publication | Pending → active → transactional finalizing → completed exercised; assistant at position **2** retained an absolute instant, exact synthetic response bytes, producing run and source provenance | Independent reader could not see uncommitted assistant. Injected failure after assistant insertion rolled back all publication changes; successful retry published the complete tuple |
| D/F: required relations and uniqueness | Missing assistant run rejected by CHECK; nonexistent producing run rejected by FK; duplicate conversation position and second response for one run rejected by UNIQUE | Requires deliberately supplied fixture constraints/transactions. SQLite does not infer these Anonymous rules |
| E: repeated request | First accepted; two subsequent identical submissions after success returned original source with unchanged full digest; concurrent duplicate returned one accepted and one replay | Application lookup/transaction logic defines idempotency; engine serialization/constraints support it |
| E: conflict, rollback, uncertainty | Same request with different payload refused; request after rolled-back first submission accepted; uncertain run's original request replayed; new intent refused without appended message | Replay does not dispatch inference or silently create a retry. Explicit eligible generation retry, auth-scoped keys, lost network acknowledgments and dispatch reconciliation remain application tests |
| F: FK failures | Six invalid insertion/update/delete cases returned `SQLITE_CONSTRAINT_FOREIGNKEY` (**787**) | Cases: orphan response/run, orphan provenance/source, nonexistent conversation/run relation, invalid run-reference update, deleting referenced run, deleting referenced source. No production cascade policy selected |
| F: per-connection setting | Two fresh connections reported `[0,0]`; enabling first yielded `[1,0]`; enabling both succeeded | In this environment each connection needs explicit FK enablement; do not rely on another connection's setting |
| G: JSON | Extracted scalar `fixture`, nested value **7**, filtered by nested value; updated count to **8** while preserving unrelated Unicode/array/bool data; malformed JSON returned `json_valid=0`; optional JSONB returned blob | JSON works for these cases. Validation was explicitly invoked; the fixture text field does not itself reject malformed JSON. No depth/size/performance/JSONB interchange guarantee tested |

An access fixture committed epoch **1** and denial **1**, visible to an independent connection and preserved by the later full logical digest/reopen check. This only tests persistence of a revocation fact. It does not test current authorization, delivery cancellation, boot/session validity, secret handling or anti-rollback restoration (CB-07).

No externally executing generation is inside a database transaction. The harness has no model. Preparation labels, actual invocation evidence, failure settlement and runtime uncertainty still need the application's owned protocol. Saved assistant bytes are retained authoritative history; no test recreates them by generating a replacement.

## 5. H–J — WAL, concurrency and admission

These are local connections representing requests to **one authoritative application server**, not clients opening a shared database or a network database test.

| Bounded case | Final run observation |
| --- | --- |
| Four simultaneous readers during an open writer transaction | Each read the previous committed version **2** ten times; 40 reads total. Per-reader ten-query elapsed intervals **0.026667–0.083209 ms**. A fresh read after commit observed version **3** |
| Writer held; second writer timeout **0 ms** | `SQLITE_BUSY` (**5**) after **0.016042 ms** |
| Writer held; second writer timeout **150 ms** | `SQLITE_BUSY` (**5**) after **176.869375 ms** |
| Writer released after intended **150 ms**; second timeout **1,000 ms** | Acquired write transaction after **155.357333 ms**; update/commit completed in **157.450791 ms** total |
| Two near-simultaneous different requests in one conversation | One accepted (**1.133125 ms**), one admission-closed refusal (**1.420708 ms**); exactly one user message and active-class run remained |
| Direct attempt to add a second active-class run | Unique constraint rejected it, `SQLITE_CONSTRAINT_UNIQUE` (**2067**) |
| Two near-simultaneous identical requests | One accepted (**0.693333 ms**), one replay (**1.372208 ms**); same source identity, one user effect |
| Stale logical version | Fixture transaction compared expected version **0** to current state and refused before append. This is application logic, not an automatic SQLite stale-client policy |

Contention numbers include scheduling and wrapper costs. Busy timeout is not a strict wall-clock service deadline: the 150 ms setting exceeded 150 ms here. Each contention case ran once; no contention p95 is claimed. No retry loop, fairness guarantee, saturated workload or long-held production transaction was tested. [SQLite busy-timeout semantics](https://www.sqlite.org/pragma.html#pragma_busy_timeout).

With a reader snapshot held open, ten short committed updates produced **41,232 WAL bytes**; `wal_checkpoint(PASSIVE)` returned **[0,10,0]** (busy indicator, log frames, checkpointed frames). A zero busy indicator did **not** mean all frames had checkpointed. Once the reader ended, `TRUNCATE` returned **[0,0,0]** and WAL size became **0**. Logical DB size was **81,920 bytes**; shared-memory size was **32,768 bytes** until connection close. Both sidecar files were absent after the last connection closed. [Checkpoint result semantics](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint).

This supports bounded admission coordination with short transactions and a suitable constraint. Pending/active/finalizing/uncertain fixture labels all participate in that constraint; the race specifically admitted pending work and rejected an additional uncertain row. This is not an exhaustive lifecycle-state matrix. **A SQLite write lock does not own generation lifetime or establish the single current application authority.** ADR-0011 ownership, cross-process startup coordination and admission release after real runtime settlement remain untested application work.

Operational concerns: only one writer at a time, bounded waits/errors must be handled, and long readers can obstruct checkpoints. These align with documented WAL behavior and the observations above. No evidence warrants changing the SQLite recommendation, but transactions must stay short and checkpoint/storage behavior needs host-specific validation. [SQLite concurrency and WAL behavior](https://www.sqlite.org/wal.html).

## 6. K–N — process loss, timestamps and historical boundaries

**Before-commit interruption:** an owned child changed synthetic access state and inserted a conversation inside an uncommitted transaction, then signaled readiness. The parent killed only that child. Reopening preserved the full baseline digest, including previously committed user/assistant history and run/provenance; the uncommitted aggregate was absent. `integrity_check` returned `ok`; `foreign_key_check` returned no rows. Child exit was **-9** on this Mac.

**After-commit unfinished generation:** a separate owned child committed a user/request/pending run, persisted active state and signaled readiness before being killed. Reopening returned **active run + user source + 0 assistant responses**, with healthy checks. The retained facts identify incomplete/uncertain execution; they do not prove whether an external runtime started, ended or needs intervention. The harness neither marks success nor automatically invokes again. This is recovery of database facts, not the Anonymous reconciliation algorithm. Child exit was again **-9**.

Orderly close/reopen also preserved the entire logical-fixture digest. The tests demonstrate process interruption with intact accessible storage, not OS crash, power loss, disk removal, disk-full behavior or disaster recovery.

**FR-15:** message identity, authoritative conversation position and absolute instant were independent. Both successful user and assistant commits retained UTC-aware values. Synthetic history items 1 and 2 shared `2026-01-01T00:00:00+00:00`; item 3 used an earlier clock value. Ordering by position remained **1–8**, while sorting by timestamp incorrectly put **3 first**. Client formatting of the same instant yielded **2025-12-31 17:00 −07:00**, **2026-01-01 00:00 UTC**, and **2026-01-01 09:00 +09:00** without changing the stored digest. Established commit instants were not edited to manufacture this result. Timestamp differences on later appends cannot reorder established history when authoritative positions are used.

The fixture uses UTC text solely as an experiment encoding. Normal fixture values are captured by its clock before COMMIT and committed with the records; this does **not** prove the exact engine commit instant or settle how Anonymous will assign its authoritative commit-time timestamp. Identity, order, encoding, precision and production commit-boundary binding remain design/application obligations. Named timezones/DST, client UI and always-visible timestamp rendering were not exercised.

**Fixed frontier:** a source boundary recorded after item **4** continued to select **1–4** after appending **5–8**. It was distinct from a live/latest view. The fixture position representation is not a production frontier design; multi-source branch/merge ancestry, selected context contributions and current authorization were not tested.

## 7. O–P — growth and bounded latencies

Growth fixture: **20 conversations, 10,000 messages** (5,000 user + 5,000 assistant), **5,000 completed runs, 5,000 provenance relations and 5,000 request associations**. Each message body was **162 UTF-8 bytes**; identifiers and metadata add storage overhead. Insertion used **100 message-batch transactions of 100 messages**, plus 20 conversation inserts, and took **122.381292 ms**. This deliberately small payload is not a representative long-answer/context or multi-year capacity test.

Before explicit checkpoint: database **4,096 bytes**, WAL **19,462,912 bytes**, shared memory **65,536 bytes**. After `TRUNCATE`: database **5,439,488 bytes**, WAL **0**, shared memory **65,536 bytes**. The large pre-checkpoint WAL reflects repeated changed pages and disabled automatic checkpoints; it is not the final dataset footprint or a recommended operating policy. Combined integrity/FK checks took **23.207209 ms**, returned `ok` and no violations.

All values below are milliseconds, **200 repetitions each**, measured with a monotonic high-resolution clock. p95 is the nearest-rank empirical 190th ordered sample, not a production tail-latency estimate or confidence bound. Reads are warm repeated operations on the newly populated fixture; no cache flush/cold-disk claim. Timings include fetching/validating query results; write timings include commit. No pooling, network, auth, encryption overhead or real model load is represented.

| Operation | Dataset / measured work | Min | Median | Rough p95 | Max |
| --- | --- | ---: | ---: | ---: | ---: |
| Simple commit | One access-counter update in autocommit | 0.038458 | 0.052333 | 0.098250 | 0.539208 |
| Small multi-record transaction | User + request + pending run inserts and aggregate update; BEGIN/read checks/COMMIT included | 0.127875 | 0.1419795 | 0.165208 | 0.262666 |
| Recent conversation history | Most recent 50 messages from a 500-message conversation in the 10,000-message fixture | 0.032333 | 0.033292 | 0.043250 | 0.081625 |
| Run/provenance/response lookup | One producing-run/source/assistant join in the 5,000-run fixture | 0.004417 | 0.005334 | 0.008750 | 0.037041 |

The write micro-fixture is separate from growth: one conversation, 200 messages/runs/request associations, one access row. Each admitted run is marked failed by a **separate, unmeasured** synthetic settlement before the next admission, to avoid measuring admission refusal. This does not simulate inference failure or define eligible generation-retry behavior. At the sampled boundary its WAL was **10,942,752 bytes**, DB **4,096 bytes**, shared memory **32,768 bytes**. Section 5 separately reports contention durations; they are not combined with this latency distribution.

## 8. Q–S — backup, corruption and resources

The Python online backup API copied the open growth database while a different connection held an **uncommitted body change**. Backup took **10.105708 ms**. A separate restored copy passed both integrity checks and had exactly the growth counts above. Canonicalized, sorted **all-table contents** of source and restore had matching SHA-256:

`b95932e933359e1beab44391fa6480cfc039b0f47251cbd05982693ca5353f69`

The uncommitted change was absent from backup, then rolled back; source digest remained unchanged. This verifies one coherent synthetic snapshot/restore, not backup during continuous committed writer churn, production schedules, encrypted export, security-state rollback handling or authority transfer. SQLite documents the supported online backup mechanism. [SQLite Backup API](https://www.sqlite.org/backup.html).

Corruption test: copy the closed owned backup, replace **only bytes 0–15** of that copy with the 16 ASCII bytes `CORRUPTEDFIXTURE!`, then request `integrity_check`. SQLite rejected the file with **SQLITE_NOTADB (26), “file is not a database”**. The check could not execute; it did not return a list of corrupt pages. The healthy source/backup were not corrupted. No repair was attempted or inferred, and other corruption classes remain untested.

| Resource observation | Final run | Interpretation |
| --- | --- | --- |
| Parent wall interval | **1,056.874167 ms** | One short local run, including deliberate waits and child orchestration |
| Parent user/system CPU | **0.342636 / 0.152304 seconds** | About **46.8% of one CPU core equivalent** across that wall interval; not whole-machine load or peak CPU; children excluded |
| Parent maximum resident-set counter | Before **28,016,640 bytes (26.71875 MiB)**; after **60,588,032 bytes (57.78125 MiB)** | Process-lifetime high-water marks, not current RSS or SQLite-only allocation; includes Python, samples and whole-content digest materialization |
| Owned regular files before cleanup | **22,061,086 bytes** | Sample after closing databases, including backup/restore/corrupt copies; not peak aggregate disk usage |
| Parent OS block-input/output deltas | **0 / 0** | OS-accounted counters, not byte throughput; zero does not mean no disk writes |
| Current RSS/system memory pressure/device throughput | **NOT_MEASURED** | No reliable continuous pressure/capacity result |
| Anonymous server/model coexistence | **NOT_TESTED** | No server or model was started; existing background host activity was uncontrolled |
| Cleanup | Owned temporary directory removed; logical sidecars absent after close | No retained fixture database, global setting or system service |

The Mac evidence does not determine a Windows RAM/storage budget, a runtime reserve, production latency targets, acceptable checkpoint frequency or long-term stability. No performance threshold was invented after seeing results.

## 9. T — requirement evidence mapping

Statuses describe different parts of a requirement and may coexist. `SUPPORTED_BY_MAC_EXPERIMENT` means representative support, not completed production acceptance. `REQUIRES_PHYSICAL_SCHEMA_DESIGN` never authorizes that work in this task. `SUPPORTED_BY_DOCUMENTATION_ONLY` is distinct from observed evidence; `NOT_TESTED` makes missing coverage explicit.

| Logical model Persistence Technology Requirement | Evidence classification and coverage | Remaining obligation |
| --- | --- | --- |
| Durability | **SUPPORTED_BY_MAC_EXPERIMENT**: C/D/K and orderly reopen preserve committed records | **REQUIRES_WINDOWS_VALIDATION**, **REQUIRES_APPLICATION_TEST**: target storage/build, actual failure handling; power-loss/disaster **NOT_TESTED** |
| Consistency and coherent publication | **SUPPORTED_BY_MAC_EXPERIMENT**: representative CB-02/03/04 transactions, rollback, references; persisted access fact | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: full CB-01–CB-07, invocation evidence, settlement, unknown outcome and authorization |
| Concurrency | **SUPPORTED_BY_MAC_EXPERIMENT**: four readers, two writers, duplicate/admission races, stale-version check | **REQUIRES_WINDOWS_VALIDATION**, **REQUIRES_APPLICATION_TEST**: real request mix, lifecycle coordination, current authority |
| Stable identity | **SUPPORTED_BY_MAC_EXPERIMENT**: retained fixture message/request/run/conversation IDs independent of time/order | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: all User/Device/Session/Model/Runtime identities and migrations; these identities **NOT_TESTED** |
| Provenance integrity | **SUPPORTED_BY_MAC_EXPERIMENT**: producing-run/source relation and FK/response checks | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: complete relationship scoping, actual versus prepared inputs, historical model/runtime evidence |
| Authoritative ordering | **SUPPORTED_BY_MAC_EXPERIMENT**: explicit positions, duplicate-position rejection, equal/backward timestamps | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: real append protocol and evolution |
| Commit-time meaning | **SUPPORTED_BY_MAC_EXPERIMENT**: both roles retain absolute values atomically, format-only conversion, reopen preservation | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: exact authoritative commit boundary/encoding and lost-ack/migration preservation |
| Restart and reconciliation | **SUPPORTED_BY_MAC_EXPERIMENT**: process-kill rollback and recoverable active run with no response | **REQUIRES_WINDOWS_VALIDATION**, **REQUIRES_APPLICATION_TEST**: real runtime reconciliation, identity of uncertain operation, safe admission release |
| Local operation and privacy | **SUPPORTED_BY_MAC_EXPERIMENT**: local synthetic operation, no network/dependencies/private inputs | **REQUIRES_WINDOWS_VALIDATION**, **REQUIRES_APPLICATION_TEST**: protected eligible path, ACLs/encryption, auth/session/diagnostic enforcement |
| Backup/export feasibility | **SUPPORTED_BY_MAC_EXPERIMENT**: supported online copy, restored contents/integrity; **SUPPORTED_BY_DOCUMENTATION_ONLY** for broader API behavior | **REQUIRES_WINDOWS_VALIDATION**, **REQUIRES_APPLICATION_TEST**: future coherent export/access implications and anti-rollback, not production restore guarantee |
| Migration/evolution | **NOT_TESTED**; backup content comparison is useful evidence technique, not a migration experiment | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**: representation/engine transitions and interruption |
| Branch/merge compatibility | **SUPPORTED_BY_MAC_EXPERIMENT** only for one fixed V0 prefix; multi-source ancestry/merges **NOT_TESTED** | **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST** in separately scoped future work |
| Derived/search/vector integration | **NOT_TESTED** | Preserve source/derived separation; future **REQUIRES_PHYSICAL_SCHEMA_DESIGN**, **REQUIRES_APPLICATION_TEST**; no vector decision |
| Operational practicality | **SUPPORTED_BY_MAC_EXPERIMENT**: bounded workload, measurements/errors/cleanup | **REQUIRES_WINDOWS_VALIDATION**: G-01–G-03; real maintenance/coexistence **REQUIRES_APPLICATION_TEST** |

Evaluation traceability:

| Evaluation criterion | This experiment's evidence / classification |
| --- | --- |
| PE-01 identity/ownership | **SUPPORTED_BY_MAC_EXPERIMENT** for fixture identities; **REQUIRES_PHYSICAL_SCHEMA_DESIGN / REQUIRES_APPLICATION_TEST** for complete identity/ownership model |
| PE-02 ordering/FR-15 | **SUPPORTED_BY_MAC_EXPERIMENT** §6; production commit-time binding/UI **REQUIRES_APPLICATION_TEST** |
| PE-03 preserved history | **SUPPORTED_BY_MAC_EXPERIMENT** §§4/6/8 exact bytes/digests/restart; production preservation **REQUIRES_APPLICATION_TEST** |
| PE-04 execution/source attribution | **SUPPORTED_BY_MAC_EXPERIMENT** §4 references/coherent publication; actual invocation/context **REQUIRES_APPLICATION_TEST** |
| PE-05 fixed frontier | **SUPPORTED_BY_MAC_EXPERIMENT** §6 V0 prefix; future multi-source frontier **NOT_TESTED** |
| PE-06 repeated accepted intent | **SUPPORTED_BY_MAC_EXPERIMENT** §§4/5; scope/auth/lost-ack behavior **REQUIRES_APPLICATION_TEST** |
| PE-07 admission/lifecycle | **SUPPORTED_BY_MAC_EXPERIMENT** §§4–6 pending/uncertain/race support; explicit eligible retry and lifetime release **REQUIRES_APPLICATION_TEST** |
| PE-08 CB-01–07/recovery | **SUPPORTED_BY_MAC_EXPERIMENT** for listed transaction/process subsets; **REQUIRES_WINDOWS_VALIDATION / REQUIRES_PHYSICAL_SCHEMA_DESIGN / REQUIRES_APPLICATION_TEST** for complete obligations |
| PE-09 V0 concurrency | **SUPPORTED_BY_MAC_EXPERIMENT** §5; **REQUIRES_WINDOWS_VALIDATION / REQUIRES_APPLICATION_TEST** |
| PE-10 access/invalidation | **SUPPORTED_BY_MAC_EXPERIMENT** for stored epoch/denial only; no-revival and current-policy enforcement **REQUIRES_APPLICATION_TEST**, here **NOT_TESTED** |
| PE-11 future branch/merge | Fixed-prefix subcase **SUPPORTED_BY_MAC_EXPERIMENT**; non-destructive multi-source merges/revisions/DAG **NOT_TESTED** |
| PE-12 derived versus source | **NOT_TESTED**; no Memory/search/index/vector implementation |
| PE-13 locality/evolution/transfer | Local operation and synthetic backup **SUPPORTED_BY_MAC_EXPERIMENT**; protected host **REQUIRES_WINDOWS_VALIDATION**; migration/verified authority transfer **NOT_TESTED / REQUIRES_APPLICATION_TEST** |

## 10. U–V — selection gate and Windows validation delta

1. **Capability blocker found?** None in the bounded cases exercised. This does not rule out untested failures or prove complete Anonymous correctness.
2. **Operational concerns?** Single-writer contention, busy-timeout wall overshoot, pinned-reader checkpoint obstruction, WAL growth when checkpoints are disabled, per-connection FK enablement, and differing bundled build defaults. No sustained-load, full-filesystem, permissions-failure or power-loss test occurred.
3. **Windows-dependent requirements?** Actual supported library/driver, patch provenance, local eligible filesystem/storage and protection, short-write waits, checkpoint/backup/recovery behavior, resource headroom and later model/server coexistence.
4. **Recommendation?** Still **RECOMMENDED_V0**, with **REQUIRES_MORE_EVIDENCE**.
5. **Final selection blocked?** Yes. The evaluation's **G-01–G-03** have not been satisfied on the intended Windows server. A Mac PASS does not waive them. No selection ADR exists or was created here.
6. **What closes that gate?** The following Windows evidence, with predeclared acceptable workload/resource limits and explicit review of any discrepancy; then a separately requested selection decision. Later G-04–G-06 are implementation/deployment/migration gates, not a demand for a complete application before technology selection.

| Windows check | Exact later evidence required |
| --- | --- |
| G-01 host/storage eligibility | Read-only actual Windows version/architecture, usable RAM/storage, owner-designated server-local non-synced path/filesystem, writable DB/WAL/shared-memory/backup locations, encryption/protection and intended account ACL capability; admin/service/sleep/update constraints. No shared/network/cloud-sync primary store |
| G-02 build/driver | Identify actual candidate driver and linked SQLite version/source ID/package provenance, support/patch status, thread mode and compile options. Verify FK per connection, JSON, WAL, backup and integrity availability. Review relevant fixes, including WAL-reset history; version string alone does not prove packaging correctness. SQLite documents the WAL-reset fix in 3.51.3 and specific backports; inspect the proposed build rather than assume Mac parity. [SQLite WAL-reset advisory](https://www.sqlite.org/wal.html#walreset) |
| G-03 bounded timing/resources | Agree payload/history sizes and acceptable latency, wait, RAM and DB/WAL/temporary-space limits before running. Repeat same bounded workload on the eligible local volume with the actual candidate driver/settings; record baseline/peak memory and disk growth, CPU/I/O where reliable, 200-sample short-write/read distributions and exact errors |
| WAL/writers/checkpoints | Repeat writer-held timeout 0/150/1,000 ms cases, delayed writer, concurrent readers/admission/duplicate scenarios, pinned-reader PASSIVE checkpoint and post-release TRUNCATE; record actual waits, result tuples, file sizes/permissions/cleanup. Review checkpoint policy costs separately; this harness disables automatic checkpoints |
| Process recovery/backup | Repeat owned-child before-COMMIT kill and committed-active-run kill on Windows; compare committed records after reopen. Repeat online backup with uncommitted writer and restored digest/integrity. Verify actual account/path permissions and sidecar behavior; no OS crash or arbitrary live-file copying |
| Coexistence/maintenance | Assess room for expected Anonymous server and local runtime on the intended Windows machine. Label unmeasured reserves as assumptions. Later observe an authorized representative coexistence workload when available; a model benchmark or full application implementation is not required to invent results or prerequisites for this engine experiment |

Use an already available, verified interpreter/driver. For this Python fixture, `python -B tools/evidence/sqlite/run_experiment.py --output NEW_WINDOWS_RESULT.json` is the invocation pattern; substitute the verified executable, never assume `python` resolves correctly. Confirm the process's temporary-directory location is on the approved local test volume before execution. Windows resource counters are deliberately not fabricated: the script omits Unix `resource` data when unavailable, so collect host-appropriate bounded process/storage observations separately. All Windows commands and results remain **REQUIRES_WINDOWS_VERIFICATION**, not executed instructions disguised as evidence.

Do not repeat the same pure identity/timezone/frontier argument as a new architecture exercise. The small regression checks may remain in a Windows suite to detect driver/build differences, but focus new evidence on host-sensitive behavior. A future non-Python driver needs equivalent transaction/error/backup checks rather than treating Python's success as its acceptance.

## 11. Review findings and completion

These were six **author review passes**, not claims of independent specialist approval or delegated agents.

| Review | Finding / disposition |
| --- | --- |
| Data & Memory | Preserved identity/order/instant distinctions and exact saved assistant bytes; fixed prefix unaffected by later appends. Explicitly limited timestamp proof to atomic representation, not engine commit-clock precision. Fixture schema/UTC text/frontier encoding are non-production; comprehensive cross-conversation semantics remain open |
| Backend | Transaction boundaries, independent-reader rollback checks, duplicate/admission races, FK failures and process reopens are representative technology probes. Added missing-run/duplicate-response/duplicate-position assertions. Did not mistake database locks for generation authority, or replay for real inference retry |
| Architect | C08 replaceability, CB-01–07 responsibilities, current server authority and Windows gate remain intact. No final engine/driver/schema/ORM/runtime choice; no ADR needed |
| Security | Only synthetic local data, owned temporary files and owned child processes; no credentials/device IDs/private history/network exposure. Access fact test is not auth/anti-rollback proof. Backup copying never activates another Anonymous authority |
| Operations | Recorded exact settings/build differences, WAL growth, checkpoint tuple interpretation, busy overshoot, process-only crash scope, backup limits and memory-counter meaning. No Mac measurement labeled Windows capacity; no unmeasured throughput/coexistence claim |
| QA | Revised full harness passed; result retains samples/counts/errors, source hash and cleanup. Report values checked against raw data. One sample per contention scenario and warm-read/disabled-checkpoint effects disclosed; no production performance threshold or repeated-run stability claim |

Completion validation: executable fixture assertions passed; all healthy `integrity_check`/`foreign_key_check` results passed; corruption was correctly detected as a rejected header; backup/source/restore content comparison passed; temporary cleanup and orderly-reopen checks passed. Report links, result/hash consistency and task file scope were checked. Repository pre-existing documents remain unchanged; no application tests were introduced or claimed. Deliverables are this report, its raw result, the evidence harness and the completed ExecPlan.

No packages installed/upgraded; no application code/framework/API/adapters/production schema/index design/ORM/migration/vector/Memory implementation; no network/security reconfiguration; no model inference or benchmark; no final database decision. Stop here. Recommended next bounded task is the read-only **Windows G-01 inventory**, once the actual intended desktop and owner-designated storage context are available, followed by a separately scoped G-02/G-03 host experiment.
