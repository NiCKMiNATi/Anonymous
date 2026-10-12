# LD-04 — Execution lifecycle, ownership, runtime control, publication and configuration continuity (V0 design)

**Status: ACCEPTED for Slice 0B-1 scope — revision 3.1, owner-ratified 2026-10-12 (0B-1 corrections in §0.4 override earlier text where they differ).** Slice 0B-1 was implemented against a scripted in-process runtime (§17), independently reviewed (`PASS` on the final diff) and verified on the macOS development host; the owner accepted the independent design review (`PASS_WITH_ADVISORIES`, advisories corrected) and decisions O1–O6 ([review record](../reviews/slice-0b-1-independent-review-record.md); [ADR-0013](../adr/0013-execution-attempt-lifecycle-and-release-evidence.md), [ADR-0014](../adr/0014-execution-configuration-provenance-and-continuity.md)). **Accepted scope is 0B-1 against a scripted/in-process runtime only; every `BLOCKED_BY_RUNTIME_EVIDENCE` and `REQUIRED_BEFORE_FULL_V0` row (§14) stays open and is not accepted by this status.** The NFR-08/LM-08 requirement wording keeps its own Draft status. History: Revision 1 was returned **BLOCKED** by independent review (seven findings F1–F7). Revision 2 remediated them; the independent re-review of revision 2 again returned **BLOCKED**, accepting F4 (runtime control), F6 (provenance) and F7 (publication recovery) as **resolved** and leaving five corrections: F1 (identity mismatch), F2 (invocation versus closure), F3 (multiple legacy unresolved executions), F5 (legacy configuration baseline) and a T7 settlement-predicate inconsistency. This revision makes those five corrections and does not reopen F4, F6 or F7 (where text outside those areas had to change, it is called out in §0.3). That revision-3 text had author review only when written; the history of later review and acceptance is in §16 and the acceptance verdict in §15.3. No application code, schema, migration, API route, test or dependency is created or changed by this document.

**Decisions recorded in:** [ADR-0013](../adr/0013-execution-attempt-lifecycle-and-release-evidence.md) (lifecycle, evidence, ownership, control, retry) and [ADR-0014](../adr/0014-execution-configuration-provenance-and-continuity.md) (configuration binding, provenance identity). **ExecPlan:** [2026-10-11-ld-04-lifecycle-and-continuity.md](../../.agent/plans/2026-10-11-ld-04-lifecycle-and-continuity.md). **Review handoff:** [ld-04-lightweight-review-handoff.md](../reviews/ld-04-lightweight-review-handoff.md).

**Three tiers used throughout.**

| Tier | Meaning | Where |
| --- | --- | --- |
| **Accepted (retained)** | Already accepted source semantics this design must not weaken: [05-data-model.md](../05-data-model.md) LM-04–LM-07, CB-02–CB-06, §§8–9, 12; [04-architecture.md](../04-architecture.md) §§8–9; V0-D03/D04/D06; ADR-0003/0004/0006/0011/0012; FR-15; INV-001–INV-015. | cited, unchanged |
| **Accepted for 0B-1** (class `ACCEPTED_FOR_0B`, formerly `PROPOSED_FOR_0B`) | The mechanisms of this document and ADR-0013/0014, accepted 2026-10-12 for Slice 0B-1 against a scripted/in-process runtime. The NFR-08 and LM-08 wording remains a draft in the requirements and data-model baselines pending the owner's separate confirmation. | §§0–15 |
| **Needs runtime evidence** | Behavior of a real runtime or of Windows that cannot be designed away (`BLOCKED_BY_RUNTIME_EVIDENCE`). | §14 |

**Source of the findings.** The text of the independent reviews is not stored in the repository (the [review record](../reviews/slice-0b-1-independent-review-record.md) states what was relayed). F1–F7 (revision 2 matrix, §0.1) are taken from the first remediation task statement; the five revision-3 corrections (§0.2) are taken from the second. Their labels (F1, F2, F3, F5, T7) refer to the same findings as in §0.1, restated after re-review.

## 0. Summary of decisions and resolution matrix

| # | Decision (revision 2) | Class |
| --- | --- | --- |
| 1 | Five stored run statuses are kept, plus a **durable closure fence** on the run. Publication requires `in_flight` **and** an open fence; any non-success exit closes the fence first (or in the same atomic step). | ACCEPTED_FOR_0B |
| 2 | One **arbiter**: a conditional write on the run record. Publication and closure/settlement are mutually exclusive and totally ordered; first durable commit wins. Stop is sent only after closure is durable. | ACCEPTED_FOR_0B |
| 3 | Four separate concerns: **A** conversation admission, **B** execution slot ownership, **C** quarantine of an unresolved execution, **D** other conversation restrictions. A `pending` run holds A only. | ACCEPTED_FOR_0B |
| 4 | The slot is owned by the **run** that acquired it, atomically with dispatch, and is held exactly while that run is `in_flight` or `indeterminate`. Reconciliation operates on the owner run and never acquires the slot. | ACCEPTED_FOR_0B |
| 5 | Release evidence is an enumerated set of machine-verifiable bases. **Operator attestation is removed.** A stop command, a timeout, a lost connection, a restart, elapsed time or a human statement is never evidence. Unresolvable ⇒ quarantine; there is no force-release path. | ACCEPTED_FOR_0B |
| 6 | The dispatch **binding** identifies the runtime instance and adapter format and is stored before invocation. `stop` and `probe` carry the full binding, are bounded, and run on a control path independent of generation. Stale or unsupported bindings stay unresolved. | ACCEPTED_FOR_0B (shape), IMPLEMENTATION_CHOICE (names) |
| 7 | Uncertain publication is resolved into three cases: committed (A), absent (B, requires a durable fence), undetermined (C, stays unresolved). | ACCEPTED_FOR_0B |
| 8 | Each conversation has a persisted **configuration binding** to an immutable, content-addressed effective configuration. Upgrades never rebind; adoption is explicit; an unavailable configuration blocks generation visibly while reading continues. Legacy 0A conversations are bound to a declared baseline without touching their old runs. | ACCEPTED_FOR_0B |
| 9 | Provenance separates **label** from **identity** and records a **verification state** per component (`verified`, `asserted`, `unspecified`); historical runs are `unrecorded`. Labels or unspecified values never prove equivalence. | ACCEPTED_FOR_0B |
| 10 | Explicit retry, reconcile triggers (no polling loop), submission-fencing classification and 0B staging are carried over from revision 1 with the corrections below. | ACCEPTED_FOR_0B |
| 11 | **(rev 3, F1)** Output, callbacks or responses attributed to a different runtime **instance** are never termination evidence. They are rejected, the run is fenced, and stop/probe address only the **persisted** binding. A **model-identity** mismatch from the verified bound instance is distinct: the instance's delivery is itself evidence that the attempt ended (B3) while the output is still rejected. | ACCEPTED_FOR_0B |
| 12 | **(rev 3, F2)** Two ordering problems, two mechanisms: publication versus closure is decided by the durable arbiter; the **external invocation handoff** versus closure is decided by an application-owned **handoff gate** plus a durable pre-handoff marker (T3b) that closure cannot overtake. `generate` is split into `start` (bounded handoff, with an acknowledgment) and `await_result`. Unresolved cases are named (§4.7), not asserted safe. | ACCEPTED_FOR_0B |
| 13 | **(rev 3, F3)** Pre-0B ("legacy 0A") unresolved runs are a distinct blocker class **E**, represented without any slot record: a derived global startup quarantine blocks all dispatch while any exists; each blocker resolves independently and only on verified evidence. Migration refuses on structural inconsistency, never on, and never settles, unresolved executions. | ACCEPTED_FOR_0B |
| 14 | **(rev 3, F5)** Continuity of legacy conversations is anchored to **golden fixtures captured from the actual Slice 0A code at `01e9f46`** ([evidence](../evidence/ld-04-slice-0a-context-golden.md)). The baseline `E0` is bound at startup only after it reproduces the fixtures; otherwise legacy conversations stay unbound, readable, and need explicit adoption. | ACCEPTED_FOR_0B |
| 15 | **(rev 3, T7)** Every transition has its own source predicate over (status, fence, handoff, record epoch, state version). T7 settles an `indeterminate`, closed run and does not require `in_flight`; repeated and concurrent T7 requests are idempotent (§4.1). | ACCEPTED_FOR_0B |

### 0.1 Resolution matrix (revision 2 — F1–F7 as first stated)

| Finding | Resolution | Sections | Scenarios | Residual risk / evidence still needed |
| --- | --- | --- | --- | --- |
| **F1 Unsafe operator release** | `operator_attested` and the weak `runtime_idle_under_exclusive_use` basis are removed. Release needs one of five enumerated, machine-verifiable bases (§1.3). `stop` is an instruction, not evidence. If nothing verifiable exists the run stays `indeterminate` and the slot stays quarantined; availability cost documented (§6.5). | 1.3, 6.1–6.5 | LDT-06, 07, 33, 34 | Whether any real runtime can produce B4/B5 is `BLOCKED_BY_RUNTIME_EVIDENCE`. A manually launched runtime may stay quarantined indefinitely (owner-facing, §6.5). |
| **F2 Closure/publication race** | Durable fence on the run record; one arbiter; ordered protocol SP-1…SP-9; explicit table for output before/during/after stop, uncertain commit, repeated publication, late callbacks (§4). Trigger on assistant publication is a backstop, not the mechanism. | 3, 4 | LDT-10, 11, 20–24 | Store must give atomic conditional writes (portable requirement, §4.1). Lost output on a closure win is accepted and retried explicitly. |
| **F3 Global generation gate** | Split into A/B/C/D (§5). Pending does not hold the slot. Slot acquired atomically at dispatch, owned by the run, released with settlement, reconstructed from run rows after restart, recovered by reconcile without acquiring. | 5 | LDT-13, 25–28, 42 | Single slot only; multi-slot deferred. |
| **F4 Independent runtime control** | Binding with instance identity; `prepare`/`generate`/`stop`/`probe` contract; bounded, concurrent control; mismatch/unsupported results; stop-before-generate tombstone; router by adapter id and binding format (§6.2–6.4). | 2, 6 | LDT-29–33, 41 | Whether a runtime can serve control during generation, and its instance identity, is runtime evidence. |
| **F5 Configuration continuity** | Persisted conversation→effective-configuration binding; immutable content-addressed manifests; explicit adoption; blocked-not-substituted; legacy baseline (§11). | 11 | LDT-17, 18, 35–38 | Catalog retention policy for old configurations; adoption UI deferred. |
| **F6 Provenance identity** | Label vs identity vs verification state; three-valued comparison; `unrecorded` vs `unspecified` (§12). | 12 | LDT-12, 17, 39, 40 | Which digests real adapters can verify (model file, runtime binary) is runtime evidence. |
| **F7 Uncertain publication** | Cases A/B/C with the evidence each requires; LDT-11 rewritten; "restart ⇒ interrupted" shortcut removed (§7). | 7 | LDT-11a–e | Store outage keeps the run unresolved for as long as it lasts. |

### 0.2 Resolution matrix (revision 3 — the five remaining corrections)

| Correction | Resolution | Sections | Scenarios | Residual risk / evidence still needed |
| --- | --- | --- | --- | --- |
| **F1 Identity mismatch** | `runtime_identity_mismatch` removed as a basis. Instance mismatch is a fault: output rejected, fence closed, **persisted** binding probed, quarantine kept unless independent B3 (from the original instance)/B4/B5 evidence exists; control is never redirected to the current instance (R-5). Model-identity mismatch with a verified instance is B3 for the original attempt and a separate failure code. | 1.3, 3.4, 4.5, 6.1, 6.3 | LDT-10, 22, 43–45 | Instance identity is an adapter-verified opaque token; its soundness for a real runtime is `BLOCKED_BY_RUNTIME_EVIDENCE`. |
| **F2 Invocation versus closure** | Problem A (publication vs closure) = durable arbiter; Problem B (handoff vs closure) = handoff gate G + durable T3b marker + closure only under G. Single-use invocation right. Explicit event traces and a short proof (§4.6). Unresolved cases U-1 (delayed delivery after an `UNKNOWN` handoff), U-2 (hung handoff), U-3 (dependence on the single-process guard) named with required behavior (§4.7). | 3, 4, 6.3 | LDT-15, 24, 46–56 | U-1/U-2/U-3 are not eliminated; they are contained by quarantine and restricted evidence. |
| **F3 Multiple legacy unresolved executions** | Class E blockers; derived global startup quarantine; no slot assigned; legacy rows preserved untouched; per-blocker resolution only on verified evidence; migration stops on structural inconsistency only (§5.5). | 5.1, 5.5, 11.3 | LDT-17, 60–64 | With no legacy-capable evidence producer, an existing development dataset containing unresolved 0A runs cannot dispatch (owner-facing O5). |
| **F5 Legacy configuration baseline** | Reference = real 0A at `01e9f46`. Golden fixtures captured from that code (committed as evidence), compared byte-for-byte against 0B-1 `E0`; startup self-test; binding created only after equivalence is shown; else unbound + readable + explicit adoption (§11.3–11.4). | 11, evidence record | LDT-18, 38, 65–67 | Pins the constructed view only; not model, runtime, persona or provenance. |
| **T7 predicate** | Per-transition source predicates (§4.1 table). T7 sources `indeterminate`/closed (no `in_flight`); admissible bases depend on handoff state; idempotent and safe under concurrent reconcilers via state version. | 3.2, 4.1 | LDT-57–59 | Requires the store to expose status, fence, handoff, epoch and version in one conditional write. |

### 0.3 What revision 3 touched outside the five corrections

F4/F6/F7 are unchanged in substance. The following edits were unavoidable: `generate` is split into `start` + `await_result` (the control contract — `prepare`, `stop`, `probe`, instance-exact routing, bounded independent control — is unchanged); B3 now says explicitly that the delivering instance must be the bound one; failure codes `runtime_identity_mismatch` and the `response_not_saved` basis row were reworded; the "dispatch record uncertain" rule (old P6) is expressed through T3/T3b; the provenance model (§12) and uncertain-publication cases A/B/C (§7) are untouched except that references to SP step numbers were updated.

### 0.4 Revision 3.1 — final 0B-1 corrections (override earlier text where they differ)

Made before implementing 0B-1; the target of 0B-1 is a **controlled, scripted, in-process** runtime. Arbitrary external runtimes, brokers, queued delivery and surviving launchers are explicitly **not** claimed safe; they remain 0B-2 evidence gates.

1. **B6 removed as release evidence.** No `isolation_verified`, no scope-wide or snapshot absence. Release needs positive evidence that execution **and any delayed invocation** cannot continue: B1 (never called), B2 (adapter guarantees nothing sent and nothing will be), B3 (bound instance delivered a terminal result), B4 (process death verified — in 0B-1 only through the exclusive guard for `owning_process` bindings, §4.8), B5 (the bound instance reports the attempt ended; after an `UNKNOWN` handoff only with a declared `late_delivery_excluded`). Uncertain ⇒ quarantine.
2. **Single-process ownership is enforced (A-1 made concrete, §4.8).** The dataset identity is canonical and validated; the guard stays held until every supervised worker has terminated or the process dies; a hung shutdown never releases it; no second process can reconcile while an old worker could resume.
3. **Legacy settlement via an adapter's declared lifetime is withdrawn** (ExecPlan discovery removed). Legacy unresolved runs stay quarantined unless valid evidence resolves them; none exists in 0B-1 (§5.5).
4. **Execution testing uses a separate clean development database;** the legacy database is preserved read-only in spirit and never settled by 0B-1.
5. **Unchanged:** F1 (no instance-mismatch evidence), F4 (persisted-binding control), F5 (golden baseline, startup binding), F6 (provenance identity), F7 (publication cases A/B/C), T7 (own source predicate). The scripted adapter and the shipped fake adapter are in-process; neither is evidence about any external runtime.

## 1. Vocabulary and evidence

Three questions stay separate (data model §8): **what is known about the work** (execution knowledge), **what history was committed** (publication outcome), and **whether the conversation and runtime may accept new work** (admission and slot).

