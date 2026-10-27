# v0.1 — bounded recent-history context (ADR-0017)

## 1. Title, status, and purpose

**Status (current, 2026-10-27): IMPLEMENTED and committed at `efad77c`; [ADR-0017](../../docs/adr/0017-bounded-recent-history-context.md) is Accepted by the owner (2026-10-25); development only. One attended real-Qwen smoke of this behavior ran on 2026-10-25 and is recorded as INCONCLUSIVE (restart persistence not verified); see [the smoke evidence](../../docs/evidence/v0-1-adr-0017-bounded-context-smoke.md).** The owner approved the design and authorized the implementation on 2026-10-25 and handles all Git operations.

*Status at the implementation handoff (2026-10-25, historical, superseded above):* IMPLEMENTED and verified on synthetic data (fake, scripted and fake-loopback runtimes only); ADR-0017 Accepted; development only; nothing run against a real model.

**Problem.** With the real runtime the input cap is 1400 characters. `whole-history@1` sends everything, so after a few turns (and sooner with long or truncated replies, ADR-0016) every send is refused before dispatch (`context_exceeds_capacity`) and the conversation is unusable.

**Outcome.** New conversations are bound to `bounded-recent-history@1`: each request carries the newest contiguous messages that fit the runtime's character limit, always including the latest user message; every message stays saved; the run records what was selected; the user sees when earlier messages were not sent.

## 2. Repository context

- [ADR-0014](../../docs/adr/0014-execution-configuration-provenance-and-continuity.md): context construction is an immutable, content-addressed manifest; `whole-history@1` is pinned to the Slice 0A golden replay; a conversation's binding is never changed by an upgrade; run provenance is written in T3 and is immutable.
- Existing path: `ConversationService` → `ExecutionCoordinator` → `RunWorker._execute` (`builder.build…`, then the character check against `RuntimePort.describe().max_input_chars`) → T3 `authorize_dispatch` writes `provenance_json`. Context code: `application/context.py`; catalog: `application/configuration.py`.
- Read first: [AGENTS.md](../../AGENTS.md), [project definition](../../docs/00-project-definition.md), [domain model](../../docs/01-domain-model.md) (INV-006, INV-015), [03-v0-scope.md](../../docs/03-v0-scope.md) V0-D01/V0-AC-08, [04-architecture.md](../../docs/04-architecture.md) Context Builder boundary, [05-data-model.md](../../docs/05-data-model.md) §6, ADR-0015, ADR-0016.

## 3. Requirements and acceptance criteria

Selection: deterministic, contiguous, newest-first within `max_input_chars`; the trigger is always selected; stop at the first older message that does not fit; never split, summarize, rewrite or delete; complete history stays in SQLite and the read API. Provenance: `context_selection` in `provenance_json` at T3, ids and counts only, absent key leaves older serialization byte-exact. API/UI: `RunDto.context`; notice beside the producing run's reply only when `omitted_count > 0`; fixed B1 message when the latest message alone is too long. Existing conversations, fake-model behavior, T4, truncation, quarantine and external-runtime safety unchanged.

**Non-goals:** summaries, Memory, retrieval, personas, branching, streaming, cancellation, token accounting, an adoption route or UI, rebinding existing conversations, any real-model run (by this implementation slice; the later attended smoke is a separately authorized activity, section 8), any change to frozen E1/E2-B/E3 evidence, any resolution of LD-06 / Q-12 / Q-19.

## 4. Constraints and open questions

Constraints: PRIVATE data stays local (the selection reads SQLite only and adds nothing to logs or provenance beyond ids and counts); modular application, no new dependency; additive only, **no schema migration** (the preserved smoke dataset is never opened).

