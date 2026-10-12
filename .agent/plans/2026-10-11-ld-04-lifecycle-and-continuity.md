# LD-04 — Runtime execution lifecycle and cross-version continuity (design; revision 3 after two BLOCKED reviews)

## 1. Title, status, and purpose

**Status:** Design work **complete and accepted for Slice 0B-1 scope (2026-10-12)**: ADR-0013 and ADR-0014 Accepted, LD-04 design revision 3.1 accepted, O1–O6 ratified. Remaining open items: NFR-08/LM-08 requirement wording confirmation, and everything gated by runtime evidence (0B-2). History: Revision 1 was returned **BLOCKED** (F1–F7); revision 2 was returned **BLOCKED** (five corrections); revisions 3 and 3.1 made them; revision 3.1 then passed independent review with advisories.

Purpose: define, safely enough that Slice 0B-1 can be implemented against a scripted port, how an execution attempt is owned, closed, published, released, recovered, retried and attributed, and how a conversation keeps its selected configuration across upgrades. Outcome: [LD-04 design](../../docs/design/ld-04-execution-lifecycle.md), [ADR-0013](../../docs/adr/0013-execution-attempt-lifecycle-and-release-evidence.md), [ADR-0014](../../docs/adr/0014-execution-configuration-provenance-and-continuity.md), revised NFR-08/LM-08 wording, and the review handoff.

## 2. Repository context

- Accepted semantics (unchanged): `docs/05-data-model.md` §§7–12 (LM-04–LM-07, CB-03–CB-06), `docs/04-architecture.md` §§8–9, `docs/03-v0-scope.md` V0-D03/D04/D06, ADR-0003/0004/0006/0011/0012, FR-15, INV-001–INV-015.
- 0A code (facts for the design): `ModelPort.generate` is synchronous with `ModelIdentity` only; `ExecutionCoordinator` settles any adapter exception as `failed(runtime_error)`; `recover_unsettled_runs` marks every `in_flight` run `indeterminate` and nothing can leave `indeterminate`; `settle_failed` accepts `pending`/`in_flight` with no basis; trigger `assistant_message_requires_in_flight_run` ignores any closure; the unique index covers `pending`/`in_flight`/`indeterminate`; runs carry only `model_id`/`runtime_id`; no retry; no binding or configuration.
- Runtime behavior is **unmeasured** (`docs/evidence/v0-mac-local-model-runtime-feasibility.md`; model download still unauthorized).
- The Codex review texts are not stored in the repository; F1–F7 and the five revision-3 corrections are taken from the remediation task statements.
- Facts used for revision 3 (verified against the code at `01e9f46`, whose `server/` tree equals the working tree): 0A's only concurrency guard is the per-conversation unique index, so unresolved runs may exist in several conversations; 0A calls `generate` only after `record_dispatch` commits; `ModelRequest` has one field (`messages`) and the context builder applies no instructions, settings or budget; `InstanceGuard` is a development exclusive file lock released by the OS on process death and explicitly not the ADR-0011 mechanism.

## 3. Requirements and acceptance criteria

Done when (revision 3 adds: the five corrections each have an explicit resolution; predicates are internally consistent; safety traces account for crashes and uncertain handoffs; migration preserves legacy facts; the golden baseline is anchored on real 0A behavior): the seven findings each have a resolution traced to design sections and scenarios; ADRs are Proposed with retained/proposed/evidence-needed separated; NFR-08/LM-08 and closely related rows are consistent; scenarios cover the required list (design §13); links resolve; no unrelated requirement is changed; handoffs exist. **Non-goals:** any implementation, real runtime, llama.cpp specifics, Memory/personas, authentication, failover, an owner force-release.

## 4. Constraints and open questions

- INV-001–INV-015, FR-15, LM-01–LM-07, CB-05 preserved; CB-05 explicitly not weakened.
- Owner-facing items needing confirmation: **O1** availability cost of quarantine and no force release; **O2** legacy conversations bound at startup after the golden check vs always requiring adoption; **O3** refusal before saving a message when quarantined, legacy-blocked or configuration-blocked; **O4** lost output on closure; **O5** existing 0A datasets with unresolved runs stay dispatch-blocked (no force release, no attestation); **O6** extra handoff write and the `start`/`await_result` split.
- Explicitly unresolved by design (contained, not asserted safe): U-1 delayed delivery after an `UNKNOWN` handoff, U-2 hung handoff, U-3 dependence on a single process (A-1).
- Blocked by runtime evidence (design §14): control during generation, instance/process identity and exit verification, idle/per-attempt status, disconnect behavior, digest and version reporting, Windows.
- Not independently accepted: nothing in this plan is.

## 5. Affected components and intended approach

C05 (supervisor, SP-1…SP-9, reconcile, retry, adopt), C06 (declares context configuration manifests), C07 (port: describe/prepare/generate/stop/probe, control router), C08 (arbiter conditional writes, fence, slot uniqueness, binding, provenance, configuration store), C10 (composition: slot id, adapter registry, boot id, startup reconcile). Source vs derived: unpublished output is transient; run evidence, binding, provenance and configuration manifests are source facts and are never relabeled.

