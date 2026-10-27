# v0.1 development prototype — owner wrappers and runbook (P0-1)

## 1. Title, status, and purpose

**Status: IMPLEMENTED and verified with stand-ins (2026-10-27); awaiting owner review and commit. The real-model acceptance smoke (P0-2) has not been run.** The owner authorized P0-1 of the [readiness assessment](#2-repository-context): an owner-operated runbook and minimal `start`/`status`/`stop` wrappers. The final real-Qwen acceptance smoke (P0-2) is an approved **future** milestone and is **not** authorized here. Synthetic-only, loopback-only and unauthenticated development restrictions stay in force. Target: a usable local development prototype on the owner's Mac, **not** V0 release acceptance and not production PRIVATE mode.

**Problem.** Starting the real model takes a `llama_ctl` launch with about ten arguments (pinned digests live only in evidence files), then an application start with several flags, then an ordered stop. Nothing packages or documents it, and the README still describes the fake-model slice.

**Outcome.** Three small shell wrappers under `tools/owner/` that call the existing identity-verified launcher, plus a concise runbook and an updated README.

## 2. Repository context

Read [AGENTS.md](../../AGENTS.md), the [project definition](../../docs/00-project-definition.md) and [domain model](../../docs/01-domain-model.md). Existing mechanisms reused, not replaced: `anonymous.adapters.model.llama_ctl` (`launch --hash`, `status`, `stop --remove-files`; identity from the kernel (pid, start); SIGTERM only; records no paths or keys in its output), `anonymous.config.require_dev_dataset` (dataset isolation), the application's own foreground lifecycle and `GET /api/v1/health`. Contracts: [ADR-0015](../../docs/adr/0015-dev-only-external-llama-runtime-adapter.md) (dev-only external runtime, fail-closed quarantine), [ADR-0016](../../docs/adr/0016-visibly-truncated-assistant-responses.md), [ADR-0017](../../docs/adr/0017-bounded-recent-history-context.md), and the [implementation record](../../docs/implementation/v0-1-external-runtime-dev.md). Pins: [E2-B pins](../../tools/evidence/runtime/e2b_pins.json) and the smoke evidence ([ADR-0017 smoke](../../docs/evidence/v0-1-adr-0017-bounded-context-smoke.md), INCONCLUSIVE). The assessment is in the owner conversation; its conclusions are restated here: no code blocker was found; P0-1 is this work; P0-2 is the acceptance smoke.

## 3. Requirements and acceptance criteria

`tools/owner/start.sh` verifies prerequisites, launches the pinned runtime through `llama_ctl` with `--hash` against the pinned digests, verifies identity, then runs the application in the foreground on `127.0.0.1`. `status.sh` reports runtime, listener and application health and dataset state without content, keys or inference. `stop.sh` stops the runtime only through the identity-verified stop, and only when the application is not running. `docs/operations/v0-1-owner-runbook.md` covers setup, start/check/stop, precautions, the 1400-character budget, truncation versus quarantine, quarantined datasets, diagnosis and clean-shutdown confirmation. The README states the actual state.

Never: download anything, signal by pid or with `pkill`, reset or delete SQLite data, bypass identity, ownership or quarantine rules, store credentials or private paths in the repository, run inference from status or setup.

**Non-goals:** supervisor, daemon or orchestration, UI changes, quarantine recovery (Q3), token accounting, Windows, any real-model run, any change to ADR-0013 to ADR-0017.

## 4. Constraints and open questions

PRIVATE data stays local; loopback only; no authentication. The application has no identity record, so the wrappers never signal it: the owner ends it with Ctrl-C in its terminal, and `stop.sh` refuses while its port is occupied. Open and untouched: Q3, Q5, LD-06, Q-12, Q-19, LD-04 evidence rows. Open for P0-2: every operational path that needs a real runtime is untested here and is reported as such.

## 5. Affected components and intended approach

New: `tools/owner/{lib.sh,start.sh,status.sh,stop.sh,pins.env,owner.env.example,dataset_state.py}`, `docs/operations/v0-1-owner-runbook.md`, `server/tests/tools/test_owner_wrappers.py`. Changed: `README.md`. Machine-specific paths (runtime binary, model) live in an untracked owner file under the owner's home, never in the repository; pins (public digests and labels) live in `tools/owner/pins.env`. Datasets live under the owner's home as `*-dev.sqlite3`; the wrappers never create, move or delete one (the application creates a new file; the wrappers read a dataset only through a read-only SQLite connection that returns run-status counts).

## 6. Work sequence

1. Verify a clean tree at `7a9bc41` (done). 2. Wrappers and helper. 3. Tests with a stand-in runtime and a stand-in application. 4. Runbook and README. 5. `bash -n`, ruff, strict mypy and the focused tests; the existing suites are not rerun except where a finding justifies it. Recovery: all edits are in the working tree; the owner commits.

## 7. Validation strategy

Focused pytest module run from `server/` with `.venv/bin/…`: prerequisite failures, missing or wrong pins, occupied ports, wrong or stale launch identity, refusal to stop while the application runs, partial startup failure with rollback, existing database preservation, status without side effects, command construction. Shell syntax with `bash -n`; `shellcheck` is not installed. Anything needing the real runtime is left to P0-2.

## 8. Progress

- [x] 2026-10-27 Tree verified clean at `7a9bc41`; `llama_ctl`, `composition`, config, pins and tools inspected.
- [x] 2026-10-27 Wrappers (`tools/owner/{lib,start,status,stop}.sh`, `pins.env`, `owner.env.example`, `dataset_state.py`), focused tests (`server/tests/tools/test_owner_wrappers.py`, 50), runbook (`docs/operations/v0-1-owner-runbook.md`) and README update.
- [x] 2026-10-27 Verification: `bash -n` on all scripts; focused tests 50 passed; six mutation checks each caught; full server suite 667 passed (617 existing + 50 new); `ruff check`, `ruff format --check` and strict `mypy` clean; documentation links, sanitization and `git diff --check` checked (see section 11).
- [ ] Owner review and local commit.
- [ ] P0-2 acceptance smoke on this workflow (separately authorized; not part of this task).

## 9. Discoveries

- `/bin/bash` is 3.2: the scripts avoid associative arrays and newer expansions.
- `llama_ctl` already contains launch rollback, stale-record handling and identity-verified stop; the wrappers only sequence it.
- The application cannot be stopped by identity (it has no launch record), so `stop.sh` ends only the runtime and refuses while the application port is occupied.
- `uvicorn` may report a normal Ctrl-C as status 130; `start.sh` treats 0, 130 and 143 as an orderly stop and leaves the runtime up, and rolls back only a runtime it launched itself when the application fails.
- `shellcheck` is not installed; syntax was checked with `bash -n` only. `/bin/bash` is 3.2.
- Test seams (`ANONYMOUS_OWNER_PYTHON`, `_PINS_FILE`, `_PMSET`, `_READY_SECONDS`) exist only so the tests can substitute stand-ins; they are documented as not for normal use.

## 10. Decision log

2026-10-27 — The wrappers do not signal the application (no identity record exists for it); ending it stays a foreground Ctrl-C, and `stop.sh` refuses while the application port is occupied. The runtime stays up after an application stop so the application can be restarted against the same verified runtime; `stop.sh` ends it. Status: owner-directed scope; no architectural change.

## 11. Final outcome

**Changed.** New: `tools/owner/` (`lib.sh`, `start.sh`, `status.sh`, `stop.sh`, `pins.env`, `owner.env.example`, `dataset_state.py`), `docs/operations/v0-1-owner-runbook.md`, `server/tests/tools/` (`__init__.py`, `test_owner_wrappers.py`), this plan. Modified: `README.md` (current phase, a prototype quickstart, the fake-model section renamed). No source under `server/src` or `client/src`, no ADR, no frozen evidence and no LD-04 classification changed; no database was written, migrated or opened except disposable synthetic files in test temporary directories.

**Validation actually performed (2026-10-27).** The wrapper tests run the real scripts, unchanged, from a copy inside a fake repository root with a stand-in runtime started by the real launcher under the real sandbox profile (health-endpoint only), a stand-in application shim, a stand-in `pmset` and disposable owner directories. Covered: prerequisite failures (11 cases), battery refusal and override, unsafe dataset names, usage errors, wrong model or runtime pin (launch refused, nothing left), occupied application and runtime ports (nothing signalled), command construction (exact application arguments, stray application settings not passed on), no secrets or machine paths printed, only `GET /health` reaches the runtime, application failure and a never-ready runtime rolled back, reuse of a verified runtime and refusal to reuse one that does not match the pins, a stale record cleaned and replaced, a record naming a different live process (start, stop and status all refuse and signal nothing; the process stays alive and the record untouched), a retained launch intent (start and stop exit 5), stop refusing while the application port is in use, stop as a no-op with nothing recorded, an unrecorded listener left alone, status with no side effects (tree snapshot equal before and after, twice), existing dataset preserved byte for byte, blocked and unreadable datasets refused and untouched, the read-only dataset probe across states, and one test of the real `anonymous` entry point against the stand-in runtime (health only) with Ctrl-C ending the application and leaving the runtime. Six mutations (dropping `--hash`, ignoring the application port in stop, disabling rollback, accepting a foreign record, allowing a blocked dataset, passing stray environment through) were each caught by the intended tests and the files restored.

**Not tested here (left to the P0-2 acceptance smoke).** A real `llama-server` launch under `sandbox-exec` through these wrappers with the real 2.5 GB model and a real hash of it; real-model readiness timing and the 60 second readiness wait; a real Ctrl-C during a real generation; the wrapper behavior across a real sleep or power event; a hand-run of the documented manual recovery procedures; `shellcheck`; behavior on other macOS versions or with a symlinked home; behavior when `caffeinate` is absent; and the runbook as followed by a person for the first time.

**Remaining limitations.** The wrappers cannot see inside the application, so "idle" for the application rests on the owner's check (the browser and `status.sh`) before Ctrl-C; `stop.sh` only establishes that the application port is free. A blocked dataset still has no recovery path (Q3). The pins live in a plain file in the repository; changing one is a deliberate act. The default dataset name is `anonymous`.
