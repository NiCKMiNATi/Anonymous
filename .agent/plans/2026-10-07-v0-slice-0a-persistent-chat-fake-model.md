# V0 Vertical Slice 0A — Persistent Local Chat with Fake Model

**Status:** Complete for slice 0A scope (awaiting independent review). Development-only; not finished V0.
**Date opened:** 2026-10-07.
**Owner role:** Builder/implementer. An independent reviewer (Codex) will review later; this plan does not pre-judge that review.

## 1. Purpose

Prove the first complete path through the accepted architecture:

```text
Browser UI -> HTTP API -> Conversation/Application services -> ModelPort -> FakeModelAdapter
                                                          \-> persistence ports -> SQLite development adapter
```

User-visible outcome: start Anonymous locally, open the browser UI, create/open a conversation, send "hello", receive a deterministic fake reply, see authoritative commit times on both messages, restart the server, and find the same conversation and messages.

This is the first implementation slice, **not** finished V0. It authorizes no work beyond the slice (see non-goals).

## 2. Repository context

Authoritative inputs (read in full before this plan): [AGENTS.md](../../AGENTS.md), [README](../../README.md), [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md), [requirements](../../docs/02-requirements.md) (FR-15 and traceability), [V0 scope](../../docs/03-v0-scope.md), [architecture](../../docs/04-architecture.md), [logical data model](../../docs/05-data-model.md), [security design](../../docs/07-security.md), ADR-0001–0012, [persistence evaluation](../../docs/evaluations/v0-persistence-technology-evaluation.md), [SQLite capability evidence](../../docs/evidence/v0-sqlite-capability-experiment.md), and the specialist guidance under `docs/agents/`.

What exists: documentation only plus a standalone SQLite evidence harness (`tools/evidence/sqlite/`, not production code). `client/` and `server/` are empty layout directories. No application code, framework, or dependency existed before this plan.

Persistence status that bounds this slice: SQLite is `RECOMMENDED_V0`, passed bounded **Mac** capability experiments, and remains **provisional** pending Windows validation (no selection ADR). SQLite is therefore used here strictly as a *development adapter behind application-owned ports* (ADR-0004). No domain/application module may import `sqlite3`.

API design ([08](../../docs/08-api-design.md)) and Memory design ([06](../../docs/06-memory-design.md)) are still "Pending". The HTTP contract implemented here is an implementation decision of this slice, not the accepted API design; it is versioned under `/api/v1` and expected to change.

## 3. Requirements and acceptance criteria

Traceability (subset of V0 requirements this slice exercises, in the V0 sense of "partial evidence", not acceptance): FR-01, FR-02 (single-turn text exchange), FR-09 (browse retained history), FR-12, FR-14 (owner identity independent of device/session), FR-15, DATA-01/02/03/05/08, REC-01 (restart with intact storage), REC-02/03 (partially), NFR-02 (model boundary), NFR-07; V0-D03/D04 as far as bounded below.

Acceptance criteria for the slice (each maps to automated tests in section 7 unless marked manual):

| ID | Criterion |
| --- | --- |
| A1 | Server starts locally bound to loopback only; refuses non-loopback bind. |
| A2 | Browser UI loads (served by the server after a client build, or via the Vite dev server) and lists conversations. |
| A3 | User can create and open a conversation. |
| A4 | Sending "hello" durably commits the user message **before** the model is invoked. |
| A5 | The fake model returns a deterministic response through `ModelPort`. |
| A6 | The assistant message is committed atomically with its producing `ModelRun` association; run, model and runtime identities are retained. |
| A7 | Both messages show server-authoritative commit instants, rendered continuously (no hover) in the client's local timezone. |
| A8 | After a server restart (orderly and SIGKILL, intact storage) the same conversation, messages, order, instants and run associations are present. |
| A9 | Message order is server-assigned and independent of timestamps (equal/decreasing instants do not reorder). |
| A10 | Fake generation failure leaves the user message, records a failed run, and creates no assistant message. |
| A11 | Replaying the same submission yields the original outcome without a duplicate message or run; same id with different content is refused. |
| A12 | Empty/oversized message, malformed conversation id, missing conversation, busy conversation, backend-unavailable and storage-failure cases give distinct, sanitized, non-corrupting failures. |
| A13 | SQLite foreign keys are verifiably enabled on every connection; domain/application layers do not import SQLite. |

