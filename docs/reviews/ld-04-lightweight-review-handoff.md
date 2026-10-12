# LD-04 design — Codex lightweight review handoff (revision 3)

**Status:** Prepared 2026-10-11 for selective independent **static** review. Revision 2 was returned BLOCKED (F4, F6, F7 resolved; five corrections open). **No independent review of revision 3 has been performed**; the author's checks are not acceptance. Read-only: do not run tests, do not edit files. Report findings with severity, section and a concrete failure scenario.

**Revision 3.1 and the 0B-1 implementation.** A later task removed B6, made single-process ownership concrete, withdrew adapter-declared legacy settlement and implemented 0B-1 against a scripted in-process runtime. Review that work with [slice-0b-1-code-review-handoff.md](slice-0b-1-code-review-handoff.md); the hashes below were last recomputed after those edits.

**Git references.** Base `01e9f46` (HEAD of `main`). Head = the **uncommitted working tree** on top of it. Tracked files: `git diff 01e9f46 -- <file>`; untracked files are read directly. sha256 of every reviewed file is at the end.

## Exact changed files

- Rewritten/new (untracked): `docs/design/ld-04-execution-lifecycle.md` (revision 3), `docs/adr/0013-execution-attempt-lifecycle-and-release-evidence.md` and `docs/adr/0014-execution-configuration-provenance-and-continuity.md` (both **Proposed**), `.agent/plans/2026-10-11-ld-04-lifecycle-and-continuity.md`, `docs/reviews/ld-04-lightweight-review-handoff.md`, **new evidence** `docs/evidence/ld-04-slice-0a-context-golden.md` and `docs/evidence/ld-04-slice-0a-context-golden.json`.
- Tracked, modified: `docs/02-requirements.md` (NFR-08, one sentence on legacy binding), `docs/03-v0-scope.md`, `docs/04-architecture.md`, `docs/05-data-model.md` (LM-08 sentence; LD-04 row → revision 3), `docs/implementation/slice-0a.md` (gate note).
- No source, test, schema, migration or dependency file changed.

## The five findings and where they are resolved

| Finding | Resolution | Design § | Scenarios |
| --- | --- | --- | --- |
| F1 identity mismatch | `runtime_identity_mismatch` removed as a basis; instance mismatch ⇒ reject, fence, probe the **persisted** binding only (R-5), quarantine unless independent evidence; model mismatch from the verified instance is B3 | 1.3, 3.4, 4.5, 6.1 | LDT-43–45 |
| F2 invocation vs closure | Handoff gate G + durable T3b marker + closure only under G + single-use invocation right; `generate` → `start`/`await_result`; traces H-1…H-9; proof; U-1/U-2/U-3 named | 4 | LDT-46–56 |
| F3 multiple legacy unresolved runs | Class E blockers; derived global dispatch block, no slot record; legacy rows untouched; per-blocker evidence-only resolution; migration stops only on structural inconsistency | 5.1, 5.5 | LDT-17, 60–64 |
| F5 legacy configuration baseline | Golden fixtures captured from the **real 0A code at `01e9f46`**; `E0` self-test; binding at startup only after equivalence; else unbound + readable + explicit adoption | 11.3–11.4, evidence record | LDT-18, 38, 65–67 |
| T7 predicate | Per-transition source predicates + `state_version`; T7 sources `indeterminate`; handoff state limits admissible bases; idempotent/concurrent T7 | 3.2, 4.1 | LDT-57–59 |

## Implementation-relevant guarantees (what 0B-1 must make true)

1. `start` is called only by the holder of the single-use invocation right, only after T3b is durable, only under G, at most once ever; a closure of an open fence commits only under G; T3b requires an open fence. ⇒ no `start` initiated after a closure commits.
2. Every transition is one conditional write on its own source predicate (§4.1 table); T7 has source `indeterminate`; repeated T7 returns `SETTLED`.
3. B1 only when durable `handoff = NONE`/`NOT_CALLED`; after an `UNKNOWN`/unrecorded handoff only B3/B4 (B5 only with declared `late_delivery_excluded`; B6 was removed in revision 3.1); no basis ⇒ quarantine.
4. Legacy rows are never modified by migration; `LB` blocks all dispatch; no slot record is created for them.
5. No database transaction is held during `start`, `await_result`, `stop` or `probe`; no atomicity with external effects is claimed.

## Specific remaining risks

