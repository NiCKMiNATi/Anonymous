# Anonymous v0.1 development prototype — owner runbook

**Status:** operational guide for the owner-operated **v0.1 development prototype** on the Mac. It is **not** V0 release acceptance ([03-v0-scope.md](../03-v0-scope.md) requires authenticated multi-device access, which does not exist yet) and it is not production PRIVATE mode.
**Written for:** the owner, at the terminal, with a fresh conversation in mind. **Plan:** [wrappers ExecPlan](../../.agent/plans/2026-10-27-v0-1-owner-wrappers-and-runbook.md). **Background:** [implementation record](../implementation/v0-1-external-runtime-dev.md), [ADR-0015](../adr/0015-dev-only-external-llama-runtime-adapter.md), [ADR-0016](../adr/0016-visibly-truncated-assistant-responses.md), [ADR-0017](../adr/0017-bounded-recent-history-context.md).

## 0. Limits that always apply

- **Synthetic data only. No personal data.** The build has no authentication, no encryption at rest and no access control.
- **Loopback only** (`127.0.0.1`): the application on port 8000, the model runtime on port 18080. Nothing is reachable from other devices, and nothing is sent to the web or the cloud.
- macOS only. One local Qwen3-4B-Q4_K_M model through the pinned llama.cpp b11440; there is no fallback model.
- The acceptance smoke ([ExecPlan](../../.agent/plans/2026-10-27-v0-1-owner-wrappers-and-runbook.md), P0-2) has **not** been run on this workflow. The wrappers were tested with stand-ins only; their first use with the real model is that smoke.

## 1. One-time setup

The wrappers never download or install anything. You provide:

1. **Server environment:** in `server/`, run `uv sync` once. The wrappers use `server/.venv`.
2. **Browser client:** in `client/`, run `npm install` and `npm run build` once (and again after client changes). The application serves `client/dist`.
3. **The pinned artifacts, already on disk:** the `llama-server` binary (llama.cpp b11440) and `Qwen3-4B-Q4_K_M.gguf`. Their expected SHA-256 values are in [tools/owner/pins.env](../../tools/owner/pins.env). Start hashes both on every launch and refuses any mismatch.
4. **Your owner file** (outside the repository, never committed): create `~/Library/Application Support/AnonymousDev/owner.env` from [tools/owner/owner.env.example](../../tools/owner/owner.env.example) with absolute `RUNTIME_BIN` and `MODEL_PATH`. Optional `LLAMA_PORT` and `APP_PORT` (defaults 18080 and 8000).