**Non-goals (explicitly out of this slice):** real model runtimes (llama.cpp/Ollama/MLX), Memory, search/embeddings, branch/merge/graph, edit/regenerate, **explicit generation retry**, artifacts, tools, agents, web/cloud, multiple users, Tailscale/private CA, authentication/device enrollment/sessions, recovery/reconciliation system beyond the minimal startup disposition in §5, backups, production Windows deployment, native mobile, WebSockets/streaming, context budgeting.

## 4. Constraints and open questions

Domain/architecture constraints applied: INV-001/002 (stable ids independent of title), INV-006/015 (context is a transient view; source history is authoritative), INV-008/009 (identities independent of model/client), INV-012 (privacy not delegated to a model), LM-01 (committed messages not mutated), LM-02 (server-authoritative order), LM-03 (absolute commit instant, never the ordering authority), LM-05 (one logical operation across delivery retries), LM-06 (admission survives process-local state), CB-02/CB-04 (user commit before dispatch; response + run association coherent), V0-D04 (busy conversation refused, not queued).

Open questions this slice must **not** silently settle (recorded, left open): LD-01 physical id/order/timestamp representation (this slice picks *implementation-local* encodings, §5, replaceable); LD-02 boundary representation; LD-03 correlation encoding (a client-supplied submission id is used here as an implementation choice); LD-04 supervision/recovery of surviving runtime work; LD-06 context budget/selection; LD-07 credentials; LD-08 pagination/stale-view contract; final persistence engine.

### Known deliberate deviations from accepted design (dev-only; must not be mistaken for V0)

1. **No authentication/device/session.** ADR-0005/0009/0010 and SEC-01–SEC-06 require device+session authority and forbid a localhost bypass in V0. This slice has none and is **not an access-capable build**. Compensations (not security claims): bind only to loopback and refuse other hosts; `Host` header allow-list (DNS-rebinding guard); `Origin` allow-list for browser requests; synthetic data only; `/health` states that auth is not implemented. The API layer obtains the acting owner from a single dependency (`current_owner`) so C03 can replace it later; every store query is owner-scoped.
2. **No exclusive-authority lock per ADR-0011** is a full design gate; a minimal single-instance guard (second server on the same database file fails closed) is included only because startup recovery would otherwise let a second process corrupt admission state. It is not claimed to satisfy ADR-0011/0012.
3. **Dev owner provisioning:** a single `users` row is created at first start so ownership (FR-14) is stored independent of device/session. This is not the owner bootstrap ceremony of ADR-0010.
4. No input contribution table; with no budget the contributing set is the whole committed prefix through the triggering user message (fixed by `triggering_message_id`). V0-D03's explicit contribution evidence is deferred with context budgeting.

## 5. Affected components and intended approach

Modular monolith (ADR-0002), package `server/src/anonymous/`, dependencies pointing inward:

```text
api (C02)  -> application services (C04, C05, C06) -> domain (C09)
adapters: model/fake.py (C07), persistence/sqlite/* (C08) implement application-owned ports
composition (C10): composition.py / __main__.py are the only places concrete adapters are named
```