- **U-1** delayed delivery after an `UNKNOWN` handoff is contained, not prevented. **U-2** a hung handoff leaves the run open until restart. **U-3** relies on A-1 (single process) backed only by the development `InstanceGuard`.
- No real producer exists for B3–B5 (B6 removed) or for legacy evidence; existing 0A datasets with unresolved runs stay dispatch-blocked (O5). Owner-facing O1–O6 are unconfirmed.
- The fixtures pin the constructed view only. The protocol model check and predicate check were author scratch scripts (not committed) and cover only the in-process protocol.

## Claims Codex must challenge

1. **The proof in §4.6** (no `start` after closure): is there any interleaving, crash point or adapter behavior within A-1…A-4 where `start` is initiated after a closure commits? Is "closer needs G" enforceable (A-4) and does it deadlock with the invoker's DB writes?
2. **A closer that cannot get G does not commit (U-2):** can a run then be stuck with an expired deadline and no recovery short of restart? Is that acceptable against CB-05/LM-06?
3. **Handoff-state ⇒ admissible-basis table (§1.3):** is B3 sound for `UNKNOWN` handoff? Is B5's restriction sufficient? Can B1 ever be claimed wrongly (T3b in doubt, NOT_CALLED written by the coordinator)?
4. **T7/T5 predicates (§4.1):** any missing source state, spurious `STALE_VERSION` livelock, or case where a legacy-epoch run is mishandled (implicit closed fence, no handoff)?
5. **Legacy handling (§5.5):** is a derived global block without any slot record adequate under "no new dispatch while any legacy execution could still be active"? Is refusing label-based resolution too strict, or is it correctly consistent with F6? Do the migration stop rules wrongly stop or wrongly proceed?
6. **Baseline evidence (§11.3–11.4, evidence record):** does the fixture set actually pin everything 0A applied (check `context.py`, `execution.py`, `ports/model.py` at `01e9f46`)? Is startup-time binding after a self-test acceptable vs migration-time binding? Re-run the capture from `git archive 01e9f46` and compare digests.
7. **Resolved areas not reopened (§0.3):** confirm F4/F6/F7 text changed only as listed; the `start`/`await_result` split does not weaken instance-exact control or provenance rules.
8. **Consistency:** transition and basis names across design, ADR-0013/0014, NFR-08/LM-08 and the scenarios; stale statements about operator attestation, fake-adapter legacy resolution or `in_flight`-only settlement.

## Not in scope

Runtime-specific behavior, Windows, UI/API route design, FR-15, authentication, Memory, persona design.

## Content hashes (sha256, working tree, excluding this handoff)

```text
61b163f016e895e5a01d390f6826b9c563a852033cce16d9ad5eb1c82ef36e93  docs/design/ld-04-execution-lifecycle.md
2652872ad11917add134faace2e4f96c9068f6d16855af176c380ba9ea73e9ce  docs/adr/0013-execution-attempt-lifecycle-and-release-evidence.md
fc15361a6395fdbf2e9dfc20cb8163031ec703a9e98ae12831a6fb83fe1b6c95  docs/adr/0014-execution-configuration-provenance-and-continuity.md
21e5202a67d35b876b72a1d72fbaab5e2d87c4503b85397476574d778dfcb846  .agent/plans/2026-10-11-ld-04-lifecycle-and-continuity.md
4f6dc16862adab4acb9481a363dbfd21aaaaef888e2ec0dbbc2ee1735b1e5cb3  docs/evidence/ld-04-slice-0a-context-golden.md
afb16c8821f80c5ce4eaf6aee328fb772ee7057e6b62c8d810fdab3e5e2d5bf1  docs/evidence/ld-04-slice-0a-context-golden.json
9fe6a81b55b980a3875e2fee92743ca571510f896965e0d9342db25d91f9a5f5  docs/02-requirements.md
adf1c2d1e6d7b01223871977f7628325f6d22baf4a83823499a0025f2ff8c11e  docs/03-v0-scope.md
7332d8d7ed79446b4784225bf77842751faa446d204b3d1153b76485d3d267c6  docs/04-architecture.md
851aa05932882db907f377bdaac302f2af2170e632960c0d82beffba9bbbfdbb  docs/05-data-model.md
260c7c3d3b6d3ca7f422a2928fd7015c28d5b65af50da9907dd98fe0f25281b5  docs/implementation/slice-0a.md
```
