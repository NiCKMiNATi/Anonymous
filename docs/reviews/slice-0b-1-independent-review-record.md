# Slice 0B-1 — independent review record (relayed)

**Provenance of this record.** The original review reports are **not stored in this repository and were not exported from Codex into it**. Everything below was supplied to this project through the project handoff (owner/ChatGPT-relayed messages in the working conversation) and recorded here on 2026-10-12. Where the relayed text is quoted it is marked as relayed. Where nothing was supplied, this record says so and does not reconstruct it. Treat this as a record of what the owner accepted, not as primary review evidence. If the original reports are available, adding them under `docs/reviews/` would strengthen the record.

## 1. Reviews and verdicts

| # | Subject | Reviewer (as relayed) | Verdict | Status of the original report |
| --- | --- | --- | --- | --- |
| 1 | 0B-1 implementation at `ecef413` (static) | Codex | Four findings (worker tracking HIGH; pending-admission race MEDIUM; missing COMMIT-boundary coverage MEDIUM; test accuracy LOW). The verdict label was not relayed. | Not stored. Findings known from the [remediation record](../implementation/slice-0b-1-remediation.md). |
| 2 | Remediation diff `ecef413..bdd1afa` (static) | Codex | `PASS_WITH_REQUIRED_FIXES`; original findings 2 and 3 accepted as resolved, three findings remained (under original findings 1 and 4) (watchdog reservation leak; AFTER_COMMIT assertions; SIGKILL synchronization). | Not stored. Findings known from the remediation record §8. |
| 3 | Final three-fix diff `bdd1afa..b33d88e` (static) | Codex | **`PASS`**, no actionable findings. | Relayed text in section 3 below. |
| 4 | ADR-0013 / ADR-0014 design, revision 3.1 | Independent reviewer (relayed as "the final independent ADR-0013/0014 revision 3.1 review") | **`PASS_WITH_ADVISORIES`**, no blocking design finding. | Only the verdict and the two advisories were relayed (section 2). |

Earlier design reviews (revision 1 `BLOCKED` with F1–F7; revision 2 `BLOCKED` with five corrections) are recorded in the [LD-04 design §16](../design/ld-04-execution-lifecycle.md) and are likewise not stored.

## 2. Design review of ADR-0013/0014 revision 3.1 (relayed summary)

- **Scope as relayed:** ADR-0013 and ADR-0014 revision 3.1. Whether the review also covered every section of the LD-04 design document was not stated.
- **Verdict:** `PASS_WITH_ADVISORIES`; no blocking findings.
- **Advisories and dispositions** (both documentation-only; corrected in local commit `4d99a86`, 2026-10-12, no semantics changed):

| Advisory | Disposition |
| --- | --- |
| A1 — ADR-0013 stale B6 references: the scripted-adapter evidence range read B3–B6 and the design handoff still permitted B6. | Corrected: B3–B5 in ADR-0013; the lightweight review handoff no longer permits B6 (B3/B4 after an unknown handoff, B5 only with `late_delivery_excluded`). B6 stays removed (revision 3.1). One dated revision-3 history entry in the LD-04 ExecPlan still mentions B3–B6 and was left as history. |
| A2 — ADR-0014 startup verification: Decision 8 and design §§11.3–11.4 implied every golden fixture replays at startup. | Corrected: startup checks the fixture digest and replays FX-01–FX-06; FX-07 is verified in the test suite through the real store (confirmed against `golden_replay` in `server/src/anonymous/application/configuration.py`). The evidence record's step 3 was aligned. |

- **Limitations:** the full report, reviewer identity beyond "independent", the reviewed commit, any reviewer observations beyond the two advisories, and the review method were not supplied.

## 3. Implementation review of `bdd1afa..b33d88e` (relayed text)

> **PASS.** Reviewed the verified range `bdd1afa309ed..b33d88ec6579`. No actionable findings within the three-fix scope.
>
> All three required corrections are present: **Worker reservations** (`supervisor.py`): claim and abandonment are mutually exclusive under the registry lock; failed child starts release their reservation; uncertain starts retain ownership; late abandoned wrappers cannot execute their target. **Fault-injection coverage** (`tests/commit_faults.py`): injection counts, immediate assertions and teardown verification prevent the identified silent-fault false positives; the inspected test paths target the intended transactions. **SIGKILL synchronization** (`tests/integration/test_process_restart.py`): the test waits for durable `STARTED/ACCEPTED` before killing the process; its single-run dataset makes the lookup unambiguous.
>
> Static tracing found no introduced regression in handoff synchronization, publication fencing, evidence-based settlement, quarantine, reconciliation, or slot ownership. The changed tests appear capable of detecting their intended failures.
>
> No files were modified. No tests, builds, lint, or type checks were executed; reported executable results were not independently verified. This remediation is suitable for development-host acceptance, subject to executable verification and outstanding owner decisions O1–O6 and ADR-0013/0014. This verdict covers scripted/in-process behavior only, not external-runtime safety.

**Limits of this review (from its own text):** static only; scope was the three-fix diff; scripted/in-process only; it executed nothing. The executable results were produced separately by the development-host verification in the [acceptance handoff](slice-0b-1-acceptance-handoff.md) §3.

## 4. What the owner accepted (2026-10-12)

The owner accepted the implementation `PASS` and the design `PASS_WITH_ADVISORIES` as satisfying the **scoped** independent-review requirements of ADR-0013 and ADR-0014 for Slice 0B-1. This record does not claim these reviews cover external runtimes, Windows, iPhone/Safari, authentication or access containment, or the NFR-08 requirement wording.