- `domain/` — frozen dataclasses (Conversation, Message, ModelRun), `MessageRole`, `RunStatus` + allowed transitions, message-content validation, typed ids, domain errors. No framework/DB imports.
- `application/ports/model.py` — **ModelPort** (`identity`, `generate(ModelRequest) -> ModelOutput`), `ModelExecutionError`. Request is a constructed view (list of role/content) with no ids.
- `application/ports/persistence.py` — purpose-specific ports (ADR-0004, not a universal repository): `ConversationStore`, `ExecutionStore`, `HistorySource` (read-only, for the Context Builder), `Clock`; `StorageFailure` (known not committed) vs `StorageOutcomeUnknown` (failure during commit).
- `application/conversations.py` (C04), `application/execution.py` (C05 admission/dispatch/publish/settle; C04 calls C05, never the reverse), `application/context.py` (C06, trivial: full committed prefix, role/order preserved).
- `adapters/model/fake.py` — deterministic reply derived from the constructed view; opt-in trigger `[fake:fail]` for failure demos; optional fixed delay.
- `adapters/persistence/sqlite/` — connection factory (explicit `PRAGMA foreign_keys=ON` verified per connection, WAL, `synchronous=FULL`, busy timeout, explicit `BEGIN IMMEDIATE` transactions), SQL migrations runner, `SqliteStore`, instance guard.
- `api/` — FastAPI app factory, Pydantic DTOs separate from domain objects, uniform error envelope, Host/Origin guards, optional static client serving.

### Request flow (maps to architecture §8)

1. **TX1 (admission, CB-02):** validate content; in one `BEGIN IMMEDIATE` transaction: resolve submission (replay/conflict), verify conversation ownership, refuse if the conversation has an unsettled run, insert user message (next position, commit instant), insert `model_run(status=pending)`, insert submission association. Commit confirms durability before anything else happens.
2. Build context view from committed prefix (C06).
3. **TX2 (dispatch association, CB-03):** `pending -> in_flight` with model/runtime identity recorded **before** invocation.
4. Invoke `ModelPort.generate` (no transaction open).
5. **TX3 (publication, CB-04):** on success insert assistant message (next position, own commit instant, `produced_by_run_id`) and set run `succeeded` atomically. On any failure: settle run `failed` with a stable code and sanitized message; no assistant message.
6. Return the authoritative outcome; the client re-reads history.

**Run lifecycle implemented:** `pending -> in_flight -> succeeded | failed | indeterminate`; `pending -> failed`. Terminal states are immutable (DB trigger + compare-and-set). A partial unique index permits at most one run in `pending/in_flight/indeterminate` per conversation (admission survives restart, LM-06).

**Startup disposition (minimal, before readiness):** unsettled `pending` runs (never dispatched) are settled `failed(interrupted_before_dispatch)`; `in_flight` runs become `indeterminate` and keep the conversation closed to new sends. No automatic replay, no automatic resolution; resolving `indeterminate` is deferred (runtime supervision, LD-04). This is intentionally conservative.

### Implementation-local choices (not architectural mandates; all replaceable)

| Concern | Choice | Notes |
| --- | --- | --- |
| Identity | UUIDv4 canonical lowercase string | Opaque; order never derives from ids. |
| Message order | `position INTEGER` per conversation, assigned inside the write transaction, `UNIQUE(conversation_id, position)` | Linear V0 only; not a branching design. |
| Commit instant | Absolute UTC instant stored as `YYYY-MM-DDTHH:MM:SS.ffffffZ` text, taken from an injected `Clock` **inside** the write transaction after the write lock is held | Never used for ordering. It approximates, but cannot prove, the engine's commit moment (as the SQLite evidence already notes). |
| Idempotency | Client-generated `submission_id` (UUID) + SHA-256 of content; scope = owner; reuse with different content or conversation = conflict | LD-03 stays open; this is an implementation encoding. Conversation creation is not idempotent in 0A (an extra empty conversation is the worst case). |
| Migrations | Numbered `.sql` files, `schema_migrations(version,name,checksum,applied_at)`, each applied in a transaction; refuse changed checksums and databases newer than the code | No heavyweight migration stack. Never drops/rewrites history. |
| Message size | 32,000 character placeholder limit | Real context budget is gated (LD-06). |
| Config | Environment variables / CLI flags, no config library | |

### Planned layout

```text
server/   pyproject.toml, uv.lock, src/anonymous/{domain,application,adapters,api}, tests/
client/   package.json, vite/vitest config, src/{api,components,...}
```

### Dependencies (justified)

Backend runtime: `fastapi` (leading API framework per PD §13; brings `pydantic` v2, `starlette`), `uvicorn` (ASGI server). Backend dev: `pytest`, `httpx` (Starlette TestClient + subprocess smoke client), `ruff` (lint+format), `mypy` (type checking). No ORM, no migration library, no settings library, no auth library. SQLite via stdlib `sqlite3`.

