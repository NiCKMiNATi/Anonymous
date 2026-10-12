# Slice 0B-1 — development-host verification and acceptance handoff

**Status: `CLOSED` on the macOS development host — 2026-10-12, for Slice 0B-1 scope only.** Engineering verification passed (section 3), both independent reviews were accepted by the owner, and the owner ratified O1–O6 (section 7). This closes the slice against a **scripted, in-process runtime**. It is not acceptance of any external runtime, real model, Windows, iPhone/Safari, production authentication or access containment (section 6). History: the handoff was `READY_FOR_OWNER_ACCEPTANCE` until the owner's ratification.

## 1. Repository state

Branch `main`; verified at `b33d88e` (`Slice 0B-1: fix watchdog reservation leak, assert COMMIT faults fired, sync SIGKILL test`) with a clean working tree before this record was added. The local `origin/main` ref equalled `b33d88e` when checked; no fetch was performed and nothing was pushed by this task, so the remote's true state is unverified (earlier records say "not pushed").

**Closure update (2026-10-12):** after ratification, only documentation changed. `git diff b33d88e HEAD -- server client` is empty, so the engineering results in section 3 were obtained on the same source and tests that are closed. The remote `main` was read-only checked at `b33d88e`; later local documentation commits are unpushed.

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
- [x] Independent review of the final remediation diff: `PASS`.
- [x] Independent design review of ADR-0013/0014 revision 3.1: `PASS_WITH_ADVISORIES`; advisories corrected (`4d99a86`).
- [x] Owner accepted both reviews as satisfying the scoped review requirement, and ratified O1–O6 (2026-10-12).
- [x] ADR-0013/0014 set to Accepted for 0B-1 scope; LD-04 design status and verdict updated; ExecPlans updated.
- [x] Source and tests unchanged since verification (`git diff b33d88e HEAD -- server client` empty).
- [ ] *Open, not a closure gate:* client tests and dedicated presentation for the new refusal codes (UX gap).
- [ ] *Open, not a closure gate:* owner confirmation of the NFR-08/LM-08 requirement wording (still Draft; it was not separately ratified).
- [ ] *Open, not a closure gate:* push state (remote `main` was `b33d88e`; later documentation commits are local).

## 6. Status classification

- **Implemented:** LD-04 revision 3.1 lifecycle against the scripted in-process runtime (migration 0002, arbiter, handoff gate, evidence-based settlement, reservations and admission gate, retry, configuration binding, instance guard).
- **Tested and verified:** sections 3-4, on macOS only (synthetic data, loopback).
- **Accepted:** Slice 0A (development host); **Slice 0B-1 (development host, scripted/in-process scope)**; ADR-0013 and ADR-0014 (0B-1 scope); LD-04 design revision 3.1 (0B-1 scope); owner decisions O1-O6.
- **Deferred or unverified (not newly accepted):** any external runtime (llama.cpp) and 0B-2; real-model integration; verified external-runtime safety; Windows; iPhone/Safari; SQLite on Windows; the ADR-0011 exclusive-instance mechanism (the development guard is not it); production authentication and access containment; U-1/U-2/U-3 (contained, not eliminated); submission fencing; a legacy-capable evidence producer; real private data and any exposure beyond loopback; NFR-08/LM-08 requirement wording; dedicated refusal-code UI and tests. Reported counts of mutation checks and earlier repeat runs come from earlier records, not re-run here.

## 7. Owner decisions O1-O6 (**ratified by the owner, 2026-10-12**)

Ratified as stated by the owner in the acceptance instruction; the text below is the recorded form. Authoritative locations: O1, O4, O5, O6 in [ADR-0013](../adr/0013-execution-attempt-lifecycle-and-release-evidence.md); O2, O3 in [ADR-0014](../adr/0014-execution-configuration-provenance-and-continuity.md); all six in [design §14](../design/ld-04-execution-lifecycle.md).

| | Decision | Ratification |
| --- | --- | --- |
| O1 | Unverifiable runtime termination quarantines the execution slot; no force release without admissible evidence. | **APPROVED** |
| O2 | Automatic startup binding only for eligible, previously unbound pre-0B conversations after the documented baseline verification (digest check plus FX-01-FX-06 replay; FX-07 by the test suite). Existing bindings never silently replaced. Explicit adoption mandatory for changes, unverifiable equivalence and unavailable configurations. No retroactive attribution of unrecorded model provenance to historical messages. | **APPROVED** |
| O3 | Refuse inadmissible sends before saving the user message; preserve unsent client drafts on definite refusal. | **APPROVED** |
| O4 | Closure may discard completed but unpublished output; explicit retry required; success already durably published is preserved. | **APPROVED** |
| O5 | Unresolved legacy execution states block unsafe dispatch until admissible reconciliation. | **APPROVED** |
| O6 | The additional durable write of the lifecycle is acceptable. | **APPROVED** |

**O2 consistency check (done 2026-10-12, no implementation change needed).** Startup binding applies only to pre-0B conversations that have no binding (`bind_legacy_conversations` selects `record_epoch = 'legacy_0a'` conversations with no binding row and inserts bindings only; it touches no run or message). `test_configuration.py` asserts historical provenance stays unrecorded. Unbound, unverifiable or unavailable cases are refused (`configuration_unbound_legacy`, `configuration_unavailable`) until explicit adoption, which exists at application level only (no route or UI).

## 8. ADR-0013 / ADR-0014

Both are **Accepted for Slice 0B-1 scope (2026-10-12).** Their stated conditions were an independent review of the revised design and owner confirmation:

- **Design review:** `PASS_WITH_ADVISORIES` with no blocking finding, both advisories corrected (ADR-0013 B3-B5 / B6 removed; ADR-0014 and design 11.3-11.4 startup replay wording). The original report is **not stored**; what was relayed is recorded in the [independent review record](slice-0b-1-independent-review-record.md), which also states its limits and that it was supplied through the project handoff.
- **Implementation review:** `PASS` on the final diff (static; relayed text in the same record).
- **Owner confirmation:** O1-O6 ratified and both reviews accepted as satisfying the scoped requirement.
- **Scope of acceptance:** decisions and 0B-1 behavior against a scripted in-process runtime. Every runtime-evidence row remains open (design section 14). The NFR-08/LM-08 *requirement wording* is a separate draft in the requirements and data-model baselines and was not separately ratified; it is **not** a condition of these ADRs, but remains an open owner item.

## 9. Next milestone

Slice 0B-2, **runtime evidence only**: [.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). It is a plan; nothing has started. No model download without the owner's separate authorization and a stated size cap; synthetic data and loopback only.
