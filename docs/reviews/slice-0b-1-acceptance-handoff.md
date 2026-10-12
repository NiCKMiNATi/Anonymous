# Slice 0B-1 — development-host verification and acceptance handoff

**Status: `READY_FOR_OWNER_ACCEPTANCE`** (not `CLOSED`). Engineering verification on the development host passed on 2026-10-12. Nothing here is owner acceptance, ADR acceptance, or evidence about any external runtime, Windows, iPhone, or production security.

## 1. Repository state

Branch `main`; verified at `b33d88e` (`Slice 0B-1: fix watchdog reservation leak, assert COMMIT faults fired, sync SIGKILL test`) with a clean working tree before this record was added. The local `origin/main` ref equalled `b33d88e` when checked; no fetch was performed and nothing was pushed by this task, so the remote's true state is unverified (earlier records say "not pushed").

## 2. Independent review and disposition

Codex static review of `bdd1afa..b33d88e` (the three-fix remediation): **PASS**, no actionable findings; static only, it ran nothing. Disposition: nothing to fix, so no source or test changed in this task and no further independent review is required (no architectural or concurrency change was made after the review). The earlier rounds are recorded in [the remediation record](../implementation/slice-0b-1-remediation.md): four findings on `ecef413` (fixed in `bdd1afa`), then three on `bdd1afa` (fixed in `b33d88e`). Seven findings in total, all remediated and now reviewed.

The original review reports are not stored in the repository; the findings are known only from those records and the handoffs.

