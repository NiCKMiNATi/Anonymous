# ADR-0014 — Conversation configuration binding, provenance identity and cross-version continuity

**Status: Proposed (revision 3).** Revision 1 was recorded as "Accepted for Slice 0B planning" on author review only and contained only per-run version attribution. The first independent review required a conversation-level configuration binding (F5) and verifiable identities (F6). The second review accepted F6 as resolved and found F5's legacy handling insufficient (the baseline was compared only with another new implementation). The status stays **Proposed** until the revised design receives independent review and the owner confirms; Claude's own checks are not independent acceptance.
**Date:** 2026-10-11 (revision 3).

## Context

The owner requires that upgrading or changing Anonymous, a model, a runtime or a related component must not silently replace or mutate authoritative history, persistent memories, user-defined persona identity and speech conventions, formatting preferences, workflows, behavior/prompt configurations, provenance or historical state (NFR-08). Existing material covers data preservation (LM-01, ADR-0006, immutable records, forward-only checksummed migrations) and model/runtime identity (DATA-08, FR-12, NFR-02). Revision 1 recorded version *labels* per run. That attributes a run but does not (a) keep an existing conversation on the configuration it selected when the application is upgraded, nor (b) distinguish a verifiable identity from a descriptive string. Behavior across different models cannot be guaranteed identical. Memory, personas and a configuration editor are out of V0.

## Retained from accepted sources

LM-01, ADR-0006, FR-15, V0-D03 (no permanent duplicated prompts, no replay-perfect output). These are unchanged.

## Implementation status (Slice 0B-1)

Implemented for 0B-1: content-addressed manifests, append-only conversation bindings, explicit adoption (application level), startup binding of legacy conversations only after the golden replay, run provenance with verification states, and the golden self-test (see the [implementation record](../implementation/slice-0b-1.md)). The ADR **stays Proposed** pending independent review of the implementation.

## Alternatives considered

- **Per-run labels only (revision 1).** Rejected: an upgrade could silently change the configuration an existing conversation uses, and equal labels could be mistaken for equal environments.
- **Reference "current" configuration from conversations.** Rejected: silently rebinds history on upgrade.
- **Full prompt/configuration snapshot per run.** Rejected: exceeds V0-D03, stores private text again.
- **Build a persona/configuration subsystem now.** Out of scope; this ADR constrains it.
- **Bind legacy conversations in the migration, verified against a second new implementation (revision 2).** Rejected: proves nothing about continuity with Slice 0A.
- **Leave legacy 0A conversations unbound and always require adoption.** Considered; it blocks every old conversation until an adoption surface exists. Preferred instead: bind at startup **only after** the baseline reproduces the real 0A behavior; otherwise require adoption (O2).
- **Guarantee equivalent output across models.** Not achievable.

## Decision (revised proposal, revision 3)

1. **Three continuity classes** (data preservation, configuration preservation, non-guaranteed behavior) are stated in NFR-08.
2. **Effective configuration.** The context-construction and behavior configuration used to build a request is an immutable manifest identified by its **content digest** (insert-only, verified on read). V0 ships one (whole-history context, no system instructions, behavior explicitly `none`).
3. **Conversation binding.** Each conversation has a persisted, append-only binding to an effective configuration digest (`origin ∈ initial, adoption, legacy_baseline`). Creation binds the build's default. **Upgrading Anonymous never rebinds** an existing conversation.
4. **Explicit adoption.** A change is an owner-scoped, idempotent adoption intent that appends a binding; refused while a run in the conversation is unsettled; affects later runs only; reversible by adopting an earlier retained, executable configuration.
5. **Unavailable configuration.** If the pinned configuration cannot be executed or fails digest verification, generation and retry are refused visibly; nothing is substituted; history stays readable.
6. **Per-run provenance.** Each dispatched run records, in the dispatch write and immutably: application build, adapter, model artifact, runtime build, context configuration, behavior configuration (or explicit `none`), and the effective configuration digest. Never-dispatched runs record none.
7. **Label vs identity.** Every component records a human-readable **label**, an **identity** (digest or immutable reference) where available, and a **verification state**: `verified`, `asserted`, `unspecified`. Historical runs are **`unrecorded`**, which is not `unspecified`. Comparison is three-valued (`IDENTICAL_VERIFIED`, `CLAIMED_IDENTICAL`, `DIFFERENT`, `NOT_COMPARABLE`); labels, unspecified values or unrecorded values are never evidence of equivalence; environments are called equivalent only if all components are `IDENTICAL_VERIFIED`. Descriptive metadata is retained even when identity is unverifiable. No historical record is required to acquire data never captured.
8. **Legacy 0A conversations (revised).** The migration binds nothing and asserts no equivalence. The reference is the **actual Slice 0A implementation at commit `01e9f46`**: golden fixtures of the constructed view (message roles, authoritative order, exact content, whole-history construction; 0A applied no system instructions, settings, budget or behavior profile) were captured by running the real 0A code ([evidence](../evidence/ld-04-slice-0a-context-golden.md), sha256 pinned). At startup the shipped baseline `E0` replays every fixture and must reproduce each recorded view byte-for-byte; only then is one `legacy_baseline` binding appended per legacy conversation, recording the fixture digest. If equivalence cannot be established, nothing is bound: history stays readable, generation is refused visibly, and explicit adoption is required. If `E0` later fails the check it becomes unavailable and the same blocked behavior applies. Legacy runs stay `unrecorded`; no persona, model, runtime or version is fabricated. The fixtures pin the constructed view only.
9. **User-owned configuration** (persona, preferences, workflows, behavior profiles) is not designed now. When introduced it must be persistent user data, change only by explicit action, be versioned and retained, never be overwritten by application defaults, and be referenced by version from each run and conversation binding.
10. **No behavioral-equivalence claim** between models or runtime versions. A candidate domain invariant INV-016 is proposed only in the design; the domain model is unchanged pending owner approval.

## Consequences

Additive persistence and composition work in 0B-1: golden-fixture replay (test and startup self-test), manifest store, binding history, adoption intent, provenance components with verification states, a catalog distinguishing retained from executable configurations. No Memory, persona or configuration editor is built, and no adoption route or UI. Reproducibility stays attribution-level (V0-D03). Which digests real adapters can verify (model file, runtime binary) depends on runtime evidence; until then those components may be `asserted` or `unspecified`, which is recorded honestly. Failing to change a configuration's digest when its behavior changes is a process risk mitigated by the golden-view test, not eliminated. Retaining old configurations has a (small) storage and maintenance cost.

## Matters requiring later runtime evidence

Availability of model-artifact and runtime-build digests and version reports from the chosen runtime; soundness of any cached-digest staleness check.

## Owner-facing items needing confirmation

O2 (startup binding of legacy conversations to `E0` after the golden check, versus always requiring adoption) and O3 (sends refused before saving while configuration-blocked). See [design §14](../design/ld-04-execution-lifecycle.md).

## Affected documents

[Requirements](../02-requirements.md) (NFR-08 revised; no existing requirement changed); [V0 scope](../03-v0-scope.md) §6 and V0-D03; [architecture](../04-architecture.md) §11; [data model](../05-data-model.md) §7 (LM-08), §15 (LD-13), §16; [LD-04 design](../design/ld-04-execution-lifecycle.md) §§11–12 and the [golden baseline evidence](../evidence/ld-04-slice-0a-context-golden.md); ADR-0003, ADR-0006. FR-15 and the domain model are unchanged.
