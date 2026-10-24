# Slice 0B-2 E3 V1 — first (and only) real pilot run: owner SIGKILL during active generation, orphan observation, identity-verified termination (n=1, macOS)

The frozen [E3 pilot protocol](v0-0b2-e3-pilot-protocol.md) is not edited by this document (its SHA-256 is bound by the consumed authorization). LD-04 register classes are unchanged. Sanitized machine-readable view: [v0-0b2-e3/summary-committed-view.json](v0-0b2-e3/summary-committed-view.json) (file SHA-256 `1d7b580554f95c8fa2c2909e9d1a449f9b304c5bcb1bb49ebb6d8cee2d3fd406`; byte-for-byte the view the harness generated, unedited).

**Status: E3 V1 CLOSED — completed with limitations (owner decision, 2026-10-24).** One authorized real pilot lifetime, n=1, run `20261023T155329Z-03ee3c` (2026-10-24 00:53 JST), frozen commit `a4628fffe115506847155f3f8ca30bb1dcda1d6c`. The evidence was sealed and accepted. **Evidence only.** No Anonymous application code ran against the runtime. This closes E3 V1 only; it does **not** close Slice 0B-2 (Option C, the synthesis and other questions remain open, §7).
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). **Protocol:** [E3 pilot protocol](v0-0b2-e3-pilot-protocol.md). **Preceding:** [E2-B first inference run](v0-0b2-e2b-first-inference-run.md), [E1](v0-0b2-e1-process-ownership-termination.md).

**Verdict in one line.** For a single-process, non-forking `llama-server` b11440 spawned and recorded by the harness, one lifetime showed that the runtime **survived the SIGKILL of its Owner during active generation**, that a Successor holding no network, key, fixture or model access **classified it alive, then terminated it by identity-verified SIGTERM** and verified the exit through the non-parent conjunction (no `waitpid`), and that the one in-flight Reader request **completed with HTTP 200 at the 384-token limit**. This supports O1, O3, O4 and a **conditional** B4 successor-side basis for that configuration only. It is one run, not reproduced; it says nothing about B3, B5, cancel, disconnect or late delivery.

## 1. What was run

| Item | Value |
|---|---|
| Run / scope | `20261023T155329Z-03ee3c`, scope `e3-pilot-v1`, variant `V1`, one lifetime, attended, owner-authorized (authorization id `e3-v1-20261024-7c4e1b`; its consumed marker exists; the authorization has since expired and is spent) |
| Frozen commit | `a4628fffe115506847155f3f8ca30bb1dcda1d6c` (HEAD at the run and at closure; working tree clean) |
| Protocol | [`v0-0b2-e3-pilot-protocol.md`](v0-0b2-e3-pilot-protocol.md), SHA-256 `ce1daa39962723decc10a31e63ccc45a21accf8d6b52a5a10e734f14cb6c0b0e` (frozen 2026-10-22; unchanged) |
| Fixture G | 605 B, SHA-256 `ca2cdcc25dd149b8ac47c4e01ae57782bbb8c11f4e9d122af6f2f4a52bcebc6b`, `max_tokens` 384, non-streaming; owner-approved 2026-10-18; unchanged. Only its hash appears here. |
| Runtime / model | llama.cpp b11440, binary SHA-256 `1bf5602a…4b6b41`; `Qwen3-4B-Q4_K_M.gguf`, SHA-256 `7485fe6f…534fdf5`; model unchanged (`model_unchanged` true). |
| Launch | As E2-B: single-model mode under `sandbox-exec` with `(deny network-outbound)` except localhost and `(deny process-fork)`; `127.0.0.1:18080`; `-c 2048 -np 1 -ngl all -t 6`; API key file 0600 (deleted by the Driver at the kill instant). |
| Roles | Driver (supervisor), Owner (spawned and recorded the runtime; SIGKILLed by the Driver), Reader (one passive request), Successor (own session; kernel network denial and read denial on fixtures, models and run scratch). |
| Implementation identities (equal to the authorization, to the live files and to the view) | `e3_harness.py` `e31ebdae…745`, `e3_lib.py` `dcf5255e…ceee2`, `e3_owner.py` `6431a616…7a68`, `e3_reader.py` `128ecc32…4075`, `e3_successor.py` `6ac6f66f…24d74c`, `e2b_harness.py` `246c5c17…14dba`, `e2b_lib.py` `849415af…8047f`, `e1_lib.py` `6190a975…2e4e`, `e2b_pins.json` `f25b500c…8bbed`, `e3_pins.json` `20026ac6…97d4f4b`; pins in use (canonical) `c635109f…5209ec8e`. The complete 64-hex values are in the view (`identities`) and in the authorization. |

## 2. Results

Times are seconds relative to the owner kill (`t0`), on the uptime clock.

**Gates.** Phase 1 load gate and Phase 2 controls passed (all of `WINDOW`, `CONT`, `G1`–`G12` true; controls passed); no stop S1–S13 was recorded (`stops` empty); swap baseline flat; leftovers check clean; artifact integrity passed.