## 6. Work sequence

1. (done) Read AGENTS.md, design, ADRs, plan, `execution.py`, `ports/model.py`, `models.py`, `store.py`, `0001_initial.sql`, data model §§7–12, architecture §§8–9, V0-D03/D04.
2. (done, rev 2) Rewrite the design; rewrite ADR-0013/0014 as Proposed; revise NFR-08, scope, architecture and data-model rows; update slice-0a note; update plan and handoff.
3. (done, rev 3) Capture the golden fixtures from `git archive 01e9f46` (twice, byte-identical) and record the evidence; revise design §§0–5, 6.1/6.3/6.4, 9, 11, 13–16; revise ADR-0013/0014; touch NFR-08/LM-08 wording and rows minimally; rewrite the handoff.
4. (done) Consistency, link and scope checks (§7); explicit-state check of the handoff protocol and of the transition predicates.
5. (next, separate authorization) Codex lightweight re-review → owner decisions O1–O4 → promote or amend ADRs → 0B-1 ExecPlan and implementation (migration, store, coordinator, port, tests LDT-01…42).
6. Then: runtime-evidence task → 0B-2.
Safe retry: all steps are document edits; re-running is idempotent.

## 7. Validation strategy

Documentation only: link check; ID/section reference check (requirement IDs, ADR numbers, design section numbers used by ADRs); status vocabulary vs `models.py`/`0001_initial.sql`; every scenario traced to a finding and an acceptance scenario; every decision classified; `git diff --stat` shows documents only. No runtime tests claimed.

## 8. Progress

- [x] 2026-10-11 Revision 1 (design, ADR-0013/0014, NFR-08).
- [x] 2026-10-11 Independent review of revision 1: **BLOCKED** (F1–F7).
- [x] 2026-10-11 Revision 2: design rewritten; ADRs set to Proposed; NFR-08/LM-08/scope/architecture/data-model/slice-0a edits.
- [x] 2026-10-11 Self-check (§11).
- [x] 2026-10-11 Independent re-review of revision 2: **BLOCKED** (F4/F6/F7 resolved; five corrections).
- [x] 2026-10-11 Revision 3: five corrections; golden baseline captured and recorded; ADRs kept Proposed; protocol and predicate checks run.
- [x] 2026-10-11 Revision 3.1 (B6 removed, concrete ownership, legacy settlement via declared lifetime withdrawn).
- [x] 2026-10-12 Independent review of revision 3.1: `PASS_WITH_ADVISORIES`, advisories corrected (`4d99a86`); relayed, original not stored ([record](../../docs/reviews/slice-0b-1-independent-review-record.md)).
- [x] 2026-10-12 Owner ratified O1–O6; ADR-0013/0014 Accepted for Slice 0B-1 scope; design status and verdict updated.
- [ ] **Open:** owner confirmation of the NFR-08/LM-08 *requirement wording* (still Draft in `docs/02-requirements.md` and `docs/05-data-model.md`); it was not separately ratified.
- [x] Slice 0B-1 implemented and closed on the development host (see [its ExecPlan](2026-10-11-slice-0b1-supervised-execution.md)).

## 9. Discoveries

- Revision 1's "closed" attempt flag was in memory while status stayed `in_flight`, so the 0A trigger would still have allowed publication after a stop decision; the fence must be durable and part of the publication condition.
- The slot can be derived from run rows with a uniqueness guarantee claimed atomically with dispatch; no separate slot table is needed, and quarantine survives restart for free.
- Closing the fence is what converts "no message seen" into "no message can appear"; absence of publication therefore needs a durable fence, not a read alone.
- Late output that passes identity checks is itself termination evidence (B3), which resolves several stop races without any probe.
- An "operator attestation" cannot be made safe by constraining who may sign it; the only safe human role is changing the world and requesting a re-probe.
- **(superseded in revision 3.1)** An earlier statement here allowed an adapter's declared in-process lifetime to release legacy blockers. That is **withdrawn**: legacy rows have no binding, and a label or declaration is not evidence (F6). Legacy unresolved runs stay quarantined unless valid evidence resolves them; none exists in 0B-1.
- Revision 2's arbiter conditioned every settlement on `in_flight`, so T7 could never apply to an `indeterminate` run; each transition needs its own source predicate. A predicate enumeration over all valid states confirmed every `indeterminate` state has a T7 exit under revision 3.
- A durable check of the fence followed by an external call is a check-then-act race; the arbiter cannot order an external handoff. The fix needs an in-process gate plus a durable marker that closure cannot overtake. An exhaustive interleaving check shows no `start` after closure with the gate and reproduces the violation without it. What remains uncontrollable is delivery already in flight after an `UNKNOWN` handoff (U-1).
- Output attributed to another runtime instance cannot be termination evidence for the bound execution; revision 2's `runtime_identity_mismatch` basis conflated that with a model-identity mismatch from the verified instance, which does end the attempt.
- A `runtime_id` label cannot be used to resolve legacy rows without breaking the label-versus-identity rule (F6); with no legacy-capable evidence producer, legacy unresolved runs keep dispatch blocked.
- Slice 0A applied no system instructions or settings: `ModelRequest` carries only `(role, content)` messages. The golden fixtures capture this from the real code, so the legacy baseline `E0` is anchored on 0A, not on another new implementation.
- Counts in the baseline remain internally inconsistent (36/37/51/52); only the selected-requirement inventory (38 with NFR-08) is maintained here.

