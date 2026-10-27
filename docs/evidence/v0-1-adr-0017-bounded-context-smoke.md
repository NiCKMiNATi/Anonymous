# v0.1 — ADR-0017 bounded recent-history real-Qwen smoke (ADR-0015/0017, n=1, macOS)

**Status: INCONCLUSIVE (owner decision, 2026-10-27).** The original full PASS criteria were **not met** because the planned restart-persistence comparison was never performed. One attended runtime lifetime, one fresh dataset at schema v3, synthetic data only, loopback only, repository HEAD `efad77c` (owner's report for the run; verified unchanged at the postmortem and at this closure). Documentation only: no source, test, ADR decision text, LD-04 classification or frozen E1/E2-B/E3 evidence was changed by this record. LD-04 runtime-evidence rows stay `BLOCKED_BY_RUNTIME_EVIDENCE` and Slice 0B-2 is not accepted by it.
**Plan:** [ADR-0017 ExecPlan](../../.agent/plans/2026-10-25-v0-1-bounded-recent-context.md). **Decisions:** [ADR-0015](../adr/0015-dev-only-external-llama-runtime-adapter.md), [ADR-0016](../adr/0016-visibly-truncated-assistant-responses.md), [ADR-0017](../adr/0017-bounded-recent-history-context.md) (stays Accepted). **Implementation:** [implementation record](../implementation/v0-1-external-runtime-dev.md). **Earlier smokes:** [first real-Qwen smoke](v0-1-first-real-qwen-smoke.md), [ADR-0016 truncation smoke](v0-1-adr-0016-truncation-smoke.md) (both unchanged). **Pins relied on:** [E2-B](v0-0b2-e2b-first-inference-run.md), [E3](v0-0b2-e3-first-pilot-run.md) (unchanged).

**Provenance of this record.** Unlike the earlier smokes, **no sanitized local record was written during or right after the run**: the shell tooling failed before the final live checkpoint (section 2). This record is built from (a) a **read-only postmortem by the assistant on 2026-10-27**, after the run and after the runtime had been shut down, of the retained local dataset (opened with SQLite `mode=ro&immutable=1`; nothing was written, migrated, launched or restarted), and (b) the owner's reports, each marked. The database, its settled copy, the raw runtime log, every prompt and every reply stay local and are not reproduced here; message **content was never read** by the assistant (only roles, positions and character counts), and per-message content hashes are deliberately omitted. The live database and the read-only settled copy kept by the owner are byte-identical (SHA-256 prefix `ae4301f2`, unchanged by the postmortem); the runtime log has SHA-256 prefix `654a8058`. No screenshots were retained where the assistant could find them.

**Evidence classes used below.** **[V]** directly verified by the assistant in the postmortem (database, log, process and listener state). **[O]** reported or observed by the owner and not independently verifiable from the retained artifacts. **[I]** an inference supported by retained artifacts. **[U]** unverified or not available.

**Verdict in one line.** One owner-attended session with the real pinned Qwen3-4B-Q4_K_M under llama.cpp b11440 completed four successful runs in one `bounded-recent-history@1` conversation; the window slid from "everything fits" to a window that omitted the three earliest messages, the immutable T3 selection provenance equals an independent recomputation for all four runs, the complete history is retained, and nothing failed or was left indeterminate; but the restart-persistence comparison was not done, the pre-run and in-run checkpoints are not documented, and the omission notice is known only from the owner's screenshot, so the smoke is **INCONCLUSIVE**, not PASS. One session, not a reliability claim.

## 1. Authorization and the criteria that were not met

The owner authorized one attended real-Qwen smoke of ADR-0017 on 2026-10-25, on a fresh synthetic dataset, with a planned comparison of the persisted state across a server restart. The original full PASS criteria were **not met** because **restart persistence was not verified** (section 7). The owner accepted the read-only postmortem and set the final overall verdict to INCONCLUSIVE on 2026-10-27. The narrower successful observations (sections 4 to 6) are recorded separately and do not change that verdict.

## 2. Protocol deviations (stated plainly)

1. **Unexpected two-character opening message [V, with [O] context].** The conversation's first user message (position 1) is two characters long and was answered by the model (run 1). It was not part of the authorized protocol; the owner reports it as unexpected. Its text was not inspected and the channel through which it was submitted is not established by the retained artifacts.
2. **Owner-authorized continuation with M1 to M3 only [O].** After the opening message the owner explicitly accepted continuing with three further messages, called M1, M2 and M3 (positions 3, 5 and 7: 455, 488 and 481 characters). **No M4 or M5 exists [V]:** the database holds exactly 4 runs, 4 submissions and 8 messages.
3. **Prompt fidelity not independently verified [U].** Only lengths were read. Whether M1 to M3 equal the authorized synthetic text was not established, and neither was the opening message's origin.
4. **Shell-tool failure interrupted the final live checkpoint [O].** The assistant's shell tooling failed, so the planned final read-only verification (state, restart comparison and snapshot) did not run while the application and runtime were live. The owner then performed the identity-verified Qwen shutdown. There is a gap of about 48 minutes between the M2 and M3 commits (05:34:40Z to 06:22:43Z, from the database) [V]; that it coincides with the tooling failure is plausible but not shown [I].
5. **Preservation copy timing [V].** The read-only settled copy of the database was made after the final shutdown (its content equals the live file, whose last write was the reply to M3). No pre-shutdown snapshot exists [U].

## 3. Runtime, identity and shutdown

| Item | Observation |
|---|---|
| Runtime | llama.cpp b11440, binary SHA-256 `1bf5602a…4b6b41`; recorded in each run's provenance as `verified` [V] and equal to the pin of the earlier records [V] |
| Model | `Qwen3-4B-Q4_K_M`, SHA-256 `7485fe6f…534fdf5`; recorded in each run's provenance as `verified` [V] and equal to the pin [V] |
| Adapter | `llama-dev-http` 1, `lifetime_scope = external`, declared bases empty, `handoff = STARTED`, `handoff_outcome = UNKNOWN` on all four runs [V]; the adapter and application-build identities are `unspecified` in provenance, as in the earlier smokes [V] |
| Runtime log | `n_slots = 1`, `n_ctx_slot = 2048`, listening on `127.0.0.1:18080`; four completion tasks; the last line is `cleaning up before exit` at 72 min 40 s of uptime [V] |
| Launch, host gate, power state, memory pressure, identity checks during the session | **Not recorded in any retained artifact [U]**; the `verified` digest status in provenance is consistent with a launch that hashed both artifacts [I] |
| Shutdown | The owner reports an identity-verified `stop` that returned `terminated` and `files_removed=true` [O]. The runtime log ends with its own orderly exit line [V], consistent with that report [I]. The `stop` output itself was not retained [U] |
| Residue at 2026-10-27 [V] | No llama, `sandbox-exec`, Anonymous server, uvicorn or vite process; no listener on 18080, 8000 or 5173; no `ANONYMOUS_*` variable; the dataset root holds only the database, its lock file, the settled copy and the runtime log (and an empty `llama-cache` directory); no launch record, key or intent file |

## 4. Persisted outcome (read-only database) [V]

Integrity and structure: `PRAGMA integrity_check` `ok`; foreign-key check clean; journal mode `delete`; schema migrations 1, 2 and 3 applied once (fresh dataset at schema v3); 1 user, 1 conversation, 1 configuration binding, 8 messages, 4 model runs, 4 submissions, 0 retry intents. The conversation is bound once (origin `initial`, no adoption) to `bounded-recent-history@1` (configuration digest prefix `f940e3f4`); both shipped manifests are present.

| Run | Trigger position | User chars | Reply chars (completeness) | Status | Requested to settled | Log prompt / generated tokens [I] |
|---|---|---|---|---|---|---|
| 1 (`a5fd5455`) | 1 | 2 | 36 (`complete`) | `succeeded` | 0.9 s | 13 / 12 |
| 2 (`6042e866`) | 3 | 455 | 46 (`complete`) | `succeeded` | 1.1 s | 132 / 15 |
| 3 (`523cc353`) | 5 | 488 | 45 (`complete`) | `succeeded` | 1.3 s | 255 / 15 |
| 4 (`290245fa`) | 7 | 481 | 46 (`complete`) | `succeeded` | 2.4 s | 260 / 15 |

All four runs: no failure code, no closure reason, `kind = initial`, no `retry_of_run_id`, `termination_basis = runtime_reported_terminal`, `completion_observed = yes` (accepted response delivery only, not natural completion, not process termination, not B3 qualification; ADR-0015 point 1, ADR-0016). Messages 1 to 8 occupy contiguous positions alternating user and assistant; every assistant message is attributed to its run and labelled `complete`, so none was a `length` cut-off under the ADR-0016 rule [I]. The pairing of the four runtime-log completion tasks (prompt and generated token counts, in order) with runs 1 to 4 is by order [I]; the log has no run identifiers.

**Quarantine [I].** No run is failed, closed or still holding the slot, and the application derives its quarantined set from runs holding the slot indeterminately; so there are no indeterminate runs and quarantine is inferred to have been absent. The `/health` endpoint was not observed [U], because the application is down and no live checkpoint was taken.

## 5. Context selection, M3 and the independent recomputation [V]

Run 4 (M3, position 7) was the first whose history did not fit the runtime's 1,400-character limit. Recomputed from the stored positions and character lengths only (newest first; stop at the first older message that does not fit; the trigger is always kept): 481 + 45 + 488 + 46 = **1,060**; adding the 455-character message at position 3 would reach 1,515, which exceeds 1,400. The window is therefore positions **4 to 7**, four messages, with **three omitted** (positions 1 to 3). It begins with an **assistant** message (position 4), as ADR-0017 anticipated.

| Field | T3 `context_selection` (immutable, run 4) | Independent recomputation |
|---|---|---|
| `first_position` / `first_message_id` | 4 / the id of the position-4 message | 4 / matches |
| `selected_count` | 4 | 4 |
| `omitted_count` | 3 | 3 |
| `selected_chars` | 1060 | 1060 |
| `limit_chars` / `measure` | 1400 / `characters` | 1400 |
| `truncated_included_count` | 0 | 0 |

The same recomputation matches the stored selection for **all four runs**: runs 1 to 3 selected everything (1, 3 and 5 messages; 2, 493 and 1,027 characters; 0 omitted), run 4 as above. The stored selection is what the application recorded at dispatch; the recomputation shows it equals what the documented policy yields from the stored history [V]. The prompt token counts in the runtime log (13, 132, 255, 260) are **consistent with** run 4 receiving about as much input as run 3 rather than the whole seven-message history, but they are not proof of which messages were sent [I]: the request body was not captured [U].

**Complete history retained [V].** All eight original messages remain persisted (positions 1 to 8, none missing, none altered by selection; completeness labels as above).

**Omission notice [O].** The owner's screenshot (not retained where the assistant could find it) showed the notice after the M3 reply stating that the three earliest messages were not received by the model. The persisted data that drives that notice (`omitted_count = 3` on the producing run) is verified [V]; the rendered notice itself, its wording and its absence on runs 1 to 3 were not independently observed [U].

## 6. What was observed once (narrower successful findings, n=1)

Separately from the overall verdict: against the real pinned runtime, ADR-0017 selected a contiguous recent window under the 1,400-character limit when the full history stopped fitting, recorded exactly that selection in immutable dispatch provenance, kept the full history in SQLite, and produced four accepted real replies with no failure or indeterminate run; the pinned model and runtime identities were recorded as `verified` on every run; and the runtime ended with an orderly exit and left no process, listener or launch artifacts. Observed once; reply content and quality were not assessed.

## 7. Verification gaps (why this is INCONCLUSIVE)

- **Restart persistence was not verified [U].** No pre-restart snapshot was taken and the database was first read by the assistant only after the final shutdown. The retained dataset is internally consistent and the selection is reproducible from it, but that is not a before-and-after comparison across a restart, and no evidence shows whether a restart occurred.
- Pre-run state (the B5-style precondition: health open, zero quarantined runs, empty dataset) is not documented [U]; a fresh dataset is inferred from migrations applied once and an empty-start history [I].
- Host gate, power and memory conditions, launch details and in-session identity checks are not documented [U].
- The rendered omission notice, a page reload and a replay of a stored run were not independently observed [U].
- Prompt fidelity (section 2) and the submission channel of the opening message are not established [U].
- The shell-tool failure means the live read-only checkpoint, the live `/health` read and a pre-shutdown database snapshot do not exist [U].

## 8. Not shown

General reliability or reproducibility; restart persistence of the new fields; the `message_exceeds_capacity` refusal on a real runtime; a truncated reply inside the window (`truncated_included_count` was 0); the retry path; migration of a populated v1/v2 dataset; token-aware fit (characters remain a proxy, and real overflow remains untested, ADR-0015 residual); how well Qwen answers a window that begins mid-conversation (observed to occur once at position 4, quality not assessed); GPU offload; B3, B4 or B5 qualification or any LD-04 reclassification; any PRIVATE-mode, authentication or non-development property. The first-smoke and truncation-smoke datasets were not touched.

## 9. Remaining open items (nothing decided here)

- Whether to run a further, separately authorized check of restart persistence (and of the rendered notice) for the bounded window. Not authorized by this record.
- ADR-0017 stays Accepted; its acceptance wording is historical. Turn-aware selection, token and template accounting, an adoption route for existing conversations, LD-06 / Q-12 / Q-19 and Q3 (recovery for a quarantined dataset) remain open and unchanged.