**Trigger and kill.** `FIRE` after 16 polls (15 consecutive); `/slots` processing was observed for the strict-boolean `is_processing` rule, so the one residual risk of §14.9 of the protocol did not materialize. The request had been in flight 1.559 s (request sent at −1.561). The Driver SIGKILLed the Owner at `t0`; the Owner's return code was −9, it was dead 0.002 s later, and the key file was deleted at `t0` and did not exist afterwards (before the Successor started at +0.028). The Driver's gate attempted 0 requests after it closed, and `lsof` saw 0 new connections after the baseline (blind interval = the 1 Hz poll period).

**Orphan.** At the Successor's first classification (+0.324) and at +1.065, +2.066, +5.064 and +10.072 the runtime's recorded (pid, start) was live: five `PROVEN_ALIVE`. It did not exit by itself (`exited_by_itself` false). The Reader's request completed at +7.993: **HTTP 200, `finish_reason` `length`, 111 prompt tokens, 384 completion tokens**, content length 2,155 bytes (content hash in the view; no text), `client_completed` true, no timeout or error. The runtime's CPU-time samples (diagnostic only) rose until about +8.5 s and were flat afterwards. The observation window therefore ended at **+17.993 s** (Reader completion + 10 s), not at the 60 s maximum.

**Termination.** The Successor sent one SIGTERM at the window end (reason `window_end`, delivered per the ledger); the exit event (`NOTE_EXIT`) was observed at +18.056 and the final verification completed at +18.18. Checks: identity gone, recorded descendants dead, process group clear, tag scan clear, port free. Signals per the ledger (lower bounds, see the view's `signals_basis`): Driver 1 attempted and 1 delivered (the Owner SIGKILL); Successor 1 attempted and 1 delivered (the SIGTERM); no refusals. The runtime exited without a SIGKILL. The Successor returned 0. **The Driver backstop was not used** (`backstop_used` null) and **no quarantine step** was taken.

**Record.** `EXIT_VERIFIED`, basis `non_parent_kernel_identity_and_conjunction`, `cleared_by` and `terminated_by` the Successor, `exit_cause` `SIGNALLED` by the Successor, `waitpid_evidence` false, `attribution_consistent` true, `owner_review_required` false, `owner_review_persisted` and `quarantine_takeover` null, 0 persistence errors. After the run: no unresolved record, no runtime, Owner, Reader or Successor process, no listener on 18080; model and fixtures unchanged.

## 3. Evidence rows (design §14; scope as stated, LD-04 classes unchanged)

**Supported (n=1).**

| Row | Verdict | Scope — what it is | Not established |
|---|---|---|---|
| O1 orphan survival | `SUPPORTS (n=1)` | The runtime was alive at the Successor's first classification and at four later ones after its Owner was SIGKILLed during active generation | Behaviour over the full 60 s; a second lifetime; other runtimes or configurations |
| O3 Successor classification consistency | `SUPPORTS (n=1; consistency only)` | The classifier never returned `PROVEN_TERMINATED` while the identity was live; it returned `PROVEN_ALIVE` five times | That the classifier is correct in general |
| O4 Successor termination | `SUPPORTS (n=1)` | Kill by a verified identity (pid and start), non-parent conjunction, no `waitpid` evidence | Termination during active generation (it happened after the response was complete); SIGKILL escalation (SIGTERM sufficed, so the escalation path is not exercised); GPU resources released |
| B4 successor-side | `SUPPORTS (conditional; n=1; harness-owned test configuration; not reproduced)` | A Successor with no application knowledge can take over and verify exit of a single-process, non-forking runtime spawned by the harness | Reproducibility; a runtime that forks, detaches or scrubs its environment; any Anonymous adapter; router mode; Windows |

**Observations — recorded, not verdict rows.**

| Observation | Value | Scope |
|---|---|---|
| O2 exited by itself before the window end | `false`; the exit cause was `SIGNALLED` by the Successor | The window was 17.993 s; self-exit after that is not excluded. The ledger covers only the experiment's own signallers. |
| O5 Reader outcome class | `COMPLETE_RESPONSE` (HTTP 200, `length`, 384 tokens) | One in-flight attempt. Client completion is a client-side fact, not server idleness. It is **not** B3, **not** a `late_delivery_excluded` qualification and **not** a cancellation result. It records that the runtime finished the request it had already accepted after its Owner died. |

**`NOT_TESTED` (unchanged, none promoted):** B3 instance-reported terminal result, B5 slot idle, request cancel, requester disconnect, `late_delivery_excluded`, adoption for generation.

Every LD-04 row remains `BLOCKED_BY_RUNTIME_EVIDENCE`. A completed generation is `INFERENCE_OBSERVED` and supports no LD-04 row by itself. Changing any register class needs separate review and acceptance and, where architectural, an ADR.

## 4. Evidence acceptance and provenance (protocol §13)

| Item | Value |
|---|---|
| Observed process exit status | **0** (reported by the owner, who supervised the run; the files cannot contain it) |
| Acceptance command line | `python3 tools/evidence/runtime/e3_harness.py accept 20261023T155329Z-03ee3c --exit-status 0` |
| Acceptance result | `{"sealed": true, "supports_verdicts": true, "reasons": []}` (command exit code 0) |
| Committed view SHA-256 | `1d7b580554f95c8fa2c2909e9d1a449f9b304c5bcb1bb49ebb6d8cee2d3fd406` |
| Seal confirmation (`seal-confirmation.json`) | `sealed` true; run id as above; outcome `PILOT_COMPLETED`; exit code 0; passes 1; `interrupt_seen` false; `summary_sha256` `aa1d45d57a7d5eed6cbe0f73c6d7aa353e4fb0404d83787307743fe9c310aee1`; `view_sha256` equal to the committed view's SHA-256 above |
| Raw artifact digests | Thirteen files (`events`, `gate-window`, `gate-context`, `series`, `post-unload`, `server.log`, `summary`, `signals`, `owner` and its stderr, `reader`, `successor` and its stderr); byte counts and SHA-256 values are in the view under `raw_artifacts` |
| Raw run directory | Outside the repository, retained in the bench (`<bench>/e3/runs/20261023T155329Z-03ee3c/`); not committed |

The acceptance check was repeated read-only at closure (2026-10-24) against the retained run directory and returned the same JSON. Per protocol §13, the check establishes the consistency of the files with each other and with the supplied exit status; it does not independently establish how the process terminated, and the digests guard against accidental change, not forgery. The operator-supplied exit status is the owner's report and was not re-observed by the assistant.

## 5. Scope that is preserved — what this evidence does not say

- **No reproducibility claim.** One lifetime, n=1.
- **No full 60-second orphan observation.** The window closed at 17.993 s because the Reader completed at +7.993 s.
- **No proven runtime SIGKILL escalation.** SIGTERM was sufficient; the escalation path and the Driver backstop were not exercised on the real runtime.
- **No demonstrated termination during active generation.** The Owner was killed during generation; the runtime was terminated only after the Reader's response was complete.
- **No B3/B5, cancellation, disconnect or late-delivery guarantee.** The Reader was passive; its outcome cannot qualify any of these.
- Warm-file load likely (protocol §14.1); GPU offload is not verified (the runtime log contains no offload lines); the generation end was not read from the runtime log (owner decision).
- macOS only, same-user visibility, one OS build, one runtime build, fixture G unvalidated beyond this run.
- The author of the harness, the tests and this record is the same assistant; the only independent review (Codex, revision 6b, PASS WITH CONDITIONS) was static and preceded execution. The executed evidence has not been independently reviewed.
- The residuals accepted by the owner for this pilot (protocol §14) stand. None was observed to materialize in this run (no stop, no backstop, no quarantine).

## 6. Discoveries

1. **The runtime outlived its Owner and completed the already-accepted request.** With the Owner SIGKILLed about 1.6 s into generation, the runtime kept running and its in-flight request returned a full 384-token response about 8 s later. This is consistent with E2-B discovery 2 (no owner-death linkage in single-model mode): in this configuration Owner death did not stop generation, and the response reached the still-connected Reader. It records the behaviour of one run; it is not a qualification of late-delivery handling, and any design consequence needs its own decision.
2. **The Successor design worked as specified on the real runtime** under the kernel network and read denial: five consistent classifications, one signal, a verified non-parent exit and no escalation.
3. **Unchanged from E2-B:** the runtime's `/props` and `/v1/models` expose the absolute model path (privacy risk for any adapter or log); `--chat-template-kwargs` for thinking is deprecated in b11440.

## 7. Slice 0B-2 questions that remain open

E3 V1 is closed; Slice 0B-2 is **not**. Open: Option C (request cancel, requester disconnect, late delivery, per-attempt registration); B3 and B5 qualification; reproducibility (a second lifetime, which needs a new authorization); termination during active generation and SIGKILL escalation on the real runtime; a cold-load and GPU-offload verification; the synthesis and the recommendation for an adapter/controller shape; the owner decision on the partial model file; the unexplained historical 54/188 synthetic gate failure (protocol §14.12); the absolute-model-path privacy risk (no mitigation designed); Windows (separate gate). Every LD-04 row stays `BLOCKED_BY_RUNTIME_EVIDENCE`.

## 8. Validation of this record

At closure (2026-10-24) the following were checked read-only against the retained run directory and the repository: HEAD equals the frozen commit and the working tree was clean; the protocol, the ten implementation files, fixture G and the pins match the consumed authorization and the view; the consumed marker exists and names this run; `accept` returned the JSON above; the committed view is byte-identical to the harness's view and its SHA-256 equals the seal confirmation's `view_sha256`; the execution record is `EXIT_VERIFIED` with no unresolved record; no runtime-related process or listener on 18080 remains; the view contains no home path, prompt, output text or key (the harness's `scan-committed` found 0 hits). No run, test or synthetic experiment was executed for this closure.
