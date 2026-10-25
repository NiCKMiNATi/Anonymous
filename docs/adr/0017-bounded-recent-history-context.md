# ADR-0017 — Bounded recent-history context (`bounded-recent-history@1`)

**Status: Accepted** by the owner on 2026-10-25, for the v0.1 development build only. The owner approved the design direction and authorized the implementation on the same date; acceptance followed review of the implementation handoff (the code is verified on synthetic data only, see the [implementation record](../implementation/v0-1-external-runtime-dev.md)). Acceptance covers the decisions below and their dev-build implementation; it does not resolve the deferred questions named under "Scope" and does not accept any real-model verification. Scope: the v0.1 development build only (the dev-only external llama.cpp adapter of [ADR-0015](0015-dev-only-external-llama-runtime-adapter.md) and the fake default). No migration, no schema change.
**Date:** 2026-10-25.

## Context

`whole-history@1` sends the entire committed history through the triggering user message and relies on the worker's character check to refuse anything over the runtime's `max_input_chars`. With the real runtime that limit is 1400 characters (a proxy for the pinned 2048-token window, [ADR-0015](0015-dev-only-external-llama-runtime-adapter.md), joint budget in `config.llama_budget_fits`). Replies lengthen history ([ADR-0016](0016-visibly-truncated-assistant-responses.md) says so explicitly), so after a few turns every send is refused before dispatch (`context_exceeds_capacity`) and the conversation is no longer usable although nothing is wrong with the new message.

Accepted sources already fix the semantics: when the whole conversation does not fit, older content may be omitted, source history is retained, the user is informed that the model did not receive it, the newest message is never silently cut and an impossible input is refused visibly ([03-v0-scope.md](../03-v0-scope.md) V0-D01, V0-AC-08; [04-architecture.md](../04-architecture.md) Context Builder boundary; [05-data-model.md](../05-data-model.md) §6, the fixed input boundary and selected-message associations; INV-015). They leave "exact budget calculation and earlier-message selection" as design work (Q-12, Q-19, LD-06). [LD-04 §2 C6](../design/ld-04-execution-lifecycle.md) says per-message selection evidence arrives with LD-06, and ADR-0016 point 8 requires future bounded selection to treat `completeness` as metadata, count it against the budget and record in provenance that a truncated message was included as is.

[ADR-0014](0014-execution-configuration-provenance-and-continuity.md) fixes how a context change is made: a context construction is an immutable manifest identified by its digest; `whole-history@1` is pinned to the Slice 0A golden replay; a conversation is bound to one digest and an upgrade never rebinds it; a new default applies to new conversations only; changes to existing conversations need explicit adoption.

## Alternatives considered

- **Change `whole-history@1` in place.** Rejected: it would silently change the context of every bound conversation and invalidate the golden-pinned baseline (ADR-0014 decisions 2–4, 8).
- **Truncate or clip individual messages, or summarize older ones.** Rejected: splitting, rewriting and summaries are out of scope; derived text must not replace source history (INV-006, INV-015).
- **Skip an older message that does not fit and keep smaller, still older ones.** Rejected: it builds a non-contiguous view that omits the middle of a conversation and is harder to explain and to reproduce from two ids.
- **Store the selection in a new table or columns.** Rejected for now: `provenance_json` is already written in the T3 dispatch transaction and is immutable afterwards; an optional key needs no migration and leaves older rows byte-exact.
- **Add an adoption route so existing conversations get the new context.** Rejected here: ADR-0014 did not accept an adoption route or UI. Start a new conversation instead.
- **Count tokens.** Not available from the runtime for a prompt before dispatch; out of scope (see decision 12).

## Decision

