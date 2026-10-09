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

**Not guaranteed, and not claimed:** equality with the database engine's own commit instant. The committing row has to contain the value before `COMMIT` runs, and committed messages are immutable by trigger, so the stored instant is *at or before* the durable commit by the duration of the remaining statements and the flush.

**What the delayed-commit tests do and do not show.** The lock-contention fixtures show that a commit delayed by waiting for the write lock gets the later instant (not the arrival time), and the generation-delay fixture shows the assistant instant is the publication moment. The tests that inject a delay (60 s in the review characterization test, 90 s in `test_instant_is_never_later_than_the_commit_it_belongs_to`) between the sample and `COMMIT` only show that the stored value is the earlier sample and never later than `COMMIT`. They are **not** evidence of exact correspondence with the physical commit instant, and nothing here should be cited as such.

**Observed interval, one host, informational (no tolerance exists):** `tools/evidence/sqlite/measure_commit_instant_gap.py`, macOS 27 / arm64 / Python 3.12 / SQLite 3.53.1, WAL + `synchronous = FULL`, 300 synthetic transactions of each kind, two runs. Elapsed time from the clock read to `COMMIT` returning: admission median ≈ 0.38–0.39 ms (p99 ≈ 0.7–0.9 ms), dispatch ≈ 0.20 ms, publication ≈ 0.33 ms (p99 ≈ 0.55–0.6 ms); largest single observation 2.6 ms. Caveats: SQLite on macOS does not request a full media flush unless `fullfsync` is enabled, so this under-represents a power-safe flush; Windows and any other target must be measured separately (the existing hardware gates G-01–G-03).

### R7 status: OPEN_PENDING_OWNER_DECISION

No normative document (FR-15, LM-03, the domain model, the scope) has been changed, and **full FR-15 compliance is not claimed**. FR-15 says the timestamp must "correspond to commitment to persistent history, including a delayed-commit fixture" without stating a tolerance. The implementation satisfies that only under the reading "assigned inside the committing transaction while the exclusive write lock is held, no later than its commit".

**Evaluation of the recommended clarification** ("each committed message has an authoritative server-assigned recording instant, sampled during finalization of the persistence operation; authoritative only when the transaction commits; no guarantee of equality with the engine's physical COMMIT instant; ordering independent of timestamps"). *Sufficient for the user's need* — to know when a message was recorded — at human precision, because the interval is a fraction of a millisecond here and the direction of the error is fixed (never later than the commit). It is *not yet sufficient as written*, for these reasons:
1. "Sampled during finalization" does not exclude a sample taken before waiting for the write lock, which would reintroduce the arrival-time error the user does not want. It must name the point: inside the committing transaction, after exclusive write access is held.
2. It omits the bound's direction (never earlier than lock acquisition, never later than the commit) that makes "approximately when it was recorded" checkable.
3. It omits the consequence for failed or unknown commits: a sample taken for an attempt that did not commit, or whose commit outcome is unknown, is discarded and never presented as committed (REC-02); a retry takes a fresh sample; a replay returns the original.
4. It renames the concept to "recording instant". FR-15, LM-03, the domain model and the scope all say commit time/instant; renaming risks being read as weakening the user's requirement. Keep "commit instant" and define it.
5. The acceptance criterion "delayed-commit fixture" must be restated, otherwise it cannot be met or falsified: the fixture that is meaningful is a commit delayed by write-lock contention (and, separately, by generation before assistant publication), checking the stored instant tracks the later moment and never exceeds the commit; no numeric tolerance until physical-design/Windows evidence sets one.

**Sampling position.** It is already as late as practical without a second, non-atomic write: after the lock, before the first INSERT; the remaining time is the INSERTs and the durable flush (≈0.2–0.4 ms of which almost all is the commit itself). Moving it a statement later would change microseconds and add risk; no code change is proposed. Re-stamping after commit (breaks LM-01 immutability and atomicity) and a second post-commit timestamp (a window with no instant) remain rejected.

**Exact wording proposed for owner approval** (not applied anywhere):

