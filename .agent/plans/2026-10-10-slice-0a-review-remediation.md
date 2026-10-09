# Slice 0A — Codex review remediation (R1–R5, R7 investigation; R6 preserved as a gate)

## 1. Title, status, and purpose

**Status:** Complete for the remediation scope; awaiting Codex re-review. R6 remains an open gate by design. Remediation changes are uncommitted on top of baseline commit `dfc33d0`.

The independent review ([report](../../docs/reviews/slice-0a-codex-review.md)) returned **PASS_WITH_REQUIRED_FIXES** for the development-only Slice 0A. This plan repairs the accepted bugs R1–R5, investigates the R7 timestamp test gap honestly, and records R6 (LD-04) as the separate design gate for real-runtime integration. It adds no features. Slice 0B, real runtimes, Memory, branching and production security are out of scope.

## 2. Repository context

- Slice 0A is described in [implementation notes](../../docs/implementation/slice-0a.md) and the [original ExecPlan](2026-10-07-v0-slice-0a-persistent-chat-fake-model.md). The server owns canonical data; the React client holds presentation state only and re-reads the server's history after each send.
- Client defects live in `client/src/App.tsx`, `client/src/useHashSelection.ts` and `client/src/components/MessageList.tsx`. The server defect lives in `server/src/anonymous/config.py` (origin allow-list used by `api/guards.py`). R7 concerns `server/src/anonymous/adapters/persistence/sqlite/store.py` and `connection.py`.
- Review artifacts (owned by Codex, not edited here): `server/review_tests/test_slice0a_review.py`, `client/review-tests/slice0a.review.tsx`, `client/review-tests/vitest.config.ts`.
- Baseline commit: `dfc33d0` (first local commit; nothing pushed). Baseline reproduced before any change: backend 95 passed; review suite 17 passed / 1 failed (R5); client 19 passed; client review suite 2 passed / 5 failed (R1×2, R2, R3, R4).

## 3. Requirements and acceptance criteria

| ID | Criterion |
| --- | --- |
| AC-R1 | A response (success or error) for a request that is no longer current never changes displayed detail, loading/error state, draft or send target. Covers A→B quickly, out-of-order responses, completion after unmount/navigation, newer selection superseding older, A→B→A, and old same-conversation refreshes. The composer is enabled only when the displayed detail belongs to the selected conversation. |
| AC-R2 | Discarding an unconfirmed send never places already-possibly-saved content into the composer, never sends anything, and never invents a successful save. Retransmission with the same `submission_id` stays available and idempotent. Creating a new message from the unconfirmed text is a separate explicit action that only becomes available after history was reconciled. Sending is blocked while reconciliation is outstanding. |
| AC-R3 | Malformed percent-encoding or invalid UTF-8 in `#/c/…` (on load and on `hashchange`) never throws; a visible "link is not valid" state keeps the conversation list usable. |
| AC-R4 | An initial or later HTTP-level failure of the list or detail load shows a user-initiated Retry. No automatic retry loop; only idempotent GETs are retried; a retry in flight cannot be double-fired. |
| AC-R5 | `http://[::1]:<port>` (and the IPv4/localhost forms) are accepted as same-origin; unrelated hosts, other ports, `null` and look-alike origins stay rejected; no wildcard. Loopback-only bind and `Host` guard unchanged. |
| AC-R7 | The documented and tested commit-instant guarantee is exactly what the implementation provides; no stronger claim; the residual gap and the smallest proposed resolution are recorded without changing FR-15. |
| AC-R6 | Recorded as an open blocker for the real-runtime milestone; no code. |
| AC-ALL | All pre-existing checks still pass (backend 95, client 19, mypy, ruff, tsc, build); the six deliberately failing review assertions pass; no history/ordering/provenance invariant changes. |

Non-goals: llama.cpp/real runtime, supervision, generation-retry redesign, streaming, cancellation, authentication, pagination, list-refresh ordering, conversation-create idempotency.

## 4. Constraints and open questions