## 10. Decision log

All entries below are **proposed**, not accepted.

- **D-LD-01 (kept):** five stored statuses; no durable "output observed"; unpublished output memory-only.
- **D-LD-02 (revised):** release only on enumerated, machine-verifiable bases B1–B6 (**revision 3.1: B6 removed → B1–B5**); stop acknowledgment, timeout, restart, elapsed time and human statements are never evidence.
- **D-LD-03 (kept):** unclassified adapter errors are `POSSIBLY_ACTIVE`.
- **D-LD-04 (kept):** retry = new run on the same user message with its own intent; not from `indeterminate`.
- **D-LD-05 (kept):** reconcile triggers startup/touching request/explicit command; no polling loop.
- **D-LD-06 (SUPERSEDED):** operator attestation as the human release path. Replaced by: no human release; operator may act on the world and request a re-probe. Rejected: any force release (would weaken CB-05).
- **D-LD-07 (revised):** provenance with label/identity/verification, plus a persisted conversation configuration binding (ADR-0014).
- **D-LD-08 (kept):** submission fencing not required for 0B; required before full V0.
- **D-LD-09 (kept):** 0B staged into 0B-1 (scripted) and 0B-2 (real runtime).
- **D-LD-10:** durable closure fence + single arbiter on the run record; stop only after closure is durable.
- **D-LD-11:** slot ownership derived from the run, claimed atomically at dispatch, released only with an evidenced settlement; `pending` holds no slot; quarantine blocks all generation.
- **D-LD-12:** binding with instance identity stored at dispatch; control calls carry it; mismatch and unsupported bindings stay unresolved; stop-before-generate tombstone.
- **D-LD-13:** uncertain publication cases A/B/C; absence requires a closed fence.
- **D-LD-14 (revised in rev 3):** conversation configuration binding to content-addressed manifests; adoption explicit; legacy conversations bound **at startup** to `E0` only after `E0` reproduces the real-0A golden fixtures, else unbound + readable + explicit adoption.
- **D-LD-15 (rev 3):** instance mismatch is never evidence; control addresses only the persisted binding; model-identity mismatch from the verified instance is B3.
- **D-LD-16 (rev 3):** handoff gate G + durable T3b marker + single-use invocation right; `generate` split into `start`/`await_result`; closure under G; unresolved cases U-1/U-2/U-3 named.
- **D-LD-17 (rev 3):** legacy unresolved runs are class E blockers with a derived global dispatch block and no slot record; resolved only by verified evidence; migration stops on structural inconsistency, never on (or by settling) unresolved executions. Rejected: label-based resolution; a force or attestation path.
- **D-LD-18 (rev 3):** per-transition source predicates with `state_version`; T7 sources `indeterminate`; handoff state limits admissible bases.
- Architectural decisions: [ADR-0013](../../docs/adr/0013-execution-attempt-lifecycle-and-release-evidence.md), [ADR-0014](../../docs/adr/0014-execution-configuration-provenance-and-continuity.md) — both **Proposed**.

## 11. Final outcome

Changed (revision 3): documents only — design, ADR-0013/0014 (both **Proposed**), NFR-08 and LM-08 wording (one added sentence each on legacy binding), data-model LD-04 row, slice-0a gate note, this plan, the review handoff, plus two new evidence files: [golden baseline record](../../docs/evidence/ld-04-slice-0a-context-golden.md) and [fixtures](../../docs/evidence/ld-04-slice-0a-context-golden.json). Validation actually performed: link check; ID/section reference check; terminology scan for removed concepts (operator attestation, `runtime_idle_under_exclusive_use`, `runtime_identity_mismatch` as evidence, `in_flight`-only settlement, migration-time legacy binding); statements about 0A code compared to the source at `01e9f46`; golden capture run twice (identical digests); an exhaustive-interleaving model check of the handoff protocol (42 states, 0 violations; negative control found violations); a transition-predicate enumeration (47 valid states, 0 invalid results, every `indeterminate` state has a T7 exit). The two scripts are scratch and not committed (documentation-only task); the capture script is reproduced in the evidence record. No source, test, schema or dependency file changed. Remaining limitations: independent re-review of revision 3 not done; owner confirmation pending; U-1/U-2/U-3 not eliminated; all runtime-specific mechanisms unmeasured; no real B3–B6 or legacy-capable producers; single slot only. Follow-up: Codex re-review → owner decisions O1–O6 → 0B-1 task → runtime evidence → 0B-2.