Everything the wrappers keep lives under `~/Library/Application Support/AnonymousDev/` (override with `ANONYMOUS_OWNER_HOME`): `runtime/` (private: launch record, per-launch key, the runtime's own log) and `data/` (your `*-dev.sqlite3` datasets). Nothing machine-specific is stored in the repository.

## 2. Start, check, stop

From the repository root:

```sh
tools/owner/start.sh                      # dataset "anonymous" (created empty on first use)
tools/owner/start.sh --dataset NAME       # NAME-dev.sqlite3; a new name starts a NEW empty dataset
tools/owner/status.sh                     # read-only report, any time
tools/owner/stop.sh                       # ends the runtime (after the application has been stopped)
```

**What `start.sh` does, in order:** checks the prerequisites and AC power; checks the dataset name and reads its run state **read-only**; refuses a blocked dataset; refuses if port 8000 is occupied; reuses an already running runtime only if it was launched and hash-verified against today's pins, otherwise launches the pinned runtime through the existing launcher (`llama_ctl launch --hash`, sandboxed, loopback, per-launch key) after cleaning only a *stale* launch record; verifies the process identity, the sole listener and both digests; waits for the runtime's readiness; then runs the application **in the foreground**. If anything fails after this invocation launched the runtime, that runtime is stopped again through the identity-verified stop.

When it prints the address, open **http://127.0.0.1:8000/** in a browser. The terminal then belongs to the application.

**Stopping, in this order:**

1. Make sure no reply is being generated (section 3).
2. Press **Ctrl-C** in the `start.sh` terminal. This ends the application only; the runtime stays up so you can start again quickly.
3. Run `tools/owner/stop.sh`. It refuses while anything still listens on port 8000, because it cannot show that no reply is in flight; otherwise it sends one SIGTERM to the recorded runtime after re-verifying its identity, never escalates, and removes the launch files once the process is confirmed gone.

`stop.sh` never signals the application: the application has no identity record, so ending it stays your Ctrl-C. Optional environment: `ANONYMOUS_OWNER_HOME`, `ANONYMOUS_OWNER_CONFIG`. (Other `ANONYMOUS_OWNER_*` variables are test seams, not for normal use. A stray `ANONYMOUS_*` application setting is ignored and reported; the wrapper passes the supported settings itself.)

## 3. While it runs

- **A generation is active** while the browser shows **"Generating response…"** and your message is marked sending. Real replies took about 1 to 3 seconds for short answers and about 10 seconds for a full-length reply. `status.sh` shows the dataset as `unsettled` while a reply is outstanding.
- **Do not stop the application, stop the runtime, close the lid, let the Mac sleep or lose power during a generation.** Any of these can leave the run's outcome unknown, which blocks the dataset (section 5).
- **Power and sleep.** `start.sh` refuses to run on battery (`--allow-battery` overrides, at your risk) and keeps the Mac awake with `caffeinate -i` while the application runs. It cannot keep a closed laptop awake: keep the lid open and the Mac on AC.
- **One request at a time.** The runtime serves one conversation turn at a time; wait for each reply.

## 4. What the limits mean

- **1,400-character context budget.** Each request carries the newest messages whose combined length fits **1,400 characters**; the newest message is always included. Older messages stay saved and visible, and the reply shows *"The model did not receive the N earliest messages."* A single message longer than 1,400 characters is refused (*"This message is longer than the model can accept; nothing was sent."*) without blocking anything. Characters are a proxy for the model's 2,048-token window, **not** token accounting: plain English text fits comfortably; long, dense or non-English text can exceed the window in a way the character count does not detect, and that ends in an error that **blocks the dataset**. Keep messages short and plain for this prototype. (Conversations created now use this behavior; a conversation made earlier in an older dataset keeps the previous whole-history behavior and is refused once its history passes the cap.)
- **Visible truncation is not a failure.** A reply that reaches the output limit (384 tokens) is saved, marked *"This reply was cut off at the model's output limit."*, and the dataset stays usable. Ask a shorter question or continue by asking for the rest.
- **Quarantine (a blocked dataset) is different.** If an earlier run **could not be shown to have ended** (the runtime stopped or slept mid-reply, a deadline passed, an HTTP error or an empty or rejected reply, or the application ended during a generation), Anonymous refuses all new generation in that dataset, **permanently**, across restarts. There is no reset or force path in this prototype.

## 5. A blocked dataset

Signs: `status.sh` shows `generation: blocked` / `blocked runs=...`, the browser refuses new messages with *"New generation is blocked…"*, and `start.sh --dataset NAME` refuses with *"is BLOCKED"*. **Nothing is lost:** the history stays readable and the file is never modified by the wrappers.

1. Stop the application (Ctrl-C), as in section 2. You do not need to stop the runtime.
2. **Keep the blocked file** (copy it if you want a backup; never delete or edit it). To read its history, run `tools/owner/start.sh --dataset NAME --allow-blocked`.
3. Start a **fresh dataset** with a new name: `tools/owner/start.sh --dataset NAME-2`. It starts empty (synthetic data only); there is no carry-forward of conversations between datasets in this prototype.
4. Restarting, relaunching the runtime or stopping and starting again does **not** clear a block.

The application applies pending schema migrations when it opens an existing dataset; copy a dataset you care about before opening it with a newer build.

## 6. Diagnosing

All wrapper messages state a fixed reason and no path, key or message content. Run `tools/owner/status.sh` first.

| Message or sign | Meaning and next step |
|---|---|
| *owner configuration not found* / *RUNTIME_BIN … / MODEL_PATH …* | Create or fix `owner.env` (section 1). |
| *virtual environment is missing*, *client is not built* | Run `uv sync` in `server/` or `npm run build` in `client/` yourself. |
| *not on AC power* | Connect power (or `--allow-battery`). |
| *artifact_digest_mismatch* | The model file or the binary is not the pinned one. Nothing was started. Replace the file with the pinned artifact; do not change the pin to fit. |
| *port N is occupied* | Another program (or another Anonymous) holds the port. Nothing was signalled. Use `lsof -nP -iTCP:N -sTCP:LISTEN` to see what; stop it yourself if it is yours. |
| *stale launch record could not be cleaned safely* / `identity_mismatch` | The recorded process id now belongs to a different process, so nothing was signalled or removed. If `lsof -nP -iTCP:18080 -sTCP:LISTEN` shows no listener and no `llama-server` process is running for you, delete `launch.json` and the `key-*` files in the `runtime/` folder by hand, then start again. If a runtime is still listening, do not guess: follow the nonce procedure below. |
| *recovery file* / `unresolved_launch_intent` / `runtime_may_survive_unrecorded` / `spawn_status_unknown` | An earlier launch was interrupted and a runtime may exist without a record. **Do not launch again.** Follow the [intent recovery procedure](../implementation/v0-1-external-runtime-dev.md#recovery-from-a-retained-launch-intent-launch_intent_without_record-unresolved_launch_intent-spawn_status_unknown-runtime_may_survive_unrecorded): locate the process by the nonce the launcher printed, verify identity, and only then terminate it and delete the retained files. |
| *did not report ready* | The runtime started but did not answer `GET /health` in 60 seconds; start rolled it back. Check the runtime's own log in `runtime/` (it contains local paths; do not share it). |
| *still running after SIGTERM* (stop, exit 4) | The runtime ignored the signal. It is not escalated. Wait, rerun `stop.sh`; killing it is your decision. |
| Application exits at start with *Refusing to start* | The configuration check failed before anything was opened; the wrapper rolled back a runtime it launched. |

## 7. Confirming a clean shutdown

`tools/owner/stop.sh` ends with **"Clean shutdown confirmed: no listener on 18080 or 8000, no launch record, no key file."** To check by hand:

```sh
tools/owner/status.sh                         # "Result: consistent (nothing running)."
lsof -nP -iTCP:18080 -iTCP:8000 -sTCP:LISTEN  # prints nothing
```

Retained on purpose and never committed: the runtime's log, the datasets, and an empty `llama-cache` folder under `runtime/`.

## 8. What v0.1 does not claim

Not V0 release acceptance. No authentication, device or session trust, remote or multi-device access, encryption at rest, or production PRIVATE mode. No recovery from a blocked dataset, no token-accurate context accounting, no turn-aware context selection, no Memory, personas or branching, no regenerate or continue, no Windows support. Reliability and reply quality are unmeasured: the real model has been exercised in a handful of attended sessions only ([smoke records](../evidence/v0-1-adr-0017-bounded-context-smoke.md), the last of which was INCONCLUSIVE). These wrappers add no supervisor and do not change any accepted execution semantics.