Open, not decided here:
- Token/template accounting: characters remain a proxy; a real overflow still ends in an HTTP error or a `length` finish and quarantines (ADR-0015 residual). Blocks nothing in this slice; blocks any claim that a prompt fits.
- Turn-aware selection (start the window at a user turn, keep a question with its answer): future configuration version.
- Existing conversations cannot adopt the new context until an adoption route is decided (ADR-0014 did not accept one).
- LD-06 / Q-12 / Q-19 stay open. **Q3** (recovery from a quarantined dataset) and the other LD-04 evidence questions (every row `BLOCKED_BY_RUNTIME_EVIDENCE`) are untouched.

## 5. Affected components and intended approach

`domain/provenance.py` (`ContextSelection`, optional field on `ExecutionProvenance`), `application/context.py` (`ContextView`, `select_recent`, `BoundedRecentContextBuilder`, `build_view` on both builders; `ContextBuilder.build` unchanged), `application/configuration.py` (second shipped manifest, not golden-checked; `default_configuration_digest`), `composition.py` (default digest chosen at the composition root only), `application/worker.py` (limit passed to the builder; selection into provenance; refusal code by view kind), `application/failures.py` (`message_exceeds_capacity`), `api/schemas.py` (`ContextSelectionDto`, `RunDto.context`), client `api/types.ts`, `components/MessageItem.tsx`. The builder is chosen from the conversation's bound digest by the existing catalog.

## 6. Work sequence

1. Verify a clean tree (HEAD `f3b17c8`). 2. ADR-0017 (Proposed, later Accepted). 3. Domain type and provenance serialization. 4. Builders and configuration. 5. Worker, failure code, composition default. 6. DTO and client. 7. Tests (unit, application, API, client), mutation checks. 8. Static checks and full suites. 9. Documentation. Recovery: all edits are in the working tree; the owner commits.

## 7. Validation strategy

Server (from `server/`, using `.venv/bin/…` because `uv run` cannot rebuild the project offline): `pytest`, `ruff check`, `ruff format --check`, `mypy` (strict). Client (from `client/`): `npx vitest run`, `npx tsc --noEmit`, `npm run build`.

| Criterion | Where tested |
|---|---|
| Fit-all, exact boundary, one character over | `tests/unit/test_bounded_context.py`, `tests/application/test_bounded_context.py` |
| Contiguous suffix, order, roles; single oversized older message | unit + application tests |
| Latest message always included when it fits; oversized trigger refused before dispatch, no quarantine, message saved | application + API tests |
| Full history retained in SQLite and the detail API | application + API tests |
| Whole-history conversations unchanged; new ones use the new digest; application default | `test_new_conversations_bind_…`, `test_the_application_default_…`, API test |
| Fake runtime with no limit unchanged | `test_a_fake_runtime_without_a_limit_…` |
| Immutable provenance; older rows without the key; byte-exact legacy serialization | unit provenance tests, `test_the_selection_is_recorded_at_dispatch_and_is_immutable` |
| Truncated reply verbatim and counted | unit + `test_a_truncated_reply_in_the_window_…` (fake loopback llama) |
| Retry and replay | `test_a_retry_records_its_own_…`, API restart/replay test |
| API and UI omission notice incl. refetch, replay, absent | `tests/api/test_bounded_context_api.py`, `client/src/omission.test.tsx` |
| Existing T4, truncation, quarantine, external safety | the unchanged existing suites |

## 8. Progress

- [x] 2026-10-25 Tree verified clean at `f3b17c8` (after the owner committed the evidence correction).
- [x] 2026-10-25 ADR-0017 written (Proposed).
- [x] 2026-10-25 Implementation (server and client) and tests written.
- [x] 2026-10-25 Mutation checks: a skip-around selection fails 3 tests; dropping the selection from provenance fails 12.
- [x] 2026-10-25 Static checks and full suites run — see §11 for the results.
- [x] 2026-10-25 Documentation.
- [x] 2026-10-25 Owner accepted ADR-0017 (documentation-only status change; no code or test change).
- [x] 2026-10-25 Owner local commit: `efad77c` "feat: add bounded recent-history context" (confirmed at HEAD on 2026-10-27, tree clean).
- [x] 2026-10-25 Separately authorized attended real-Qwen smoke, partially executed: one unexpected two-character opening message was answered; the owner accepted continuing with M1 to M3 only; M3 received a real reply and the owner's screenshot showed the omission notice for three earliest messages; shell tooling then failed, so the final live checkpoint and the planned restart-persistence comparison did not happen; the owner performed an identity-verified shutdown.
- [x] 2026-10-27 Read-only postmortem of the retained dataset (nothing written, launched or restarted), then evidence closure: [smoke evidence](../../docs/evidence/v0-1-adr-0017-bounded-context-smoke.md), overall **INCONCLUSIVE**.
- [ ] Future: turn-aware selection; token accounting; an adoption decision for existing conversations; a further separately authorized check of restart persistence and the rendered notice (none is authorized).

