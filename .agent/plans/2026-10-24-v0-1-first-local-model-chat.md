# v0.1 — first local-model chat through a dev-only external llama.cpp adapter

## 1. Title, status, and purpose

**Status: IMPLEMENTED, REMEDIATED after the first independent review and patched after the focused re-review (PASS WITH CONDITIONS, conditions resolved); development only; ready for owner acceptance of ADR-0015 and the owner's first local commit; the attended real-model smoke is NOT started and NOT authorized. [ADR-0015](../../docs/adr/0015-dev-only-external-llama-runtime-adapter.md) is Proposed, not accepted.** Record: [implementation record](../../docs/implementation/v0-1-external-runtime-dev.md).

**Problem.** Slice 0B-1 runs the full execution lifecycle only against a scripted, in-process runtime. The owner wants the first usable Anonymous conversation with the local Qwen3-4B model, reusing the React and FastAPI flow, keeping SQLite authoritative and PRIVATE data local, without misrepresenting an external process as owned and without weakening an accepted invariant.

**Outcome.** A disabled-by-default adapter that talks to an independently launched, loopback-only llama.cpp server, a dev launcher/cleanup tool, and a narrow settlement guard, so a conversation can complete and every non-clean outcome fails closed.

## 2. Repository context

Read [AGENTS.md](../../AGENTS.md), the [project definition](../../docs/00-project-definition.md) and [domain model](../../docs/01-domain-model.md). The lifecycle is [LD-04](../../docs/design/ld-04-execution-lifecycle.md) with [ADR-0013](../../docs/adr/0013-execution-attempt-lifecycle-and-release-evidence.md)/[0014](../../docs/adr/0014-execution-configuration-provenance-and-continuity.md), accepted for 0B-1 scope only. The runtime measurements are E1, E2-B and the closed E3 V1 pilot ([record](../../docs/evidence/v0-0b2-e3-first-pilot-run.md)); every LD-04 runtime-evidence row stays `BLOCKED_BY_RUNTIME_EVIDENCE` and Slice 0B-2 is open ([ExecPlan 0B-2](2026-10-12-slice-0b2-runtime-evidence.md)). The read-only integration trace found that the existing `RuntimePort`, coordinator and SQLite contracts support the success path, and that B3-shaped settlements, an adapter-produced B4 and the success stamp needed an explicit decision (ADR-0015, F1–F4). Existing: `FakeModelAdapter` via `InProcessRuntime` ([composition.py](../../server/src/anonymous/composition.py)). Added by this plan: the files in the implementation record.

## 3. Requirements and acceptance criteria

Done when (all met on simulated HTTP unless marked): the default configuration still uses the fake model; the real adapter needs explicit configuration and a canonical `*-dev.sqlite3` dataset; a complete, attributable, nonempty, accepted response publishes through T4 and history persists; rejected, ambiguous, failed and late responses cannot release a quarantine through B3/B4/B5; the binding is `EXTERNAL` with no declared bases and `late_delivery_excluded = False`; scripted and in-process behavior is unchanged; only `POST /v1/chat/completions` is requested; no key, path or prompt reaches logs or run records; the launcher and cleanup refuse identity mismatches and never reach SQLite; the existing 302 tests, ruff and strict mypy still pass. **Not met (by design, pending authorization):** a real launch, a real Qwen response, an end-to-end browser conversation.

**Non-goals:** streaming, cancellation, personas, memory, Windows, new runtime experiments, any LD-04 reclassification, a force release or reset, a schema migration, use with personal data.

## 4. Constraints and open questions

Invariants kept: [domain model](../../docs/01-domain-model.md) and AGENTS.md; CB-05 (failure alone never releases admission); PRIVATE data stays on loopback; secrets and absolute model paths never enter the database, logs or committed files. Constraints from the owner: successor-side B4 must not by itself release an external binding; the owner performs all Git staging and commits.

Open (each blocks only what is stated): **Q1** owner acceptance of ADR-0015 (blocks treating the slice as accepted and any smoke run); **Q2** a separate authorization for the attended smoke (blocks real execution); **Q3** whether a later ADR should provide any release or recovery path for a quarantined dev dataset (blocks nothing now; today recovery is a new dataset); **Q4** a store-level `declared_bases` check (needs a migration; deferred); **Q5** whether the 1400-character input cap and `max_tokens` 384 suit real use (needs the smoke).

## 5. Affected components and intended approach