> *FR-15 statement, first sentence replaced by:* Anonymous shall persist an authoritative **commit instant** for every user and assistant message. The commit instant is read from the server clock inside the same atomic persistence transaction that commits the message to conversation history, after that transaction holds exclusive write access and as late as practicable before commit is requested, and is stored as an absolute instant independent of client timezone. It is therefore never earlier than the moment the server obtained exclusive write access and never later than that transaction's commit, and it is not guaranteed to equal the storage engine's own physical commit instant. It becomes authoritative only if that transaction commits; a value read for an attempt that did not commit, or whose commit outcome is unknown, is discarded and never presented as committed history. A committed message keeps its instant across reads, retransmission, reconciliation and restart. Timestamps shall not be the sole source of conversation ordering, and no ordering is derived from them.
>
> *FR-15 acceptance criteria, "including a delayed-commit fixture" replaced by:* Delay the commit of a user-message save (for example by holding the write lock from another connection) after the request arrived, and separately delay assistant publication by slow generation: the stored instants reflect the later lock-acquisition and publication moments, not request arrival, generation start or client time, and are not later than the corresponding commit. The observed interval between the instant and the commit is recorded for the evidence host; no numeric tolerance is required until persistence physical design sets one.
>
> *LM-03 and the "Commit instant" glossary row (05-data-model §§4–5):* the same definition, replacing "the authoritative instant when the server commits the message" by "the authoritative server-clock instant assigned inside the committing transaction, no later than its commit (FR-15)". *Domain model §9 "Commit time" row:* one added clause with the same meaning.

**Affected contracts if approved:** `docs/02-requirements.md` FR-15; `docs/05-data-model.md` glossary row and LM-03; `docs/01-domain-model.md` §9 row; consistent wording check of `docs/03-v0-scope.md` (lines 24, 81, 126, 174) and `docs/04-architecture.md` (line 95). No ADR is needed unless the owner treats it as architectural. No code change follows from approval; the tests listed above already match the proposed acceptance.

**If not approved**, the requirement stays as written, R7 stays open, and the implementation and tests stay as they are.

## Frontend

React + TypeScript (Vite). State is presentation state only; after every send the client re-reads the authoritative history. Message times are rendered continuously next to the author label (no hover) in the browser's timezone from the server's UTC instant, with the full date/time in the `title`. A send whose outcome cannot be confirmed (network/5xx) is kept as "Not confirmed saved" and can be retried with the **same** `submission_id`. Message text is rendered as plain text.

## Running the checks

See the README. Server: `uv run pytest`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`. Client: `npm test`, `npm run typecheck`, `npm run build`. The pytest suite includes a real-process restart test (orderly stop and SIGKILL) marked `process`.

## Review remediation (client and guard behavior)

Changes made after the independent review ([report](../reviews/slice-0a-codex-review.md), [remediation plan](../../.agent/plans/2026-10-10-slice-0a-review-remediation.md)). None alters server semantics.

- **History freshness (R1).** Only the request that is still the latest for the *currently selected* conversation may update the screen; late successes and late errors for anything else are discarded. Navigating away or unmounting invalidates in-flight loads. The composer is enabled only while the displayed conversation is the selected one. A restored draft or send error belongs to the conversation it was written in.
- **Unconfirmed sends (R2, corrected in the follow-up).** Only the server's answer to a submission's own `submission_id` settles its outcome. A history read never does: a snapshot can be older than a save that is still arriving, so neither the absence nor the presence of a message in the history is read as the outcome (and the client never matches by content). An unconfirmed message therefore keeps its id and stays on screen as *Not confirmed saved* until one of:
  - **Retry sending** — same id. The server returns the original outcome (`200 replayed`, no duplicate message or run) if it was saved, or saves it now. Success removes the record; a definite refusal (4xx) means that attempt saved nothing and restores the text to the composer with a notice that an *earlier* attempt was never confirmed (only server-side fencing of the id, see below, could rule that out).
  - **Discard and reload** — a user decision to stop tracking it. Immediate and local: it sends nothing, restores nothing, and refreshes the view only. The message stays listed as *Abandoned — outcome unknown* (explicitly "not confirmed failed"), with *Retry abandoned message* (same id) and *Forget abandoned message* (removes the note only).
  - **Abandon, then send again as a new message** — the same abandonment plus the text placed in the composer. A new id exists only if the user then presses Send, which may duplicate the abandoned message if it was in fact saved; the notice says so.

  States shown: sending; not confirmed saved; abandoned (outcome unknown); saved (record removed, history shows it); refused (error plus notice). There is no polling and no automatic retry. The records are in-memory presentation state: a browser reload drops them (the server's history is unaffected), a known limitation.
  *Residual limitation, proposed extension not implemented:* a refused retransmission proves that attempt saved nothing, not that an earlier in-flight attempt cannot still commit. Closing that needs the server to fence the id, e.g. an "abandon submission" operation that records a tombstone so a late request with that id is refused (and returns the saved outcome if it already committed). That adds a persisted fact type, so it needs an owner/design decision; no API or schema change was made.
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