## 9. Discoveries

- Provenance already holds a per-run immutable JSON written in T3, so the selection needed no migration; the key is omitted when absent so older rows and whole-history runs serialize exactly as before.
- `ConfigurationService.startup` binds legacy conversations for every golden-checked configuration; the new one is therefore not golden-checked, and `whole-history@1` stays first.
- `shipped_configurations()` order and the catalog default are separate: the default is passed only by the composition root, so the existing fixtures that build a catalog directly keep `whole-history@1` and exercise the unchanged baseline path.
- The worker's capacity check stays the final guard for both builders; the new code `message_exceeds_capacity` is used only when a bounded view's trigger alone is too long, because the old text ("The conversation is longer…") would be wrong there.

## 10. Decision log

2026-10-25 — Owner approved the bounded recent-window design and authorized implementation under ADR-0017 (Proposed at the time). Decisions within that authority: a new configuration and digest rather than changing `whole-history@1`; default for new conversations only; no adoption route; selection recorded in the existing `provenance_json` (alternatives: new columns or table, rejected as unnecessary); singular wording of the notice for exactly one message; the window may begin with an assistant message (turn alignment deferred). Status: ADR-0017 accepted by the owner on 2026-10-25.

2026-10-27 — Owner accepted the read-only postmortem of the 2026-10-25 smoke, set its final overall verdict to INCONCLUSIVE (the restart-persistence comparison was not performed, so the original full PASS criteria were not met) and authorized documentation-only evidence closure. This is not an architectural decision; ADR-0017 stays Accepted and no decision, classification or open question changed.

## 11. Final outcome

**Implemented as specified; see [the implementation record](../../docs/implementation/v0-1-external-runtime-dev.md#adr-0017-bounded-recent-history-context-2026-10-25-implemented-and-verified-with-synthetic-data-only) for what was run and the results.** *At the implementation handoff (2026-10-25, historical):* not done: any real-model run, any acceptance of ADR-0017, any change to existing conversations. Remaining limitations are listed in ADR-0017 and the implementation record.

**Update 2026-10-27 (smoke outcome).** Acceptance happened on 2026-10-25, and the implementation was committed at `efad77c`. The attended real-Qwen smoke is **INCONCLUSIVE**, recorded in [the smoke evidence](../../docs/evidence/v0-1-adr-0017-bounded-context-smoke.md). Narrower findings, observed once: four succeeded real runs in one `bounded-recent-history@1` conversation (the first, an unexpected two-character opening message, outside the protocol); the M3 run (position 7) selected positions 4 to 7 (4 messages, 1,060 of 1,400 characters, 3 omitted), and the stored T3 selection equals an independent recomputation for all four runs; all 8 messages, 4 submissions and 4 runs are retained, with integrity and foreign-key checks clean, no retries and no indeterminate run (quarantine absence inferred from persisted state); pinned model and runtime recorded as `verified`; the runtime has been shut down with no process, listener or launch record left. The omission notice is owner-observed only. **Not verified:** restart persistence (the reason the smoke is not PASS), the pre-run state, the rendered notice, the live `/health`, and prompt fidelity. No change to ADR-0017, LD-04 classifications or any open question.
