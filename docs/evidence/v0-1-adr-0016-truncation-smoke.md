# v0.1 — ADR-0016 real-Qwen truncation confirmation smoke (ADR-0015/0016, n=1, macOS)

**Status: PASS with two documented process deviations (owner decision, 2026-10-24).** One attended runtime lifetime, one fresh dataset at schema v3, synthetic data only, loopback only, repository HEAD `6833406` before and after. Documentation only: no source, test, ADR decision text, LD-04 classification or frozen E1/E2-B/E3 evidence was changed by this record. LD-04 runtime-evidence rows stay `BLOCKED_BY_RUNTIME_EVIDENCE` and Slice 0B-2 is not accepted by it.
**Plan:** [v0.1 ExecPlan](../../.agent/plans/2026-10-24-v0-1-first-local-model-chat.md). **Decisions:** [ADR-0015](../adr/0015-dev-only-external-llama-runtime-adapter.md), [ADR-0016](../adr/0016-visibly-truncated-assistant-responses.md). **Implementation:** [implementation record](../implementation/v0-1-external-runtime-dev.md). **Earlier smoke:** [first real-Qwen smoke](v0-1-first-real-qwen-smoke.md) (unchanged). **Pins relied on:** [E2-B](v0-0b2-e2b-first-inference-run.md), [E3](v0-0b2-e3-first-pilot-run.md) (unchanged).

**Provenance of this record.** It condenses a sanitized local record kept **outside the repository and not committed** (SHA-256 `a89e93d784a07a4c6995ee9271486cbad973a15c64379d57fb5361d7893ffb7f`; unchanged by this closure). Observations were made by the assistant (commands, read-only database and API reads, `ctl status` and `ctl stop`) or reported by the owner (the browser interaction and its screenshots); each owner report is marked. The raw runtime log, the database, the key, the launch record, every prompt and every reply stay local and are not reproduced here. A read-only copy of the settled database is kept locally (SHA-256 prefix `e3594143`). The first-smoke database was neither opened nor migrated.

**Verdict in one line.** One owner-submitted browser message produced a non-empty, attributable reply from the real pinned Qwen3-4B-Q4_K_M under llama.cpp b11440 that stopped at exactly the output limit (`max_tokens` 64, `finish_reason: length`). Anonymous published it through T4 as a succeeded run with a message labelled `truncated`, showed the visible notice, did **not** quarantine, kept the result identical across a server restart without further inference, and the runtime was stopped by identity-verified `stop` with no residue. One run, not a reliability claim.

## 1. Scope and criteria

Authorized by the owner: one attended smoke, one browser-submitted message (one authorized synthetic browser message, 75 characters; prompt content omitted from the committed evidence), `ANONYMOUS_LLAMA_MAX_TOKENS=64` so that the cutoff is reached quickly, no retry, a mandatory 10-sample host gate, identity-verified cleanup. Pass criteria: non-empty `length` reply; run `succeeded` with no failure code; assistant message `truncated`; notice visible and composer available; no quarantine; identical state after a restart; clean runtime stop. The result would have been INCONCLUSIVE had the model finished with `stop`; it did not.

## 2. Host gate and runtime