Frontend runtime: `react`, `react-dom`. Dev: `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`. No router, state library, CSS framework, or linter (type-check via `tsc --noEmit`; absence of ESLint is a recorded gap).

Toolchain: Node was not installed; Node v24 LTS was installed in user space via the already-present `fnm` (outside the repository). uv-managed Python 3.12 already existed.

## 6. Work sequence

Working directory: repository root. Commands marked *(proposed)* were unverified when written; results are in Progress.

1. Write this plan; add `.gitignore`.
2. Backend: domain -> ports -> fake adapter -> SQLite adapter + migration -> services -> API -> composition/CLI. Tests alongside. *(`cd server && uv sync && uv run pytest`)*
3. Frontend: scaffold, API client, time formatting, UI, tests. *(`cd client && npm install && npm test`)*
4. Integration: real-process restart test; client build served by the backend; manual smoke including a headless browser using a throwaway driver kept outside the repository.
5. Docs: README development instructions, `docs/implementation/slice-0a.md` (contract, schema, run/test instructions), completion report/handoffs.
6. Self-review against INV-001–015 and the acceptance table.

Safe retry: all steps are file creation or local dependency installs. The dev database lives under an ignored directory and can be recreated; no step deletes existing project history. Migrations are forward-only.

## 7. Validation strategy

| Criterion | Check |
| --- | --- |
| A1 | unit test for host validation; manual start |
| A2/A3/A7 | frontend tests (list, create, send, timestamps across timezones/date boundary), manual browser smoke |
| A4 | integration test: model double inspects the store while generating and finds the committed user message and `in_flight` run |
| A5/A6 | service + HTTP tests: deterministic reply; assistant `produced_by_run_id` resolves to the run with model/runtime identity |
| A8 | store reopen test; HTTP test across app restart; **subprocess test** with orderly stop and SIGKILL then restart |
| A9 | service tests with equal and decreasing clock values |
| A10 | failure tests (adapter error, unknown exception, empty output, identity mismatch, publish storage failure) |
| A11 | replay, conflict, busy (threaded) tests |
| A12 | HTTP error-case tests; frontend failure-state tests |
| A13 | per-connection `foreign_keys` test, orphan-insert rejection, immutability/uniqueness trigger tests, import-boundary test (no `sqlite3`/adapters imported in domain/application) |

Also run: `ruff check`, `ruff format --check`, `mypy`, `tsc --noEmit`, `vitest run`, production client build.

## 8. Progress

- [x] 2026-10-07 Read required documents; verified toolchain (uv/Python 3.12 present; Node installed via fnm).
- [x] 2026-10-07 ExecPlan written.
- [x] 2026-10-07 Backend scaffold, domain, ports, application services.
- [x] 2026-10-07 Fake model adapter.
- [x] 2026-10-07 SQLite adapter, migration runner + initial migration, instance guard.
- [x] 2026-10-07 HTTP API, Host/Origin guards, CLI with loopback-only enforcement.
- [x] 2026-10-07 Backend tests green: 95 passed (unit, persistence, application, HTTP integration, real-process restart).
- [x] 2026-10-07 Frontend scaffold and UI.
- [x] 2026-10-07 Frontend tests green: 19 passed; `tsc --noEmit` clean; production build OK.
- [x] 2026-10-07 Real-process restart tests (orderly stop and SIGKILL) pass.
- [x] 2026-10-07 Manual smoke (real server serving the built client, headless Chrome on macOS): create, send, timestamps, other-timezone rendering, failure state, SIGKILL + restart, reload — passed (driver kept outside the repo).
- [x] 2026-10-07 README and `docs/implementation/slice-0a.md` written.
- [x] 2026-10-07 Self-review against INV-001–015 and the acceptance table (see Final outcome).
- [ ] Independent review (Codex) — not started; outside this task.

## 9. Discoveries