Data flow is unchanged: client → `POST /api/v1/conversations/{id}/messages` → `ExecutionCoordinator` → `RunWorker` → `RuntimePort` (new adapter) → loopback `llama-server`. Source of truth is SQLite; the model response exists only in memory until T4. The adapter attaches to a runtime launched independently by `anonymous-llama-dev`, whose launch record (outside the repository and SQLite) carries the pid and start identity, nonce, loopback address and key-file path. Files created and changed are listed in the implementation record. No migration or recovery change: a quarantined run is recovered only by a new dataset.

## 6. Work sequence

Milestones (working directory `server/`; commands as run on the final files):

1. ADR-0015 revision and conflict check (done): no schema, worker or trigger change needed.
2. Adapter, launch record, identity helper, launcher/cleanup (done).
3. Configuration and composition, default fake (done).
4. Settlement guard and its tests (done).
5. Verification: `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy` (done; see §11).
6. Focused independent review of the diff (next).
7. Owner acceptance of ADR-0015, then a separately authorized attended smoke (proposed, not started): launch with `--hash` and pinned digests on a fresh dev dataset, send synthetic prompts, `stop --remove-files`, write a sanitized record.

Safe retry: all state-changing steps are code edits; the launcher is the only process-changing tool and is idempotent-refusing (`already_running`, `port_in_use`); a failed smoke that quarantines the dataset is retried with a new dataset file, never by editing the database.

## 7. Validation strategy

Each criterion maps to the tests named in the implementation record: adapter and persisted-state tests (`tests/adapters/test_llama_http.py`, the handoff marker/outcome test), the guard and its choke-point structure (`tests/application/test_external_settlement_guards.py`), configuration and default (`tests/unit/test_runtime_config.py`), record and launcher/cleanup (`tests/adapters/`). Failure, preservation and privacy cases are included. Review evidence still needed: an independent static review of `settling.py`, `llama_http.py`, `llama_ctl.py` and the ADR. Real-runtime evidence does not exist and is not claimed.

## 8. Progress