- No change to server transaction, ordering, idempotency or provenance semantics (INV-003/006, LM-01–LM-05).
- Do not weaken FR-15 or silently redefine it (§5, R7). No requirement document is edited in this task.
- **Open (not resolved here):** FR-15 "correspond to commitment" has no stated tolerance; see R7 and Decision D-4.
- **Blocker preserved:** R6/LD-04 (see §9, §10 D-6).

## 5. Affected components and intended approach — finding map

| Finding | Component | Root cause | Fix | Regression test | Acceptance |
| --- | --- | --- | --- | --- | --- |
| **R1** HIGH | `App.tsx` detail loading, send completion, draft/send-error state | `loadDetail` applied every response to one shared `detail` with no freshness/selection check; send completion reloaded its *original* conversation; draft and send error were global; render accepted any `detail` | Per-selection request generation (`detailSeq`) invalidated on selection change/unmount via layout-effect cleanup; `loadDetail` only runs for the currently selected id and applies results only if still current (success **and** error); displayed detail must match `selectedId`; draft and send error carry their conversation id | `App.test.tsx` R1 group: cross-conversation send completion, stale same-conversation refresh, late error after switch, rapid A→B→A out-of-order, unmount in flight; review tests R1×2 | AC-R1 |
| **R2** MED | `App.tsx` `discard`; `MessageList.tsx` actions | Discard cleared the only `submission_id` and prefilled the composer with possibly-saved text, so the next Send was a new intent | Discard now **reconciles first** (keeps the pending record until history was reloaded), restores nothing, blocks sending while reconciling; reload failure keeps the uncertain record and its retry. Separate explicit action "Save as a new message" restores text to the composer (new `submission_id` on Send) only after reconciliation, with a visible note | `App.test.tsx` R2 group: discard does not prefill/duplicate; retry still reuses id; reconciliation failure keeps record; explicit new-message path creates a distinct id; no send while reconciling; review test R2 | AC-R2 |
| **R3** MED | `useHashSelection.ts`, `App.tsx` | `decodeURIComponent` throws `URIError` during state init and on `hashchange` | Safe parse returning `{ id } \| { invalid }`; hook exposes `invalid`; App shows a message and does not auto-select over it | `useHashSelection.test.tsx` + `App.test.tsx`: `%`, `%E0%A4%A`, `%FF`, valid/empty, `hashchange` after mount, recovery by choosing a conversation; review test R3 | AC-R3 |
| **R4** LOW | `App.tsx` error panels | Retry only rendered for transport failure (`serverDown`); HTTP errors dead-ended; detail error had no action | "Retry loading …" buttons on list and detail error panels (user-initiated GETs; error cleared while retrying so it cannot be double-fired) | `App.test.tsx`: list 503 → retry → recovers; detail 503 → retry → recovers; no automatic refetch; network-down banner unchanged; review test R4 | AC-R4 |
| **R5** LOW | `config.py` `allowed_origins`, dev client origins | Origin set built for IPv4/localhost only although `::1` is a supported bind and `[::1]` an allowed Host | Build explicit loopback same-origin set (`127.0.0.1`, `localhost`, `[::1]`) for the configured port; add `http://[::1]:5173` dev origin; no wildcard | `tests/api/test_http.py`: positive (3 same-origin forms, IPv6 POST) and negative (other port, other host, `null`, look-alike, wrong scheme, unbracketed IPv6) | AC-R5 |
| **R7** MED (test gap) | `store.py`, `connection.py`, docs | Instant is sampled **inside** the write transaction after `BEGIN IMMEDIATE` and admission checks, immediately before the INSERTs; `COMMIT` follows. The row cannot contain the exact COMMIT instant | No semantic change. Document the exact guarantee; add tests for what *is* provable: sampling happens only after the write lock is held (lock-contention delayed-commit fixture), assistant instant is the publication instant not dispatch/generation time, instant never later than its COMMIT (see §7) | `tests/persistence/test_commit_time.py` | AC-R7 |
| **R6** HIGH design gap | model port / execution coordinator | Port exposes only synchronous `generate`; no supervision/termination/publication-uncertainty protocol | **Not fixed.** Recorded as blocker | — | AC-R6 |

