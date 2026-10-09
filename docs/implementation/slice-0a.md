# Implementation notes — V0 Vertical Slice 0A (persistent local chat with a fake model)

**Status:** Implemented as a development-only slice. Not finished V0, not an access-capable build, not release evidence. The [ExecPlan](../../.agent/plans/2026-10-07-v0-slice-0a-persistent-chat-fake-model.md) records scope, decisions and results. This page describes *what the code does*; the design documents ([architecture](../04-architecture.md), [logical data model](../05-data-model.md), ADRs) remain authoritative and are unchanged. Nothing here finalizes an open design question.

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

Investigated for review finding R7. Behavior is unchanged; this records exactly what the adapter does so no stronger claim is made.

| Step | When it happens |
| --- | --- |
| Client composes/sends | Not used for any stored instant. |
| Request arrives / waits for the write lock | Not used. A request delayed by lock contention gets the instant of *winning the lock*, not of arrival (tested). |
| Transaction start | `BEGIN IMMEDIATE` acquires the exclusive write lock. |
| **Instant sampled** | Once per write transaction, from the injected clock, after the lock is held and the admission checks passed, immediately before the INSERTs. The same value stamps the message and its run/submission rows in that transaction. |
| Message insertion | Statements after the sample. |
| Durable commit | `COMMIT` with `synchronous = FULL`. |
| Client presentation | Formatting of the stored UTC instant in the browser timezone only. |

Guarantees (tested in `server/tests/persistence/test_commit_time.py`): the instant is never earlier than the moment the write lock was acquired; it is never later than the `COMMIT` of the transaction that made the message durable; no other writer commits between sample and `COMMIT` (the write lock is held); the assistant message has its own instant taken at publication (not generation start or user-message time); the stored instant never changes on reads, replay or restart; order is the integer `position`, never the instant.

**Not guaranteed, and not claimed:** equality with the database engine's own commit instant. The committing row has to contain the value before `COMMIT` runs, and committed messages are immutable by trigger, so the stored instant is *at or before* the durable commit by the duration of the remaining statements and the flush. In this adapter nothing waits between the sample and `COMMIT` except those statements and the disk flush, but no numeric tolerance has been measured or specified. The review's characterization test (`review_tests`, one-minute artificial delay between sample and `COMMIT`) demonstrates exactly this gap.

**Open question recorded, not resolved here:** FR-15 requires the timestamp to "correspond to commitment to persistent history, including a delayed-commit fixture" but does not state a tolerance. The implementation satisfies the requirement only under the reading "sampled inside the committing transaction while the write lock is held". Smallest proposed resolution (needs the owner's decision; an ADR only if the decision becomes architectural): add one sentence to FR-15/LM-03 stating that reading and that acceptance is demonstrated with a lock-contention delayed-commit fixture plus the "never later than COMMIT" bound, with any numeric tolerance deferred to the physical-design task. Rejected alternatives: re-stamping after commit (breaks LM-01 immutability and atomicity) and a second, post-commit timestamp (adds a window in which a committed message has no instant). Requirements and domain documents are intentionally unchanged.

## Frontend

React + TypeScript (Vite). State is presentation state only; after every send the client re-reads the authoritative history. Message times are rendered continuously next to the author label (no hover) in the browser's timezone from the server's UTC instant, with the full date/time in the `title`. A send whose outcome cannot be confirmed (network/5xx) is kept as "Not confirmed saved" and can be retried with the **same** `submission_id`. Message text is rendered as plain text.

## Running the checks

See the README. Server: `uv run pytest`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`. Client: `npm test`, `npm run typecheck`, `npm run build`. The pytest suite includes a real-process restart test (orderly stop and SIGKILL) marked `process`.

## Review remediation (client and guard behavior)

Changes made after the independent review ([report](../reviews/slice-0a-codex-review.md), [remediation plan](../../.agent/plans/2026-10-10-slice-0a-review-remediation.md)). None alters server semantics.

- **History freshness (R1).** Only the request that is still the latest for the *currently selected* conversation may update the screen; late successes and late errors for anything else are discarded. Navigating away or unmounting invalidates in-flight loads. The composer is enabled only while the displayed conversation is the selected one. A restored draft or send error belongs to the conversation it was written in.
- **Unconfirmed sends (R2).** An unconfirmed message keeps its `submission_id` until the saved history has been reloaded. Three distinct actions: *Retry sending* (same id, idempotent), *Discard and reload* (reload history, then forget the local copy; sends nothing, restores nothing), and *Reload, then send again as a new message* (reload history, then place the text in the composer with a notice; sending it deliberately creates a new message with a new id). Sending and the other recovery actions are blocked while the reload is outstanding; if the reload fails the unconfirmed record stays. The client never decides by content that a message was or was not saved.
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
- Never verified on Windows or iPhone/Safari; only headless Chrome on macOS and jsdom.
