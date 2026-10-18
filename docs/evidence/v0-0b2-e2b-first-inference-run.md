# Slice 0B-2 E2-B — first real-runtime run (single lifetime, macOS)

The frozen [E2-B protocol](v0-0b2-e2b-protocol.md) is not edited by this document. LD-04 register classes are unchanged. Sanitized machine-readable view: [v0-0b2-e2b/summary-committed-view.json](v0-0b2-e2b/summary-committed-view.json) (file SHA-256 `0a8ecfe76a4d0d676681fdc0826dc3ab52f5b7163309d47d0fd29a50a68d943e`; byte-for-byte the view the harness generated, unedited).

**Status:** E2-B executed on 2026-10-18 under owner authorization, base scope, Phases 1–4, run `20261018T043949Z-13e9c7`, HEAD `6b03706`. **Evidence only.** One server lifetime, seven synthetic generation requests, loopback only. No Anonymous application code ran against the runtime. Option C, any A/B control, E3 and the synthesis are not started.
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). **Protocol:** [E2-B protocol](v0-0b2-e2b-protocol.md) (SHA-256 `f27b7162…e28e174`). **Preceding:** [E1](v0-0b2-e1-process-ownership-termination.md), [E2 preflight](v0-0b2-e2-preflight-runtime-topology.md), [E2-A](v0-0b2-e2a-model-acquisition.md).

**Verdict in one line.** For a single-process, non-forking `llama-server` b11440 in single-model mode, spawned and recorded by a harness under a no-fork sandbox profile, one lifetime produced seven well-formed authenticated generations, every control and stop check passed, and a verified-exit conjunction (`PROVEN_TERMINATED`) held at shutdown. This supports a **conditional** B4 basis for that configuration only. It is one run, a warm-file load, with GPU offload unverified, and it says nothing about cancel, disconnect, late delivery, B3 or B5 qualification, or any Anonymous adapter.

## 1. What was run

