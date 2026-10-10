# Anonymous

Anonymous is a local-first personal AI system and conversation workspace. It aims to preserve conversations, knowledge, memory, files, and provenance while keeping models replaceable and private information under user control.

**Current phase: architecture and design, with the first implementation slice closed on the development host.** [Vertical Slice 0A](docs/implementation/slice-0a.md) (persistent local chat with a fake model) is implemented as a *development-only* slice (platform acceptance on real browsers, Windows and iPhone is still pending): no authentication, loopback only, SQLite as a provisional development adapter. It is not finished V0 and not an access-capable build. Further implementation still requires a new implementation task.

Start with the authoritative drafts:

- [Project definition](docs/00-project-definition.md): vision, principles, constraints, and provisional technology direction.
- [Domain model](docs/01-domain-model.md): concepts, relationships, invariants, and open questions.

Both source documents use the project name **Anonymous**. The supplied project definition was updated only to normalize the project name; its design content is otherwise unchanged.

The [requirements](docs/02-requirements.md), [V0 scope](docs/03-v0-scope.md), [architecture](docs/04-architecture.md), [logical data model](docs/05-data-model.md), and [security design/threat model](docs/07-security.md) baselines are documented. Concrete security mechanisms and deployment evidence remain open gates before an access-capable build. [Memory design](docs/06-memory-design.md) and [API design](docs/08-api-design.md) remain pending. Document completion is not implementation or release acceptance. Significant architectural decisions are recorded in `docs/adr/`.

For repository work, read [AGENTS.md](AGENTS.md), [ExecPlan guidance](.agent/PLANS.md), and [specialist responsibilities](docs/agents/README.md). Future plans belong in `.agent/plans/`.

`server/` (Python/FastAPI) and `client/` (TypeScript/React) hold the slice 0A code, kept separate so clients never touch persistence. SQLite remains **provisional** pending Windows validation; see the [implementation notes](docs/implementation/slice-0a.md).

## Development (slice 0A — local only, no authentication)

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

The development database defaults to `server/.anonymous-data/anonymous-dev.sqlite3` (git-ignored). Type `[fake:fail]` in a message to exercise the failure path with the fake model.
