# v0.1 — first attended real-Qwen conversation smoke (ADR-0015, n=1, macOS)

**Status: COMPLETED WITH DEVIATION AND QUARANTINE (owner decision, 2026-10-24).** It is **not** a fully passing execution of the authorized one-message protocol. One attended runtime lifetime, synthetic data only, loopback only, repository HEAD `6a6ad1c` before and after. Documentation only: no source, test, ADR decision text, LD-04 classification or frozen E1/E2-B/E3 evidence was changed by this record. LD-04 runtime-evidence rows stay `BLOCKED_BY_RUNTIME_EVIDENCE` and Slice 0B-2 is not accepted by it.
**Plan:** [v0.1 ExecPlan](../../.agent/plans/2026-10-24-v0-1-first-local-model-chat.md). **Decision:** [ADR-0015](../adr/0015-dev-only-external-llama-runtime-adapter.md). **Implementation:** [implementation record](../implementation/v0-1-external-runtime-dev.md). **Runtime evidence relied on for the pins:** [E2-B](v0-0b2-e2b-first-inference-run.md), [E3](v0-0b2-e3-first-pilot-run.md) (unchanged).

**Provenance of this record.** It condenses a sanitized local record kept **outside the repository and not committed** (SHA-256 `d8175933aed5d0b61bde7e5d38f1a4f30185756683ccbcfc8bc57b461dbd05be`; unchanged). Observations were made by the assistant (commands, read-only database and API reads, `ctl status` and `ctl stop`) or reported by the owner; each such report is marked. The raw runtime log, the database, the key, the launch record and every prompt and reply stay local and are not reproduced here. A read-only copy of the settled database is kept locally (SHA-256 prefix `da3b438d`). Where the local record is looser (an approximate time for the failed gate, "Ctrl-C" for the owner's two server stops, per-run latencies, and a browser-reload statement without its provenance), this record is the stricter one and the local file was left unchanged.

**Verdict in one line.** One sandboxed `llama-server` b11440 with Qwen3-4B-Q4_K_M, launched and verified by the dev launcher, served two accepted conversation turns through the React UI and the ADR-0015 adapter; both assistant replies were persisted and survived a server restart; a third message, **sent outside the authorized scope**, generated exactly `max_tokens` (384), was rejected by design, closed the run `indeterminate` and quarantined the disposable dataset; the quarantine survived a restart unaltered and the runtime was stopped by identity-verified `stop` with no residue. These are observations from one run, not reliability guarantees.

## 1. Protocol deviation (stated plainly)

- **Authorized:** one user message through the browser UI (the prescribed text was `Name three colors of the rainbow, in one short sentence.`, 56 characters).
- **Actual:** three user messages (positions 1, 3, 5) in one conversation, submitted through the React UI (owner's report and screenshot). The assistant sent nothing and made no inference request; no curl, Python or other automated submission was used and no retry was made.
- The second and third messages were outside the authorization. The first message is recorded as 33 characters; the message texts were **not inspected**, so conformity of message 1 with the prescribed 56-character text is not established.
- The owner closed the smoke as completed with deviation and quarantine; it is not repeated and no second dataset or retry was made under this authorization.

## 2. Host gate and runtime

| Item | Observation |
|---|---|
| Gate before launch (10 samples, ~5 s apart) | AC power 10/10; memory pressure level 1 in 10/10; free memory 66–68 %; swap used flat at 663.5 MiB; disk 361 GiB free; no competing runtime process; ports 18080 and 8000 free; no `ANONYMOUS_*` variable; no launch record or intent; repository clean at `6a6ad1c` |
| Earlier gate | An earlier gate of the same kind **failed** (pressure level 2 in 10/10); nothing was launched; a later gate passed |
| Host | macOS development host, 16 GiB memory (observed), the Apple M1 Pro host of the E2-B record, AC power, attended |
| Runtime | llama.cpp b11440, binary SHA-256 `1bf5602a…4b6b41` (equals the pin; 42-file/18-link tree equals `e2b_pins.json`, checked read-only before the run) |
| Model | `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 B, SHA-256 `7485fe6f…534fdf5` (equals the pin) |
| Launch | `launch --hash`, exit 0, about 2 s including hashing (warm file cache); argv and sandbox profile equal the E2-B/E3 profile; run through `python -m anonymous.adapters.model.llama_ctl` because the `anonymous-llama-dev` script was not installed in the pre-existing virtual environment |
| Identity | `process_identity_matches` and `sole_listener_is_recorded_process` true after launch, after the quarantine, after the restart and immediately before stop (no check was taken between the application start and the first message); listener exactly `127.0.0.1:18080` |
| Digests | model `verified`, runtime `verified` (hashed by the launcher, equal to the pins) |
| Readiness | manual `GET /health`: HTTP 200 on the first poll (an owner-permitted check outside the committed CLI; the adapter never requests it) |
| Application | `anonymous-server --runtime llama-dev` on a fresh `*-dev.sqlite3`, started by the owner in a foreground terminal. The planned B5 check (health open, 0 quarantined runs) was **not run before the first message**: the owner's browser interaction preceded it. The assistant's first application health read was after the quarantine; a fresh dataset with no run before the first message is inferred from the database (three runs, all from this interaction) |

## 3. Outcomes (read-only database and API)

| Run | Message (chars) | Status | Result |
|---|---|---|---|
| 1 | position 1 (33) | `succeeded` | assistant reply, 223 characters, position 2 |
| 2 | position 3 (41) | `succeeded` | assistant reply, 397 characters, position 4 |
| 3 | position 5 (23) | `indeterminate`, `closure_reason = runtime_failure`, `settled_at` null, `closed_at` set | no assistant message |

All three runs carry the expected binding: adapter `llama-dev-http`, format `llama-dev-http/1`, `lifetime_scope = external`, declared bases empty, `late_delivery_excluded = 0`, `handoff = STARTED`, `handoff_outcome = UNKNOWN`, instance prefix `llama-b6df4d01`. Runs 1 and 2: `termination_basis = runtime_reported_terminal` and `completion_observed = yes`, which for this binding means *accepted response delivery*, not process termination and not B3 qualification (ADR-0015 point 1). Run 3: no basis recorded.

**Why run 3 was rejected.** The runtime log (only path-free timing lines were read) shows three requests in order: 23 prompt tokens and 75 total in 1.44 s; 96 and 183 in 2.52 s; and for the third **198 prompt tokens and 582 total, i.e. 384 generated, in 9.83 s**, which equals `max_tokens` 384 (the lines are matched to runs by order). A 200 response that stopped at the limit reaches the worker as an incomplete delivery, is refused as `output_truncated`, the settler refuses the undeclared B3 basis and the worker closes with `runtime_failure` (read from the committed code, [worker.py](../../server/src/anonymous/application/worker.py) `_handle_delivery` and `_settle_known`; the Terminal B server log lines that would corroborate it were not captured). The 120 s deadline played no part (about 9.9 s from dispatch to closure). This is the plain-`length` quarantine that ADR-0015 point 2 states deliberately. The persisted row does not record *which* rejection occurred: the code `output_truncated` is not stored for an unsettled run, so `runtime_failure` alone is also what an empty or model-mismatched delivery would show.

The history at run 3 was 717 characters, within the 1400-character input cap; the cap did not intervene.

## 4. Persistence, restart and quarantine

- **API and database agree** after the quarantine: five messages in order (user, assistant, user, assistant, user) and three runs.
- **Browser reload:** reported by the owner in the closure decision; not independently observed by the assistant.
- **Server restart:** the server was stopped by the owner while no attempt was active (run 3 was already closed), the settled database was copied read-only, `integrity_check` returned `ok`, and the server was started again with the same command and the runtime still live. Messages, runs and conversation read through the API (hashes and lengths, snapshots deleted afterwards) were **identical before and after**; the run rows were unchanged (run 3 still closed, unsettled, no basis).
- **Quarantine:** health reported `generation.state = blocked`, `reason = runtime_quarantined`, `quarantined_runs = 1` before and after the restart. The restart neither released nor altered it. No reset, replacement dataset, edit or retry was attempted.
- `integrity_check` was `ok` after each shutdown and after the runtime was stopped. Database reads used Python read-only (`mode=ro`) because the `sqlite3` command-line tool could not open the file from the assistant's environment.

## 5. Cleanup and final state

`stop --remove-files` after the server was down: exit 0, `signalled = true`, `result = terminated`, `files_removed = true`. Afterwards: no process carrying the launch nonce; no listener on 18080 or 8000; no llama or `sandbox-exec` process; no launch record, key or intent (`status` reports `record_missing`); repository clean at `6a6ad1c`, nothing staged, committed or pushed by the smoke. Retained locally by design: the runtime's own log (it contains local paths), the empty `llama-cache` directory and the read-only database copy; none is committed.

## 6. What this shows, and does not

**Observed once:** the real launcher under `sandbox-exec` with the real server and the pinned flags; the macOS libproc/`lsof` identity facts against a real runtime; `--hash` verification; a real `/v1/chat/completions` response parsed by the adapter, including a real `length` finish; the unknown-outcome-to-T4 path publishing a real response; identity-verified `stop`; an end-to-end browser conversation (owner's report); and the quarantine persisting across a restart.

**Not shown:** B3, B4 or B5 qualification, cancel, disconnect, streaming, late delivery or reproducibility (n=1); any LD-04 reclassification; verified GPU offload; real context overflow; behaviour under a listener swap; the thinking-tag behaviour of the replies (not inspected); the content or quality of any reply; any PRIVATE-mode, authentication or non-development property; the stronger peer attribution residual of ADR-0015 point 10, which is untouched. Weights are verified only to the extent of the launcher's own hash of the file it launched. The model's reply that it was running "in the cloud" (reported by the owner from the UI) is a model-output quality issue; the runtime ran under a sandbox denying outbound network except localhost, and this record does not treat the claim as evidence of any external connection.

## 7. Observations for the open questions (assessment only; nothing decided here)

These are data points, not decisions; Q3 and Q5 stay open in the [ExecPlan](../../.agent/plans/2026-10-24-v0-1-first-local-model-chat.md).

1. **Q5.** `max_tokens` 384 was reached on the third turn of a short conversation, so the permanent-quarantine consequence of ADR-0015 was met in the first real use, not rarely. The persisted run does not say which delivery rejection occurred.
2. **Q3.** The quarantined dataset remains readable with its two accepted replies intact; the supported recovery today is a new dataset file, which does not carry the conversation forward.
3. The model's incorrect statement about where it runs points to a later runtime-context and product-quality topic (what the model is told about its environment); it is not a security finding.
4. Documentation status drift (ADR header Accepted against stale "Proposed" current-status text) was found during this closure and reconciled in the same documentation change.