- [x] 2026-10-24 Read-only integration trace (code, tests, SQL triggers) and ADR-0015 draft; owner refinements applied; ADR revision 2 (Proposed).
- [x] 2026-10-24 Adapter, record reader, identity helper, launcher/cleanup, configuration, composition, guard, tests.
- [x] 2026-10-24 Verification on simulated HTTP: 428 passed (302 existing + 126 new), ruff and strict mypy clean.
- [x] 2026-10-24 UNKNOWN-to-T4 path traced and pinned by a persisted-state test; mutation-hang cause fixed in the tests (gates released in `finally`, bounded waits, a thread-free guard assertion, a structural choke-point test).
- [x] 2026-10-24 Implementation record and this ExecPlan.
- [x] 2026-10-24 First independent review (Codex): **BLOCKED**, four High and three Medium findings. Owner accepted all seven and authorized a narrow remediation (no redesign).
- [x] 2026-10-24 Remediation F1–F7 (see the [implementation record](../../docs/implementation/v0-1-external-runtime-dev.md)): launch protected from the spawn to the record (validated path, synced intent, handle containment, retain-and-report); `IdentityUnavailable` instead of treating inspection failure as absence; listener verified at dispatch and before accepting a response; the rule enforced inside the store's shared settlement transaction (no migration); strict HTTP framing; ambiguous writes stay `POSSIBLY_ACTIVE`; launch record loaded before any database side effect. 177 new tests; full suite 479 passed; `ruff` and strict `mypy` clean.
- [x] 2026-10-24 Focused independent re-review (Codex): **PASS WITH CONDITIONS**. F1–F4, F6, F7 closed; F5 needed one correction (repeated `Content-Length` was not rejected although documented); two bounded F1 launcher windows; a concrete recovery procedure for a retained intent; the operating conditions of the first smoke.
- [x] 2026-10-24 Closure patch (C1–C3): repeated `Content-Length` rejected (identical and conflicting) with regression tests; launcher artifact ownership (the intent created first and exclusively, never deleting another launcher's intent) and an uncertain spawn retains the recovery evidence (`spawn_status_unknown`); retained-intent refusals print the nonce and port; operator recovery procedure and smoke operating conditions documented. 7 new tests; the full suite on the final source bytes: 486 passed (302 + 184); `ruff check`, `ruff format --check` and strict `mypy` clean.
- [ ] Owner acceptance of ADR-0015.
- [ ] Separate owner authorization of one attended smoke; the smoke itself; its sanitized record.
- [ ] Implementation of any follow-up the review requires.

## 9. Discoveries

- Two durable handoff facts exist: the marker (`handoff`, T3b, before `start`) and the outcome (`handoff_outcome`, T3c, after). T4 depends on the marker only, so an `UNKNOWN` outcome does not block publication. No pre-existing test persisted that combination through to a published response.
- Every B3-shaped settlement path funnels through `RunSettler.apply_evidence`; one guard there covers all of them. The router filtered `declared_bases` only for probe results.
- Non-daemon worker threads mean a test that arms a runtime gate must release it in `finally`, or a failing assertion hangs the interpreter at exit (this explained the hanging mutation run).
- Under the owner's rules a plain `finish_reason: length` quarantines the dev dataset permanently.
- The independent review found what the author's tests missed: `HTTPResponse.read(n)` returns a short Content-Length body without raising; a listener check in `prepare` is stale by dispatch; `proc_pidinfo` failure is indistinguishable from absence unless `errno` is read (only `ESRCH` is absence; a process of another user gives `EPERM`); the store can enforce the declared-basis rule in Python with no migration. Writing the F1 tests also exposed a leftover log file in the containment path (fixed).
- The runtime's own responses and log expose the absolute model path (E2-B), so the adapter reads no metadata endpoint and the runtime log stays local.

## 10. Decision log

2026-10-24 — Owner accepted all seven findings of the independent review (BLOCKED) and authorized a narrow remediation. Decisions within that authority (proposals pending ADR acceptance): a pure domain rule shared by the settler and the store; a synced launch-intent file plus `Popen`-handle containment rather than a permanent controller; `identity_of` returns `None` only on `ESRCH`; attribution by kernel facts at dispatch and before accepting a response, with the residual race stated rather than a larger peer-attribution change; strict framing that rejects close-delimited and ambiguous bodies; the launch record loaded in `preflight_runtime` (liveness stays per attempt). Alternatives rejected: a SQL trigger check (migration); a permanent launcher daemon; treating the bearer key as attribution; accepting close-delimited bodies. ADR-0015 stays Proposed.

2026-10-24 — Owner approved the adapter subject to twelve refinements (ADR-0015 revision 2): T4 only for accepted responses; rejected, late and ambiguous responses never settle through B3/B4/B5; HTTP 4xx/5xx is `POSSIBLY_ACTIVE`; `EXTERNAL` binding with no declared bases; preserve scripted and in-process behavior; guard all B3-shaped paths; disabled by default; canonical dev dataset; chat endpoint only; external identity and no verified-weights claim; identity-verified launcher and cleanup that never touch SQLite; frozen artifacts untouched. Decisions within that authority (proposals pending ADR acceptance): the guard is placed in `apply_evidence` (the only choke point) and scoped to `EXTERNAL` so existing behavior is unchanged; `start` returns `UNKNOWN` after writing the request, never `ACCEPTED`; the launcher records pins as `asserted` and only its own hash as `verified`. Alternatives rejected: guarding only `late_delivery`; settling truncated or empty responses to avoid quarantine; treating complete HTTP errors as ended; an in-process wrapper; a server-owned runtime; B4 from the cleanup tool; a reset or force release. ADR-0015 stays Proposed; no accepted decision is claimed.

## 11. Final outcome

**Implemented, remediated after the first independent review, patched after the focused re-review, and verified on simulated HTTP; not accepted and not run against a real runtime.** Validation actually performed (final source bytes, 2026-10-24): after the closure patch, the focused adapter and launcher tests (96 passed), then one complete server suite: 486 passed (302 pre-existing unchanged, 184 new); `ruff check`, `ruff format --check` and strict `mypy` clean; a scan of the changed and new files for home paths, model paths and key patterns found only the intentional synthetic test key; no leftover processes or stray key/intent/log files. The first remediation's focused run showed four failures (a leftover log file, a real defect, and a racy test), corrected before its full run; the closure patch's focused run passed. Not run: the client suite (untouched), any real launcher, sandbox, model or inference. Deviations: none from the owner's scope. Remaining limitations: the permanent-quarantine consequence for the disposable dataset, the character-based input proxy, macOS-only identity facts with an unbounded pid-reuse window, the attribution residual (a swapped-and-restored listener, a hostile same-user process), an uncatchable launcher termination between spawn and record leaves only the intent, key and log for the documented nonce-based manual recovery, the SQL trigger itself still does not check `declared_bases`, and every item under NOT TESTED in the implementation record. Follow-up: the owner's ADR-0015 acceptance decision and first local commit, then a separately authorized attended smoke under the documented operating conditions, with a sanitized record.
