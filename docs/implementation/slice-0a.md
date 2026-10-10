# Implementation notes — V0 Vertical Slice 0A (persistent local chat with a fake model)

**Status:** Closed as a development-only slice (2026-10-11). Implementation and tests complete on the development host (macOS); the FR-15 contract is accepted and applied (R1–R7 all resolved). **Platform acceptance is still pending** on real browsers, Windows and iPhone — see [Pending platform acceptance](#pending-platform-acceptance). Not finished V0, not an access-capable build, not release evidence. The [ExecPlan](../../.agent/plans/2026-10-07-v0-slice-0a-persistent-chat-fake-model.md) records scope, decisions and results. This page describes *what the code does*; the design documents ([architecture](../04-architecture.md), [logical data model](../05-data-model.md), ADRs) remain authoritative. Nothing here finalizes an open design question.

## What is (and is not) there

```text
Browser (React/TS)  ->  HTTP /api/v1  ->  ConversationService (C04) -> ExecutionCoordinator (C05)
                                                                          |-> ContextBuilder (C06)
                                                                          |-> ModelPort -> FakeModelAdapter (C07)
                                                                          '-> ExecutionStore / ConversationStore / HistorySource
                                                                                 -> SqliteStore (SQLite development adapter, C08)
```

Not implemented (deferred): authentication/devices/sessions, real model runtimes, streaming, context budgeting/omission reporting, explicit retry of a failed generation, runtime-surviving-restart reconciliation, branch/merge/edit/regenerate, Memory, search, files, tools, web/cloud, backups, conversation-creation idempotency, pagination, Windows validation.

## Security posture of this slice

There is **no authentication, device approval or session**. ADR-0005/0009/0010 and SEC-01–SEC-06 are not satisfied and must be implemented before any access-capable build or real private data. Compensating development measures (not security claims):

- The CLI refuses any non-loopback `--host` (exit code 2, before touching storage).
- Requests must carry a loopback `Host` (DNS-rebinding guard; strictly `host[:port]` for `127.0.0.1`, `localhost` or the bracketed `[::1]`) and, if an `Origin` is present, it must be one of this server's own loopback origins on its configured port (`127.0.0.1`, `localhost`, `[::1]`) or the Vite dev origins (port 5173, same three names). Matching is exact; there is no wildcard or prefix match, and `null` or look-alike origins are refused.
- Responses are `Cache-Control: no-store`, `nosniff`, `no-referrer`, with a restrictive CSP; no CORS is enabled.
- Uvicorn access logging is off (request paths contain object ids); application logs never include message content.
- `/api/v1/health` states that no authentication exists. The UI shows a development banner.
- The acting owner comes from one dependency (`current_owner` in `api/app.py`); all store queries are owner-scoped, so C03 can replace it without touching the services.

## HTTP contract (implementation decision of this slice; not the accepted API design)

| Route | Result |
| --- | --- |
| `GET /api/v1/health` | `200`/`503` readiness: schema version, storage state, security notice |
| `POST /api/v1/conversations` `{title?}` | `201` conversation |
| `GET /api/v1/conversations` | list, newest first |
| `GET /api/v1/conversations/{id}` | conversation, messages in authoritative order, every run (including failed) |
| `POST /api/v1/conversations/{id}/messages` `{submission_id, content}` | `201` outcome (`user_message`, `run`, `assistant_message` or `null`); `200` with `replayed: true` for an already accepted `submission_id` |

Errors use `{"error": {"code", "message"}}`: `400 invalid_identifier`/`invalid_host`, `403 forbidden_origin`, `404 conversation_not_found`, `409 conversation_busy`/`idempotency_conflict`, `422 invalid_message`/`invalid_request`, `503 storage_unavailable`/`storage_outcome_unknown`. A generation failure after the user message committed is a normal `201` whose `run.status` is `failed`; it is not an HTTP error.

## Request flow and durability checkpoints

1. **Admission (one transaction):** replay/conflict check → conversation ownership → refuse if an unsettled run exists (`409`) → user message (next `position`, commit instant) + `pending` run + submission association. Nothing else happens before this commits.
2. Context view built from the committed prefix through the triggering message (whole history; no budget yet).
3. **Dispatch (one transaction):** `pending → in_flight` with model/runtime identity recorded **before** invoking the model.
4. `ModelPort.generate` runs with no transaction open.
5. **Publication (one transaction):** assistant message (own position and commit instant, `produced_by_run_id`) + run `succeeded`. Otherwise the run is settled `failed` and no assistant message exists. Output from a different model identity than dispatched, or empty output, is a failure.

If storage cannot confirm a step the coordinator raises (`503`) instead of claiming success or absence; replaying the same `submission_id` reports the real state.

## Persistence (SQLite development adapter)

Provisional: SQLite is `RECOMMENDED_V0` with bounded Mac evidence; final selection awaits Windows validation. Only `server/src/anonymous/adapters/persistence/sqlite/` imports `sqlite3` (enforced by a test).

- Every connection sets and verifies `PRAGMA foreign_keys = ON`; also WAL and `synchronous = FULL`. Writes are `BEGIN IMMEDIATE`; a new short-lived connection is used per operation.
- Tables: `users`, `conversations`, `messages`, `model_runs`, `submissions`, `schema_migrations`.
- Integrity enforced in the schema: unique `(conversation_id, position)`; assistant message ⇔ `produced_by_run_id` (unique, composite FK keeping conversation consistent); immutable/undeletable messages, submissions and settled runs (triggers); an assistant message requires an `in_flight` run and `succeeded` requires its message; at most one `pending/in_flight/indeterminate` run per conversation (partial unique index, so admission survives restart); per-status run field checks; fixed-width UTC timestamp format check.
- Migrations: numbered SQL files in `adapters/persistence/sqlite/versions/`, checksums recorded in `schema_migrations`, forward-only, each in a transaction; refuses changed applied files and databases newer than the code.
- Startup (before readiness): migrate, ensure the single development owner, then disposition of leftover runs — `pending` (never dispatched) → `failed(interrupted_before_dispatch)`; `in_flight` → `indeterminate`, which **keeps the conversation closed** (no automatic replay or resolution; resolution is deferred).
- A single-instance guard (exclusive lock on `<db>.instance-lock`) makes a second server on the same database fail closed. This is a development safeguard, **not** the ADR-0011/0012 authority lock.

### Implementation-local encodings (replaceable; not architectural mandates)

IDs are UUIDv4 canonical strings. Order is an integer `position` per conversation. Commit instants are UTC text `YYYY-MM-DDTHH:MM:SS.ffffffZ` taken from an injected clock inside the write transaction after the write lock is held; they are never used for ordering. Idempotency uses a client-generated `submission_id` plus a SHA-256 of the content, scoped to the owner.

## Commit instants (FR-15 / LM-03) — what is and is not guaranteed

Review finding R7, resolved by the accepted FR-15 contract ([FR-15](../02-requirements.md#fr-15--persist-and-continuously-display-message-timestamps), accepted by the owner 2026-10-11). The adapter's behavior was verified against that contract and needed no change; this records exactly what it does so no stronger claim is made.

| Step | When it happens |
| --- | --- |
| Client composes/sends | Not used for any stored instant. |
| Request arrives / waits for the write lock | Not used. A request delayed by lock contention gets the instant of *winning the lock*, not of arrival (tested). |
| Transaction start | `BEGIN IMMEDIATE` acquires the exclusive write lock. |
| **Instant sampled** | Once per write transaction, from the injected clock, after the lock is held and the admission checks passed, immediately before the INSERTs. The same value stamps the message and its run/submission rows in that transaction. |
| Message insertion | Statements after the sample. |
| Durable commit | `COMMIT` with `synchronous = FULL`. |
| Client presentation | Formatting of the stored UTC instant in the browser timezone only. |

What the adapter does, stated as the order of events (not as wall-clock inequalities: a wall clock can step backwards, so nothing is promised about how a stored instant compares numerically with any other reading). Covered by `server/tests/persistence/test_commit_time.py`:

- The clock is read once per write transaction, after `BEGIN IMMEDIATE` has acquired the exclusive write lock and the admission checks passed, before the INSERTs and before `COMMIT` is issued; the same value stamps the message and its run/submission rows. No other writer can commit between that read and this transaction's commit attempt.
- A commit delayed by waiting for the write lock carries the reading taken once the lock was won, not the arrival time; an assistant message published after slow generation carries its own reading at publication, not generation start or the user message's reading.
- A reading taken for a transaction that is known not to have committed is not retained. When the commit outcome is *unknown*, nothing is inferred (no rollback is assumed): a later same-id reconciliation either finds the committed operation and returns its original instant unchanged (tested), or finds nothing and the retry takes its own new reading (tested). A call whose outcome is unknown reports "unknown", not success.
- A stored instant never changes on reads, replay or restart; order is the integer `position`, never the instant (existing tests: equal and decreasing instants do not change order).

**Not guaranteed, and not claimed:** equality with the database engine's own commit-completion instant, or any numeric bound on the difference. The committing row has to contain the value before `COMMIT` runs, and committed messages are immutable by trigger, so the application cannot record the engine's own instant. The tests that inject a delay between the clock read and `COMMIT` (60 s in the review characterization test, 90 s in `test_instant_is_read_before_the_commit_attempt_not_at_commit`) show only *which* reading is stored under a controlled clock; they are **not** evidence of correspondence with the physical commit-completion instant and must not be cited as such.

**Observed interval, one host, informational only (no tolerance exists or is proposed):** `tools/evidence/sqlite/measure_commit_instant_gap.py`, macOS 27 arm64, Python 3.12, SQLite 3.53.1, WAL + `synchronous = FULL`, 300 synthetic transactions per kind, two runs, measured on a monotonic counter: clock read to `COMMIT` returning has median ≈ 0.2–0.4 ms and p99 ≤ ≈ 1 ms, with one 2.6 ms outlier. SQLite on macOS does not request a full media flush unless `fullfsync` is enabled, so this under-represents a power-safe flush; Windows and other targets must be measured separately (hardware gates G-01–G-03). It is context, not a contract.

### R7 status: RESOLVED (contract accepted and applied 2026-10-11)

The owner accepted the revised FR-15 contract; it is applied in `docs/02-requirements.md` (FR-15 Statement, rationale, acceptance criteria, status) and aligned in `docs/01-domain-model.md` §9, `docs/03-v0-scope.md`, `docs/04-architecture.md` and `docs/05-data-model.md` (glossary, §5, LM-03). The original display requirements (continuous visibility near the message action area, no hover, selected/local timezone, secondary full date/time) are retained. History note: the wording was applied prematurely in `873926f`, withdrawn in `83da324` because it had not been approved, and applied again on acceptance.

Mapping of the accepted semantics to what is tested on the development host:

| Accepted semantic | Verified by |
| --- | --- |
| Every committed user/assistant message has a server-authoritative absolute timestamp | `test_commit_time.py`, `test_store_behavior.py`; UTC text instant in every message DTO |
| Sampled inside the committing transaction, after write authority, before the commit attempt | `test_each_write_transaction_samples_the_clock_once_inside_itself`, `test_instant_is_read_before_the_commit_attempt_not_at_commit`, lock-wait and slow-generation fixtures |
| Authoritative only for an operation that committed; an attempt known not to have committed retains none | `test_a_reading_taken_for_an_attempt_known_not_to_have_committed_is_not_retained` (added at closure to cover this acceptance criterion; the implementation needed no change) |
| Uncertain outcome: no success claim, possible original timestamp not discarded; reconciliation preserves the original if it committed, else a later success samples its own | `test_uncertain_commit_that_was_durable_…`, `test_uncertain_commit_that_did_not_persist_…`, `test_uncertain_publication_that_was_durable_…`; client "Not confirmed saved" shows no time |
| No promise of physical commit-time equality, millisecond accuracy or unconditional bounds | stated above; delay tests assert only *which* reading is stored |
| Identity, position and timestamp independent; clock adjustments never reorder history | `test_order_is_server_assigned_even_when_instants_are_equal_or_decreasing` (`test_execution.py`); client renders server order, not timestamp order (`App.test.tsx`) |
| Continuously visible near the message, no hover; full date/time available; client-local or selected timezone | `MessageItem`; `App.test.tsx` (visible `<time>` per message), `time.test.ts` (timezone, date boundary) — **jsdom only; see pending acceptance** |
| Existing history and provenance preserved | no schema or data change was made |

This is the *accepted contract* and *development-host test evidence*. It is not full V0 acceptance of FR-15: the display acceptance criteria require inspection on Windows, macOS and iPhone.

## Pending platform acceptance

Nothing below has been done; V0 platform acceptance (NFR-05, V0-AC-01–V0-AC-03, FR-15 display criteria) is **not** complete.

- **Real browser** — the client has only been exercised under jsdom and headless Chrome on macOS. The no-hover, continuously-visible time and layout need inspection in real Safari/Chrome/Edge; `toBeVisible` in jsdom does not evaluate real layout.
- **Windows** — the slice has never run on Windows (server or client). SQLite/WAL/`synchronous = FULL` behavior and the commit-gap timing are unmeasured there (hardware gates G-01–G-03).
- **iPhone/Safari** — never run. Needs the real viewport, touch reachability, and a check that the secondary full date/time (currently the `title` attribute, which has no hover on touch) is actually discoverable; if it is not, that is a client change to make then.
- **Timezone display** — verify on each device, across a date boundary, with the device's real local timezone (unit-tested only).

## Frontend

React + TypeScript (Vite). State is presentation state only; after every send the client re-reads the authoritative history. Message times are rendered continuously next to the author label (no hover) in the browser's timezone from the server's UTC instant, with the full date/time in the `title`. A send whose outcome cannot be confirmed (network/5xx) is kept as "Not confirmed saved" and can be retried with the **same** `submission_id`. Message text is rendered as plain text.

## Running the checks

See the README. Server: `uv run pytest`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`. Client: `npm test`, `npm run typecheck`, `npm run build`. The pytest suite includes a real-process restart test (orderly stop and SIGKILL) marked `process`.

## Review remediation (client and guard behavior)

Changes made after the independent review ([report](../reviews/slice-0a-codex-review.md), [remediation plan](../../.agent/plans/2026-10-10-slice-0a-review-remediation.md)). None alters server semantics.

- **History freshness (R1).** Only the request that is still the latest for the *currently selected* conversation may update the screen; late successes and late errors for anything else are discarded. Navigating away or unmounting invalidates in-flight loads. The composer is enabled only while the displayed conversation is the selected one. A restored draft or send error belongs to the conversation it was written in.
- **Unconfirmed sends (R2, corrected twice).** Only the server's answer to a submission's own `submission_id` settles its outcome. A history read never does: a snapshot can be older than a save that is still arriving, so neither the absence nor the presence of a message in the history is read as the outcome (and the client never matches by content). An unconfirmed message keeps its id, conversation and content and stays on screen as *Not confirmed saved* until one of:
  - **Retry sending** — same id. The server returns the original outcome (`200 replayed`, no duplicate message or run) if it was saved, or saves it now. Success removes the record. **A refused retry (e.g. `409 busy`) does not settle anything:** it says nothing about whether an earlier transmission with that id will still arrive and commit. The submission therefore stays *Not confirmed saved*, with the same id, conversation and content and Retry still available, plus a line "the server refused this retry: … that does not show that the earlier attempt failed". It is never turned into an ordinary composer draft, however many times retries are refused. Only a **first and only** transmission that is definitively refused (nothing else outstanding) restores the text to the composer as a draft with the server's error.
  - **Discard and reload** — a user decision to stop tracking it. Immediate and local: it sends nothing, restores nothing, and refreshes the view only. The message stays listed as *Abandoned — outcome unknown* (explicitly "not confirmed failed"), with *Retry abandoned message* (same id; the record moves straight into the active slot, so a refusal returns it to *Not confirmed saved*, never to a draft) and *Forget abandoned message* (removes the note only).
  - **Abandon, then send again as a new message** — the same abandonment plus the text placed in the composer. A new id exists only if the user then presses Send, which may duplicate the abandoned message if the delayed original later commits; the notice says so. This is the only way a new id is created for an uncertain message.

  States shown: sending; not confirmed saved (including after refused retries); abandoned (outcome unknown); saved (record removed, history shows it). There is no polling and no automatic retry. The records are in-memory presentation state: a browser reload drops them (the server's history is unaffected), a known limitation.
  *Residual limitation, proposed extension not implemented (and out of scope for this task):* the server cannot tell the client that an id is dead, so an abandoned-then-rewritten message can duplicate if the delayed original lands. Closing that needs server-side fencing of the id (e.g. an "abandon submission" tombstone); it adds a persisted fact type and needs an owner/design decision.
- **Links (R3).** A `#/c/…` hash that cannot be decoded shows "That conversation link is not valid" with the conversation list still usable and is not silently replaced. Identifier *format* remains the server's decision (`400 invalid_identifier`).
- **Load failures (R4).** HTTP-level failures of the list or conversation load show an error with a user-initiated "Retry loading …" button (a single idempotent GET each). There is no automatic retry. Transport failures still use the banner Retry.
- **Origins (R5).** See the security posture above.

## Gate carried forward: R6 / LD-04 (not addressed in 0A)

`ModelPort` is a synchronous `generate` call. Before any real, long-running or separately supervised runtime is attached (Slice 0B), a design task (likely with an ADR) must define: runtime correlation and supervision; known termination versus uncertain transport failure; the durable fact "output observed, publication uncertain"; safe admission release for `in_flight`/`indeterminate` runs; and explicit retry on the same saved user message with a new run. Treating a transport exception as proof of non-execution is not permitted. This is a blocker for the real-runtime milestone, not a defect of the fake adapter.

## Known limitations

- A conversation whose run is `indeterminate` stays blocked until a future reconciliation mechanism exists (workaround for development: use another conversation or delete the dev database).
- No pagination; `GET /conversations/{id}` returns all messages and runs.
- Conversation creation is not idempotent.
- No client linter (type-check only).
- The conversation *list* has no freshness guard analogous to the history one (a stale list response could briefly omit a just-created conversation until the next refresh); not part of the accepted findings.
- Never verified on Windows or iPhone/Safari; only headless Chrome on macOS and jsdom (see Pending platform acceptance).
