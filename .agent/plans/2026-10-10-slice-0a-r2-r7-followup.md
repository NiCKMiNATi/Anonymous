# Slice 0A — R2 correction and bounded R7 / FR-15 evaluation (follow-up to the lightweight Codex review)

## 1. Title, status, and purpose

**Status:** Complete for scope; R2 fixed, R7 `OPEN_PENDING_OWNER_DECISION`. Base `dfc33d0`, head at start `9ded738` (contains the first remediation). Codex's lightweight review of `dfc33d0..9ded738` returned **PASS_WITH_REQUIRED_FIXES**: R1, R3, R4, R5 resolved; R2 not resolved; R7 is a design discrepancy. This plan fixes R2 and evaluates R7 without changing any normative requirement.

## 2. Repository context

- The remediation (`.agent/plans/2026-10-10-slice-0a-review-remediation.md`) made *Discard and reload* "reconcile first": it reloaded conversation history and, on **any** successful GET, dropped the pending record (and its `submission_id`). Code: `client/src/App.tsx` `reconcile()`.
- Authoritative sources: `docs/05-data-model.md` LM-05 (retransmission "resolves original acceptance/outcome"; reconcile "establishes the existing outcome"), `docs/03-v0-scope.md` V0-D04 ("neither 'saved' nor 'nothing was saved' is asserted until reconciliation establishes the outcome"; "on reconnect, inspect the authoritative saved outcome"), `docs/02-requirements.md` REC-02/FR-15.
- Server side already provides the correlated resolver: `POST /conversations/{id}/messages` with the same `submission_id` returns the original outcome (`200 replayed: true`) if it committed, never a duplicate; a brand-new admission otherwise. No server change is needed for R2.

## 3. Requirements and acceptance criteria

R2 (all must hold):
1. The `submission_id` of an uncertain send is preserved until a server-correlated result or an explicit user abandonment.
2. Absence from, or presence in, a history response is never interpreted as the submission's outcome; a successful history GET never changes the submission's state.
3. Only the response to a request carrying that `submission_id` (success/replay, or a definite server refusal) establishes the outcome.
4. Same-ID retry keeps working and cannot duplicate history.
5. No automatic send, retry, or polling.
6. The UI distinguishes **sending**, **not confirmed**, **abandoned by the user (outcome still unknown)**, **saved (confirmed)** and **refused (definitely not saved by that attempt)**.
7. Abandonment is user-initiated, local, and never presented as confirmed failure.

R7: evaluate the recommended wording; do **not** edit normative documents without owner approval; classify R7 `OPEN_PENDING_OWNER_DECISION`; make no claim of full FR-15 compliance; keep the existing delayed-commit tests honest about what they prove.

Non-goals: R1/R3/R4/R5 changes, LD-04, real runtime, streaming, Memory, authentication, branching/merging, a new submission API.

## 4. Constraints and open questions

- LM-05/V0-D04 fix the product outcomes; transport/correlation mechanics are design work. The HTTP contract of Slice 0A is an implementation decision of the slice.
- **Residual limitation (documented, not solved):** a definite refusal of a *retransmission* proves that attempt did not save; an earlier attempt still in flight could in principle commit later. Only server-side fencing of the id would close that. Proposed (not implemented): a small `abandon submission` operation recording a tombstone so a late request with that id is refused. Needs owner/design approval because it adds a persisted fact type.
- Open: owner decision on FR-15 wording (R7).

## 5. Affected components and intended approach

| Part | Change |
| --- | --- |
| `App.tsx` | Remove history-gated reconciliation. Add an `abandoned` list. `abandon()` moves the active record to it (user action), optionally restoring the text to the composer for a deliberately new message; it refreshes the view but never alters the record. `retryAbandoned`/`forgetAbandoned`. A refused retransmission restores the draft with an explicit "earlier attempt never confirmed" notice. |
| `MessageList.tsx` | States and actions per §3.6; abandoned items rendered separately and visibly. |
| `client/src/test/fakeBackend.ts` | Test support: ability to lose a request whose commit lands later, to reproduce an older history snapshot followed by a late commit. |
| `docs/implementation/slice-0a.md`, this plan | Replace the "reconcile" description; record the R7 evaluation, measurement and proposal. |
| Server | No behavior change. |

## 6. Work sequence

1. Fake backend support for a delayed commit. 2. Client change. 3. Rewrite the R2 regression group. 4. Measure sample→COMMIT gap (evidence script). 5. Docs and R7 evaluation. 6. Full validation (commands as in the previous plan §7). 7. Commit locally.

## 7. Validation strategy

Deterministic client tests (no timers except flush): older-snapshot GET leaves the record untouched; late original commit then same-ID retry yields one user message and a replayed result; submission id identical across every transmission; refusal after uncertainty handled with the cautionary notice and no reuse of the id; switching conversations keeps the record; explicit abandon sends nothing, restores nothing, keeps an "abandoned" note; forget; rewrite-as-new produces a **different** id only when the user presses Send. Plus the whole existing suite, review suites, mypy, ruff, tsc, build.

## 8. Progress

- [x] 2026-10-10 Context read; plan written.
- [x] Fake backend support for a request that commits after the client gave up (`deferNextCommit` / `commitDeferred`).
- [x] Client: history-gated reconciliation removed; abandoned list; same-id retry of abandoned; refusal-after-uncertainty notice (`App.tsx`, `MessageList.tsx`).
- [x] R2 regression group rewritten (11 tests).
- [x] Sample→COMMIT measurement (`tools/evidence/sqlite/measure_commit_instant_gap.py`).
- [x] Docs + R7 evaluation (`docs/implementation/slice-0a.md`); test docstring corrected.
- [x] Validation (see §11) and local commit.