### 1.1 Terms

- **Attempt / run:** one `ModelRun`; its `RunId` is the attempt id.
- **Fence (closure):** a durable, irreversible mark on an `in_flight` run saying "this attempt may never publish". Reasons are enumerated (`deadline`, `shutdown`, `publication_unconfirmed`, `connection_lost`, `runtime_failure`, `instance_mismatch`, `supervisor_fault`, `orphan_reconcile`). Legacy runs carry no fence (see record epoch).
- **Closure intent:** an in-memory request to close (deadline fired, shutdown). It has no effect on history until the closure write commits.
- **Arbiter:** the conditional write on the run record that decides publication versus closure (§4.1).
- **Binding:** the durable description of the runtime instance and adapter that an attempt was dispatched to (§2, §6.2).
- **Supervisor:** the in-process controller of one run in this boot. An **orphan** is an `in_flight` run recorded by an earlier boot, or by this boot without a registered supervisor.
- **Invocation right:** the single-use, in-memory entitlement to call `start` for one attempt, held by the party whose T3 commit won and consumed by the T3b commit. It cannot be copied, recovered after restart, or re-created by a replacement supervisor.
- **Handoff:** the bounded external step by which an attempt is delivered to the bound runtime instance (`start`). It is not generation; it ends when the adapter returns a start acknowledgment.
- **Handoff gate (G):** an application-owned, in-process, per-run mutual exclusion. The invoker holds it from before T3b until after the start acknowledgment is recorded; every in-process closer must hold it to commit closure (§4.3). It is never held during generation, probes, stops or publication.
- **Record epoch:** `legacy_0a` for runs that existed when the 0B schema was applied (no binding, fence, handoff, slot or provenance recorded); `0b` otherwise. Legacy runs are never altered by migration (§5.5).

### 1.2 Execution knowledge (adapter-reported for a `start`/`await_result` outcome)

`NEVER_REACHED` (the request provably never began executing on the bound instance), `ENDED` (the **bound** instance reported a terminal outcome for this attempt), `POSSIBLY_ACTIVE` (anything else). Any unclassified error, exception, timeout or disconnect is `POSSIBLY_ACTIVE`. A report that cannot be attributed to the bound instance is `POSSIBLY_ACTIVE`, never `ENDED`.

### 1.3 Termination evidence — the admissible bases

A run may be settled `failed` (and a slot released) only on one of these recorded bases. The set is closed; the store rejects any other value.

| Basis | What it establishes | Who may produce it | Notes |
| --- | --- | --- | --- |
| **B1 `never_dispatched`** | The application never called `start` for this run: durable `handoff = NONE`, or `handoff_outcome = NOT_CALLED`, or a `pending` run (including legacy `pending`, which 0A guarantees was never dispatched). | Coordinator, from the durable record. | Never usable once `start` may have been called (`handoff_outcome` `ACCEPTED`/`UNKNOWN`/unrecorded). |
| **B2 `adapter_never_reached`** | `start` was called and returned `NOT_STARTED`: the adapter guarantees nothing was sent and nothing will be (connection refused before send; binding instance mismatch rejected before execution; stop-before-start tombstone). | Adapter, as a classified result, recorded as `handoff_outcome = NOT_STARTED`. | Adapter must not claim it for ambiguous failures (timeout, reset after send ⇒ `UNKNOWN`). |
| **B3 `runtime_reported_terminal`** | The **bound** instance reported a terminal outcome (result or terminal error) for **this** attempt id, via the attempt's own channel or a verified probe, **and the adapter verified at delivery that the delivering instance's identity equals the persisted binding's `instance_ref`**. Late output that passes both checks is this evidence. | Adapter. | Output, callbacks or responses attributed to any other instance, or whose instance cannot be established, are **not** B3 and not evidence of anything about the bound execution (§4.5). A model-identity mismatch from the verified bound instance is still B3 (the attempt ended); only the output is rejected. |
| **B4 `process_exit_verified`** | The specific process named by the binding has exited, verified against a launch identity (pid **plus** start-time/launch token, or an owned process handle/job). | Adapter or deployment controller that owns or can verify the launch identity; **or**, for a binding whose `lifetime_scope = owning_process` (the runtime exists only inside the owning Anonymous process: no external transport, broker, queue or launcher), the **exclusive instance guard held by a later boot** — the previous owner process has died and every worker thread with it (§4.8). | A pid alone is not an identity; a missing process in a snapshot is not evidence; "a different instance now answers" is not B4. The guard-based form applies only to bindings recorded at dispatch with that lifetime scope, never to legacy rows or labels. |
| **B5 `execution_terminated_verified`** | The bound instance (identity verified) authoritatively reports that this attempt is neither executing nor queued; or, where the runtime exposes only slot state, that the slot is idle **and** the runtime is exclusive to this Anonymous instance **and** the adapter has declared the signal reliable. | Adapter, only after runtime evidence qualifies the signal. | Not producible by any real adapter until `BLOCKED_BY_RUNTIME_EVIDENCE` rows are answered. |
| **B6 `isolation_verified`** | **Removed as release evidence for 0B-1 (§0.4).** Reserved for 0B-2: it needs a verifiable controller that owns a resource scope, which does not exist in 0B-1. "Scope-wide absence" and process-snapshot absence are never evidence. | — | — |

**Never evidence:** a stop request or its acknowledgment; a timeout; a lost or reset connection; absence of a reply; an exception; a restart of Anonymous or of the runtime *by itself*; elapsed time; a human statement; matching labels; a different instance answering at the same address; **any output, callback or response from a runtime instance other than the bound one (instance mismatch)**; an "unknown attempt" reply from an instance whose attempt registration guarantees are unestablished.

**Handoff state limits the bases (rev 3).** What may be claimed depends on how far the handoff got:

| Durable handoff state | Admissible bases |
| --- | --- |
| `handoff = NONE` (T3b never committed) | B1 (proof: `start` can never be called, §4.6) |
| `STARTED`, outcome `NOT_CALLED` | B1 |
| `STARTED`, outcome `NOT_STARTED` | B2 |
| `STARTED`, outcome `ACCEPTED` | B3, B4, B5 |
| `STARTED`, outcome `UNKNOWN` or unrecorded | B3, B4; **B5 only if** the binding declares `late_delivery_excluded` (U-1, §4.7) |
| legacy epoch (no binding) | **none in 0B-1** (§5.5) |

**Control results** (`stop`/`probe`): `CONFIRMED_ENDED(basis ∈ B3–B5)`, `STILL_ACTIVE`, `UNKNOWN(reason)`, `INSTANCE_MISMATCH`, `UNSUPPORTED`. Only the first is evidence; every other result keeps the run unresolved. A timeout is `UNKNOWN`.

## 2. Runtime correlation

```text
conversation C ── configuration binding (§11): effective configuration E (content-addressed)
  └─ frontier F = committed prefix of C through U                 (fixed, LM-04)
       └─ U = triggering committed user message                     (immutable)
            ├─ S = submission (owner, submission_id) ──┐            operation intent
            ├─ T = retry intent (owner, retry_id)    ──┤            (each maps to ≤ 1 run)
            └─ R = run / attempt (RunId) <─────────────┘
                 │ attempt id  = R.id        application-generated, content-free
                 │ binding     = ExecutionBinding   durable BEFORE invocation (with slot, boot id)
                 │ provenance  = ExecutionProvenance (§12), durable BEFORE invocation
                 │ fence       = closure state (§4); handoff = invocation-start marker (§4)
                 ▼
            start(attempt, binding, request) ─► ack ─► await_result ──► observed output (transient, provisional)
                                                       │ publish (arbiter, atomic)
                                                       ▼
                                                  assistant message A (produced_by_run_id = R, unique)
```

- **C1.** A run has one triggering message; an assistant message has one producing run; a run produces at most one assistant message.
- **C2.** Each run is reached through one operation intent (submission for the first run, retry intent for later ones). Intents are owner-scoped and immutable; one intent never creates two runs; reuse with a different target or content is a conflict.
- **C3.** All runs of one user message share its frontier. Retry applies only to the latest saved user message, so a retry's frontier equals the whole history through U. `retry_of` points only to earlier runs of the same message (acyclic, INV-011).
- **C4.** The attempt id is application-generated, content-free and safe to send to the runtime and to logs. Runtime-assigned handles are evidence, not identity.
- **C5.** The **binding** is determined by `prepare` and recorded in the same atomic step as dispatch authorization (T3), so a crash cannot leave a possibly-executing attempt without a recorded instance. It is opaque to the domain (no paths, secrets, content).
- **C6.** In 0B the contributing messages are exactly the frontier (no omission). Per-message selection evidence arrives with LD-06.
- **C7.** Run facts are never relabeled: provenance, binding and outcome evidence of earlier runs are unchanged by retry, upgrade, adoption or runtime replacement.

## 3. Run lifecycle

### 3.1 Stored status, fence and handoff

Durable run state is the tuple **(status, fence, handoff, record epoch, state version)** plus facts recorded at authorization (binding, provenance, slot, boot id, configuration). Statuses (unchanged names):

| Status | Meaning | Fence | Handoff | Conversation admission (A) | Slot (B) |
| --- | --- | --- | --- | --- | --- |
| `pending` | Accepted; user message and run committed. No external call has been, or can be, made. | n/a | n/a | held | **not held** |
| `in_flight` | T3 committed: invocation is *authorized*; binding, provenance, configuration and slot recorded. Whether the runtime was called depends on `handoff`. | **open** (publication allowed) or **closed** (publication forbidden; settlement in progress) | `NONE` (T3b not committed: `start` has never been and can never be called while the fence is closed) or `STARTED` (T3b committed: `start` may have been called) with an `outcome` | held | held |
| `indeterminate` | Fence closed; bounded evidence gathering produced no admissible basis. Not a failure and not a success. | always closed | any | held | **held (quarantine, §5)** |
| `succeeded` | Assistant message and this status committed atomically. | open (never closed) | `STARTED` | released | released |
| `failed` | Settled with an admissible basis and no assistant message. | open (never-dispatched) or closed | any | released | released (if it was held) |

`handoff_outcome ∈ {NULL, NOT_CALLED, NOT_STARTED, ACCEPTED, UNKNOWN}`; `NULL` with `handoff = STARTED` means *unrecorded* and is treated as `UNKNOWN`. Legacy-epoch runs have no fence, handoff, binding or slot columns populated; for every predicate below they are treated as **closed, handoff unrecorded, never publishable** (§5.5).

Invariants (store-enforced where possible): `in_flight` with a closed fence may never become `succeeded`; T4 requires `handoff = STARTED`; `indeterminate` requires a closed fence (epoch `0b`); `succeeded` has an open fence and a message; a fence, once closed, is never reopened; `handoff` goes `NONE → STARTED` at most once; `failed` records `termination_basis ∈ {B1…B5}` and `completion_observed ∈ {yes, no, unknown}`; settled runs are immutable; `state_version` increases by one on every write.

### 3.2 Transitions

Every transition is a single conditional write whose predicate names **its own permitted source state** (§4.1 gives the full predicate table). "Settle" means the run leaves A and B in the same atomic step as its status change.

| # | From → To | Trigger | Required condition / evidence | Effect |
| --- | --- | --- | --- | --- |
| T1 | ∅ → `pending` | submission or accepted retry intent | ownership; no unsettled run in C; configuration resolvable (§11); slot not quarantined; **no legacy blocker (§5.5)**; retry eligibility (§8) | holds A; atomic with user message or retry intent |
| T2 | `pending` → `failed` | context unavailable; over capacity; slot wait timed out, quarantined or legacy-blocked; configuration unavailable; `prepare` failed; startup finds `pending` | B1 | releases A; no provenance fabricated |
| T3 | `pending` → `in_flight`/open/`NONE` | dispatch **authorization** | `prepare` returned a binding; provenance and configuration recorded; **slot acquired** (unique among runs in `in_flight`/`indeterminate`); no legacy blocker; boot id recorded | holds B; the supervisor receives the invocation right; **no external call yet** |
| T3b | `in_flight`/open/`NONE` → `in_flight`/open/`STARTED` | handoff entry | fence open; current boot; invoker holds G | consumes the invocation right; `start` may be called only after this commit is confirmed |
| T3c | `in_flight`/(open or closed)/`STARTED`, outcome `NULL` → same, outcome set | `start` returned (or was not called) | outcome ∈ {`NOT_CALLED`, `NOT_STARTED`, `ACCEPTED`, `UNKNOWN`}; written while holding G | informational but conservative: if lost, outcome stays unrecorded (= `UNKNOWN`) |
| T4 | `in_flight`/open/`STARTED` → `succeeded` | publication | valid output (non-empty, bound-instance identity verified, model identity consistent, natural completion), epoch `0b`, no message | message + status atomic; releases A and B |
| T5c | `in_flight`/open → `in_flight`/closed | closure | any reason (§4); in-process closers hold G | fence closed; nothing else changes |
| T5 | `in_flight`/(open or closed) → `failed` | settlement from `in_flight` | basis admissible for the handoff state (§1.3); no message for the run; an open fence is closed in the same write | releases A and B |
| T6 | `in_flight`/closed → `indeterminate` | evidence exhausted | bounded `stop`/`probe` budget used without an admissible basis | slot **stays held** (quarantine) |
| T7 | `indeterminate` (closed) → `failed` | settlement from `indeterminate` (reconcile) | basis admissible for the handoff state (**B1 through B5**); no message for the run; `expected_version` matches | releases A and B; **does not require `in_flight`** |

Forbidden: any transition out of `succeeded`/`failed`; `indeterminate` → `in_flight`/`succeeded`; any → `pending`; settlement with a basis outside the set or not admissible for the handoff state; T3b after closure; a second T3b; any transition not expressed as a conditional write on its own source predicate. Orphan recovery is not a separate transition: it is T5c followed by T5 or T6 (§9).

The existing schema trigger (assistant message requires an `in_flight` producing run) remains a backstop. It is **not** the mechanism: it does not see closure intent, the fence or the handoff, and would permit publication from a closed `in_flight` run. The 0B-1 schema work must extend it to require an open fence, `handoff = STARTED` and epoch `0b` (§4.1).

### 3.3 Output observed versus published