1. **`whole-history@1` is preserved**, with its digest, its golden baseline (FX-01–FX-06 replay at startup) and its behavior, including the `context_exceeds_capacity` refusal. `ContextBuilder.build` is unchanged.
2. **`bounded-recent-history@1` is a new shipped configuration** (manifest `context_construction = {id: bounded-recent-history, version: 1}`, no baseline reference, `behavior = none`) with its own digest, executable alongside `whole-history@1`. It is not golden-checked and never binds legacy conversations.
3. **It is the default for new conversations only.** The default digest is chosen at the composition root; `ConversationService.create_conversation` binds it atomically as before.
4. **No existing conversation is rebound.** A conversation bound to `whole-history@1` (including every legacy one) stays on it. The builder is chosen from the conversation's bound digest through the catalog, never from the application default. Adoption stays application-level only, as in ADR-0014.
5. **Selection is deterministic and contiguous**, a pure function of (the committed history through the triggering message, `limit_chars`). `limit_chars` is the runtime's declared `max_input_chars`; `None` (fake and in-process runtimes) selects the whole history, so their behavior is unchanged.
6. **The triggering user message is always selected.** If it alone exceeds the limit the view still contains it and the worker's existing capacity check, the final guard for every configuration, refuses before dispatch.
7. **Selection stops at the first older message that does not fit.** Messages are added newest-first while the running character total stays ≤ the limit; a smaller, older message beyond a misfit is never reached.
8. **Messages are never split, summarized, rewritten or deleted.** The view carries role and content only, verbatim; a truncated assistant reply is sent as is with no marker (ADR-0016 point 8).
9. **The complete history stays in SQLite** and in the conversation read API. The selection only decides what one model request contains.
10. **Selection provenance is recorded at T3.** `ExecutionProvenance` gains an optional `context_selection` written in the dispatch transaction inside the existing immutable `provenance_json`: `first_message_id`, `first_position`, `selected_count`, `omitted_count`, `selected_chars`, `limit_chars`, `measure = "characters"`, `truncated_included_count`. Ids and counts only, no content. With the run's triggering message these identify the exact view from immutable history. The key is omitted when absent, so older rows and whole-history runs serialize exactly as before; absence means *unrecorded*, never "nothing omitted". A run refused before dispatch has no provenance.
11. **Omission is displayed.** `RunDto.context` exposes the persisted selection; the client shows, beside the assistant reply of the producing run only and only when `omitted_count > 0`: "The model did not receive the N earliest messages. They remain saved above." (singular for one). It is driven by persisted data, so it survives reload, replay and restart. A refusal because the latest message alone is too long uses a new fixed failure code `message_exceeds_capacity` ("This message is longer than the model can accept; nothing was sent."), a B1 failure: no quarantine, the message stays saved.
12. **Characters are a proxy, not token accounting.** `limit_chars` bounds the character sum of message contents; it ignores chat-template tokens, multi-byte text and the model's tokenizer. It does not prove that a prompt fits the 2048-token window; the joint budget of `llama_budget_fits` and the ADR-0015 residual (a real overflow is an HTTP error or a `length` finish) are unchanged.

## Scope: what this settles and what it does not

This settles only the **narrow v0.1 development selection policy** above. It does **not** resolve Q-12, Q-19, LD-06 or template/token accounting; it does not select by turn, relevance, importance or recency of use; it adds no Memory, retrieval, summary, persona or branching; and it does not change what any other component records. Future turn-aware selection (for example starting the window at a user turn, or keeping a question with its answer) would be a new configuration version and a new decision.

## Consequences

- A conversation stays usable as it grows: each request fits `max_input_chars` and the newest message is never cut. The model no longer sees older turns, and the user is told.
- A new conversation's context label is `bounded-recent-history@1` (digest `sha256:…` of its manifest); runs of existing conversations keep `whole-history@1`. Comparison of environments is unaffected (ADR-0014 decision 7).
- The window may start with an assistant message, because messages are never reordered or skipped; a model may answer such a view less coherently. This is a known limitation.
- An oversized message permanently ends the window for later turns at that point (the next window begins after it); the oversized message stays saved and visible.
- A retry computes its selection again over the same frontier; the failed attempt recorded none because it never dispatched.
- Existing conversations do not get the feature. The owner starts a new conversation; an adoption route would need its own decision.
- No change to T4, truncation (ADR-0016), quarantine (ADR-0015), runtime ownership, the fake-model default or PRIVATE-mode boundaries. The selection is computed from local SQLite only and sends nothing anywhere.

## Preserved invariants

ADR-0014 (immutable manifests, conversation binding never changed by an upgrade, per-run provenance written in T3, absent means unrecorded), ADR-0015 (adapter, fail-closed quarantine and capacity refusal before dispatch), ADR-0016 (completeness is message metadata; verbatim replay; the marker never enters the model input), INV-006 and INV-015 (the model request is a constructed view; source history is retained).

## Affected documents

[Implementation record](../implementation/v0-1-external-runtime-dev.md); [ExecPlan](../../.agent/plans/2026-10-25-v0-1-bounded-recent-context.md); [LD-04 §2 C6](../design/ld-04-execution-lifecycle.md) and [05-data-model.md](../05-data-model.md) (LD-06 row) and [03-v0-scope.md](../03-v0-scope.md) (Q-12 row) as pointers only. ADR-0014, ADR-0015 and ADR-0016 are not edited.