## 6. Work sequence

1. Baseline commit (done) and baseline test reproduction (done).
2. R3 (smallest, isolates hook), R1 (restructure loading), R2 (builds on R1's ownership), R4. Working directory `client/`; run `npm test`, `npm run typecheck`, review config.
3. R5 in `server/`; run `uv run pytest`, review suite, mypy, ruff.
4. R7 investigation, tests, documentation in `docs/implementation/slice-0a.md`.
5. Full validation, documentation, plan reconciliation. (No remediation commit: left in the working tree for review.)

Retry/recovery: every step is a source edit under version control; revert with `git checkout -- <file>`. No state-changing runtime operation is involved; tests use a temporary DB.

## 7. Validation strategy

- Commands (all from the stated directory): `server/`: `uv run pytest`, `uv run pytest review_tests/test_slice0a_review.py -q`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`. `client/`: `npm test`, `npm exec vitest run -- --config review-tests/vitest.config.ts`, `npm run typecheck`, `npm run build`. (Node from fnm; see review report §2.)
- Expect: all original tests still pass; all review assertions pass (backend 18/18, client 7/7); new tests listed in §5 pass.
- Preservation/privacy cases: server tests are not weakened; origin negatives keep the guard honest; no content is logged; test data are synthetic.
- R7 tests prove only: (a) instant sampled after the write lock was acquired (a request that waits for the lock gets the later instant); (b) assistant instant ≠ dispatch/generation start; (c) instants are monotone with positions when the clock is monotone, and ordering is unaffected by backward clocks; (d) the instant persists unchanged across reads/restart/replay. They do **not** claim equality with the engine's COMMIT instant.

## 8. Progress

- [x] 2026-10-10 Baseline local commit `dfc33d0`; baseline test counts reproduced.
- [x] 2026-10-10 ExecPlan created.
- [x] 2026-10-10 R3 safe hash parsing (`useHashSelection.ts`) + invalid-link state.
- [x] 2026-10-10 R1 request freshness / selection ownership / per-conversation draft and send error (`App.tsx`).
- [x] 2026-10-10 R2 reconcile-before-forget; three explicit actions (`App.tsx`, `MessageList.tsx`, `Composer.tsx`).
- [x] 2026-10-10 R4 user-initiated retry on list and detail HTTP errors.
- [x] 2026-10-10 R5 exact IPv4/localhost/IPv6 loopback origins; strict `Host` parsing (`config.py`, `api/guards.py`).
- [x] 2026-10-10 R7 investigation, tests (`tests/persistence/test_commit_time.py`), documentation; FR-15 reading proposed, not applied.
- [x] 2026-10-10 R6 recorded as a gate in `docs/implementation/slice-0a.md` and here.
- [x] 2026-10-10 Full validation (see §11).
- [ ] Codex independent re-verification (not part of this task).

## 9. Discoveries

- Passing the review tests alone proved little: the original 5 failing client assertions pass with a much smaller change than needed for the underlying races. The new regression tests were therefore checked against the **old** source: 16 of the 20 new client tests and 4 of the new server tests fail there (the remaining ones are preservation guards), and the commit-time tests were mutation-checked by sampling the clock before the write lock in `publish_response` (2 tests failed; change reverted).
- The Host guard parsed `[::1].evil.example:8000` as `[::1]` because it cut at the first `]` and ignored what followed. It is not a realistic browser-reachable bypass (such a name is not a valid DNS host) but it contradicted "exact" matching, so the parser was made strict while fixing R5. A bracketed literal with a trailing suffix, a non-numeric port, userinfo or an unbracketed IPv6 are now `400 invalid_host`.
- R1 had a second leak not named in the report: a refused send's restored draft and error message were global, so a refusal arriving after navigation put A's text into B's composer. Both are now bound to their conversation.
- The old `Composer` draft was never cleared after sending, so leaving and re-entering the conversation could re-insert a stale draft. `send` now clears it (no remount).
- The R2 test only needs "no restored draft", but a bare removal of the prefill would silently lose the user's text if the first attempt had *not* saved. That is why the explicit "send again as a new message" path exists.
- R7: the sample point is already after the write lock and before the INSERTs, so a request delayed by lock contention gets the later instant (new fixture). The unavoidable residual is sample → COMMIT. No change to production code was needed or made for R7.
- Latent, not in the findings: the conversation *list* response has no freshness guard (documented in the implementation notes limitations).
- Environment: `npm` is not on the login-shell PATH; the fnm Node path from the review report was used. A real Chrome/Safari smoke was not possible; a real-process IPv6 smoke with curl was run instead.

## 10. Decision log

- **D-1 (2026-10-10):** Keep the existing button label "Discard and reload" (the review test and users know it), but change its behavior to reconcile-then-forget; no prefill. Accepted (implementation-level).
- **D-2:** Do not validate UUID shape in the client; the server owns identifier format (implementation-local per implementation notes) and already returns `400 invalid_identifier`. Only *undecodable* hashes are classified client-side.
- **D-3:** `detailSeq` + selected-id ref instead of AbortController: the API wrapper has no signal plumbing and result discarding is sufficient because the requests are idempotent GETs.
- **D-4 (R7, PROPOSAL — not accepted, no document changed):** state in FR-15/LM-03 that the commit instant is sampled inside the committing transaction while the write lock is held (≤ durable COMMIT), accept it with a lock-contention delayed-commit fixture and a "never later than COMMIT" bound, and defer any numeric tolerance to physical design. Rejected: post-commit re-stamp (breaks immutability/atomicity), a second post-commit timestamp (window with no instant). Needs the owner's decision; ADR only if it becomes architectural.
- **D-5:** The review test files are not edited. New regression tests live in the normal test directories.
- **D-6:** R6/LD-04 stays an explicit blocker for Slice 0B; no ADR written because nothing architectural is decided here.
- **D-7:** Tightening the `Host` parser is treated as part of R5 ("review Host and Origin validation"), not new scope.

## 11. Final outcome

**Changed:** client (`App.tsx`, `useHashSelection.ts`, `MessageList.tsx`, `Composer.tsx`, `styles.css`), server (`config.py`, `api/guards.py`), tests, `docs/implementation/slice-0a.md`, this plan. No server transaction, ordering, idempotency, provenance or schema code changed; no ADR, requirement or domain document changed.

**Validation actually run (2026-10-10, macOS):**

| Check | Result |
| --- | --- |
| `server`: `uv run pytest` | **106 passed** (95 original + 5 origin/host + 6 commit-time) |
| `server`: `uv run pytest review_tests/test_slice0a_review.py` | **18 passed** (was 17 passed / 1 failed) |
| `server`: `uv run mypy` | no issues in 50 source files |
| `server`: `uv run ruff check .` / `ruff format --check .` | pass / 51 files formatted |
| `client`: `npm test` | **43 passed**, 4 files (19 original + 20 remediation + 4 hash-parser) |
| `client`: review config | **7 passed** (was 2 passed / 5 failed) |
| `client`: `npm run typecheck`, `npm run build` | pass; 24 modules |
| Real-process smoke (`::1`, curl) | same-origin POST 201; other port 403; foreign origin 403; `[::1].evil.example` Host 400; `0.0.0.0` bind refused |

**Not verified:** real browser rendering (Chrome/Safari unavailable), Windows, iPhone, or any physical-timing measurement of sample → COMMIT.

**Unresolved:** R6/LD-04 (by design, gate for 0B). R7 FR-15 wording decision D-4. List-refresh freshness (latent, not a finding). Codex re-verification pending.

**Follow-up:** Codex re-review → owner decision on D-4 → minimal LD-04 design task (+ ADR) → explicit authorization for Slice 0B.