- **P1.** Output returned by the runtime exists only in the supervisor's memory. It is provisional, never exposed as a message, never stored in a run record, never logged, never described as saved.
- **P2.** History changes only by T4. Nothing else may create an assistant message.
- **P3.** Unpublished output is discarded when the fence closes, when the run is settled without it, or when the process ends. A lost long generation is regenerated by an explicit retry, not recovered. (Recovering output from the runtime after restart is deferred; it would be a second publication path.)
- **P4.** Truncation or an output limit is not natural completion: not published in 0B (`output_truncated`, `completion_observed = yes`).
- **P5.** Output that arrives after the fence closed is evidence only, subject to §4.5.
- **P6 — non-invocation is proved by the durable handoff record, not by memory.** If recording T3 or T3b is uncertain, the supervisor does not call `start` unless a read confirms its own T3b. A run whose durable state shows `handoff = NONE` (or outcome `NOT_CALLED`) is settled B1; a run whose T3b is durable but whose outcome is unrecorded is **not** claimed never-invoked and takes the evidence path (§1.3). (Replaces revision 2's in-memory "the process has not called the model" shortcut.)

### 3.4 Failure vocabulary

| Code | Basis | `completion_observed` | Retry eligible once settled |
| --- | --- | --- | --- |
| `context_unavailable`, `context_exceeds_capacity`, `runtime_busy`, `dispatch_not_recorded`, `dispatch_not_confirmed`, `interrupted_before_dispatch` (includes a closed run whose durable `handoff = NONE`), `binding_unavailable` (`prepare` failed) | B1 | no | yes |
| `runtime_quarantined`, `generation_blocked_legacy_unresolved`, `configuration_unavailable` (each when the cause arises after admission) | B1 | no | yes, once the cause is resolved |
| `runtime_unavailable` (`start` returned `NOT_STARTED`) | B2 | no | yes |
| `runtime_rejected` (terminal runtime error from the bound instance) | B3 | no | yes |
| `empty_output`, `output_truncated`, `response_not_saved`, **`model_identity_mismatch`** (output delivered by the verified bound instance whose reported model identity differs from the binding; output rejected) | B3 | yes (not published) | yes |
| **`runtime_instance_mismatch`** (output/callback attributed to a different instance, or whose instance cannot be established; rejected, fenced) | **never B3 from the mismatching delivery.** Settled only on independent evidence about the **original** binding: B3 from the original instance, B4 or B5; otherwise the run stays `indeterminate` | unknown | yes, once settled |
| `deadline_exceeded`, `connection_lost`, `runtime_restarted`, `supervisor_fault`, `interrupted_shutdown`, `interrupted_server_restart` | B3, B4 or B5 as obtained and admissible for the handoff state | unknown (yes if late output from the bound instance was observed) | yes |
| `legacy_interrupted` — **not producible in 0B-1** (no admissible basis exists for a binding-less run; reserved for a 0B-2 evidence producer, §5.5) | — | — | — |

Revision 1's `runtime_timeout_stopped`, `runtime_connection_lost_stopped`, `runtime_restarted` implied that a stop had succeeded; they are renamed to describe the reason, with the basis carrying the proof. `operator_confirmed_ended` is removed. Revision 2's single `runtime_identity_mismatch` (listed under B3) is **withdrawn**: it conflated a mismatch of the delivering instance, which proves nothing, with a mismatch of the model reported by the verified instance, which does. Failure messages are sanitized and bounded; runtime text is never copied through ([security §§11–12](../07-security.md)).

## 4. Synchronization protocol: authorization, invocation handoff, execution, publication, closure, stop, settlement (F2, T7)

### 4.1 Two ordering problems, and the arbiter predicates

| Problem | Question | Mechanism | What it guarantees |
| --- | --- | --- | --- |
| **A. Publication versus closure** | If output is ready and a closure is requested, which one defines history? | The **durable arbiter**: conditional writes on the same run record. | Exactly one of T4 and T5c/T5 commits; the loser observes the winner's state. |
| **B. External invocation handoff versus closure** | Can the runtime be handed the attempt *after* closure has been declared victorious? | The **handoff gate G** (in-process mutual exclusion), the **durable T3b marker** conditioned on an open fence, and the rule that an in-process closer commits closure **only while holding G** (§4.3). | No call to `start` is *initiated* after a closure commits (proof, §4.6). It cannot prevent effects of a `start` that already returned (U-1, §4.7). |

The arbiter alone does **not** solve B: a durable check "fence open" followed later by an external call is a check-then-act race, and an external runtime cannot participate in a database commit. B therefore needs the gate; the arbiter supplies the durable, irreversible, ordered facts the gate protects.

**Per-transition predicates.** Each conditional write names its own source state. All predicates are evaluated and applied atomically per run by the store (portable requirement; assumption A-2). `v` is the `state_version` the actor read; actors that act on state they did not write (T5, T6, T7, and T5c by reconcile) must supply `expected_version = v`; the live supervisor's own sequence (T3b, T3c, T4, and its T5c) is guarded by the predicates alone. Every successful write increments `state_version`.

| Transition | Source predicate (all must hold) | Writes | If the predicate fails, the caller receives |
| --- | --- | --- | --- |
| **T2** | `status = pending` | `failed`, basis B1, code | `WRONG_SOURCE(current)`; if already `failed`/`in_flight`, the caller re-reads |
| **T3** | `status = pending`; slot free (unique claim); no legacy blocker; epoch `0b` | `in_flight`, fence open, `handoff = NONE`, binding, provenance, configuration, slot, boot id | `WRONG_SOURCE`; `SLOT_BUSY(holder_status)`; `LEGACY_BLOCKED` |
| **T3b** | `status = in_flight`; fence **open**; `handoff = NONE`; `execution_boot_id = current boot` | `handoff = STARTED` | `FENCE_CLOSED` (closure won first: `start` must not be called); `ALREADY_STARTED`; `WRONG_SOURCE` |
| **T3c** | `status = in_flight`; `handoff = STARTED`; `handoff_outcome IS NULL` | outcome | `WRONG_SOURCE`; harmless: the outcome stays unrecorded (= `UNKNOWN`) |
| **T4** | `status = in_flight`; fence **open**; `handoff = STARTED`; epoch `0b`; no message for the run | message, `succeeded` | `ALREADY_CLOSED`/`SETTLED`/`PUBLISHED`; output is discarded |
| **T5c** | `status = in_flight`; fence **open** | fence closed with reason | `PUBLISHED` (T4 won: **stop is never sent**); `ALREADY_CLOSED`; `SETTLED` |
| **T5** | `status = in_flight` (fence open or closed) epoch `0b` (**legacy epoch: refused in 0B-1, §5.5**); no message; basis admissible for the durable handoff state (§1.3); `expected_version` where applicable | `failed`; an open fence is closed in the same write | `PUBLISHED`; `SETTLED` (idempotent: stored result returned, nothing rewritten); `ALREADY_INDETERMINATE` (caller re-reads and uses T7); `STALE_VERSION` |
| **T6** | `status = in_flight`; fence **closed**; `expected_version` | `indeterminate` | `SETTLED`; `ALREADY_INDETERMINATE`; `STALE_VERSION` |
| **T7** | `status = indeterminate` (fence closed; epoch `0b` — **legacy epoch refused in 0B-1**); no message for the run; basis admissible for the durable handoff state, **B1 through B5**; `expected_version` | `failed`, basis, code, `completion_observed`; releases A and B | `SETTLED` (a repeated or concurrent T7 returns the stored result); `STALE_VERSION` (re-read, re-evaluate, retry within the bound); `WRONG_SOURCE` |

Revision 2 conditioned every settlement on `status = in_flight`, which made T7 unsatisfiable (an `indeterminate` run is not `in_flight`). That predicate is withdrawn; T7 above is its own transition with its own source.

**Repeated and concurrent T7.** (i) A repeated T7 finds `failed` and returns `SETTLED` with the stored basis and code; it neither rewrites evidence nor re-releases the slot (release is part of the first write and idempotent by construction). (ii) Two reconcile actors may each gather evidence; the first commit wins, the second receives `SETTLED` and records its evidence only as a content-free log line; if their bases differ, the first stands. (iii) An actor that read `in_flight`/closed and races a T6 receives `ALREADY_INDETERMINATE` and continues with T7 after re-reading. (iv) `STALE_VERSION` is retried a bounded number of times after re-reading; evidence about the **binding** stays valid across versions, but the actor must re-check that the run is still unsettled and message-free. (v) A per-run in-process reconcile lock reduces duplicate probing and is an optimization, not a correctness requirement.

### 4.2 Durable state, and what a commit does and does not mean

Logical fields on the run (layout is IMPLEMENTATION_CHOICE): `status`, `closed_at`, `closure_reason`, `handoff` (`NONE`/`STARTED`), `handoff_outcome`, `execution_boot_id`, `slot_id`, binding, `state_version`, `record_epoch`, `termination_basis`, `completion_observed`.

- A database commit orders **Anonymous's own durable facts**. It does not make an external runtime's side effects atomic with those facts, and this design never claims it does. Safety comes from *ordering* (the T3b marker is durable before the external call) and from *exclusion* (the gate), not from atomicity across systems.
- **No database write transaction is open during `start`, `await_result`, `stop` or `probe`.** T3b, T3c, T4, T5c, T5, T6, T7 are short, separate transactions. G is an in-memory lock, not a database lock.
- A commit whose result is unknown (`StorageOutcomeUnknown`) is resolved by reading (§7); the actor never assumes either outcome.

### 4.3 The handoff gate and the start contract

**Gate G.** One per run, created by the T3 winner, owned by the supervisor registry (so it survives replacement of a supervisor thread within a boot), keyed by `RunId`. G is a plain mutual-exclusion lock with a bounded wait; it provides no queueing or fairness promises.

| Who | When G is held | Bound |
| --- | --- | --- |
| **Invoker** | from before T3b until after `start` has returned and T3c was attempted | handoff deadline H (the adapter must return by H) |
| **In-process closer** (deadline, shutdown, publication-unconfirmed, instance-mismatch, supervisor fault) | around the closure write (T5c, or T5 when the fence is open) | G wait ≤ H + slack |
| Publication, `await_result`, probes, stops, reconcile of an orphan from an earlier boot | **never** | — |

**Rule G-1 (closure under G).** A closure of an open fence is committed only by a caller that holds G. **Rule G-2 (invoke under G).** `start` is called only by the holder of the invocation right, only while holding G, only after T3b has been confirmed (or confirmed by a read), and at most once ever (T3b can succeed once). **Rule G-3.** If a closer cannot obtain G within its bound, it does **not** commit closure (U-2).

**Port: `generate` is split.** `start(attempt_id, binding, request, handoff_deadline) → StartAck` and `await_result(attempt_id, binding, deadline) → Completed | Failed`. (A blocking `generate` convenience may exist if it exposes the same boundary, e.g. by invoking an acknowledgment callback; the boundary, not the shape, is the contract.)

| `StartAck` | Meaning | Recorded as (`handoff_outcome`) | What it establishes |
| --- | --- | --- | --- |
| `ACCEPTED` | The **bound** instance acknowledged receipt of the attempt. Execution may be in progress. | `ACCEPTED` | Invocation began. Not termination evidence. B1/B2 are no longer available. |
| `NOT_STARTED` | The adapter guarantees nothing was sent and nothing will be (connection refused before send; instance mismatch rejected before send; stop-before-start tombstone). | `NOT_STARTED` | B2. |
| `UNKNOWN` | The request may have been sent (timeout, reset, error after send). | `UNKNOWN` | Not "never invoked". Delayed delivery cannot be excluded (U-1). |

Adapter obligations (testable on a scripted adapter): `start` returns by its deadline; **once it has returned, the adapter initiates no further transmission for that attempt** (it sets its own tombstone atomically with returning); after an accepted `stop(attempt)`, a later `start(attempt)` returns `NOT_STARTED` (defense in depth — the application does not rely on it for in-process safety); `start` verifies `binding.instance_ref` against the live instance before sending (mismatch ⇒ `NOT_STARTED`).

### 4.4 Protocol

- **SP-1 Admission.** T1 under the rules of §5. No external call.
- **SP-2 Authorization.** `prepare` (no execution) → T3. The T3 winner receives the **invocation right**. T3 authorizes; it does not invoke.
- **SP-3 Handoff entry.** The invoker acquires G.
- **SP-4 Handoff marker.** T3b. `FENCE_CLOSED` or `ALREADY_STARTED` ⇒ release G, **do not call `start`**, go to settlement (§4.6 H-1, second interleaving). Unknown commit ⇒ do not call `start`; read; only a confirmed own T3b allows SP-5; otherwise release G, leave the run for reconcile (outcome later recorded `NOT_CALLED` if the store allows, else treated `UNKNOWN`/unrecorded).
- **SP-5 Handoff.** `start(...)` under G; the invoker may skip it and record `NOT_CALLED` if a closure intent is already pending.
- **SP-6 Handoff outcome.** T3c (best effort) under G, then release G.
- **SP-7 Execution.** `await_result` — no G, no database transaction. Output is provisional.
- **SP-8 Publication.** T4 (arbiter). Before T4 the coordinator checks the delivery identities (§4.5).
- **SP-9 Closure.** Intent (deadline, shutdown, fault, mismatch) → closer acquires G → T5c (or T5 with evidence in hand) → releases G. `PUBLISHED` ⇒ done, stop never sent.
- **SP-10 Stop.** Only after SP-9 is durable, and only if the durable handoff state admits a started attempt (`STARTED` with outcome `ACCEPTED`, `UNKNOWN` or unrecorded). If `handoff = NONE`, `NOT_CALLED` or `NOT_STARTED`, **no external action is taken**; the run is settled B1/B2 at once. `stop(attempt, persisted binding)`; its acknowledgment is not evidence.
- **SP-11 Verification.** Bounded `probe`s of the **persisted** binding, or late output from the verified bound instance (B3). An admissible basis for the handoff state ⇒ T5; none within the budget ⇒ T6; later reconcile ⇒ T7.
- **SP-12 Settlement is final.** After T4, T5 or T7 commits, every later callback, output, probe result, stop acknowledgment or reconcile call is read-only: at most a content-free fault counter.

### 4.5 Race, mismatch and uncertainty table

| Situation | Durable facts | Result |
| --- | --- | --- |
| **Output before stop** | fence open, `STARTED` | T4 wins; a later T5c returns `PUBLISHED`; stop never sent. Original message identity and commit instant preserved (FR-15). |
| **Output during stop** | fence closed | Discarded. If delivered by the verified bound instance it is **B3**: T5 `failed` with `completion_observed = yes`. |
| **Output after stop/settlement** | closed or settled | Discarded; fault counter; state unchanged (SP-12). If still unresolved and from the verified bound instance, it is B3 as above. |
| **Instance mismatch** — output, callback or response attributed to a runtime instance other than the persisted binding's, or whose instance the adapter cannot establish | any | **Not evidence of anything.** (1) Reject for publication; content discarded and never logged. (2) If the fence is open, close it (reason `instance_mismatch`) under G. (3) Probe/stop the **persisted** binding only through the router (never "whichever instance is currently active"). (4) Settle only on independent admissible evidence about the original binding (B3 from the original instance, B4, B5); otherwise T6 and quarantine. (5) A replacement instance that happens to be running is neither probed nor stopped on this attempt's behalf. |
| **Model-identity mismatch** — delivered by the verified bound instance, reported model identity differs from the binding | fence open or closed | The bound instance has ended the attempt: **B3**. Output rejected; T5 `failed(model_identity_mismatch)`, `completion_observed = yes`. Termination is established by the instance delivery, not by the mismatch. |
| **Publication commit uncertain** | unknown | §7 (cases A/B/C). |
| **Repeated publication attempts** | at most one message | The second attempt finds `succeeded`, returns the original result; no second message, no new instant. |
| **Closure and publication simultaneous** | arbiter | Exactly one wins; no partial combination. |
| **Late callback after settlement** | settled | No-op (SP-12). |
| **Delayed `start` acknowledgment** | G held by the invoker until return | A closer cannot commit before the acknowledgment (or its deadline); an acknowledgment arriving after the adapter's deadline is a contract violation (U-2), recorded as a fault and treated `UNKNOWN`. |

### 4.6 Invocation-versus-closure event traces and proof

Notation: **I** = invoker (holds the invocation right); **C** = in-process closer; **R** = reconcile in a later boot; durable state is `(status, fence, handoff/outcome)`. Pauses are arbitrary and may occur between any two steps of an actor.

**H-1 — pause between the authorization check and the external handoff (the case revision 2 allowed).**

| # | Actor | Event | Durable state |
| --- | --- | --- | --- |
| 1 | I | T3 commits; receives invocation right | `(in_flight, open, NONE)` |
| 2 | I | acquires G; reads local closure intent: none | same |
| 3 | I | **pauses** (before T3b) | same |
| 4 | C | deadline fires; wants to close; `G` is held by I ⇒ blocks (bounded) | same |
| 5a | I | resumes; T3b commits (fence open) | `(in_flight, open, STARTED/NULL)` |
| 6a | I | `start` returns `ACCEPTED`; T3c; releases G | `STARTED/ACCEPTED` |
| 7a | C | acquires G; T5c commits | `(in_flight, closed, STARTED/ACCEPTED)` — the handoff **completed before** closure; stop and verification follow (SP-10/11) |

Alternative interleaving of the same pause: at step 3 the closer is *already inside* G (it acquired G before step 2). Then:

| # | Actor | Event | Durable state |
| --- | --- | --- | --- |
| 2′ | C | acquires G; T5c commits; releases G | `(in_flight, closed, NONE)` |
| 3′ | I | tries to acquire G; succeeds after C | same |
| 4′ | I | T3b: fence closed ⇒ `FENCE_CLOSED`; **does not call `start`**; releases G | same |
| 5′ | C/I | `handoff = NONE`, fence closed ⇒ B1 (`interrupted_before_dispatch`) via T5; **no stop, no probe** | `failed`, slot released |

In neither interleaving can `start` be initiated after closure committed.

**H-2 — pause after T3b, before `start`.** I holds G throughout. C blocks on G; closure commits only after `start` returned and T3c was attempted. Result as 5a–7a. If I's pause exceeds C's bound, C does not commit closure (U-2); nothing is claimed.

**H-3 — closure committed before runtime acceptance** (`start` returned `UNKNOWN`): `(…, closed, STARTED/UNKNOWN)`. Stop is issued (SP-10); only B3, B4 (B5 only with `late_delivery_excluded`) can settle; otherwise T6 (U-1).

**H-4 — stop during handoff.** Stop is sent only after closure is durable (SP-10), and closure needs G, so a stop can never overlap a `start` of the same attempt in the same process. The adapter tombstone covers only direct misuse.

**H-5 — runtime acceptance before closure.** Outcome `ACCEPTED`; closure follows normally; B3–B5 required.

**H-6 — server crash during handoff.** (a) Before T3b commit: durable `(in_flight, open, NONE)`. New boot: R closes the fence (T5c, expected version) and, since `NONE`, settles B1 with no external action — `start` can never be called, because T3b now fails on a closed fence and the old process is gone (A-1). (b) After T3b: `(in_flight, open, STARTED/NULL)`; R closes, probes the persisted binding; B3/B4 (B5 restricted). Unknown ⇒ T6, quarantine.

**H-7 — delayed callbacks.** Output, an acknowledgment, a probe reply or a stop reply arriving after closure or settlement: read-only (SP-12); output from the verified bound instance may serve as B3 for an unresolved run; mismatching output is a fault.

**H-8 — supervisor replacement or restart.** The invocation right is single-use and in memory. A replacement supervisor in the same boot has no right and cannot call `start`; it may perform closure (under the same G from the registry) and verification. After restart there is no right at all; `handoff = STARTED` can never be re-entered. A second `start` for the same attempt is impossible by T3b's `NONE → STARTED` single transition.

**H-9 — T3b commit unknown.** I does not call `start` until a read confirms its own T3b; if the store is unreadable, `start` is not called and the durable record, whichever it is, is handled conservatively (`STARTED/NULL` ⇒ evidence path; never claimed never-invoked unless `NONE`/`NOT_CALLED` is durable).

**Invariants.** I-1: `start(R)` is called only after T3b(R) committed (SP-4, G-2). I-2: T3b requires an open fence and the fence is irreversible. I-3: an in-process closure commits only under G (G-1), and I holds G across T3b…`start` return…T3c. I-4: T3b succeeds at most once and the invocation right is single-use.

**Claim.** If a closure write for run R commits at time *t_c*, no call to `start(R)` is initiated after *t_c*. *Proof.* By I-1 a `start(R)` call requires a committed T3b. If T3b had not committed by *t_c*, then because the fence is closed from *t_c* on and T3b requires an open fence (I-2), T3b can never commit, so `start(R)` is never called. If T3b committed before *t_c*, the invoker acquired G before T3b and releases it only after `start` returned (I-3); the closer needs G to commit (I-3), so *t_c* is after `start` returned — the call was initiated before *t_c*. I-4 excludes a second call. Reconcile in a later boot has no concurrent invoker (A-1). ∎ The claim concerns **initiation of the call**; it does not cover the external consequences of a call that already returned (U-1).

### 4.7 Assumptions and unresolved cases

**Assumptions the proof depends on.**

- **A-1 (single process).** At most one Anonymous process uses the dataset at a time and **holds the guard for as long as any supervised worker could still run**; a different process closes or reconciles a run only after the previous holder has exited (§4.8). In 0B-1 this rests on the development `InstanceGuard` (exclusive lock released by the OS on process death), which its own documentation says is *not* the ADR-0011 exclusive-instance mechanism (local filesystems only; no network storage; no bind-mount aliasing). It is `REQUIRED_BEFORE_FULL_V0` to back A-1 with the ADR-0011 mechanism.
- **A-2 (atomic conditional writes).** The store evaluates each predicate and applies the write atomically per run (§4.1).
- **A-3 (adapter contract).** `start` returns by its deadline and initiates no further transmission afterwards (§4.3). Testable on scripted adapters; unverifiable for a real runtime until measured.
- **A-4 (single closure path).** Every closure of an open fence in this process goes through one function that acquires G. A structural test must ensure no other writer of the fence exists.

**Unresolved cases — not asserted safe; behavior is containment.**

- **U-1 Delayed delivery after an `UNKNOWN` handoff.** After `start` returned `UNKNOWN`, bytes may still be in a socket or network buffer and reach the runtime after closure. The application cannot prevent it. Containment: the run is never claimed never-invoked; closure fences publication regardless; the slot stays held; only evidence that holds even if a late request arrives is admissible — **B4** (the process is gone), **B3** (the runtime itself reported terminal for this attempt id; it has processed it), and **B5 only when the binding format declares `late_delivery_excluded`** (a runtime-evidence matter). Otherwise quarantine persists.
- **U-2 Hung handoff.** If the invoker does not leave the handoff section within its bound (adapter contract violation or a stuck thread), closers cannot take G and **do not commit closure**. The run stays `in_flight`/open, the slot and conversation stay held, and a fault is raised. Recovery is a process restart, after which R handles it as H-6(b). The application does not assert safety while the invoker is stuck.
- **U-3 Dependence on A-1.** If two processes could use one dataset, H-6 and the proof fail. Out of scope here; gated by ADR-0011/0012 and A-1.

### 4.8 Process ownership (revision 3.1)

- **Canonical dataset identity.** The guard derives its lock from the **canonical, validated** dataset path: all symlinks resolved, `..` and relative forms normalized, the dataset required to be a regular file (or absent), not a hard-linked file (link count 1; an alias that bypasses the lock is refused), on a local path. Every alias that resolves to the same file therefore names the same lock. A case-variant alias on a case-insensitive filesystem resolves to the same lock file by the filesystem itself. Bind-mount and network-filesystem aliases are not detectable portably and stay under ADR-0011/0012.
- **Held until workers are gone.** `shutdown` stops admitting work, requests closure of every active attempt, and joins the workers with a bound. The guard is released **only** when no supervised worker remains alive. If a worker is still alive (a hung adapter), the guard **stays held**: shutdown reports `incomplete`, the process must exit (which releases the lock because the process, and with it every worker, is dead) and never "completes" shutdown by releasing ownership.
- **Consequence for B4 (§1.3).** A later boot that acquires the exclusive guard thereby knows the previous owning process — and every worker thread in it — no longer exists. For a binding recorded at dispatch with `lifetime_scope = owning_process` this is positive evidence that execution and any delayed invocation ended (no external transport, broker, queue or launcher exists for such a runtime). For any other lifetime scope it is **not** evidence.
- **No concurrent reconcile.** Reconcile runs in the guard-holding process only; a second process cannot start, hence cannot reconcile while an old worker could resume.

## 5. Admission, slot ownership and quarantine (F3)

### 5.1 Five separate concerns

| | Question | Durable authority | Acquired | Released | After restart |
| --- | --- | --- | --- | --- | --- |
| **A. Conversation admission** (pending generation admission) | May this conversation accept a new user operation? | at most one run of C in `pending`/`in_flight`/`indeterminate` (existing unique index) | T1 | T2, T4, T5, T7 | reconstructed from run rows (LM-06) |
| **B. Execution slot** (actual runtime ownership) | Which attempt owns the runtime resource? | `slot_id` on the run; unique among runs in `in_flight`/`indeterminate` (V0: one slot id, set by composition) | **T3 only**, atomically with dispatch | with settlement (T4, T5, T7); never by a timer | reconstructed from run rows |
| **C. Quarantine** (unresolved execution) | Is some attempt possibly still using the runtime? | slot held by an `indeterminate` run (or an orphan not yet resolved) | T6 | T7 only | reconstructed from run rows |
| **D. Conversation restrictions** | Is this conversation, specifically, barred from generating? | unsettled run (A); retry ineligibility (§8); configuration unavailable (§11); store unreadable | per restriction | per restriction | evaluated from current state |
| **E. Legacy unresolved-execution blockers** | Could a pre-0B execution still be active anywhere? | derived predicate `LB` over legacy-epoch rows (no slot record; §5.5) | recomputed from rows | each blocker settles by verified evidence (T5/T7); `LB` lifts at zero | recomputed from rows |

A `pending` run holds A only. It waits **in memory** for the slot (bounded); there is no durable queue (V0-D04: no silent queue). Slot identity is composition configuration, never an adapter claim.

### 5.2 Ownership diagram

```text
              T1                       T3 (slot acquired; authorizes, no call)           T4 / T5 / T7
 (no run) ─────────► PENDING ──────────────────────────► IN_FLIGHT/open ──────────► SUCCEEDED / FAILED
                     holds A             │                 holds A + B                 releases A + B
                     slot: FREE          │ slot busy                │ T5c (closure)
                     waits (memory)      └─► stay pending;          ▼
                                             wait ≤ bound,     IN_FLIGHT/closed ──► FAILED (basis admissible for handoff state)
                                             or fail-fast               │ evidence budget exhausted (T6)
                                             if quarantined             ▼
                                             (T2: runtime_busy /   INDETERMINATE  = QUARANTINE (C)
                                              runtime_quarantined)  holds A + B     slot stays held
                                                                       │ T7 (basis admissible for the handoff state, via reconcile)
                                                                       ▼
                                                                    FAILED, A + B released
```

### 5.3 Acquisition, release, restart, reconciliation

- **Acquisition.** T3 is one atomic write that moves the run to `in_flight`, records binding/provenance/configuration, **and** claims the slot through a uniqueness guarantee. A conflict leaves the run `pending`. A run therefore cannot be dispatched without owning the slot, nor own it without a durable, attributable run id.
- **Release.** Happens inside the settlement write; it is idempotent by construction (the run has left `in_flight`/`indeterminate`; repeating a settlement fails the condition and reports the stored result). A settlement never releases a slot owned by another run.
- **Release only on evidence.** B and A are released together with a settlement that has an admissible basis (T4: output delivered; T5/T7: B1–B5 as admissible for the durable handoff state). Marking failure without a basis is impossible (§3.2), so CB-05 is preserved: "failure alone cannot release admission while old work may still run".
- **Restart.** A new boot id is generated. `pending` runs → T2 (B1). Legacy blockers are handled by §5.5 (derived global quarantine, no slot). `in_flight` runs of earlier boots are orphans: reconcile applies T5c then probe (§9). `indeterminate` runs are unchanged and **still hold the slot**: quarantine survives restart because it is derived from rows, not memory.
- **Reconciliation by another actor.** Reconcile acts on the run row that owns the slot (startup, a later request touching C or the slot, or an explicit reconcile command). It uses only the control path (`probe`/`stop`) and conditional writes on the owner run. It never needs capacity and never acquires the slot.

### 5.4 When new generation is intentionally blocked, and how it recovers

| Cause | Effect | Recovery |
| --- | --- | --- |
| Slot held by a live `in_flight` run | Other conversations' `pending` runs wait (bounded); then `runtime_busy`. | Normal completion/settlement. |
| `in_flight`/closed (stop in progress) | As above. | Evidence within the bounded budget, or T6. |
| **Quarantine (`indeterminate` holds the slot)** | **All** new sends and retries (any conversation) are refused at admission with `runtime_quarantined`; nothing is appended. If quarantine begins after admission, dispatch settles `failed(runtime_quarantined)`, B1. Reading is unaffected. | Reconcile obtains an admissible basis (B3–B5 for a started attempt; e.g. the deployment lets Anonymous verify the old process exited or the runtime reports termination). No other path (§6.5). |
| **Legacy unresolved executions (class E)** | **All** new sends and retries refused with `generation_blocked_legacy_unresolved`; reading unaffected; no slot record involved. | Each blocker resolved by verified evidence (§5.5); no force path. |
| Conversation has an unsettled run | `ConversationBusy`. | Settlement of that run. |
| Pinned configuration unavailable | Send/retry refused `configuration_unavailable`. | Run a build that can resolve it, or adopt an available configuration explicitly (§11). |
| Store unreadable | No transition possible; runs stay as stored. | Storage returns; reconcile. |

### 5.5 Legacy (Slice 0A) unresolved executions (F3)

**Facts of the 0A dataset (from `01e9f46`).** The 0A schema's only concurrency guarantee is *one unsettled run per conversation*; runs in many conversations may be `pending`, `in_flight` or `indeterminate` at once. A 0A run records `model_id`, `runtime_id`, `dispatched_at` and a status; it has no binding, instance identity, fence, handoff, slot, provenance beyond those two labels, or configuration. 0A's coordinator calls `generate` only after `record_dispatch` commits, so a legacy `pending` run (`model_id` and `dispatched_at` null) was **provably never dispatched**; a legacy `in_flight` or `indeterminate` run **may have been invoked**; 0A startup converted every `in_flight` run to `indeterminate` and nothing could leave `indeterminate`.

**Representation (nothing is rewritten, nothing is invented).**

- Migration adds the 0B columns with NULL/default values and sets `record_epoch = legacy_0a` on every existing run. It does **not** change any status, label, instant, failure field or message; it sets no fence, no handoff, no binding, no provenance, no slot.
- Legacy `in_flight`/`indeterminate` runs are **blockers of class E**. They are treated by every predicate as *closed, handoff unrecorded (= `UNKNOWN`), never publishable*. They keep holding **A** for their own conversation (the existing per-conversation unique index) and appear in no slot record: `slot_id` is NULL, and NULL values do not collide in the slot uniqueness guarantee. Two or more legacy blockers therefore never contend for the single slot, and are never assigned to it.
- **Global startup quarantine (derived, not stored).** `LB` = at least one run with `record_epoch = legacy_0a` and `status IN (in_flight, indeterminate)`. While `LB` holds: T1 refuses every new send and retry in every conversation (`generation_blocked_legacy_unresolved`, nothing appended); T3 refuses dispatch (`LEGACY_BLOCKED`) for runs admitted before `LB` was observed (they settle B1 via T2); reading is unaffected. `LB` is recomputed from rows, so it survives restart and needs no occupied slot record.

**Three concepts kept apart.**

| Concept | Representation | Effect |
| --- | --- | --- |
| Physical runtime slot ownership (B) | `slot_id` on 0B runs only | one owner at most |
| Legacy unresolved-execution blockers (E) | derived from rows by `LB`; one per run | block **all** dispatch until each is resolved |
| Per-conversation restrictions (A/D) | existing unique index and other rules | block that conversation |

**Resolution of each blocker (revision 3.1).** A legacy blocker has no binding, no instance identity and no recorded lifetime; `runtime_id` is a descriptive label. **No admissible basis exists for such a run in 0B-1**: B6 and "scope-wide absence" are removed (§0.4), an adapter's declared lifetime or a missing process in a snapshot is not evidence, the guard-based B4 (§1.3, §4.8) applies only to bindings recorded at dispatch with `lifetime_scope = owning_process`, and there is no operator path. The store therefore **refuses every T5/T7 settlement of a legacy-epoch `in_flight`/`indeterminate` run** (it accepts only the legacy `pending` → T2/B1 case). Legacy blockers stay quarantined, each independently, and the global dispatch block (`LB`) stays in force, until a later task introduces a verified evidence producer (a 0B-2 prerequisite). Safe handling in 0B-1 is: **preserve the legacy database and its history untouched, and run 0B-1 execution tests against a separate, clean development database** (the 0B-1 default database file is new; the old file can still be opened to read history).

**Diagnostics while blocked.** A content-free structured status (logged at startup and available to the readiness check) lists the count of legacy blockers and, per blocker: run id, conversation id, status, `runtime_id` label and the resolution attempt result (`UNSUPPORTED`, `STILL_ACTIVE`, `UNKNOWN`, …). The API's generation-refusal reason names the class (`generation_blocked_legacy_unresolved`). No prompt, output or path appears.

**Legacy `pending`.** A legacy `pending` run is not a blocker: 0A guarantees it never dispatched, so startup reconcile settles it T2/B1 `interrupted_before_dispatch` — exactly 0A's own startup behavior, with the proof recorded.

**Does migration stop?** The migration is one forward-only, checksummed transaction that **never settles an execution**. It **stops safely** — rolls back, leaves the original dataset byte-identical, and the server does not reach readiness, with a content-free diagnostic — when a structural precondition fails, i.e. when the dataset cannot be represented without inventing facts:

| Precondition checked inside the migration transaction | Stop if |
| --- | --- |
| Success/message agreement | a `succeeded` run has no assistant message, or an assistant message belongs to a run that is not `succeeded` |
| Single unsettled run per conversation | a conversation has more than one `pending`/`in_flight`/`indeterminate` run |
| Admission order | messages exist after the triggering message of an unsettled run (a new message was accepted while a run was unresolved) |
| Run/message integrity | a run references a trigger that is not a user message of its conversation; dispatch labels inconsistent with status |
| Migration bookkeeping | applied-migration checksum or version mismatch (existing behavior) |

Unresolved legacy executions are **not** structural inconsistencies: they are representable, so the migration succeeds, the server reaches readiness, history is readable, and dispatch stays blocked (`LB`) until each blocker is resolved by evidence. Stopping on them would deny read access and offer no resolution path (0A cannot resolve them either); proceeding without `LB` would let a new dispatch overlap a possibly active old execution.

**Owner-facing consequence (O5).** An existing development dataset that contains unresolved 0A runs cannot dispatch under 0B-1 until each such run is resolved by verified evidence. There is no force release and no operator attestation. If the owner wants to treat synthetic 0A development data differently, that is an explicit weakening of CB-05 requiring its own ADR; it is **not** proposed here.

## 6. Termination evidence and independent runtime control (F1, F4)

### 6.1 Rules

- **R-1.** `stop` is an instruction; its acknowledgment is never evidence (§1.3). After any stop the supervisor must obtain an admissible basis by `probe` or by late output.
- **R-2.** Bases B4/B5 are valid only when the producer verified them **against the recorded binding**. A component that cannot interpret the binding cannot produce evidence for it.
- **R-3.** If no admissible basis can be obtained, the run stays `indeterminate`, the slot stays quarantined and nothing conflicting is admitted. The unresolved execution and its binding are preserved.
- **R-4.** CB-05 is not weakened: failure without a basis never releases admission.
- **R-5 (persisted binding is the only control target).** `stop`, `probe` and every later control call address the binding **persisted at T3**, resolved through the router by its recorded `adapter_id`/`binding_format`. No operation resolves "the currently active instance", re-binds an attempt, or substitutes a replacement instance because it is available. Output or callbacks attributed to another instance never alter the target.

### 6.2 Binding and instance identity

Logical `ExecutionBinding` (names illustrative; recorded durably at T3):

| Field | Purpose |
| --- | --- |
| `binding_format` | Namespaced, versioned identifier of the opaque payload layout; selects the control handler. |
| `adapter_id`, `adapter_version` | Which adapter produced it. |
| `instance_ref` | Opaque token identifying **one runtime instance lifetime** (e.g. launch nonce + start identity); never reused across instances. No path, secret or content. |
| `control_ref` | Opaque, optional routing hint; resolved only through adapter configuration, never a raw credentialed URL. |
| `declared_bases` | Which of B3–B5 the adapter can produce for this binding. |
| `lifetime_scope` | `owning_process` (the runtime exists only inside the owning Anonymous process; no external transport, broker, queue or launcher) or `external`. Recorded at dispatch; selects whether the exclusive guard held by a later boot is B4 evidence (§4.8). |
| `late_delivery_excluded` | Declared by the adapter: after `start` returned, a delayed delivery of the request cannot occur (true for `owning_process` runtimes). Required for B5 after an `UNKNOWN` handoff. |
| provenance parts | model artifact and runtime build components (§12). |

The domain never parses the payload; it stores, compares for equality and passes it back.

### 6.3 `ModelPort` and control contract

Application-owned and vendor-neutral (ADR-0003); no runtime request formats, flags or endpoints cross it. Names are IMPLEMENTATION_CHOICE; the content is the proposal.

| Operation | Contract |
| --- | --- |
| `describe()` | adapter id/version, binding formats supported, bases it can produce, input-capacity declaration. |
| `prepare(attempt_id) → ExecutionBinding \| Failed(NEVER_REACHED)` | Identifies the live instance and its verifiable components. Performs **no** execution. A failure here settles B1. |
| `start(attempt_id, binding, request, handoff_deadline) → StartAck` | **(rev 3, replaces the first half of `generate`)** Bounded external handoff (§4.3). Sends to the instance named by `binding` only; if the live instance differs it returns `NOT_STARTED` without sending. Returns `ACCEPTED`/`NOT_STARTED`/`UNKNOWN` by its deadline and initiates no further transmission afterwards. Honors the stop-before-start tombstone. |
| `await_result(attempt_id, binding, deadline) → Completed(content, binding_used, finish_reason) \| Failed(code, public_message, knowledge)` | **(rev 3, second half of `generate`)** Waits for the attempt's result on the bound instance. `binding_used.instance_ref` must be the instance that actually delivered; the coordinator compares it with the persisted binding (§4.5). Never truncates silently. Any escaping exception is `POSSIBLY_ACTIVE`. |
| `stop(attempt_id, binding, deadline) → StopAck` | `ACCEPTED`, `REFUSED`, `UNREACHABLE`, `UNSUPPORTED`, `INSTANCE_MISMATCH`, `TIMEOUT`. No evidence. After acceptance a later `start(attempt)` must send nothing (`NOT_STARTED`). |
| `probe(attempt_id, binding, deadline) → ProbeResult` | `CONFIRMED_ENDED(basis)`, `STILL_ACTIVE`, `UNKNOWN(reason)`, `INSTANCE_MISMATCH`, `UNSUPPORTED`. |

Control obligations (each is a testable adapter-conformance check):

1. **Independent.** `stop` and `probe` are callable while an `await_result` (or a `start`) for another or the same attempt is blocked, on a control path that does not share the generation lock, thread, connection or executor. If a runtime cannot serve control during generation, the adapter returns `UNKNOWN`; it never blocks forever.
2. **Bounded.** Every control call takes a deadline and returns within it; expiry returns `TIMEOUT`/`UNKNOWN`, never evidence. The supervisor also bounds the overall stop-and-verify budget and then performs T6.
3. **Instance-exact.** Every call carries the full binding. An adapter verifies `binding.instance_ref` against the live instance **before** acting. If they differ it returns `INSTANCE_MISMATCH` and touches nothing, so a replacement instance is never probed or stopped on behalf of an old attempt (R-5).
4. **Mismatch is not termination.** `INSTANCE_MISMATCH` means "the bound instance is not the one I serve". It is evidence of nothing, unless the adapter can additionally verify the old instance's absence (B4). A different instance answering at the old address proves nothing about the old one.
5. **Routing.** Composition registers adapters; a control router selects the handler by `binding_format`/`adapter_id`. No handler for a format ⇒ `UNSUPPORTED`.

### 6.4 Runtime replacement and unsupported bindings

| Case | Behavior |
| --- | --- |
| Runtime replaced while idle | New `prepare` returns a new `instance_ref`; later runs record it; earlier runs keep theirs. |
| Replaced while a run is active | Stream breaks (`POSSIBLY_ACTIVE`) → closure → `stop(old binding)` → `INSTANCE_MISMATCH` (new instance untouched) → B4 only if the adapter can verify the **old** launch identity has exited; else T6. The new instance's own work is never affected. |
| Old binding with an unregistered adapter or format | `UNSUPPORTED`; stays `indeterminate` unless another component that can interpret the binding produces B4. |
| Legacy 0A rows (no binding) | `UNSUPPORTED` by the binding-based router. Resolution only through a legacy-capable controller producing verified evidence (§5.5). A declaration that an old `runtime_id` label was an in-process runtime is **not** evidence (revision 2's fake-adapter shortcut is withdrawn). |
| Domain logic | Depends only on the port; nothing in it names llama.cpp or any vendor. |

### 6.5 Availability trade-off (owner-facing)

A run whose termination cannot be verified quarantines the **single** execution slot. Consequences: no new generation in **any** conversation until resolved; reading continues; the affected conversation stays closed. This is deliberate: releasing on belief risks two executions contending for one runtime and violates CB-05. It costs availability for manually launched runtimes that expose no verifiable process or termination signal. Ways out that preserve safety: a deployment mode in which Anonymous (or a controller it can authenticate) owns the runtime process so B4 is obtainable; a runtime that reports per-attempt termination (B3/B5). Not provided, and not added here: an owner "force release". If the owner ever wants one it is an explicit weakening of CB-05 and requires its own ADR and acceptance criteria; it is **not** part of this proposal.

**Operator role.** An operator may act on the world (stop or restart the runtime, then ask Anonymous to `reconcile`). The reconcile re-runs `probe`; only its verified result changes state. A statement that the runtime "is stopped" has no effect on state; it may be logged as a content-free audit line.

## 7. Uncertain publication (F7)

A transport outage, a storage error on commit, or a restart alone proves neither success nor failure. After a publication attempt (T4) whose result is unknown, the supervisor resolves the outcome **by reading and by the arbiter**, never by calling the model again.

| Case | How established | Required behavior |
| --- | --- | --- |
| **A. Committed** | A read finds the assistant message with `produced_by_run_id = R` and the run `succeeded`. (They are atomic; one without the other is a fault.) | Return the stored result. Preserve the original message id, position, **commit instant** and provenance (FR-15). Never overwrite success during recovery; closure, settlement and retry are refused (`PUBLISHED`). |
| **B. Absent** | The run's fence is **durably closed** and no message exists. A read showing no message while the fence is still **open** is *not yet* absence: a delayed or in-doubt commit could still land. Closing the fence is what converts "not seen" into "can no longer happen". | No assistant success exists. The run may be **settled only if** an admissible basis for runtime termination or non-invocation exists (§1.3). If output was held, its late-arrival/observation is B3 (`response_not_saved`, `completion_observed = yes`). Otherwise the run stays `in_flight`/closed or `indeterminate` until evidence arrives. |
| **C. Undetermined** | The store cannot be read, or reading is itself uncertain. | Remain unresolved. Make no status change. Do not fabricate success or failure. Admission stays closed, the slot stays held, and reconcile runs before any retry or admission decision (§9). |

Supervisor procedure after an unknown T4: (1) read; Case A → done. (2) Read shows `in_flight`/open/no message and output still held → bounded idempotent re-publication (unique `produced_by_run_id` plus the arbiter make repeats safe). (3) Bounded attempts exhausted → write T5 (closure + settlement, B3, `response_not_saved`); if that returns `PUBLISHED` the commit had landed (Case A); if the write itself is unknown go to (1). (4) Store unreadable → Case C.

A restart changes none of this: reconcile re-reads; an orphan with no message is closed (SP-9, which proves absence) and then needs termination evidence like any other. Revision 1's "restart ⇒ `failed(interrupted_server_restart)`, retry eligible" for an unresolved publication is **withdrawn**: it released admission without evidence.

## 8. Explicit retry

### 8.1 Three different things

| Mechanism | Identity | Effect | Status |
| --- | --- | --- | --- |
| **HTTP retransmission** of the same submission | same `submission_id` | resolves the original outcome; no new message, no new run (LM-05) | exists (0A) |
| **Explicit new generation attempt** (retry) | new `retry_id` referencing message U | one new run on the same saved U after a settled failure; no new user message | **0B** |
| **Deliberate regeneration** after success | — | out of V0 | deferred |

### 8.2 Eligibility (server-side, one transaction, current state)

A retry `(retry_id, message_id)` creates a run only if: the owner owns the conversation; U is the **latest** saved message and a user message; U's most recent run is `failed`; no run of the conversation is `pending`/`in_flight`/`indeterminate`; U has no `succeeded` run; the slot is not quarantined; the conversation's pinned configuration is resolvable. Otherwise it is refused with an observable reason and creates nothing.

| Situation | Result |
| --- | --- |
| Latest run `failed` | accepted → new run (T1), `retry_of` = that run |
| Same `retry_id` replayed | returns the run it created |
| Same `retry_id`, different target | conflict (`idempotency_conflict`) |
| Different `retry_id` while the first retry's run is unsettled | refused busy; no queue |
| Different `retry_id` after the first retry failed | new explicit intent → new run (no cap in V0) |
| Latest run `indeterminate` (or publication undetermined) | refused `execution_unresolved`; reconcile first (§9). Retry from an unresolved run could create a second concurrent execution |
| Latest run `succeeded` / U superseded | refused (V0-D04) |
| Slot quarantined / configuration unavailable | refused `runtime_quarantined` / `configuration_unavailable` |
| After restart | startup reconcile first; only runs that became `failed` are eligible |

No automatic or speculative retry exists. The server calls `start` only for a run it created in response to an explicit submission or retry intent. A retry's new run resolves the conversation's **current** configuration binding and records its own provenance.

### 8.3 What retry preserves

The user message keeps identity, position and commit instant (FR-15); earlier runs keep provenance, binding, outcome and failure facts; the new run has its own and, on success, its own assistant message and commit instant.

## 9. Supervision and recovery

- **S1 Ownership.** Execution belongs to a server-side supervisor, independent of the HTTP request. Whether the POST waits is IMPLEMENTATION_CHOICE; correctness must not depend on it.
- **S2 Disconnect.** A closed client connection says nothing about the run and neither stops, retries nor settles it.
- **S3 Release rule.** A run is settled `failed` only on B1–B5 (§1.3) and through the fence (§4). Never on exception text, timeout expiry, connection loss, missing acknowledgment, restart, a client's or human's wish, or time.
- **S4 Closure and stop.** On deadline or shutdown: closure intent → T5c under G → stop → verification (SP-9…SP-11).
- **S5 Reconcile triggers.** (a) startup, before readiness, bounded; (b) a replay, send or retry touching a conversation or slot whose owner run is unresolved and has no live supervisor; (c) an explicit reconcile command. No background polling loop. Reconcile is idempotent, rate-limited (IMPLEMENTATION_CHOICE), never invokes the model, never acquires the slot, and acts only on orphans or `indeterminate` runs.
- **S6 Orphans.** An orphan never executes anything again; it has no invocation right. Reconcile performs T5c (with `expected_version`), then: durable `handoff = NONE` or `NOT_CALLED` ⇒ T5 B1 with **no external action**; `NOT_STARTED` ⇒ T5 B2; otherwise `probe` of the **persisted** binding — admissible basis for the handoff state → T5, else T6 (and later T7 by any reconcile actor).
- **S11 Legacy blockers.** Class E blockers (§5.5) are reconciled independently, at startup and on touching requests, only by verified evidence; their count gates all dispatch.
- **S7 Concurrency.** A (one unsettled run per conversation) plus B (one slot, V0 default one) as §5. A run waits in `pending` for the slot (bounded), fail-fast when quarantined.
- **S8 Shutdown.** Orderly shutdown closes and stops active attempts; settled only on an admissible basis (`interrupted_shutdown`); otherwise the run is left as stored for the next startup reconcile.
- **S9 Observability.** Each transition logs run id, code, basis and counters; never content, prompts, outputs, paths or secrets. Contradictory evidence (late output for a settled run, evidence conflicting with stored state) is a distinct logged fault and never alters history.
- **S10 Presentation.** The API distinguishes *active* (`pending`/`in_flight`) from *unresolved* (`indeterminate`/quarantine) and from *blocked by configuration*; the unresolved state says reading continues, new generation is blocked, and what can resolve it. A refresh cannot resolve it.

### 9.1 Scenario matrix

| Scenario | Evidence | Action | Human needed? |
| --- | --- | --- | --- |
| Client disconnects mid-generation | none about the run | supervisor completes; normal publication | no |
| Runtime refuses connection | B2 | T5 `runtime_unavailable` | no |
| Runtime returns a terminal error | B3 | T5 `runtime_rejected` | no |
| Reset or read timeout after send | `POSSIBLY_ACTIVE` | T5c → stop → probe: basis → T5 `connection_lost`; else T6 | only if T6 persists |
| Deadline expires | closure intent | T5c (or `PUBLISHED` if publication won) → stop → probe | only if T6 persists |
| Late output arrives during stop | fence closed | discard; if delivered by the verified bound instance, B3 → T5; if attributed to another instance, fault, not evidence (§4.5) | no |
| Runtime process restarts mid-run | stream breaks | T5c → stop(old) `INSTANCE_MISMATCH` → B4 if old process verified gone, else T6 | only if T6 persists |
| Anonymous crashes, runtime continues | at restart: orphan | T5c → probe(recorded binding): B3/B5 → T5; `STILL_ACTIVE`/`UNKNOWN` → stop, re-probe, else T6 | only if unverifiable |
| Anonymous crashes, runtime dies | orphan | probe: B4 → T5 `interrupted_server_restart` | no |
| Anonymous crashes before the handoff marker (T3b) | durable `handoff = NONE` | T5c, then T5 B1 `interrupted_before_dispatch`; no probe, no stop | no |
| Anonymous crashes during the handoff | durable `STARTED`, outcome unrecorded | closure, probe persisted binding; B3/B4 (B5 only with `late_delivery_excluded`); else T6 | only if unverifiable |
| Legacy 0A run unresolved | no binding, label only | not evidence; blocker E; dispatch blocked; diagnostics | resolves only when a verified evidence producer exists |
| Restart finds `pending` | no dispatch recorded | T2 B1 | no |
| Control path unreachable | `UNKNOWN` | T6; quarantine; reading continues | resolves only when evidence becomes obtainable |
| Publication outcome unknown | §7 | case A/B/C | no |
| Two sends / two clients | single admission authority | second refused busy | no |

### 9.2 When someone must act

Only when a run stays `indeterminate` after bounded reconciliation: no component can verify that the work ended. A person can change the **world** — stop the runtime, restart it under a controller that can verify exits, restore the control path — and then request a reconcile. No human statement changes state (§6.5).

## 10. Submission fencing

**Limitation (0A, documented):** an abandoned uncertain submission may still be committed after the user deliberately creates a new message, producing a duplicate user message and, for a real model, a second generation.

**Analysis.** *Integrity:* no history corruption (immutable messages, one message per intent, one-run-per-conversation admission). *Residual harm:* a duplicate user message and an extra real generation. Privacy and security are unaffected (own data, same owner). *Likelihood:* an abandoned id is usually uncertain because a **response was lost**, so the new message is a visible, user-chosen duplicate (LM-05: distinct intent). The narrow window fencing closes — a genuinely delayed request — widens on mobile/handoff networks (V0-AC-04). *Mechanism if built:* a server-answered "resolve" for a submission id that either returns the committed outcome or durably records a fence refusing a later arrival (`submission_fenced`); the client creates a new id only after that answer.

**Classification.** Slice 0B (development, synthetic data, loopback): not required; the 0A notice stays accurate. Before full V0: `REQUIRED_BEFORE_FULL_V0` (V0-AC-04/07), or an explicit owner-accepted limitation. Not implemented here.

## 11. Conversation configuration continuity (F5)

NFR-08 requires more than attribution: an existing conversation must keep its selected context and behavior configuration across application updates. This is a **minimal V0 mechanism, not a configuration subsystem**: no persona management, no Memory, no profile editor.

### 11.1 Objects

- **Effective configuration** `E`: an immutable manifest — `{ context_construction: {id, version, parameters, definition_digest}, system_instructions: text or none, behavior_configuration: {id, version, content_digest} or none }` — in a deterministic canonical form. `E`'s identity is its **content digest** (algorithm and canonical-form version are part of the digest string). V0 ships one effective configuration (whole-history context, no system instructions, behavior `none`). The behavior part is always an explicit `none` in V0.
- **Manifest store:** insert-only, content-addressed, verified on read (a stored manifest whose digest does not recompute is a fault and treated as unavailable). Composition registers every configuration the build ships (insert if absent; if present it must be identical).
- **Catalog:** the set of configurations the running build can **execute** (it has the context-builder implementation for `context_construction.id/version`). *Retained* (a manifest exists) is distinct from *executable* (the build can run it).
- **Binding:** an append-only history of `(conversation, seq, effective_configuration_digest, origin, created_at)`; the current binding is the highest `seq`. `origin ∈ {initial, adoption, legacy_baseline}`. A binding is never updated or deleted.

### 11.2 Rules

1. **Creation.** A new conversation is bound, atomically with its creation, to the build's default effective configuration (`origin = initial`).
2. **Upgrade never rebinds.** Installing a build with a different default changes only the default for **new** conversations. Existing bindings are untouched.
3. **Dispatch.** T3 records the resolved digest (and the component labels/digests of §12) on the run. Generation uses exactly that configuration.
4. **Explicit adoption.** `adopt(conversation, target_digest, adoption_id)` is an owner-scoped, idempotent intent that appends a new binding. It requires: no unsettled run in the conversation; the target manifest exists; the target is executable. It affects only **later** runs. Reversal is adopting an earlier retained digest, if still executable. Adoption via an API route or UI is deferred; 0B-1 exposes it as an application-level operation so it is testable.
5. **Unavailable.** If the pinned digest is not executable (missing code, failed digest verification, a failed `E0` self-test), generation and retry for that conversation are **refused visibly** (`configuration_unavailable`; no message appended; if it arises after admission, T2 `configuration_unavailable`). Nothing is silently substituted. Reading history is unaffected. Adopting an available configuration is the explicit way out; it is recorded as such.
6. **Historical runs keep their provenance.** Adoption or upgrade never rewrites runs; the old run's digest remains.
7. **Not a mechanism for private data.** V0 configurations are application-shipped assets. User-owned configurations, when introduced, must satisfy NFR-08 class 2 and are out of scope here.

### 11.3 Legacy Slice 0A conversations (F5)

0A conversations have no configuration binding and their runs have no provenance. Revision 2 bound them to a baseline `E0` in the migration and "verified" it by comparing two newly written implementations. That proved nothing about continuity with 0A and is **withdrawn**. Revision 3:

- **The migration binds nothing and asserts no equivalence.** It creates no binding rows and makes no claim about 0A behavior.
- **0A's actual behavior is the reference** (§11.4): the constructed view produced by the real 0A code at commit `01e9f46`, captured as golden fixtures.
- **Binding happens at startup, after equivalence is shown.** Startup runs the **`E0` self-test**: the fixture file's pinned digest is checked and the shipped `E0` context builder replays the golden fixtures that carry a replayable history (FX-01–FX-06); its constructed views must equal the recorded views byte-for-byte (§11.4). FX-07 (two interleaved conversations) is not replayed at startup; the test suite verifies it through the real store and coordinator. Only if it passes does startup append, for each conversation that has no binding row and existed before the 0B schema (record epoch `legacy_0a`), one binding with `origin = legacy_baseline`, recording the golden fixture digest as `baseline_evidence`. The step is idempotent and logged (counts only).
- **If equivalence cannot be established** (fixture file missing or digest mismatch, `E0` builder fails any fixture, `E0` absent from the build): nothing is bound; legacy conversations stay **readable**; generation and retry for them are refused visibly (`configuration_unbound_legacy`, no message appended); **explicit adoption** of an available configuration is required before generation. Nothing is silently rebound or substituted.
- **If `E0` later fails the self-test after being bound** (a later build changed context construction), the binding stands, `E0` is *unavailable* (not executable), and §11.2 rule 5 applies: blocked, history readable, explicit adoption.
- 0A runs keep provenance **`unrecorded`**; no model, runtime, persona, configuration or version is fabricated for them. `E0` is a statement about the **constructed view** only.
- Legacy runs that were unresolved are handled separately by §5.5; binding a conversation's *configuration* has no bearing on whether its old execution could still be active.

### 11.4 Golden baseline from the actual Slice 0A implementation (evidence procedure)

Full record and the capture script: [ld-04-slice-0a-context-golden.md](../evidence/ld-04-slice-0a-context-golden.md); fixtures: [ld-04-slice-0a-context-golden.json](../evidence/ld-04-slice-0a-context-golden.json) (sha256 `afb16c8821f80c5ce4eaf6aee328fb772ee7057e6b62c8d810fdab3e5e2d5bf1`).

- **What 0A applied** (from the real source and its types at `01e9f46`): whole-history prefix through the triggering user message, roles and content verbatim, ordered by `position`; **no** system instructions, sampling or other settings, budget/omission, behavior profile or Memory; `ModelRequest` has the single field `messages` and `ContextMessage` the fields `role`, `content`. Every one of these is also *captured* in the fixture file, not only asserted here.
- **Captured fixtures (7):** single message; multi-turn prefixes; verbatim text fidelity (whitespace, CRLF, NFC/NFD, emoji, RTL, bracket marker); the 32,000-character maximum; a failed run; position-versus-instant ordering (clock runs backwards); two interleaved conversations.
- **How captured:** the real 0A `migrate`, `SqliteStore`, `ExecutionCoordinator` and `ContextBuilder` were driven from a read-only `git archive` of `01e9f46` with a scripted model that records the request it receives; two runs were byte-identical. Nothing in the repository was modified to do so.
- **How compared with the 0B-1 baseline:** (1) the 0B-1 test suite loads the fixture file (pinned by digest, also recorded in the `E0` manifest together with the reference commit) and replays all seven histories through the 0B-1 store and `E0`, while the startup self-test checks the digest and replays FX-01–FX-06 only (FX-07 needs the real store and coordinator and is test-suite only); (2) compare canonical serializations byte-for-byte; (3) any difference fails the build and, at startup, marks `E0` unavailable. (4) An independent reviewer can re-run the capture from `01e9f46` without the 0B-1 code and compare digests.
- **Not claimed:** equivalence of model behavior, of the fake adapter's reply text, of capacity refusal (0B refuses over-capacity input; 0A had no budget), or of any provenance. The fixtures pin the constructed view only. They are an evidence and compatibility requirement, not a persona or Memory feature.

## 12. Provenance identity (F6)

### 12.1 Components

Each dispatched run records these components. For each: a **label** (human-readable id/version string, descriptive only), an **identity** (digest or immutable reference, if any) and a **verification state**.

| Component | Typical identity | Typical verification in V0 |
| --- | --- | --- |
| Application build | VCS commit + clean flag or distribution digest | `asserted` (packaging) → `verified` if a distribution digest is checked |
| Adapter | id + version | label (part of the application build) |
| Model artifact | content digest of the model file | `verified` only if Anonymous or the adapter computed and matched it; `asserted` if reported by the runtime; else `unspecified` |
| Runtime build | digest of the runtime executable / build id | `verified` if the adapter owns and hashed the executable; `asserted` if version-reported |
| Context configuration | content digest of the manifest part | `verified` (computed by Anonymous from the stored manifest) |
| Behavior configuration | content digest, or explicit `none` | `verified`; `none` is a recorded explicit value |

**Verification states:** `verified` (identity computed or checked by Anonymous or a component that verifies against the actual artifact at or before dispatch); `asserted` (supplied by a component or deployment and not checked); `unspecified` (capture attempted; no value available). Separately, **`unrecorded`** means the run predates capture; it is not `unspecified`. A cached digest is `verified` only if the adapter's staleness check is sound; otherwise `asserted` (IMPLEMENTATION_CHOICE).

### 12.2 Rules

1. Provenance is durably recorded in T3, before invocation, and is immutable afterward. Never-dispatched runs record none and never fabricate any.
2. Historical rows are never required to acquire data that was never captured; they stay `unrecorded`.
3. **Comparison is three-valued.** For one component: `IDENTICAL_VERIFIED` (both verified, same digest algorithm and value); `CLAIMED_IDENTICAL` (equal asserted digests); `DIFFERENT` (digests differ); `NOT_COMPARABLE` (either side `unspecified`, `unrecorded` or label-only). Two unspecified values, or two equal labels, are `NOT_COMPARABLE`, **never** equal.
4. Two execution environments may be called equivalent only if **every** component is `IDENTICAL_VERIFIED`. Even then no behavioral equivalence of output is asserted (NFR-08 class 3).
5. The post-call check that the output's reported identity matches the binding is a consistency check: a mismatch refuses publication; a match proves nothing about equivalence.
6. Descriptive metadata (labels, versions as reported) is always retained even when identity is unverifiable, and is shown as such.

## 13. Deterministic acceptance scenarios

Future tests, driven by a **scripted fake port** (controllable results; holds and releases via events or barriers, not sleeps; scriptable `prepare`/`stop`/`probe`/instance identity), the injected clock, the store's fault-injection technique, and real-process restart tests where noted. Race scenarios use barriers to force both orderings. **None has been run;** they are design-level criteria. `F` = finding addressed; `AC` = V0 release scenario.

### 13.1 Existing scenarios (revised where noted)

| ID | F | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-01 | | Success: scripted `Completed` | `pending→in_flight→succeeded`; one assistant message with its own instant; provenance recorded; order U,A; slot released in the publishing write | 01 |
| LDT-02 | | Known failure `Failed(ENDED)` | `failed`, basis B3, no assistant message, `completion_observed=no`; retry eligible | 06 |
| LDT-03 | | Runtime unavailable `Failed(NEVER_REACHED)` | `failed(runtime_unavailable)`, basis B2; no cloud fallback; later retry succeeds | 06 |
| LDT-04 |  | Client disconnect while held | run still publishes; second client sees it; replay returns the original outcome; exactly one `start` call | 02, 07 |
| LDT-05 | F1 | **Revised.** Real-process kill while the attempt is awaited (`handoff = STARTED/ACCEPTED`); restart; `probe` of the persisted binding → B4 (scripted) | orphan: closure (T5c) then T5 `failed(interrupted_server_restart)` basis B4; slot free; retry eligible; message count unchanged. Restart alone settles nothing | 02 |
| LDT-06 | F1, F3 | **Revised.** Restart; `probe` → `UNKNOWN`/`STILL_ACTIVE` after bounded budget | `indeterminate`; slot quarantined; reading works; send refused `runtime_quarantined`/busy; retry refused `execution_unresolved` | 02, 07 |
| LDT-07 | F1, T7 | **Revised.** From LDT-06: later `probe` → B3/B4/B5; trigger by replay, send, or explicit reconcile | **T7** (source `indeterminate`/closed) → `failed` with the basis; slot released; **no operator-statement path exists**; refused if a message exists | 02, 06 |
| LDT-08 | | Explicit retry, no duplicate | one new run on the same U; `retry_of` set; replay returns same run; conflicting target → 409 | 06, 07 |
| LDT-09 | | Retry refusals (succeeded, active, indeterminate, superseded, quarantined, configuration unavailable) | no run, no message, specific reasons | 07 |
| LDT-10 | F2 | **Revised.** Deadline fires; closure; stop acknowledged; then output arrives from the verified bound instance | no assistant message; output discarded; B3 → `failed(deadline_exceeded)`, `completion_observed=yes`; fault counter; no content in logs (output from another instance: see LDT-43) | 06, 14 |
| LDT-11 | F7 | **Rewritten:** see §13.2 | | 07 |
| LDT-12 | F6 | **Revised.** Run; change model/runtime/context/behavior identity; run again; plus a never-dispatched failure | each dispatched run keeps its own components with verification states; earlier rows unchanged; never-dispatched run has none | 01, 11 |
| LDT-13 | F3 | **Revised.** Two conversations; slot busy | second conversation's run stays `pending` **without owning the slot**, waits (bounded), then dispatches or `failed(runtime_busy)` B1; same-conversation second send 409 | 07 |
| LDT-14 | F1 | Bare exception from adapter | `POSSIBLY_ACTIVE`; closure; evidence decides `failed` vs `indeterminate`; never `runtime_error`-and-release | 06 |
| LDT-15 | F2 | **Revised.** Dispatch authorization (T3) or handoff marker (T3b) commit uncertain | `start` is **not** called unless a read confirms the supervisor's own T3b; durable `handoff = NONE` ⇒ B1; durable `STARTED` with unrecorded outcome ⇒ **not** claimed never-invoked, evidence path | 07 |
| LDT-16 | | Capacity | refused before dispatch, `context_exceeds_capacity`, nothing truncated | 08 |
| LDT-17 | F3, F5, F6 | **Revised.** Apply the new migration to a populated 0A database (including unresolved runs) | messages/runs/submissions byte-identical; every run `record_epoch = legacy_0a`; **no status changed, no fence, handoff, binding, slot or provenance written**; old provenance `unrecorded`; **no configuration binding created by the migration**; refusal and rollback on structural inconsistency (LDT-63) | 02, 15 |
| LDT-18 | F5 | **Revised.** Golden constructed view against the **actual 0A reference** (evidence file, sha256 pinned) | the 0B-1 `E0` builder reproduces every fixture's recorded views byte-for-byte; any difference fails the build; later configurations may differ only with a different digest (LDT-65) | 01, 08 |
| LDT-19 | | Privacy of diagnostics | markers in prompts, outputs, runtime error text, binding payload absent from logs, failure messages, run records, API | 14 |

### 13.2 LDT-11 — uncertain publication (rewritten)

| ID | Case | Setup → action | Expected |
| --- | --- | --- | --- |
| LDT-11a | **A** | Fault injected **after** COMMIT of T4 (durable) | supervisor reads: `succeeded`; original message id and commit instant; model called once; a later closure attempt returns `PUBLISHED`; stop never sent |
| LDT-11b | **A** | Replay of the submission after LDT-11a, and after a process restart | returns the same message; instant unchanged; no overwrite; no second message |
| LDT-11c | **B** | Fault **before** COMMIT; output held | read shows open fence, no message ⇒ not yet absent; bounded re-publication succeeds ⇒ `succeeded`. If re-publication is exhausted: T5 (closure+settle, B3, `response_not_saved`, `completion_observed=yes`); no success fabricated |
| LDT-11d | **B** | Orphan after restart, no message, fence closed by reconcile | absence is proven by the fence; the run still needs B3–B5; with `probe` → `UNKNOWN` it stays unresolved (not `failed(interrupted_server_restart)`) |
| LDT-11e | **C** | Persistent store outage after the publication attempt | no status change; run stays as stored; admission and slot stay held; no retry/admission decision; after storage returns, reconcile resolves to A or B |

### 13.3 New scenarios

| ID | F | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-20 | F2 | **Publication wins the race.** Barrier forces T4 to commit before closure | message + `succeeded` atomic; closure returns `PUBLISHED`; stop never sent; result preserved | 07 |
| LDT-21 | F2 | **Closure wins the race.** Barrier forces T5c before T4 | T4 refused (`RunStateConflict`); output discarded as provisional; no message ever; no later invocation of the closed attempt | 07 |
| LDT-22 | F2, F1 | **Output during stop.** Closure committed; stop in progress; output arrives from the **verified bound instance** | discarded; B3 settles `failed`; never published; no content in logs. Output from any other instance is *not* evidence (LDT-43) | 06, 14 |
| LDT-23 | F2 | **Repeated publication and late callbacks.** T4 twice; stale completion after settlement; duplicate probe result | one message; second returns the original; callbacks after settlement change nothing; fault counters only | 07 |
| LDT-24 | F2 | **Closed attempt cannot be invoked.** Closure intent between T3 and T3b; duplicate supervisor attempt; adapter receives `stop` before `start` | `start` not called (T3b `FENCE_CLOSED`), or adapter tombstone returns `NOT_STARTED` (B2); replay/retry/restart never call `start` for an existing run (see LDT-46–54) | 07 |
| LDT-25 | F3 | **Restart with occupied slot.** Orphan `in_flight`; probe `UNKNOWN`; restart again | run `indeterminate`; slot still held after both restarts (derived from rows); other conversations' sends refused `runtime_quarantined`; reading works | 02, 07 |
| LDT-26 | F3, F4 | **Reconciliation while the slot is occupied.** Quarantine held; trigger reconcile from a different request/actor; probe → B4 | run `failed` via T7 with no slot acquisition; slot released; next generation (any conversation) dispatches | 02 |
| LDT-27 | F3 | **Pending holds no slot.** Pending run waiting while another conversation's run executes | exactly one run owns the slot; the pending run owns only A; on release it dispatches; on timeout `failed(runtime_busy)` B1 | 07 |
| LDT-28 | F3 | **Idempotent, owner-checked release.** Repeat settlement; attempt to settle a run that does not own the slot | no change on repeat; no other run's ownership is released; slot uniqueness holds under concurrent T3 | 07 |
| LDT-29 | F4 | **Unavailable original binding.** Orphan whose `binding_format`/adapter is no longer registered | `UNSUPPORTED`; stays `indeterminate`; slot quarantined; nothing probes or stops another instance (R-5) | 02, 11 |
| LDT-30 | F4 | **Safe runtime replacement.** Replace instance mid-run; control with the old binding | `INSTANCE_MISMATCH`; the new instance's active attempt is untouched; settlement only if the adapter verifies the old launch identity exited (B4), else `indeterminate` | 06, 11 |
| LDT-31 | F4 | **Control independent of blocked generation.** `await_result` held | `stop` and `probe` return within their deadlines concurrently | 06 |
| LDT-32 | F4 | **Control timeout.** `probe`/`stop` exceed deadline | `UNKNOWN`/`TIMEOUT`; no release; T6 after the bounded budget | 06 |
| LDT-33 | F1 | **Stop is not evidence.** `stop` → `ACCEPTED`; then `probe` → `STILL_ACTIVE` or `UNKNOWN` | `indeterminate`; slot quarantined | 06 |
| LDT-34 | F1 | **Incorrect operator assertion.** Operator states the runtime is stopped while it is not; reconcile invoked | state unchanged; probe `STILL_ACTIVE`; statement has no field in the store; only a content-free audit line | 06 |
| LDT-35 | F5 | **Application upgrade with an old conversation configuration.** Conversation bound to `E1`; build default becomes `E2` | existing conversation still runs `E1`; new conversations bind `E2`; old runs keep `E1` digest; no rebinding | 01, 11 |
| LDT-36 | F5 | **Unavailable pinned configuration.** Binding to a digest the build cannot execute | generation/retry refused `configuration_unavailable`; nothing substituted; history readable; no message appended | 06, 11 |
| LDT-37 | F5 | **Explicit adoption.** Adopt `E2` (and later `E1` again) | new binding appended; refused while a run is unsettled; replay of `adoption_id` is idempotent; earlier runs untouched | 11 |
| LDT-38 | F5, F6 | **Legacy 0A conversation, equivalence established.** Startup `E0` self-test passes; first generation after migration | startup appended one `legacy_baseline` binding with the fixture digest; run executes under `E0`; old runs remain `unrecorded`; no fabricated versions | 02, 15 |
| LDT-39 | F6 | **Verified vs unverifiable provenance.** Components `verified`, `asserted`, `unspecified`, `unrecorded` | comparison returns `IDENTICAL_VERIFIED`/`CLAIMED_IDENTICAL`/`DIFFERENT`/`NOT_COMPARABLE`; two unspecified or equal labels ⇒ `NOT_COMPARABLE`; environments not called equivalent unless all five verified | 01, 11 |
| LDT-40 | F6 | **Descriptive metadata retained.** Unverifiable model digest | label and version retained, verification `unspecified`; no digest invented | 11 |
| LDT-41 | F4 | **Stale/unsupported binding never acts on a different instance.** Replacement adapter receives an old `instance_ref` | refuses with `INSTANCE_MISMATCH`; no stop/probe reaches the live instance | 11 |
| LDT-42 | F3 | **Quarantine at admission.** Quarantined slot (0B run) *or* legacy blocker; send/retry in any conversation | refused `runtime_quarantined` / `generation_blocked_legacy_unresolved`; no user message appended; if the block begins after admission ⇒ `failed(...)` B1 via T2 | 07 |

Coverage check for the required list: stop/publication racing — 20, 21; late output during stop — 10, 22; unknown publication commit — 11a–e; restart with occupied slot — 25; reconciliation while gate occupied — 26; unavailable original runtime binding — 29; application upgrade with old config — 35; unavailable pinned config — 36; immutable vs unverifiable provenance — 12, 39, 40; incorrect operator assertion — 34; safe runtime replacement — 30, 41.

### 13.4 Revision-3 scenarios (five corrections)

Race scenarios force each interleaving with barriers on both the invoker and the closer, and inject a pause at every step boundary of §4.4. `R3` marks the revision-3 correction addressed.

**Correction 1 — identity mismatch**

| ID | R3 | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-43 | F1 | **Instance mismatch output.** Output delivered with `binding_used.instance_ref` ≠ persisted | rejected for publication; content discarded and never logged; fence closed (`instance_mismatch`); the persisted binding is probed; with probe `UNKNOWN` ⇒ T6, quarantine; **no B3 from this output** | 06, 14 |
| LDT-44 | F1 | **Model-identity mismatch, instance verified.** Output from the bound instance with a different reported model | rejected; T5 `failed(model_identity_mismatch)`, basis **B3**, `completion_observed=yes`; slot released | 06 |
| LDT-45 | F1 | **No redirect to a replacement.** A replacement instance is live and busy with another attempt; the original attempt is closed on a mismatch | `stop`/`probe` go to the persisted binding only; the router yields `INSTANCE_MISMATCH`/`UNSUPPORTED`; the replacement's work is untouched; quarantine unless independent B3 (original instance)/B4/B5 | 11 |

**Correction 2 — invocation versus closure**

| ID | R3 | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-46 | F2 | **Pause between the authorization check and the handoff (H-1, both interleavings).** Invoker paused after taking G and before T3b; closure requested | Interleaving 1: closer blocks on G; T3b commits; `start` returns; closure commits after; no `start` after closure. Interleaving 2: closure commits first; T3b returns `FENCE_CLOSED`; `start` **never called**; B1 settle; no stop/probe | 07 |
| LDT-47 | F2 | **Pause after T3b, before `start`.** Closer waits on G | `start` is initiated before closure commits; closure follows; stop only after closure | 07 |
| LDT-48 | F2 | **Stop requested before invocation.** Closure while `handoff = NONE` | **no external action**; T5 B1; scripted adapter records zero calls | 07 |
| LDT-49 | F2 | **Stop during handoff.** Stop requested while `start` is in progress | stop is not sent until closure is durable; closure waits for G; `start` and `stop` never overlap for the attempt | 07 |
| LDT-50 | F2 | **Crash before T3b** (real-process kill, fault injection) | restart: orphan closed, `handoff = NONE` ⇒ T5 B1 with no external action; `start` never called by any boot | 02 |
| LDT-51 | F2 | **Crash during/after the handoff** (`STARTED`, outcome unrecorded) | orphan closed; probe of the persisted binding; B4 accepted; B5 **refused** unless `late_delivery_excluded`; unknown ⇒ T6 quarantine; no second `start` | 02 |
| LDT-52 | F2 | **Acceptance before closure** (`ACCEPTED`), then closure | closure and stop follow; B1/B2 refused; B3–B5 required | 07 |
| LDT-53 | F2 | **Supervisor replacement/restart.** Replacement supervisor in the same boot; second T3b attempt; restart | no invocation right ⇒ no `start`; T3b `ALREADY_STARTED`; at most one `start` per attempt across everything | 07 |
| LDT-54 | F2 | **Delayed callbacks.** Late start acknowledgment after closure; late output; late probe reply | read-only (SP-12); no state change; a late acknowledgment beyond the adapter deadline is recorded as a contract fault and treated `UNKNOWN` | 07 |
| LDT-55 | F2 | **`UNKNOWN` handoff then closure (U-1).** `start` returns `UNKNOWN`; closure; only B5 evidence available | not settled; run stays quarantined; B4/B3 settle | 06 |
| LDT-56 | F2 | **Hung handoff (U-2).** `start` exceeds its deadline while holding G | closer does **not** commit closure; run stays `in_flight`/open; fault raised; slot held; no settlement; after restart handled as LDT-51 | 07 |

**Correction 5 — T7 and the predicates**

| ID | R3 | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-57 | T7 | **T7 from `indeterminate`.** Indeterminate, closed run; evidence B4 | T7 commits without any `in_flight` precondition; slot released in the same write; basis stored | 02 |
| LDT-58 | T7 | **Repeated and concurrent T7.** Two reconcile actors, same evidence and different evidence; replayed request | exactly one write; the other receives `SETTLED` with the stored result; no second evidence write; a stale `expected_version` is re-read and retried boundedly | 02 |
| LDT-59 | T7 | **Predicate matrix.** Every transition attempted from every wrong source (including T5 on `indeterminate`, T7 on `in_flight`, T7 with a message, T3b after closure, T4 on a closed fence or `NONE`) | each is refused with the specified result and changes nothing | 07 |

**Correction 3 — legacy unresolved executions**

| ID | R3 | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-60 | F3 | **Several legacy unresolved runs in different conversations** (mixed `in_flight`/`indeterminate`) | all rows and original facts preserved; none assigned a slot; slot uniqueness not violated; `LB` holds ⇒ all sends/retries refused `generation_blocked_legacy_unresolved`; each blocker's conversation closed; reading works; diagnostics list each | 02, 07 |
| LDT-61 | F3 | **No settlement path for binding-less runs (rev 3.1).** Attempt T5/T7 on legacy `in_flight`/`indeterminate` runs with every basis, a scripted `CONFIRMED_ENDED`, an operator-style note, and a matching `runtime_id` label | every attempt refused by the store; rows unchanged; `LB` still holds; legacy `pending` still settles T2/B1 | 02 |
| LDT-62 | F3 | **No evidence available.** No controller; label `runtime_id` equals a registered adapter's | label is not evidence; blockers remain; dispatch stays blocked; clear diagnostics; nothing settled to make startup succeed | 02, 07 |
| LDT-63 | F3 | **Migration stops safely.** Dataset with an assistant message on a non-`succeeded` run; one with two unsettled runs in a conversation | migration rolls back; the dataset is byte-identical; no readiness; content-free diagnostic. Unresolved legacy runs alone do **not** stop it | 02, 15 |
| LDT-64 | F3 | **Legacy `pending`.** Startup after migration | settled T2 B1 `interrupted_before_dispatch` from the 0A proof (null dispatch labels); not counted as a blocker | 02 |

**Correction 4 — configuration baseline**

| ID | R3 | Scenario | Expected | AC |
| --- | --- | --- | --- | --- |
| LDT-65 | F5 | **`E0` reproduces the real 0A fixtures.** Replay all 7 fixtures through 0B-1 | byte-identical views; fixture file digest equals the pin | 01, 08 |
| LDT-66 | F5 | **Equivalence not established.** Fixture file altered, or `E0` builder deliberately differs, or `E0` absent | no `legacy_baseline` binding created; history readable; generation/retry refused `configuration_unbound_legacy`; adoption of an available configuration required and recorded; no silent rebinding | 06, 11 |
| LDT-67 | F5 | **Independent recapture.** Re-run the capture from `git archive 01e9f46` | output byte-identical to the evidence file | 15 |

Coverage of the five corrections: F1 — 43–45, 10, 22; F2 — 15, 24, 46–56; F3 — 17, 25, 42, 60–64; F5 — 17, 18, 38, 65–67; T7 — 7, 26, 57–59. F4/F6/F7 scenarios (LDT-11a–e, 12, 29–32, 39–41) are unchanged in intent.

### 13.5 Revision-3.1 scenarios (0B-1 implementation tests; each is an executable test)

| ID | Scenario | Expected |
| --- | --- | --- |
| LDT-68 | Second process on the same dataset by symlink, `..` and relative aliases | refuses to start; hard-linked dataset refused; lock identity canonical |
| LDT-69 | Shutdown with a hung worker | `shutdown` reports incomplete; guard **still held** (second process refused); after the worker is released and joined, the guard releases |
| LDT-70 | Crash/restart (real process kill) at: before T3b, after T3b, during `await_result`, during publication | new boot reconciles: `NONE` ⇒ B1; otherwise B4 via the guard for `owning_process` bindings; an `external` binding stays quarantined |
| LDT-71 | Legacy 0A database with several unresolved runs opened by 0B-1 | rows preserved byte-for-byte; every settlement attempt refused; dispatch blocked in every conversation; reading works |

## 14. Decisions and open-question register

| Item | Class | Note |
| --- | --- | --- |
| Five statuses plus durable fence and handoff marker; T1–T7 with T3b/T3c; per-transition source predicates | ACCEPTED_FOR_0B | §3–4, ADR-0013 |
| Arbiter requirement on the persistence port | ACCEPTED_FOR_0B | §4.1 |
| A/B/C/D/E separation; slot owned by run; acquisition at T3; derived legacy startup quarantine | ACCEPTED_FOR_0B | §5 |
| Evidence bases B1–B5 (B6 removed for 0B-1); no operator release; quarantine | ACCEPTED_FOR_0B | §1.3, §6 |
| Binding, bounded independent control, persisted-binding-only targeting (R-5), `start`/`await_result` split and start acknowledgment | ACCEPTED_FOR_0B | §4.3, §6.2–6.4 |
| Handoff gate G and the single-use invocation right | ACCEPTED_FOR_0B | §4.3–4.6 |
| Instance mismatch ≠ evidence; model mismatch from verified instance = B3 | ACCEPTED_FOR_0B | §1.3, §4.5 |
| Legacy blockers, migration stop rules | ACCEPTED_FOR_0B | §5.5 |
| Golden baseline from the actual 0A code; `E0` self-test; startup (not migration) binding | ACCEPTED_FOR_0B | §11.3–11.4, evidence record |
| Uncertain-publication cases A/B/C | ACCEPTED_FOR_0B | §7 |
| Retry model | ACCEPTED_FOR_0B | §8 |
| Configuration binding and adoption | ACCEPTED_FOR_0B | §11, ADR-0014 |
| Provenance identity and verification states | ACCEPTED_FOR_0B | §12, ADR-0014 |
| Deadline, stop budget, probe count, re-publication bounds, reconcile rate limit | IMPLEMENTATION_CHOICE | configurable, conservative defaults |
| Field names, migration layout, route paths, opaque formats, canonical manifest form, thread/executor model | IMPLEMENTATION_CHOICE | |
| Can a real runtime serve `stop`/`probe` during generation? Per-attempt registration guarantee? | BLOCKED_BY_RUNTIME_EVIDENCE | decides B3/B5 and "unknown attempt" semantics |
| Can a runtime/transport guarantee `late_delivery_excluded` after an `UNKNOWN` handoff? Can `start` bound its handoff and abandon sends? | BLOCKED_BY_RUNTIME_EVIDENCE | decides whether B5 can ever settle U-1; adapter contract A-3 |
| Instance identity, process identity (pid + start identity) and exit verification, on Mac and Windows | BLOCKED_BY_RUNTIME_EVIDENCE | decides B4 |
| Reliable slot-idle signal, faithful input, `finish_reason`, version and artifact-digest reporting | BLOCKED_BY_RUNTIME_EVIDENCE | decides B5, §12 verification |
| Behavior on requester disconnect; request-level cancel | BLOCKED_BY_RUNTIME_EVIDENCE | |
| Submission fencing | REQUIRED_BEFORE_FULL_V0 | §10 |
| Authenticated reconcile command | REQUIRED_BEFORE_FULL_V0 | 0B uses a development trigger; it carries no evidence power |
| Windows evidence for all runtime-evidence rows; runtime containment (SD-08, ADR-0011) | REQUIRED_BEFORE_FULL_V0 | 0B uses synthetic data |
| ADR-0011 exclusive-instance mechanism backing assumption A-1 (single process) | REQUIRED_BEFORE_FULL_V0 | 0B-1 relies on the development `InstanceGuard`, which does not claim to satisfy ADR-0011 |
| A legacy-capable evidence producer (controller owning the resource scope) | BLOCKED_BY_RUNTIME_EVIDENCE | without one, legacy unresolved runs keep dispatch blocked (O5) |
| Context budget/omission evidence (LD-06) | REQUIRED_BEFORE_FULL_V0 | 0B refuses over-capacity |
| Streaming; cancel UI; regeneration; retry caps; partial-output retention; polling loop; multi-slot; persona/Memory/configuration editor; compatibility notices; failover; output recovery from the runtime | DEFERRED | |

**Owner decisions O1–O6 — ratified by the owner on 2026-10-12** (each was previously an owner-facing consequence not silently settled; the original questions and the recommendation record are in the [acceptance handoff](../reviews/slice-0b-1-acceptance-handoff.md) §7):

- **O1 — Availability. APPROVED.** Unverifiable runtime termination quarantines the execution slot and blocks all generation until verified; no force release without admissible evidence (§6.5). Making the runtime process controller-owned stays a 0B-2 question; weakening CB-05 would need its own ADR.
- **O2 — Legacy conversations. APPROVED.** Automatic startup binding is permitted only for eligible, previously unbound pre-0B conversations after the documented baseline verification (fixture digest and the golden replay, §11.3). An existing binding is never silently replaced. Explicit adoption remains mandatory for changes, for unverifiable equivalence and for unavailable configurations. Startup binding does not retroactively attribute unrecorded model provenance to historical messages or runs. Startup binding and adoption are not competing mechanisms: the first only attributes an unbound pre-0B conversation to the configuration shown to reproduce 0A (recorded with its evidence); the second is how any configuration is otherwise established or changed.
- **O3 — Refusal before saving. APPROVED.** An inadmissible send (slot quarantined, pinned configuration unavailable) is refused at admission and no user message is saved; the client preserves the unsent draft on a definite refusal. (Dedicated presentation and tests for the new refusal codes are follow-up work.)
- **O4 — Lost output. APPROVED.** Closure may discard a completed but unpublished result; explicit retry is required; success already durably published is preserved (uncertain-publication Case A, §7).
- **O5 — Existing 0A datasets with unresolved runs. APPROVED.** Unresolved legacy execution states block unsafe dispatch until admissible reconciliation; no force release or attestation exists (§5.5). Special treatment of synthetic development data would be a CB-05 weakening needing its own ADR and is not approved.
- **O6 — Handoff cost. APPROVED.** The additional durable writes (T3b, and best-effort T3c) and the `start` + `await_result` split are acceptable.

## 15. 0B-1 implementation boundaries and readiness

### 15.1 In 0B-1 (scripted port, no real runtime)

1. Domain: statuses unchanged; fence; transitions T1–T7; evidence basis set; configuration, provenance and verification types; three-valued comparison.
2. Store: conditional writes with the per-transition predicates of §4.1 (arbiter, `state_version`); fence, handoff and outcome columns and triggers (assistant publication requires an open fence, `handoff = STARTED` and epoch `0b`; closure irreversible; `NONE → STARTED` once; indeterminate requires closure for epoch `0b`; provenance immutable after dispatch); slot uniqueness among `in_flight`/`indeterminate` (NULL slots for legacy rows); derived legacy-blocker predicate `LB`; boot id; binding storage; retry intent table; configuration manifest store, binding history and adoption intent; one forward-only, checksummed migration with the LDT-17 behavior. (Schema sketch below is non-binding.)
3. Coordinator: supervisor registry; handoff gate; SP-1…SP-12; bounded slot wait; reconcile (startup, request-triggered, explicit command); retry; `adopt`.
4. Port: `describe/prepare/start/await_result/stop/probe`, control router (persisted-binding targeting), a scripted adapter and the fake adapter mapped to the new contract. The fake adapter does **not** resolve legacy rows (§5.5).
5. API surface: only the minimum to expose active/unresolved/blocked states and retry; no adoption route, no reconcile route (a development trigger only).
6. Tests: LDT-01…67 as above, including the golden-baseline replay and the migration stop/proceed cases.

### 15.2 Not in 0B-1

Any real runtime or model download; llama.cpp specifics; real external B3–B5 producers; authentication; submission fencing; streaming; cancel UI; persona/Memory/profile editor; adoption UI; multi-slot; output recovery from a runtime.

**Non-binding schema sketch.** Run: `closed_at`, `closure_reason`, `handoff`, `handoff_outcome`, `state_version`, `record_epoch`, `execution_boot_id`, `slot_id`, binding fields, provenance components (label/digest/verification each), `configuration_digest`, `termination_basis`, `completion_observed`, `kind`, `retry_of_run_id`; partial unique index on `slot_id` for `in_flight`/`indeterminate`; insert-only tables for effective configurations, conversation bindings, retry intents, adoption intents; triggers per 15.1.

### 15.3 Readiness

**Verdict (2026-10-12): `ACCEPTED` for Slice 0B-1 scope, against a scripted in-process runtime on the macOS development host.** Basis: the independent design review of revision 3.1 (`PASS_WITH_ADVISORIES`, both advisories corrected), the independent implementation review (`PASS` on the final diff), development-host verification (302 server tests, client suite, lint, strict types, loopback smoke) and the owner's ratification of O1–O6. **Not accepted and still open:** every `BLOCKED_BY_RUNTIME_EVIDENCE` row (real-runtime control, instance/process identity and exit verification, `late_delivery_excluded`, bounded `start`, faithful input and version reporting, disconnect behavior); a legacy-capable evidence producer; all `REQUIRED_BEFORE_FULL_V0` rows (Windows evidence, runtime containment SD-08/ADR-0011, the exclusive-instance mechanism behind A-1, submission fencing, authenticated reconcile, context budget evidence); U-1, U-2 and U-3 (contained, not eliminated); the NFR-08/LM-08 requirement wording; and any real-model, LAN or private-data use. **0B-2** is not started; its runtime-evidence plan is [2026-10-12-slice-0b2-runtime-evidence.md](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md) and needs the owner's separate model-download authorization and size cap before any download. Earlier verdicts: `DESIGN-READY PENDING INDEPENDENT REVIEW`, then `PROPOSED` pending implementation review.

## 16. Review record and validation

| Review | Record |
| --- | --- |
| Independent review of revision 1 | **BLOCKED**, seven findings (F1–F7). Addressed by this revision; the claim that revision 1 was "Accepted" was an author-review status only and has been withdrawn (ADRs set to Proposed). |
| Independent re-review of revision 2 | **BLOCKED.** F4, F6, F7 resolved; five corrections remained (F1 identity mismatch, F2 invocation versus closure, F3 multiple legacy unresolved executions, F5 legacy baseline, T7 predicate). Addressed by revision 3. |
| Independent re-review of revision 3 / 3.1 | **`PASS_WITH_ADVISORIES`**, no blocking finding (relayed 2026-10-12; original report not stored). Advisories: stale B6 text in ADR-0013 and the review handoff, and startup-replay wording in ADR-0014/§§11.3–11.4; both corrected in documentation (`4d99a86`). See the [review record](../reviews/slice-0b-1-independent-review-record.md). |
| Author checks of revision 3 (not independent) | (1) **Protocol model check** — an exhaustive interleaving of invoker, closer, crash and reconcile over the §4.4 steps (scratch script, not committed): 42 states, **0** violations of "no `start` initiated after closure", "B1 only if `start` was never called" and "B1 only with `handoff = NONE`"; a negative control that removes the gate requirement from the closer **does** reproduce the revision-2 violation (6 counterexamples), so the check is not vacuous. It models the in-process protocol only; it does not model U-1, U-2 or an adapter contract violation. (2) **Predicate check** — the §4.1 predicates were enumerated over all 47 valid (status, fence, handoff, outcome, epoch, message) states: every applicable transition lands in a valid state and every `indeterminate` state has a T7 exit. (3) **Golden baseline** captured twice from the real 0A code at `01e9f46`: byte-identical. (4) Resolved areas F4/F6/F7 compared against revision 2 by diff: only the edits listed in §0.3. |
| Author consistency review (revision 2) | Transition completeness: every status/fence pair has an entry or exit; no path settles without a basis; slot owner and release traced for T2–T7 and restart; publication/closure ordering checked against `execution.py`, `store.py` (`publish_response`, `settle_failed`, `recover_unsettled_runs`) and the `0001_initial.sql` triggers. Known deltas from 0A: `recover_unsettled_runs` marks every `in_flight` run `indeterminate` with no fence, binding or probe; `settle_failed` accepts `in_flight` with no basis; the trigger `assistant_message_requires_in_flight_run` does not consult closure; `ModelPort` has no binding/stop/probe; `ExecutionCoordinator` classifies any exception as `runtime_error`. All are 0B-1 work. |

**Validation of this deliverable (documentation only):** links and referenced IDs/sections checked (every relative link resolves, including the new evidence files); requirement and ADR wording checked for consistency with NFR-08, LM-08, V0-D03/D04, CB-05, LM-06, FR-15; no source, test, schema or dependency file changed; no runtime or unit test executed or claimed.

## 17. Slice 0B-1 implementation record (2026-10-11)

0B-1 implements §§1–12 against a **controlled, scripted, in-process** runtime (`ScriptedRuntime`, `InProcessRuntime`) with no external broker, launcher, transport or surviving runtime process; it proves nothing about any external runtime (0B-2 evidence gates). Record: [docs/implementation/slice-0b-1.md](../implementation/slice-0b-1.md). Deviations and discoveries relative to this document:

- **Three-valued-logic hole found by the parity test.** The first version of the settlement trigger compared nullable columns with `=`; for an unrecorded handoff outcome the admissibility test evaluated to NULL and the trigger did not fire, so *every* basis was accepted. The test that enumerates every (handoff, outcome, late-delivery) × basis combination against the pure domain rule exposed it; the trigger now uses `IS` comparisons. The store also checks admissibility in code, so the hole was a defense-in-depth failure, not a path used by the coordinator.
- **Reconcile also settles stranded `pending` runs** (a worker that could not confirm T3 and exited): a `pending` run with no live worker was never dispatched (B1). Startup alone is no longer the only trigger.
- **Refusal order at admission:** conversation busy first, then global blocks (legacy, quarantine), then configuration. Replays are resolved before any refusal.
- **Run order** in a conversation is insertion order, never `requested_at` (an instant must never decide order).
- **Slot waiting** is a bounded poll, not a condition variable.
- **Golden self-test** replays FX-01…FX-06 at startup; FX-07 (two interleaved conversations) is replayed by the test suite through the real store and coordinator.
- **The shipped default configuration is the baseline itself** (`whole-history@1` with its Slice 0A reference); there is one shipped configuration, and tests add a second to exercise upgrade, adoption and unavailability.
- **Default dataset file** is now `anonymous-0b1-dev.sqlite3`: 0B-1 execution tests use a clean database and never execute against a legacy one.
- **API surface:** a retry route and a `generation` block in `/health`; no adoption or reconcile route (application-level only).
- **Codex's 0A review probes** (`server/review_tests/`) are pinned to the 0A API (`recover_unsettled_runs`, `record_dispatch`) and are not part of the suite; 15 of 18 fail against 0B-1 for that reason alone.

### 17.1 Remediation after the static review of 0B-1 (2026-10-11)

Four findings were fixed without changing this design ([record](../implementation/slice-0b-1-remediation.md)). Implementation-level rules the design relies on, now explicit:

- **Ownership accounting (supports §4.8, B4).** Supervised work is counted by *reservation* before it can begin and released only after it has certainly ended; "not alive yet" is never "ended". Shutdown forbids new top-level reservations and waits for all of them; the guard is released only when none is outstanding. A thread start that cannot be shown not to have started keeps ownership (shutdown reports incomplete).
- **Pending admission (supports §5.3).** A `pending` run is *abandoned* only if it has no live worker **and** no admission is between its commit and its live mark; both facts are read under one process-wide admission gate. Applies identically to submissions, retries, startup and request-triggered reconcile.
- **Unknown settlement outcome (supports §9, T5/T7).** A commit of unknown outcome is resolved by reading the run and, if it did not land, applying the *same* evidence again (bounded); a run that still cannot be resolved stays as stored. Reconcile contains one run's storage fault so the others (and startup) proceed.