| Item | Observation |
|---|---|
| Gate before launch (10 samples, ~5 s apart) | AC power 10/10; memory pressure level 1 in 10/10; free memory 73–74 %; swap used flat at 607.5 MiB; disk 361 GiB free; no competing runtime process; ports 18080 and 8000 free; no `ANONYMOUS_*` variable; no launch record; repository clean at `6833406` |
| Host | macOS development host (the Apple M1 Pro host of the E2-B record), AC power, attended |
| Runtime | llama.cpp b11440, binary SHA-256 `1bf5602a…4b6b41` (equals the pin) |
| Model | `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 B, SHA-256 `7485fe6f…534fdf5` (equals the pin) |
| Launch | `launch --hash`, exit 0, about 2 s; model and runtime digests `verified` (hashed by the launcher, equal to the pins); exactly one process carried the launch nonce |
| Identity | `process_identity_matches` and `sole_listener_is_recorded_process` true after launch, after the reply, after the restart and immediately before stop; listener exactly `127.0.0.1:18080` |
| Readiness | manual `GET /health`: HTTP 200 on the first poll (owner-permitted check outside the committed CLI; the adapter never requests it) |
| Application | `anonymous-server --runtime llama-dev` on a fresh `*-dev.sqlite3`, started by the owner in a foreground terminal with `ANONYMOUS_LLAMA_MAX_TOKENS=64` |

## 3. Pre-message state (read-only, before the owner's message)

Health `ok`; schema version 3 (`schema_migrations` 1, 2, 3; `messages.completeness` present); `generation.state = open`; 0 quarantined runs; 0 conversations, 0 messages, 0 runs; `integrity_check` `ok`. This is the B5-style precondition check that the first smoke could not make.

## 4. Browser interaction (owner's report and screenshots)

One conversation, one authorized synthetic user message of 75 characters (equal to the authorized message's length; prompt content omitted from the committed evidence; the text was not inspected by the assistant). Nothing was submitted by curl, Python or any automated interface; no second message and no retry. The screenshot after the reply shows the reply, the italic notice "This reply was cut off at the model's output limit." and the composer available.

## 5. Persisted outcome (read-only database and API)

| Item | Observation |
|---|---|
| User message | position 1, 75 characters, completeness `NULL` |
| Assistant message | position 2, 319 characters, completeness `truncated`, produced by the run |
| Completeness values in order | `[null, truncated]` (API and database agree) |
| Run | `succeeded`, no failure code, no closure reason |
| Binding | adapter `llama-dev-http`, `lifetime_scope = external`, declared bases empty, `handoff = STARTED`, `handoff_outcome = UNKNOWN` |
| T4 stamps | `termination_basis = runtime_reported_terminal`, `completion_observed = yes`: accepted response delivery only, not natural completion, not process termination, not B3 qualification (ADR-0015 point 1, ADR-0016) |
| Runtime log (path-free timing lines only) | 28 prompt tokens, **64 generated tokens**, 92 total, 1.79 s: exactly the limit |
| Quarantine | none: health `open`, `quarantined_runs = 0`; `integrity_check` `ok` |

The `length` finish itself is inferred from the exact token count and from the persisted `truncated` label (which the adapter sets only for the exact finish `length`); the raw response body was not inspected.

## 6. Persistence across a server restart (no additional inference)

A content-free snapshot (ids, lengths, SHA-256 of contents, labels, commit times, run fields) was taken before the owner's shutdown and compared after the restart: the conversation, both messages and the run were **identical**; labels `[null, truncated]`; no new run appeared; health unchanged (`open`, 0 quarantined); `integrity_check` `ok`. A page reload after the restart (owner's screenshot) showed the same reply with the notice. The snapshot was deleted afterwards. No message was sent and no inference request was made after the first reply.

## 7. Cleanup and final state

After the server was confirmed down: `integrity_check` `ok`; a read-only copy of the settled database was kept locally; `stop --remove-files`: exit 0, `signalled = true`, `result = terminated`, `files_removed = true`. Afterwards: no process carrying the launch nonce; no listener on 18080 or 8000; no llama, `sandbox-exec` or Anonymous server process; no launch record, key or intent (`status` reports `record_missing`). Re-checked read-only at closure: same state, repository clean at `6833406`. Retained locally by design: the runtime's own log (it contains local paths), the empty `llama-cache` directory and the database copy; none is committed.

## 8. Process deviations (both recorded, neither affects a pass criterion)

1. **Database-copy timing.** The owner restarted the application before the assistant's down-window read-only step ran, so the preservation copy of the database was taken after the **final** shutdown instead of in the first down window. The restart comparison used the pre-shutdown snapshot, so the evidence is complete.
2. **Python read-only SQLite inspection.** The database was read with Python `sqlite3` (`mode=ro`) because the `sqlite3` command-line tool cannot open the file from the assistant's environment (as in the first smoke).

## 9. What this shows, and does not

**Observed once (n=1):** ADR-0016 end to end against the real pinned runtime: an exact `length` stop published through T4 as a visibly truncated message with no quarantine; the label persisted at schema v3 (migration 0003 applied to a fresh dataset), survived a server restart and a reload, and was shown by the real UI; the pinned launcher, `--hash` verification, identity facts and `stop` behaved as in the first smoke.

**Not shown:** general reliability or reproducibility; B3, B4 or B5 qualification (T4 still means accepted response delivery only); any LD-04 reclassification; behaviour for other finish reasons, prompts or longer conversations; the content or quality of the reply; verified GPU offload; real context overflow; any PRIVATE-mode, authentication or non-development property; migration of a populated v1/v2 dataset by this build against a real runtime. The **1400-character history cap is unchanged and was not exercised** (the only request carried a 75-character history). The notice says "cut off", not why (`length` also covers a context-full stop). The first-smoke database and its quarantine were not touched.

## 10. Remaining open items (nothing decided here)

- **Q5:** the truncation-visibility part is now observed once on the real runtime; history handling remains open (1400-character cap, no bounded context selection, no token-aware accounting; accepted truncated replies reach the cap sooner).
- **Q3:** recovery for a quarantined dataset (read-only transcript export, later carry-forward) remains open; this smoke produced no quarantine and did not touch the quarantined first-smoke dataset.
- No regenerate or continue feature exists; a truncated run is `succeeded` and not retryable.
