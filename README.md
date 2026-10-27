# Anonymous

Anonymous is a local-first personal AI system and conversation workspace. It aims to preserve conversations, knowledge, memory, files, and provenance while keeping models replaceable and private information under user control.

**Current phase: architecture and design, plus a v0.1 local development prototype on the macOS development host.** [Vertical Slice 0A](docs/implementation/slice-0a.md) (persistent local chat with a fake model) and [Slice 0B-1](docs/reviews/slice-0b-1-acceptance-handoff.md) (supervised execution lifecycle against a *scripted, in-process* runtime; ADR-0013/0014 Accepted for that scope, 2026-10-12) are closed. Slice 0B-2 runtime evidence (E1 to E3) is closed with limitations and is **not accepted**; every LD-04 runtime-evidence row stays `BLOCKED_BY_RUNTIME_EVIDENCE`. On top of that, a *development-only* path talks to an independently launched local llama.cpp server running the pinned Qwen3-4B-Q4_K_M model ([ADR-0015](docs/adr/0015-dev-only-external-llama-runtime-adapter.md), visibly truncated replies [ADR-0016](docs/adr/0016-visibly-truncated-assistant-responses.md), bounded recent-history context [ADR-0017](docs/adr/0017-bounded-recent-history-context.md), all Accepted for the development build). It has been exercised in three attended real-model sessions, n=1 each ([evidence](docs/evidence/v0-1-adr-0017-bounded-context-smoke.md) for the latest, which is INCONCLUSIVE); owner wrappers and a [runbook](docs/operations/v0-1-owner-runbook.md) make it operable, and a final acceptance smoke on that workflow is still pending.

**The v0.1 development prototype is not V0 release acceptance.** It is synthetic-data-only, loopback-only and unauthenticated, with SQLite as a provisional development adapter; there is no device or session trust, remote or multi-device access, encryption at rest, production PRIVATE mode, quarantine recovery or Windows/iPhone support, and platform acceptance on real browsers, Windows and iPhone is still pending. It is not finished V0 and not an access-capable build. Further implementation still requires a new implementation task.

Start with the authoritative drafts:

- [Project definition](docs/00-project-definition.md): vision, principles, constraints, and provisional technology direction.
- [Domain model](docs/01-domain-model.md): concepts, relationships, invariants, and open questions.

Both source documents use the project name **Anonymous**. The supplied project definition was updated only to normalize the project name; its design content is otherwise unchanged.

The [requirements](docs/02-requirements.md), [V0 scope](docs/03-v0-scope.md), [architecture](docs/04-architecture.md), [logical data model](docs/05-data-model.md), and [security design/threat model](docs/07-security.md) baselines are documented. Concrete security mechanisms and deployment evidence remain open gates before an access-capable build. [Memory design](docs/06-memory-design.md) and [API design](docs/08-api-design.md) remain pending. Document completion is not implementation or release acceptance. Significant architectural decisions are recorded in `docs/adr/`.

For repository work, read [AGENTS.md](AGENTS.md), [ExecPlan guidance](.agent/PLANS.md), and [specialist responsibilities](docs/agents/README.md). Future plans belong in `.agent/plans/`.

`server/` (Python/FastAPI) and `client/` (TypeScript/React) hold the slice 0A code, kept separate so clients never touch persistence. SQLite remains **provisional** pending Windows validation; see the [implementation notes](docs/implementation/slice-0a.md).

## Running the v0.1 development prototype (real local model)

Prerequisites you provide once (the wrappers never download or install anything): `uv sync` in `server/`, `npm install && npm run build` in `client/`, the pinned `llama-server` binary and `Qwen3-4B-Q4_K_M.gguf` already on disk, and an owner file outside the repository (see the [runbook](docs/operations/v0-1-owner-runbook.md), section 1).

```sh
tools/owner/start.sh                # verify pins, launch the runtime, run Anonymous in the foreground
                                    #   (--dataset NAME picks or starts a dataset; browse http://127.0.0.1:8000/)
tools/owner/status.sh               # read-only report: runtime identity, application health, datasets
tools/owner/stop.sh                 # after Ctrl-C of the application: identity-verified runtime stop
```

Read the [owner runbook](docs/operations/v0-1-owner-runbook.md) before the first run: it covers the AC-power and sleep precautions, the 1,400-character context budget, the difference between a visibly truncated reply and a blocked (quarantined) dataset, how to keep a blocked dataset and start a fresh one, diagnosis, and what v0.1 does not claim. **Synthetic data only; no personal data.** The wrappers were verified with stand-ins only; their first use with the real model is the pending acceptance smoke.

## Development and tests (fake model by default; local only, no authentication)

The slice listens on loopback only and has no authentication or device/session layer yet. Use synthetic data only. Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12+ is fetched by uv) and Node.js 20+ with npm.

```sh
# Backend: install, test, type-check, lint
cd server
uv sync
uv run pytest            # unit, persistence, application, HTTP integration, real-process restart
uv run mypy
uv run ruff check . && uv run ruff format --check .

# Frontend: install, test, type-check, build
cd ../client
npm install
npm test                 # vitest
npm run typecheck        # tsc --noEmit
npm run build            # writes client/dist

# Run Anonymous (server also serves client/dist at http://127.0.0.1:8000/)
cd ../server
uv run anonymous-server  # --port, --db-path, --fake-delay-seconds are available

# Alternative: hot-reloading client (proxies /api to the server on 127.0.0.1:8000)
cd ../client && npm run dev   # http://127.0.0.1:5173/
```

The development database defaults to `server/.anonymous-data/anonymous-0b1-dev.sqlite3` (git-ignored). Type `[fake:fail]` in a message to exercise the failure path with the fake model.