- 2026-10-07: system `python3` is 3.9.6 (below the 3.12 requirement); uv-managed 3.12.14 is already installed and is used via `uv`.
- 2026-10-07: Node/npm were absent; installed Node v24.21.0 LTS with fnm into the user's home (not the repo).
- 2026-10-07: `uv sync` run before any `src/` existed produced an empty editable install; `uv sync --reinstall-package anonymous-server` fixed it. Fresh checkouts are unaffected.
- 2026-10-07: A migrations *directory* named `migrations/` next to `migrations.py` shadowed the module; the SQL files live in `versions/`.
- 2026-10-07: Starlette 1.x warns that `TestClient` with `httpx` is deprecated; the dev dependency is `httpx2` instead.
- 2026-10-07: SQLite fires `BEFORE INSERT` triggers ahead of `CHECK` constraints, so the rejection reason for an assistant message without a run is whichever guard runs first (tests accept either).
- 2026-10-07: Mutation spot-checks (order by timestamp, skip FK pragma, dispatch after invocation, remove busy check) were each caught by the suite.
- 2026-10-07: The server's own CSP blocked a `data:` favicon during the browser smoke test; the client now ships `public/favicon.svg`.
- 2026-10-07: AGENTS.md still says the repository is in the architecture/design phase; it was left unchanged (repository guidance is the user's to update).

## 10. Decision log

| Date | Decision | Alternatives | Status |
| --- | --- | --- | --- |
| 2026-10-07 | Plain `sqlite3` + SQL migrations, no ORM | SQLAlchemy/Alembic | Implementation choice, replaceable |
| 2026-10-07 | Sync service/adapter code; FastAPI sync endpoints run in the threadpool; one short-lived connection per operation | async + aiosqlite; shared connection | Implementation choice |
| 2026-10-07 | Assistant->run link stored only on the message (`produced_by_run_id UNIQUE`); no reverse column on the run | duplicate column on run | Implementation choice (bidirectional lookup is a query) |
| 2026-10-07 | Generation failure is returned as a successful HTTP exchange whose run is `failed` (user message committed); storage errors are 5xx | 5xx for model failure | Contract choice for this slice |
| 2026-10-07 | No ADR created: every decision above is replaceable and recorded here/in implementation docs | ADR for submission-id idempotency | Re-evaluate if retained into the API design |

## 11. Final outcome

**What changed:** `server/` (FastAPI modular monolith: domain, application ports/services, fake model adapter, SQLite development adapter with migration runner and instance guard, HTTP API, loopback-only CLI), `client/` (React/TypeScript chat UI), `.gitignore`, README development section, `docs/implementation/slice-0a.md`, this plan. No ADR was created and no design document was changed beyond README status text.

**Validation actually performed (2026-10-07, macOS, Python 3.12.14, SQLite via the uv Python, Node 24.21.0):**

| Check | Result |
| --- | --- |
| `uv run pytest` (server) | 95 passed |
| `uv run mypy` (strict, src + tests) | no issues in 49 files |
| `uv run ruff check . && ruff format --check .` | clean |
| `npm test` (vitest, jsdom) | 19 passed |
| `npm run typecheck` / `npm run build` | clean / built |
| Real-process restart (orderly + SIGKILL), second-instance refusal, non-loopback refusal | passed (pytest, marker `process`) |
| Browser smoke through the real server (headless Chrome) | passed, incl. other-timezone rendering, failure state, SIGKILL restart |
| Mutation spot-checks | 4/4 caught |

**Acceptance A1–A13:** met as evidenced above, within the slice's development-only scope. A2/A7 browser behavior was verified on macOS Chrome and jsdom only; Windows/Edge and iPhone/Safari were not exercised.

**Deviations / limitations:** see section 4 (no authentication; minimal instance guard; dev owner provisioning; no contribution table) and `docs/implementation/slice-0a.md` (indeterminate runs block their conversation; no pagination; no explicit retry; conversation creation not idempotent; no client linter). SQLite remains provisional pending Windows validation.

**Follow-up:** independent review; then next slice per the handoff recommendation (explicit retry + runtime-supervision/reconciliation design gate, or the security/access baseline) — each needs its own task and plan.