## 3. Verification actually run (2026-10-12, macOS, from `server/` and `client/`)

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest tests -q` | **302 passed** (19.6 s) |
| `ruff check .` / `ruff format --check .` | clean / 80 files formatted |
| `mypy` (strict) | no issues in 79 source files |
| `npm test` (vitest) | **53 passed** (4 files) |
| `vitest run --config review-tests/vitest.config.ts` | **7 passed** |
| `npm run typecheck` (`tsc --noEmit`) / `npm run build` | no errors / built, 24 modules (`client/dist` is git-ignored) |
| Concurrency, reservation, watchdog, recovery subset (`tests/application`, `tests/integration`, concurrent submissions, commit-time; 180 tests) | 8 consecutive runs, all passed |
| `docs/evidence/ld-04-0b1-remediation-race-repro.py` on the current tree | F1 `shutdown()` returns False with the guard held, and stays held after the worker starts; F2 reconcile did not run inside the admission window, run `succeeded` with an assistant message |
| Real-process smoke (loopback, fake model, throwaway database, synthetic text) | health open (0 legacy-unresolved, 0 quarantined); send 201; replay of the same submission id 200; `[fake:fail]` send recorded a `failed`/`fake_failure` run; retry 201 left **one** user message and two runs; SIGTERM exit clean (both servers) |

Not re-run in this task: the 15-20x repeat counts reported earlier, mutation checks, and the `server/review_tests` historical suite (obsolete API, outside the suite).

Two scripting slips occurred while smoke testing (a zsh glob error that prevented the second server from starting, and a blank exit-code echo from a bash-only variable). Both were harness mistakes, were rerun, and are not product results.

## 4. Behavioral checks

| Required behavior | How it was checked | Result |
| --- | --- | --- |
| Retry reuses the authoritative user message | `test_retry.py::test_retry_creates_one_new_run_on_the_same_user_message_and_no_duplicate_message`; 15 retry-related tests pass; HTTP smoke above | verified |
| Unresolved execution cannot dispatch unsafely | `-k "unresolved or quarantine or legacy"`: 21 passed; commit-boundary, reconcile and ownership/crash tests (full suite) | verified (scripted/in-process) |
| Slot release requires documented evidence | `-k "slot or release or T7"`: 23 passed; SQL-versus-domain admissibility parity test; arbiter tests | verified (scripted/in-process) |
| Late results cannot publish after an incompatible closure | `-k "late or closure"`: 17 passed; handoff-protocol and run-arbiter tests | verified (scripted/in-process) |
| Legacy 0A data intact | `test_migration_0002.py`, `test_legacy_dataset.py` (6 pass; before-state snapshots captured before the operation) | verified |
| Configuration and runtime provenance consistent | `-k "provenance or configuration or golden"`: 26 passed, including all 7 golden fixtures through the real store | verified |
| Client keeps an unsent draft on a refused send | Code read (`App.tsx` `submit`: any definite refusal of a first transmission restores the draft for its own conversation) and tests `App.test.tsx` (refusal, 409 busy) and `App.remediation.test.tsx` (draft stays in its conversation). | verified for the generic path; **gap below** |

**Outstanding UX gap (recorded, not fixed):** the restore path is code-agnostic, but only `conversation_busy` is exercised at the client. The 0B-1 refusal codes (`runtime_quarantined`, `generation_blocked_legacy_unresolved`, `configuration_*`, `retry_not_eligible`, `execution_unresolved`) have no client test and no dedicated presentation; the user sees the server's sanitized message. This was already listed in [slice-0b-1.md](../implementation/slice-0b-1.md).

## 5. Development-host acceptance checklist

- [x] Server suite, lint, format and strict types pass on the committed tree.
- [x] Client suite, review suite, `tsc` and build pass.
- [x] Concurrency/reservation/recovery subset stable over repeated runs.
- [x] Before/after race reproduction behaves as designed.
- [x] Real-process loopback smoke: send, replay, failure, explicit retry, clean shutdown.
- [x] Independent review of the final remediation diff: PASS.
- [ ] Owner decisions O1-O6 (section 7).
- [ ] ADR-0013/0014 status decision (section 8).
- [ ] Push state confirmed with the owner (section 1).
- [ ] Optional: client tests for the new refusal codes (UX gap).

## 6. Status classification

- **Implemented:** LD-04 revision 3.1 lifecycle against the scripted in-process runtime (migration 0002, arbiter, handoff gate, evidence-based settlement, reservations and admission gate, retry, configuration binding, instance guard).
- **Tested and verified:** items in sections 3-4, on macOS only.
- **Accepted:** Slice 0A (development host). **Nothing in 0B-1 is formally accepted.**
- **Deferred or unverified:** any external runtime (llama.cpp), 0B-2, Windows, iPhone/Safari, SQLite on Windows, the ADR-0011 exclusive-instance mechanism (the development guard is not it), authentication, LAN or public exposure, and production security. Reported counts of mutation checks and earlier repeat runs are from earlier records, not re-run here.

## 7. Owner decisions O1-O6 (recommendations; **all six PENDING owner ratification**)

Nothing below is owner approval. A decision is ratified only when the owner states it explicitly (a decision, not silence or a prior task instruction), at which point it is recorded with its date in the ADR/design it affects and in the table's last column. The two review advisories (stale B6 text; startup replay wording) were corrected in documentation only and change no decision below.

| | Question | Recommendation | Ratification |
| --- | --- | --- | --- |
| O1 | Unverifiable termination quarantines the single slot; no force release | Accept for 0B-1. Make "can Anonymous own the runtime process" an explicit question of the 0B-2 evidence task rather than weakening CB-05. | PENDING |
| O2 | Bind legacy conversations at startup only after the baseline reproduces the real 0A golden fixtures | Accept. Startup binding checks the fixture digest and replays FX-01–FX-06; FX-07 is verified by the test suite only. Explicit adoption remains the way to change a configuration, and the requirement if equivalence cannot be shown. | PENDING |
| O3 | Refuse before saving while quarantined or the configuration is unavailable | Accept, and keep the draft-restoring client behavior (section 4). | PENDING |
| O4 | Closure discards a completed but unpublished result; the user retries | Accept. | PENDING |
| O5 | Existing 0A datasets with unresolved runs cannot dispatch; no force release or attestation | Accept; use the fresh `anonymous-0b1-dev.sqlite3`. Any special treatment is a CB-05 weakening needing its own ADR. | PENDING |
| O6 | One extra durable write (T3b) and one best-effort write (T3c) per dispatch | Accept; the cost is small and carries the safety property. | PENDING |

## 8. ADR-0013 / ADR-0014

Both stay **Proposed**. Their own text requires (a) independent review of the revised design and (b) owner confirmation.

- **(a) Design review: satisfied, as reported.** The independent review of revision 3.1 returned `PASS_WITH_ADVISORIES` with no blocking finding; the review report itself is not stored in the repository, so this rests on the report relayed to this task. The implementation was also reviewed (`PASS` on the final diff). The two advisories were corrected in documentation only: ADR-0013's scripted-adapter evidence range is now B3–B5 and the lightweight handoff no longer permits B6 (B6 stays removed); ADR-0014 Decision 8 and design §§11.3–11.4 now say startup replays FX-01–FX-06 and checks the fixture digest, while FX-07 is verified in the test suite through the real store.
- **(b) Owner confirmation: not given.** O1–O6 are pending. The ADRs' "Implementation status" paragraphs also still say the implementation has not had independent review, which is now outdated; update them in the same change that records ratification, not before.

**O2 clarification.** Startup binding and explicit adoption cover different circumstances and do not conflict. Startup binding applies only to a pre-0B conversation that has no binding, only after the fixture digest and FX-01–FX-06 replay pass, and records `legacy_baseline` with its evidence; it never touches an already-bound conversation (`bind_legacy_conversations` selects only legacy conversations with no binding). Explicit adoption is the only route in every other case: changing a configuration, or establishing one when equivalence cannot be shown (the conversation is then refused with `configuration_unbound_legacy`). If the baseline later fails the self-test after binding, the binding stands, the configuration becomes unavailable (`configuration_unavailable`), and adoption is again required. The code and both documents agree; no implementation change is needed. The only policy question left is the owner's: may startup attribute unbound legacy conversations to the verified baseline without a per-conversation owner action (as proposed), or must adoption always come first?

**Remaining owner-acceptance gates:** (1) ratify O1–O6 explicitly; (2) confirm that the relayed `PASS_WITH_ADVISORIES` design review suffices as the independent review (ideally store its report); (3) then update ADR-0013/0014 status and implementation-status text, the design's §14 and verdict, and the ExecPlan; (4) confirm the push state; (5) only then mark Slice 0B-1 closed. Until then the status stays `READY_FOR_OWNER_ACCEPTANCE`.

## 9. Recommendation for the next milestone

1. Owner answers O1-O6 and the ADR-review question in section 8, then the ADRs are updated in a documentation-only change.
2. Then start the **0B-2 runtime-evidence task** (Mac host: control during generation, process ownership and exit verification, late-delivery behavior, identity reporting). It is an evidence task only, with no model download until the owner authorizes one and sets a size cap, synthetic data, and loopback only.
3. Do not start the access/security slice or runtime integration before the above.
