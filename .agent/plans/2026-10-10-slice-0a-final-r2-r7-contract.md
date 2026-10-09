# Slice 0A — final R2 remediation and R7 contract preparation

## 1. Title, status, and purpose

**Status:** Complete for scope. R2: fixed. R7: `OPEN_PENDING_OWNER_DECISION` — candidate wording prepared, **no normative document changed**. Base `873926f`; supersedes the FR-15 application in that commit (withdrawn here).

Codex's lightweight review of `9ded738..1eaae70` found: **R2 (MEDIUM)** a refused retransmission lost the unresolved submission's correlation; **R7 (MEDIUM)** my timestamp proposal contained unsupported wall-clock bounds and described unknown-commit timestamp disposal incorrectly. This plan fixes R2 and corrects/prepares R7. It does not implement server-side fencing, LD-04, Slice 0B, authentication or Memory.

## 2. Repository context

- Earlier plans: `2026-10-10-slice-0a-review-remediation.md` (R1–R5), `2026-10-10-slice-0a-r2-r7-followup.md` (R2 abandonment model, R7 evaluation, and an addendum recording a premature application of FR-15 wording that is **withdrawn** here).
- Client code: `client/src/App.tsx` (`submit`, `retry`, `abandon`, `retryAbandoned`), `client/src/components/MessageList.tsx`. Test fake: `client/src/test/fakeBackend.ts`.
- Authoritative docs for R2: `docs/05-data-model.md` LM-05 and `docs/03-v0-scope.md` V0-D04 (a refusal or missing confirmation asserts neither "saved" nor "nothing was saved"; the server's answer to the same submission settles it).
- Authoritative docs for R7: `docs/02-requirements.md` FR-15, `docs/05-data-model.md` §5/LM-03/glossary, `docs/01-domain-model.md` §9.

## 3. Requirements and acceptance criteria

**R2 — all hold:**
1. A refused retransmission (e.g. `409 busy`) keeps the original `submission_id`, conversation binding, content and *uncertain* state; Retry stays available.
2. A refusal of a retransmission never implies the earlier request with that id failed; it never becomes an ordinary composer draft, however many times it repeats.
3. A new submission id is created only by a distinct explicit user action (Send after "Abandon, then send again as a new message", or a brand-new message).
4. A successful history read never settles a submission by presence or absence.
5. No automatic send/retry/polling. R1/R3/R4/R5 behavior untouched.

**R7:** normative documents unchanged; exact edits and affected references prepared; the proposal states: transaction-scoped sampling, after write authority, before the commit attempt; no numeric/wall-clock bounds; unknown outcome ≠ rollback; reconciliation preserves the original timestamp if it committed; ordering independent of timestamps. No claim of full FR-15 compliance.

## 4. Constraints and open questions

- Do not change FR-15, the domain model or the logical data model without explicit owner approval (AGENTS.md; repeated by the owner). **Open:** owner approval of the wording below.
- Out of scope: server fencing of abandoned ids (proposal only, remains a documented limitation).

## 5. Affected components and intended approach

| Part | Root cause → fix |
| --- | --- |
| R2 `App.tsx` `submit` | In the `catch`, only `unknownOutcome` errors kept the record; any 4xx cleared `pending` and restored an ordinary draft, which for a retransmission discarded the id while the delayed original could still commit. Now: `unknownOutcome \|\| afterUncertainty` keeps the record as `unknown` (message: "the server refused this retry … does not show that the earlier attempt failed"); only a **first and only** transmission's definite refusal still restores a draft. The unused refusal notice was removed. `retryAbandoned` moves the record into `pending` in the same step, so its identity is never held by nothing. |
| R2 tests | `App.remediation.test.tsx`: the previous refusal test was replaced by five tests (below). |
| R7 docs | `docs/implementation/slice-0a.md`: wall-clock claims removed; event-order statements; unknown ≠ rollback; status `OPEN_PENDING_OWNER_DECISION`. `test_commit_time.py`: docstrings/renamed test no longer claim inequalities between wall-clock readings; "accepted" → "candidate". |
| Normative docs | `01`, `02`, `03`, `04`, `05` restored to the `1eaae70` content (verified: zero diff). |

## 6. Work sequence (done)

1. Client fix + tests, checked against the prior implementation (all 5 new tests fail there). 2. Withdraw normative edits (`git checkout 1eaae70 -- docs/0{1,2,3,4,5}-*.md`). 3. Correct tests and notes. 4. Full validation. 5. Commit locally.

## 7. Validation strategy

Server: `uv run pytest`, `uv run pytest review_tests/test_slice0a_review.py`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`. Client: `npm test`, `npm exec vitest run -- --config review-tests/vitest.config.ts`, `npm run typecheck`, `npm run build`. R2 cases: busy retry while the original is delayed; original later commits; same-id recovery; three consecutive refused retries; refused retry of an *abandoned* message; conversation switching; explicit new id only after a distinct action; no extra sends.

## 8. Progress

- [x] R2 fix and five regression tests.
- [x] Normative edits withdrawn; verified identical to `1eaae70`.
- [x] R7 corrections in notes and tests; this plan.
- [x] Full validation (§11) and local commit.
- [ ] Owner decision on the candidate FR-15 wording (blocked on the owner).
- [ ] Codex re-review.

## 9. Discoveries

- Root cause of R2 was one branch in `submit`: refusal handling assumed "refused ⇒ this id is dead". True for a first transmission, false for a retransmission after uncertainty. Both `retry` and `retryAbandoned` flow through it.
- **My process error:** in the previous turn I treated the owner's pasted FR-15 text as approval and applied it to the five normative documents (`873926f`). It was a candidate. The edits are withdrawn; nothing else depended on them. The three uncertain-outcome tests added then remain: they assert implementation behavior, which is valid under the candidate and does not need approval.
- The earlier proposal's "never earlier than the lock / never later than COMMIT" is a wall-clock inequality and is unsupported (wall clocks can step); and "discard a value for an attempt whose outcome is unknown" wrongly implied rollback. Both removed from docs and from test docstrings. `test_instant_is_never_later_than_the_commit_it_belongs_to` asserted `<=` between two readings of a controlled clock; renamed and changed to assert *which* reading is stored (`!=` the later reading, `==` the earlier).

## 10. Decision log

- **D-13:** A refused retransmission keeps the submission uncertain for every 4xx class (not only 409): the server's refusal is an answer to *that request*, not to the earlier one (V0-D04). Rejected: classifying some refusals (e.g. validation) as proof of failure — more cases, same unfenced residual.
- **D-14:** Retry of an abandoned message returns to the active *uncertain* state after a refusal rather than back to the abandoned list: the user re-engaged, and the composer stays blocked until they act. Alternative (return to abandoned) rejected as hiding a fresh refusal.
- **D-15:** Normative FR-15 changes withheld pending owner approval; prepared edits below. Supersedes D-10's "applied" addendum in the earlier plan.
- **D-16:** Fencing stays unimplemented (explicitly out of scope).

### Proposed normative edits (NOT applied)

Apply only on explicit owner approval; then re-run the commit-time tests and update `docs/implementation/slice-0a.md` status.

**A. `docs/02-requirements.md`, FR-15 (`### FR-15 — Persist and continuously display message timestamps`; keep the heading text so existing anchors keep working).**

*Statement — replace the whole bullet with (owner-supplied wording, verbatim):*

> Every committed user and assistant message shall have a server-assigned absolute timestamp, designated its **commit timestamp**.
> The commit timestamp shall be sampled within the transaction responsible for committing the message, after the transaction has obtained the required write authority and before its commit attempt.
> The sampled timestamp becomes authoritative only if the corresponding message is successfully committed.
> If the transaction outcome is uncertain, the system shall not present the message or its timestamp as confirmed solely on the basis of that attempt. Reconciliation must determine whether the original operation committed. If it did, the originally persisted timestamp shall be preserved; if it did not, a subsequent successful operation may establish a new timestamp.
> The commit timestamp represents the server's recording time for the committed message. It does not guarantee exact equality with the storage engine's physical commit-completion instant or a universally bounded difference.
> Message identity, authoritative order and commit timestamp are independent. Equal timestamps, clock adjustments or non-monotonic wall-clock readings must never alter established message order.
> Clients shall display the authoritative timestamp in the selected or local timezone, continuously visible near its message.

*Source/rationale — append:* "The Statement was replaced on <approval date> by the owner-supplied wording, resolving review finding R7; it supersedes 'representing when that message is committed to persistent conversation history'. The no-hover, 'near the message action area' and optional secondary full date/time display details are not repeated in the Statement and remain required by the acceptance criteria and V0 Scope unless the owner states otherwise."

*Acceptance criteria — replace the first sentence ("Save both user and assistant messages and verify their timestamps correspond to commitment to persistent history, including a delayed-commit fixture.") with:* "Save both user and assistant messages and verify, by instrumenting the transaction, that each commit timestamp is read inside the committing transaction after it obtained write authority and before its commit attempt. Delayed-commit fixtures: a commit delayed by waiting for write authority, and an assistant message published after slow generation, carry the reading taken at that later point — not request arrival, generation start or client time. Verify that a timestamp read for an attempt known not to have committed is not retained, and that after an attempt with an uncertain outcome nothing is assumed either way: reconciliation determines whether it committed; if so the originally persisted timestamp is kept and returned unchanged, otherwise a subsequent successful operation establishes a new timestamp. No equality with, or numeric bound on the difference from, the storage engine's physical commit-completion instant is required or asserted." *(Remaining sentences — reopen/reconnect/restart, no-hover display on Windows/macOS/iPhone, timezone rendering, secondary full date/time, ordering independence, REC-02/REC-03 — unchanged.)*

*Status — change to:* "Draft — user-directed; Statement wording supplied by the owner <approval date>; acceptance criteria adapted by the implementer, confirmed by the owner <date or 'pending'>; REQUIRED_V0 selection is recorded in V0 Scope."

**B. `docs/05-data-model.md`.**
- Glossary row "Commit instant" → "The server's recording time for a committed message: an absolute instant sampled within the committing transaction after it obtained write authority and before its commit attempt (FR-15). Authoritative only if that transaction commits; not guaranteed equal to the storage engine's physical commit-completion instant. Required for every persisted user/assistant message. Stable across reads, retry/reconciliation and timezone rendering; distinct from execution timings."
- §5 sentence "commit instant answers **when it became persistent history**" → "**when the server recorded it as persistent history** (FR-15)".
- LM-03: after the first sentence add: "The instant is sampled within the committing transaction after it obtained write authority and before its commit attempt, becomes authoritative only if that transaction commits, and carries no guarantee of equality with, or a bounded difference from, the storage engine's physical commit-completion instant (FR-15). If a commit outcome is uncertain, reconciliation decides whether the original operation committed: if so its original instant is kept; an attempt known not to have committed establishes none, and a later successful operation samples its own." Keep "A write that committed before its acknowledgment was lost retains the original instant upon reconciliation. …" unchanged.

**C. `docs/01-domain-model.md` §9 "Commit time" row** → "The server's authoritative recording time for a message committed to persistent conversation history, sampled within the committing transaction after it obtained write authority and before its commit attempt (FR-15); not guaranteed equal to the storage engine's physical commit-completion instant. It is retained with the message as an absolute instant independent of client timezone. It does not mean client composition/send time, model generation start/completion, or client receipt/display time." (Domain model is an authoritative starting document: needs explicit owner approval specifically.)

**D. Consistency clauses (wording only):** `docs/03-v0-scope.md` the paragraph beginning "Each user and assistant message retains an authoritative timestamp for its commitment…" and `docs/04-architecture.md` the paragraph beginning "For FR-15, C05/C08 establish and preserve…": add "sampled within the committing transaction after write authority and before the commit attempt; authoritative only if it commits; not guaranteed equal to the engine's physical commit-completion instant".

**E. Affected references reviewed and expected to need no change:** `03-v0-scope.md` (summary table row, display paragraph, requirement table, V0-AC rows citing FR-15), `04-architecture.md` traceability row, `05-data-model.md` traceability row, `07-security.md` (commit time is not the security-expiry clock), `01-domain-model.md` §9 introductory sentence and invariants INV-001–INV-015 (unchanged). No ADR is needed unless the owner treats the change as architectural.

## 11. Final outcome

**R2 fixed.** Validation on macOS, 2026-10-10: server `pytest` **109 passed**; Codex backend review suite **18 passed**; `mypy` clean (50 files); `ruff check` and `ruff format --check` clean. Client `npm test` **53 passed** (4 files); Codex client review suite **7 passed**; `tsc` 0 errors; `npm run build` passes. The five new R2 tests fail against the previous `App.tsx` (checked).

**R7 open.** Normative FR-15/domain/data-model text unchanged (zero diff against `1eaae70`); proposal in §10; no full-compliance claim.

**Limitations:** unfenced ids (an abandoned-then-rewritten message can duplicate if the delayed original lands); in-memory records lost on browser reload; no real-browser, Windows or iPhone verification; commit-gap measurement is one host and informational only.

**Follow-up:** owner decision on the wording → apply edits A–D and update notes → Codex re-review → LD-04 design task (which may also decide fencing).