## 9. Discoveries

- The defect was only in the Discard path: `reconcile()` treated a successful history GET as proof and dropped the `submission_id`. Refresh never cleared the record, so the "older snapshot / late commit / retry" scenario passes on the old code as well; it is kept as a guard. The tests that fail on the old code are the discard/abandon ones (5 of the 11 R2 tests).
- The first remediation also made the composer, Refresh and recovery buttons wait on that GET; with abandonment being immediate and local none of that gating is needed, so it was removed rather than adapted.
- Server API was already sufficient: same-id POST is the correlated resolver (LM-05). A definite refusal of a *retransmission* still cannot rule out an earlier in-flight attempt; only fencing the id could. Recorded as a proposal, not built.
- Sample→COMMIT interval on this Mac is ≈0.2–0.4 ms median, ≤≈1 ms p99 (one 2.6 ms outlier); macOS does not full-flush by default, so this understates a power-safe flush.
- The 90 s (and review 60 s) delayed-commit tests prove an inequality only; wording in the test and the docs says so.

## 10. Decision log

- **D-8:** No new API for R2 (same-id POST is the correlated resolver, LM-05).
- **D-9:** Keep the label "Discard and reload" (Codex's R2 probe clicks it). Meaning now: abandon tracking, refresh the view; nothing sent, nothing restored, record kept as abandoned.
- **D-10 (R7):** `OPEN_PENDING_OWNER_DECISION`. No normative edit. Exact proposed wording and affected documents are in `docs/implementation/slice-0a.md` ("R7 status"). The recommended wording is sufficient for "know when it was recorded" but needs five tightenings (sampling point after the write lock; bound direction; discard-on-failure rule; keep the term "commit instant"; restated acceptance fixture).
- **D-11:** No sampling-position code change: already after the lock and before the first INSERT; the rest is the commit itself.
- **D-12 (proposal only):** server-side fencing ("abandon submission" tombstone) to close the retransmission-refusal residual. Needs owner/design approval (adds a persisted fact type).

## 11. Final outcome

**R2: fixed.** Submission state changes only on the server's answer to that submission's id or on an explicit user abandonment; history reads never change it. **R7: open, awaiting owner approval;** no normative document touched; no claim of full FR-15 compliance. R1/R3/R4/R5 code untouched (the R1 stale-selection logic, hash parsing, list/detail retry and origin validation are unchanged).

**Validation (2026-10-10, macOS):** server `pytest` 106 passed; Codex backend review suite 18 passed; `mypy` clean (50 files); `ruff check` and `ruff format --check` clean. Client `npm test` 49 passed (4 files; 43 → 49 because the R2 group grew from 5 to 11 tests); Codex client review suite 7 passed; `tsc` and `npm run build` pass.

**Limitations:** records of uncertain/abandoned messages are in memory and lost on browser reload; the retransmission-refusal residual above; no real-browser, Windows or iPhone run; commit-gap measurement is one host.

## 12. Addendum — owner-supplied FR-15 wording (2026-10-10, after commit `1eaae70`)

> **SUPERSEDED / WITHDRAWN.** The owner's text was a *candidate*, not an approval; applying it in `873926f` was a mistake. The normative edits were withdrawn and R7 is `OPEN_PENDING_OWNER_DECISION` again — see [2026-10-10-slice-0a-final-r2-r7-contract.md](2026-10-10-slice-0a-final-r2-r7-contract.md). The text below is kept as history only; its statements that the contract is accepted and applied are no longer true.

The owner pasted a replacement FR-15 statement. It was treated as the approval the plan was waiting for (D-10 → **superseded**): R7 moves from `OPEN_PENDING_OWNER_DECISION` to *contract accepted; server side implemented and tested; device acceptance pending*.

- **Applied:** FR-15 Statement verbatim (heading text unchanged so existing anchors keep working); consistent clauses in `05-data-model.md` (glossary, §5 sentence, LM-03), `01-domain-model.md` ("Commit time" row), `03-v0-scope.md` (timestamp paragraph) and `04-architecture.md` (FR-15 paragraph). The FR-15 *acceptance criteria* were adapted by the implementer (delayed-commit fixture restated as lock-contention/slow-generation fixtures; uncertain-outcome reconciliation; no physical-instant bound) and are marked as awaiting owner confirmation.
- **Differences from the earlier proposal (D-10):** the owner's wording does not promise "never earlier than the lock / never later than COMMIT" and explicitly disclaims any bounded difference; those remain implementation facts documented in the notes, not contract. It also uses "commit timestamp" (the term was kept) and does not repeat the display details; they remain in the acceptance criteria and V0 Scope.
- **Tests added** (`test_commit_time.py`, +3): uncertain-but-durable admission keeps the original instant on same-id reconciliation; uncertain-and-not-durable leaves no message and the retry samples anew; uncertain-but-durable publication keeps its sampled instant. Backend suite 109 passed; review suite 18 passed; mypy, ruff clean. No application code changed.
- **Not claimed:** full FR-15 acceptance (device display on Windows/macOS/iPhone, owner confirmation of the re-derived acceptance criteria, real-browser check).