| Item | Value |
|---|---|
| Runs | Preflight Phases 1–2 only: `20261018T042948Z-9da6f1` (13:29, passed, no spawn). Full Phases 1–4: `20261018T043949Z-13e9c7` (13:39:49–13:42:31 JST). |
| Host | Apple M1 Pro, 16 GiB, macOS 27.0.1, AC power, lid open, attended; no `caffeinate`, no power-setting change. |
| Runtime | llama.cpp b11440 (`0.6.0-dev (build 11440, commit 1a3011cc0)`), binary SHA-256 `1bf5602a…4b6b41`, 42-file/18-link tree pinned and re-verified at Phase 1 and before the spawn. |
| Model | `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 B, SHA-256 `7485fe6f…534fdf5` (re-hashed at Phase 1; same file by stat identity before the spawn and at the end). |
| Launch | Single-model mode under `sandbox-exec` with `(deny network-outbound)` except localhost and `(deny process-fork)`; `127.0.0.1:18080`; `-c 2048 -np 1 -ngl all -t 6 -b 512 -ub 128`, `--api-key-file` (0600), `--no-cache-prompt --cache-ram 0`, allow-listed environment. |
| Tools | harness `246c5c17…14dba`, lib `849415af…8047f`, pins `f25b500c…8bbed`, `e1_lib` `6190a975…2e4e`; the synthetic suite passed 137/137 on the committed tree (commit `6b03706` isolates the synthetic probe clock from host sleep). |
| Owner decisions applied | The §16 residuals were accepted for this experiment on 2026-10-18: model and runtime-library replacement windows; protocol-hash-only authorization; S13 thresholds and the ten-sample swap baseline (64 MiB bound); monitor-enforced 600 s limit (spawn → verified exit may exceed it). The `.partial` file stays untouched and unresolved. |

## 2. Results

**Phase 1 — Load Gate (61 samples, all passed, no tolerance used).** Contiguous (60 intervals); AC in every sample; pressure max level 1; swap rise 0.00 MiB; pageouts Δ0 and swapouts Δ0; free memory ≥ 78 %; CPU idle mean 88.0 % (min 71.4 %); no thermal warning; 0 competing processes; 362 GiB free; attended (operator idle 36 s; display-awake assertion held); artifacts verified; no tagged process, no listener on 18080, 0 unresolved records.

**Phase 2 — controls (2.1 s).** `fork()` denied under the profile (5/5, EPERM) and allowed without it (5/5); IPv4 UDP `connect()` to a documentation-range address denied under the profile (5/5) and allowed without it (5/5); loopback TCP allowed under the profile (5/5); `--version` and `--list-devices` (Metal device pattern) passed 3/3 unconfined and 3/3 under the profile. C2d (informational) was `null`. C2 establishes only that the profile's outbound rule applies to an IPv4 UDP `connect()` to a non-local address; it does not establish absence of external TCP egress, DNS or IPv6.

**Phase 3 — pre-spawn and launch.** Artifact re-verification passed; swap baseline median 1,487.5 MiB, spread 8 MiB; monitor ready before the spawn; ready (`/health`) 1.05 s after the spawn; sole listener was the recorded pid and exactly `127.0.0.1:18080`; no descendant observed.

**Authentication matrix (20 calls + 2 chat probes).** `/health` public (200 without or with a wrong key); `/props`, `/slots`, `/v1/models`, `/tokenize`, `/apply-template`: 401 without or with a wrong key, 200 with the key; both unauthenticated chat probes were rejected (401) before any generation. No S10.

**Template and token checks.** Both rendered prompts passed the structural check (messages verbatim and in order, assistant prefix, empty think block); `/tokenize` counts (75 and 87, with and without BOS) equal the server's `prompt_tokens`.

**Seven requests (all HTTP 200, all PASS).**

| Request | finish_reason | prompt / completion tokens | elapsed | accounting | slot idle after |
|---|---|---|---|---|---|
| P1 ×3 | stop | 75 / 4 | 0.34–0.53 s | consistent | yes ×3 |
| P2 ×2 | stop | 87 / 77 | 2.09–2.13 s | consistent | yes ×2 |
| P3 | length | 87 / 16 | 0.62 s | consistent | yes |
| P4 | stop | 75 / 4 | 0.33 s | consistent | yes |

Content hashes are identical across the three P1 runs and across the two P2 runs (the sampling here was deterministic; not investigated). During both P2 runs `/health` and `/slots` were polled every 0.5 s (10 polls each, 20 total): all 200, all ≤ 2 ms, and `is_processing` was seen true in both.

**Resources.** Runtime resident memory 2,801–2,809 MiB (cap 5,120); pressure level 1 throughout; swap flat at 1,479.5 MiB; free memory ≥ 58 % during the run; 60-sample post-unload window: level 1, swap flat, free ≥ 77 %. Spawn → `BOUND` 1.12 s; spawn → `EXIT_VERIFIED` 7.75 s. The server log reports the model loaded 0.88 s after start (the file had just been read for hashing: **warm-file load, not cold-load evidence**).

**Phase 4 — shutdown and exit evidence.** SIGTERM sent (no SIGKILL needed); the child was reaped with return code 0; the conjunction held: reaped, recorded (pid, start) gone, no recorded descendant alive, no extra process-group member, no tagged process, port 18080 free. The E1 classifier returned `PROVEN_TERMINATED`; record state `EXIT_VERIFIED` (basis `owner_waitpid_and_conjunction`), `owner_review_required` false, 0 persistence errors. The runtime was its own session and process-group leader (pid = pgid = sid). Sandbox deny query: available, 0 operations. Attribution: `NONE`. No stop S1–S13 fired. Afterwards: no leftover process, no listener, 0 unresolved records; model and `.partial` file unchanged.

## 3. Evidence rows (design §14; scope as stated, LD-04 classes unchanged)

| Row | Verdict | Scope — what it is | Not established |
|---|---|---|---|
| B4 identity and exit | `SUPPORTS (conditional; 1 lifetime; harness-owned; not reproduced)` | One single-process, non-forking runtime spawned and recorded by the harness; the owner (watching) and a recorded-identity conjunction agree | Successor-side recovery after an owner crash with the real runtime (E3); reproducibility; any Anonymous adapter; router mode; Windows |
| Control during generation | `SUPPORTS` | `/health` and `/slots` answered ≤ 2 ms at every 0.5 s poll in 2 P2 runs (20 polls) | B5 reliability; cancel; probes from a different process |
| Slot-idle signal | `SUPPORTS (consistency only)` | slot idle after each of 7 completed requests | B5 qualification; behaviour after crash or abandonment |
| `finish_reason` | `SUPPORTS` | `stop` ×2 (P2) and `length` ×1 (P3) | other terminal reasons; error paths |
| Input accounting | `SUPPORTS (self-consistency only)` | server `prompt_tokens` equals `/tokenize` counts of `/apply-template` output, 7/7 | that the rendered prompt is the faithful intended input |
| Version / artifact reporting | version present; digest `DOES_NOT_SUPPORT` (scoped) | build `b11440-1a3011cc0` appears in `/props`; the exact 64-hex SHA-256 is absent from `/props` and `/v1/models` | any other digest form or endpoint |
| B3, request cancel, disconnect, late delivery, attempt registration | `NOT_TESTED` | — | Option C |

Every LD-04 row remains `BLOCKED_BY_RUNTIME_EVIDENCE`. A completed generation is `INFERENCE_OBSERVED` and supports no LD-04 row by itself. Changing any register class needs separate review and acceptance and, where architectural, an ADR.

## 4. Discoveries

1. **Integration/privacy risk: the runtime's own responses expose the absolute model path.** `/props` (`model_path`, `model_alias`) and `/v1/models` (`id`) carry the full local path of the model, including the user's home directory, even though the endpoints require the API key. Nothing in the committed view contains it (checked). It is a **risk for any Anonymous adapter, log, diagnostic or error report** that would store, forward or display these responses: a private path (and with it the user's account name) would leave the local runtime boundary, which the project rules treat as private data. Until a design position exists, treat raw `/props` and `/v1/models` bodies as PRIVATE: reduce them to booleans, build info and counts before storing, and never pass them to logs, WEB, cloud or external tools. Whether the path can be suppressed by a runtime option or a different model alias is **not investigated**. This record proposes no mitigation design; it needs an owner decision and, if it constrains the adapter, a design note.
2. **No owner-death linkage in this configuration.** The runtime was started with `stdin` at `/dev/null` (immediate EOF) and kept running, so llama.cpp's stdin-EOF exit watcher (documented for router children, [preflight §2.4](v0-0b2-e2-preflight-runtime-topology.md)) is not active in plain single-model mode. Inference, not a direct test; E3 measures what owner death does.
3. **Startup was fast and quiet.** Ready 1.05 s after the spawn (the model-less router start in E1 needed ~6.7 s); with warm files. The log contains no Metal or offload lines, so GPU use is **not verified** although `-ngl all` was requested and the Metal device pattern matched in Phase 2.
4. **`--chat-template-kwargs '{"enable_thinking":false}'` is deprecated** in b11440 (log warning; the flag still produced the empty think block). A later build may drop it.
5. **Slot selection by prompt similarity was logged despite `--no-cache-prompt`** ("selected slot by LCP similarity", `f_keep` 0.962); every request still re-evaluated the full prompt and reported `cache_n` 0. Not a finding about caching correctness; recorded so a reader of the raw log is not surprised.
6. **The unauthenticated 401 path logs only "Invalid API Key"**; the 12 rejected calls were individually logged but carried no request content.
7. **The harness behaved as designed on a real runtime**: `--list-devices` under `(deny process-fork)` initialised Metal devices (previously unverified); the listener, sole-pid and exact-address checks, the monitor and the shutdown conjunction worked without a stop.

## 5. Limitations that remain

One server lifetime, not reproduced. Warm-file load. GPU offload not verified. No cancel, disconnect or late-delivery test; B3 and B5 not qualified. B4 is conditional on the tested harness-owned, single-process, no-fork configuration; a runtime that forks, detaches or scrubs its environment is outside it (E1 F6, closed here only by the sandbox profile). macOS only, same-user visibility, one OS build. No Anonymous application runtime integration. The model and runtime-library replacement windows remain accepted residuals. The author of the harness, tests and this record is the same, and the only independent review was static (protocol §16).

## 6. Validation of this record

The committed view was checked against the raw run directory on 2026-10-18: all seven raw-artifact SHA-256 values and lengths match; the view's run id, outcome, stops, rows, trials (fields other than polls), gate values, control results, swap baseline (without samples), artifact integrity and model-unchanged flag equal the raw summary; the view contains no home path and no prompt or output text. Protocol and tool hashes equal the committed files at HEAD. Not repeated: the model re-hash (done by the harness at Phase 1), a second lifetime.

## 7. Raw evidence

Outside the repository: `<bench>/e2b/runs/20261018T043949Z-13e9c7/` (`events.jsonl`, `gate-window.jsonl`, `gate-context.json`, `series.jsonl`, `post-unload.jsonl`, `server.log`, `summary.json`, `summary-committed-view.json`) and the execution record `<bench>/e2b/records/20261018T043949Z-13e9c7.json` (contains local paths; never commit). The sanitized view is committed at `docs/evidence/v0-0b2-e2b/summary-committed-view.json` (unchanged copy of the generated view).
