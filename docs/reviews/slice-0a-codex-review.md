# Anonymous Slice 0A — independent Codex review

Date: 2026-10-07 (Asia/Tokyo). Scope: **Persistent Local Chat with Fake Model**. Review only; no product fixes implemented.

**Verdict: PASS_WITH_REQUIRED_FIXES**

The server's current fake-model path is structurally sound. Independent transaction, concurrent-request, replay and real-process recovery probes found no duplicate generation, partial published response, or loss of confirmed history in the tested cases. The frontend has a high-severity selection/history race and four additional bounded bugs across the UI and development-origin configuration. Repair these before attaching a real runtime. The current ModelPort is a useful replacement seam, but its synchronous success/exception contract does not close LD-04.

## 1. Review scope and evidence

Read fully: AGENTS.md, README, project definition, domain model, requirements, V0 scope, architecture, logical data model, security baseline, implementation notes, accepted ADRs 0001–0012, the completed Slice 0A ExecPlan, and all specialist responsibility files. Inspected all production modules under `server/src/anonymous/` and `client/src/`, configuration, original tests, and the experimental SQLite schema. No separate **CODEX REVIEW HANDOFF** was found by filename/content search. The implementation plan's assertions were treated as claims to verify.

This is an independent single-reviewer assessment with executable probes, not independent specialist-agent approvals. No external research, private data, real inference, or dependency installation was needed. SQLite remains provisional pending Windows evidence. Production authentication, explicit generation retry, context budgeting, and comprehensive recovery are deliberately outside 0A.

The repository was entirely untracked at the start. A pre-review SHA-256 inventory was used to verify preservation of existing source, test, configuration and documentation files; a git diff alone would not establish that.

Review artifacts:

- [This report](slice-0a-codex-review.md).
- [Review ExecPlan](../../.agent/plans/2026-10-07-slice-0a-independent-review.md).
- [Backend adversarial tests](../../server/review_tests/test_slice0a_review.py), explicitly selected rather than included in the normal pytest testpaths.
- [Frontend adversarial tests](../../client/review-tests/slice0a.review.tsx) and [opt-in configuration](../../client/review-tests/vitest.config.ts). The `.review.tsx` filename keeps these out of default Vitest discovery.

The new suites contain ordinary failing assertions for known bugs, not xfail/skip annotations. Their nonzero exits are expected evidence of unresolved defects. They must not be described as passing suites. The frontend probes reuse the existing transport fake, with additional controlled response ordering; the backend probes use actual SQLite transactions and HTTP routing.

## 2. Baseline validation

Working directory is stated per command. Dependencies were already installed. README installation commands `uv sync` and `npm install` were unnecessary and were not run. No lockfile was changed. `npm` was absent from the login-shell PATH; the existing fnm installation was made available using:

```sh
export PATH=/Users/user/.local/share/fnm/node-versions/v24.21.0/installation/bin:$PATH
```

| Directory | Exact check command | Result |
| --- | --- | --- |
| `server` | `uv run pytest` | **95 passed**, 4.22 seconds; includes 4 process tests, HTTP integration, application, persistence and unit tests. No skips or reported warnings. |
| `server` | `uv run mypy` | **Pass**, no issues in 49 source files. |
| `server` | `uv run ruff check .` | **Pass**. |
| `server` | `uv run ruff format --check .` | **Pass**, 49 files formatted at baseline; 50 after adding the review test file. |
| `client` | `npm test` | **19 passed**, 2 files; no skips or reported warnings. |
| `client` | `npm run typecheck` | **Pass**. |
| `client` | `npm run build` | **Pass**, TypeScript and Vite build; 24 modules transformed. |
| `server` | `uv run pytest review_tests/test_slice0a_review.py -q` | **17 passed, 1 failed**, 1.52 seconds. Failure: R5 IPv6 same-origin request gets 403. |
| `client` | `npm exec vitest run -- --config review-tests/vitest.config.ts` | **2 passed, 5 failed**, 7 tests. Two failures prove R1; one each proves R2–R4. |

Environment observed: macOS, uv-managed Python 3.12.14, pytest 9.1.1, Node 24.21.0, Vitest 5.0.3, Vite 8.3.3. There is no configured frontend linter. The review-only TypeScript probes are executed by Vitest and are outside the existing `tsconfig.json` include list; no separate strict type-check claim is made for those artifacts.

A temporary real server was also started from `server` with:

```sh
uv run anonymous-server --db-path /tmp/anonymous-review-browser.vtZgLq/browser.sqlite3 --port 18765 --fake-delay-seconds 2
```

A local `uv run python`/httpx2 smoke probe verified HTTP 200 for built HTML/JS/CSS, conversation creation, a successful send, same-ID replay returning 200 with unchanged two-message history, and `[fake:fail]` returning a failed run. This verifies serving/API integration, **not rendered-browser behavior**. The temporary server was stopped after review.

Fresh visual/browser smoke could not be completed: Chrome was unavailable, browser discovery returned no connections, and native Safari access reported pending Accessibility/Screen Recording permissions. No settings were changed. The implementation's earlier Chrome smoke is historical evidence, not independently rerun here. Windows/Edge, Safari/iPhone, physical power loss, actual disk failure and long-running real inference remain unverified.

The first review-only Vite-config run warned about an extensionless import; the new review configuration was corrected to include `.ts`, and the final run had no such warning. Review-artifact lint/style issues were corrected only in the new test file. All failures in the final adversarial runs above remain visible.

## 3. Severity-ranked findings

### R1 — Late history responses can replace the selected conversation and regress confirmed history

**HIGH · BUG · Blocks attaching a real runtime: yes.**

Affected: FR-01/FR-02, NFR-03, LM §10 stale-view semantics, C01 presentation correctness. The backend's identity/order invariants remain intact, but subsequent user input can be committed to a different conversation than the visible transcript suggests.

Evidence: `client/src/App.tsx:54–66` applies every `getConversation(id)` result to one shared `detail` without checking selection or request freshness. Send completion at lines 110–112 reloads its original conversation. Rendering at lines 211–215 accepts any `detail`; sending at lines 133–135 targets `selectedId`.

Reproduction: start a delayed send in Alpha, select Beta and let Beta load, then complete Alpha's send. The URL and selected navigation item still identify Beta, but the heading/history become Alpha. The review test receives **Alpha where Beta is required**. A separate probe holds an old refresh snapshot, completes a send and its newer history load, then releases the old response: the newly confirmed response disappears from the UI while remaining saved on the server.

Consequence: misleading history and run/busy status; a follow-up typed against Alpha's displayed history is addressed to Beta. The stale-refresh variant can also falsely keep a settled conversation blocked or appear to lose saved content.

Direction for Claude: bind detail, loading/error state and draft restoration to the intended conversation; reject obsolete request results using selection/request generations or equivalent cancellation plus freshness checks. Ensure send completions can update their conversation without replacing another selected view. Keep the composer disabled unless displayed detail matches the selected target. Guard same-conversation out-of-order refreshes as well as cross-conversation changes. Add tests for late errors and rapid A→B→A changes.

### R6 — The fake-model lifecycle contract is insufficient for supervised real inference

**HIGH · DESIGN_GAP · Blocks real-runtime integration: yes; intentionally outside complete 0A recovery.**

Affected: LD-04, LM §8/§12, CB-03/CB-05/CB-06, ADR-0002/0003. This is not a claim that omitted production recovery is a current fake-adapter bug.

Evidence: `application/ports/model.py` exposes only `identity` and blocking `generate`. `application/execution.py:95–112` settles any ordinary adapter exception as failure, while unknown commit outcomes propagate without an observation/termination/finalization protocol. There is no runtime correlation, supervision, cancellation acknowledgment, or durable distinction for “output received but publication uncertain.”

The eight real-connection commit-fault cases show that replay after an uncertain admission can return `pending` forever in the current process, and replay after uncertain dispatch/publication/failed settlement can return `in_flight` after the coordinator has already exited. No background executor remains for those attempts. Admission stays closed, which is safe, but replay reports stored facts rather than completing reconciliation. Restart converts pending to failed and in-flight to indeterminate; the latter is still permanently closed in this slice. A model output observed before an uncertain publication is not retained as a separate durable execution-completion fact.

Consequence: the advertised adapter/composition-only replacement is valid for a compatible synchronous test adapter, not sufficient evidence for a separate runtime whose work may survive a timeout or server restart. Treating a real transport exception as proven runtime termination could release admission too early. Current conservative uncertainty must not become normal successful recovery UX.

Direction: before 0B, resolve the minimal LD-04 gate for the selected runtime: distinguish failed dispatch, possible dispatch, observed execution/termination, finalization and publication outcome; define bounded observation or confirmed termination, safe admission release and explicit eligible retry using a new run on the same saved user message. Preserve known execution facts; never infer nonexecution from missing acknowledgment. Document required port/application changes and tests. Do not implement the deferred recovery system as part of this review.

### R2 — “Discard and reload” converts an unconfirmed send into a fresh prefilled intent

**MEDIUM · BUG · Blocks attaching a real runtime: yes.**

Affected: REC-02, LM-05, V0-D04 reconnect/reconciliation semantics and basic UI correctness.

Evidence: `client/src/App.tsx:142–147` restores the pending content as a draft, clears the only submission identity, and starts a quiet history reload. A later Send generates a new ID at line 135. `MessageList.tsx` labels the action “Discard and reload” beside an assurance that retrying cannot save the same message twice.

Reproduction: lose the HTTP acknowledgment after backend success, choose Discard and reload, then click Send on the automatically restored draft. The review probe observes **two saved user messages instead of one**, with distinct submission IDs. The backend correctly regards the second ID as a new intent; this is a client reconciliation/interaction bug, not a failure of server deduplication. A quiet reload also leaves a window before refreshed run state is known.

Consequence: duplicate history and unnecessary generation from a recovery control that appears to discard an unconfirmed operation. If the first request is still active the second may instead be refused as busy.

Direction: preserve original correlation until reconciliation establishes the outcome. Discarding the pending UI should not silently prefill a new send of possibly committed content. If deliberate “send again as a new message” is offered, make that action explicit and separate from safe replay. Confirmed saved content should leave the composer empty; block dependent sending while reconciliation is outstanding.

### R3 — Malformed percent encoding in the selected-conversation hash crashes the client

**MEDIUM · BUG · Blocks the fix-completion gate: yes; bounded client repair.**

Affected: slice A12 malformed-ID handling, C01 error/reconnect behavior, FR-01.

Evidence: `client/src/useHashSelection.ts:8–10` calls `decodeURIComponent` without handling `URIError`, both during initial state creation and later hash changes.

Reproduction: load `/#/c/%`. The review test throws **URIError: URI malformed** during `<App />` rendering instead of displaying a recoverable invalid selection. Backend malformed-UUID handling does not protect this pre-request failure.

Consequence: unusable client until the user edits the URL; an untrusted link can trigger it without affecting saved history.

Direction: safely parse untrusted hashes, render an invalid/missing-selection state, and preserve access to conversation navigation. Test invalid percent escapes, invalid UTF-8, malformed IDs and hash changes after mount.

### R7 — Full FR-15 commit-time acceptance has not been established

**MEDIUM · TEST_GAP with a timestamp-contract question · Blocks claiming full FR-15 compliance; no demonstrated ordering defect.**

Affected: FR-15 delayed-commit acceptance, LM-03, Slice A7/A9 evidence claims.

Evidence: `sqlite/store.py:248` samples the user's instant before inserts and result reads; line 320 does the same before assistant publication. `connection.py:78` commits later. The implementation plan honestly calls this an approximation, but its overall acceptance conclusion does not supply a delayed-commit result. Original clock tests establish absolute encoding, retention and timestamp-independent ordering, not correspondence to actual commitment under delay.

The new characterization test advances a synthetic wall clock by one minute between timestamp sampling and actual COMMIT. Both messages retain the earlier sampled instant; order remains correct. That passing characterization is **evidence of the approximation**, not a passing strict FR-15 delayed-commit acceptance test. No physical disk timing tolerance is inferred from it.

Direction: explicitly document and review the supported timestamp meaning/precision and delayed-commit acceptance boundary. Add a test that delays before commitment rather than merely supplying equal/decreasing clock values. Do not silently redefine FR-15 as request-arrival or generation-completion time, or claim an exact engine commit clock that is not available. Any accepted semantic relaxation belongs in the affected requirements/design documentation, with an ADR if architectural. This review makes no such decision.

### R4 — An initial HTTP storage error has no in-app recovery action

**LOW · BUG · Not a foundational milestone blocker; include in bounded fixes.**

Affected: slice A12/backend-unavailable state and C01 recovery usability.

Evidence: `App.tsx:37–50` sets `serverDown` only for transport failures. On the first HTTP 503, `conversations` remains null; lines 185–197 display only the error and hide conversation controls. The only global Retry button is conditional on `serverDown` at lines 173–179. There is no detail yet to expose Refresh.

Reproduction: return `503 storage_unavailable` for the initial list request. The review test finds the error but **no Retry or Refresh button**. Restoring the backend does not trigger another fetch automatically. A browser reload is a workaround.

Direction: give list/detail error states an explicit retry path, distinguishing unreachable transport from server/storage failures without leaving a dead-end screen. Test both network failure and valid HTTP error responses.

### R5 — Accepted IPv6 loopback hosting rejects its own browser Origin

**LOW · BUG · Not a blocker for default IPv4; repair or explicitly remove advertised IPv6 support.**

Affected: slice A1/A2/A3, meaningful same-origin development guard.

Evidence: `config.py` includes `::1` in supported CLI hosts and `[::1]` in allowed Host values, but `allowed_origins()` at lines 41–43 constructs only IPv4 and localhost origins.

Reproduction: configure `host='::1'`, then POST to `http://[::1]:8000/api/v1/conversations` with `Origin: http://[::1]:8000`. Real FastAPI/SQLite integration returns **403 forbidden_origin**, although this is the server's own origin. The backend review test fails at the expected 201 assertion.

Consequence: page/GET access can work while browser mutations fail on an explicitly allowed bind address. This is denial of legitimate access, not an origin-bypass vulnerability.

Direction: construct and validate exact supported origins consistently, including bracketed IPv6 and the configured port. Keep hostile/null origins rejected; do not weaken the guard to a wildcard.

### Finding inventory

| Severity | BUG | DESIGN_GAP | TEST_GAP |
| --- | --- | --- | --- |
| CRITICAL | None found | None | None |
| HIGH | R1 | R6 | — |
| MEDIUM | R2, R3 | — | R7 |
| LOW | R4, R5 | — | — |

**INFORMATIONAL / DEFERRED_BY_SCOPE:** production auth/device/session/CA/overlay controls; explicit generation retry; context budgets/omission reporting; input-contribution tables; Windows/iPhone validation; pagination; conversation-create idempotency; backup/restore; robust cross-alias/global authority enforcement. These are not classified as bugs merely because absent. Their existing gates remain binding. No new production-security prerequisite before synthetic loopback-only 0B is justified by this review.

## 4. Architecture findings

| Responsibility | Independent assessment |
| --- | --- |
| Domain independence | Domain imports stdlib and its own types/errors only. No FastAPI, SQLite, HTTP DTO, React or fake-runtime dependency. |
| Persistence boundary | ConversationService, ExecutionCoordinator and ContextBuilder depend on Anonymous-owned purpose-specific protocols. Only the SQLite adapter package imports sqlite3. No SQL or SQLite exception type leaks into use cases. Transaction guarantees are stated in the port, implemented by the adapter. |
| Model boundary | Coordinator depends on ModelPort, not FakeModelAdapter; ConversationService delegates to the coordinator. Alternate test ModelPort implementations run against the same durable store without domain/client changes. Real supervised-runtime requirements remain R6. |
| ContextBuilder | Reads the committed prefix through the triggering message and returns immutable role/content tuples, with no persistence IDs or provider objects. It neither writes sources nor invokes inference. No budget yet, explicitly deferred. |
| Client authority | Server ignores client ordering, timestamps, owner and run status; extra DTO fields are rejected. Client renders server-provided message order and instants. R1 compromises the association between the displayed view and the selected target, not server ordering authority. |
| Composition/API | Composition names concrete adapters. API translates DTOs/errors and resolves the dev owner, with no SQL. A limited outward coupling remains: API imports concrete `Application`, and health calls its `SqliteStore.schema_version()`; future store replacement must update lifecycle/health wiring, not domain semantics. This is not a core boundary break. |
| Owner scope | External create/list/read/admission paths are owner-scoped. Internal run mutations and HistorySource use run/conversation IDs following authorized admission; the blanket comment that every user-data method is owner-scoped is too broad. Future C03 integration must preserve the internal trusted-caller boundary. No reachable owner bypass was found in 0A. |

Application domain transition helpers and SQLite conditions duplicate a small state vocabulary. `can_transition` itself is not what enforces production transitions; the adapter's conditional updates are. Review checked those predicates rather than accepting the standalone domain transition test as sufficient proof.

## 5. Transactions, UNKNOWN outcomes, and ordering

### Coherent write boundaries

| Boundary | Implementation and fault result |
| --- | --- |
| Admission | `BEGIN IMMEDIATE` precedes replay lookup, ownership/busy decisions, next-position calculation and all three inserts. Message, pending run and submission association commit together. Review triggers aborting each insert leave all three absent and invoke no model. |
| Dispatch | Conditional update accepts only pending and stores model/runtime/dispatched time before model invocation. Failed known write can settle pending as failed. Unknown commit propagates and invokes no model. Two dispatches cannot both transition the same run through the adapter. |
| Publication | Run must be in-flight. Assistant row and succeeded update share one transaction. The unique producing-run reference and same-conversation FK retain attribution. A trigger aborting the succeeded update rolls back the assistant and the coordinator records `response_not_saved` if settlement succeeds. |
| Failed settlement | Conditional pending/in-flight→failed update, with code/time, no assistant insert. Known model failure preserves the user. If settlement itself fails, no fabricated durable failed status is returned. |
| Recovery | One write transaction converts all pending to failed and in-flight to indeterminate before readiness, behind the development instance guard. No model call. |

SQLite serialization is not the sole argument: the **read/check/allocate/write sequence all occurs after acquiring the immediate write lock**, and uniqueness constraints back it up. No TOCTOU window between a pre-transaction “not found” check and insertion was found. Publication computes the next position under the same kind of write lock. Equal timestamps in all review clock fixtures do not affect positions. The original decreasing-clock tests also pass.

History reads use `BEGIN` with one connection for conversation/messages/runs, giving one committed snapshot. Reads are ordered by `position`; context reads use a fixed prefix by the triggering message's position. Run lists use request timestamps and rowid, so their “oldest first” comment is a clock-based presentation ordering, not a guaranteed attempt chronology under clock reversal. No current UI or admission decision depends on that ordering.

### Exact uncertainty windows

`write_transaction()` classifies SQLite failures while executing COMMIT as `StorageOutcomeUnknown` and then attempts rollback. Statement/BEGIN failures are `StorageFailure`. Classification is deliberately conservative: a pre-commit error followed by successful rollback may have a known absent effect, but callers still receive UNKNOWN. A connection close or OS failure was not simulated as a physical disk failure.

Review injection wraps a **real connection** and raises a SQLite error immediately before or immediately after its real COMMIT. This exercises rollback/confirmation handling and both possible durable outcomes, without claiming all SQLite hardware failure modes produce both outcomes.

| Failed confirmation | Durable facts if COMMIT did not happen | Durable facts if COMMIT happened | Same-ID replay after storage recovery |
| --- | --- | --- | --- |
| Admission | No message/run/submission; no model call. | User + pending run + submission; no model call. | Absent case can accept the original intent and run once; present case returns pending and does not run. |
| Dispatch | User + pending run; no model call. | User + in-flight run with identities; still no model call by this coordinator. | Returns stored pending/in-flight; no fresh generation. |
| Publication | User + in-flight run; model ran and returned, no assistant committed. | User + assistant + succeeded run atomically. | Returns in-flight or original saved success; no second output/run. |
| Failed settlement | User + in-flight run; model failed, failed disposition not durable. | User + failed run. | Returns in-flight or original failed run; no retry inference. |

Replay of committed success establishes the existing result safely and preserves IDs, positions and instants. Replay of pending/in-flight/indeterminate is safe against duplication but **does not establish a final outcome**. R6 records that limitation. A response lost only after backend success is client uncertainty; the stored run remains succeeded.

Frontend network and 5xx errors retain the submission ID and show unconfirmed text. “Retry sending” uses that ID and is safe on the tested success and failure paths. A successful replay may return pending/in-flight, after which the UI reloads history and keeps sending paused. A 4xx is treated as definite refusal; contract changes must not use a 4xx to describe an accepted-but-uncertain operation. R2 is the unsafe recovery interaction outside the same-ID retry path.

## 6. Idempotency and concurrency

The submission key is `(owner_user_id, submission_id)`. Stored conversation ID and SHA-256 of the exact UTF-8 content bind its meaning. Reuse with changed content or another conversation returns conflict. Same content with a deliberately new ID is a new intent. Records are immutable and retained; no expiration permits reuse. Owner identity comes from the server dependency, not submitted JSON.

Eight barrier-released identical HTTP requests produced one 201 and seven 200 replays, exactly one model call, one user/assistant pair and one run. Eight requests sharing one ID but different content produced one 201 and seven 409 conflicts, with the same at-most-one effects. The requests may observe pending, active or terminal state depending on scheduling; exact old HTTP-response reproduction is not promised.

Original and added tests cover replay after success, failure, rollback, active execution and restart-indeterminate state, plus target/content conflicts. The original simultaneous-new-send test correctly permits both submissions if the first fully settles before the second obtains admission; a barrier is not evidence both evaluated an active run. The blocked-model test checks the actual busy refusal separately. Frontend double-click produced one submission. No backend deduplication/position defect was found.

## 7. Lifecycle and crash matrix

Implemented transitions: pending→in-flight or failed; in-flight→succeeded, failed or indeterminate. Terminal succeeded/failed runs are immutable. Indeterminate has no supported outgoing transition and stays admission-blocking. Conditional adapter writes reject publish-before-dispatch, double dispatch, double publish, and settlement after success. The database additionally enforces status field consistency and immutable history, but is not a complete independent state-machine validator for arbitrary privileged SQL; the supported adapter is the mutation boundary.

| Crash point | Durable state / restart interpretation | User-visible and retry behavior | Evidence |
| --- | --- | --- | --- |
| After user commit, before dispatch | Pending becomes failed(`interrupted_before_dispatch`); user retained. | Saved user + failed run; replay resolves same failed attempt. New message may proceed; generation retry is deferred. | Fresh process startup on durable pending fixture passed. |
| After dispatch, before model call | In-flight becomes indeterminate; durable intent cannot prove invocation. | Readable user; conversation closed; replay cannot invoke. | Dispatch after-COMMIT fault plus reopen passed; crash-window interpretation by code. |
| During model execution | In-flight becomes indeterminate. | No fake completion; no fresh send or replay inference. | Actual SIGKILL during delayed fake generation and HTTP restart passed. |
| After model return, before publication | In-flight; output is transient and lost on crash. | Indeterminate after restart; known completion is not separately durable. | Code inspection, publication-before-COMMIT fault; LD-04 gap. |
| During publication | Transaction either rolls back or commits assistant+succeeded together. | Rolled-back branch becomes indeterminate; committed branch returns original success. | Both COMMIT sides and second-statement abort tested; not a power-cut claim. |
| After publication commit, before HTTP response | Succeeded with both messages; unchanged after restart. | Replay returns the existing response, never re-generates. | After-COMMIT injection; baseline successful-process restart; UI lost-ack replay. |
| During failed-run settlement | Old pending/in-flight or committed failed. | Restart settles pending as failed, in-flight as indeterminate, or preserves failed. | Both settlement COMMIT sides tested. |

Cases involving possible/live runtime execution, unrecoverable output, uncertain finalization and safe explicit retry require LD-04 before real inference. Merely deleting recovery rows or unblocking indeterminate conversations would violate the reviewed safety boundary. Development users can use another conversation; deleting the dataset is not a preservation-oriented reconciliation design.

The original four process tests kill/restart only after a completed exchange, plus instance/bind refusal. They do not themselves prove a crash during generation. The new SIGKILL test supplies that missing active-run evidence. The pending test launches a fresh process over an admitted fixture; it does not claim to have paused/killed an executing process at that exact instruction.

## 8. SQLite adapter, schema and migration review

Every application data connection uses the factory, enables and verifies foreign keys, requests WAL, sets synchronous FULL, and uses a five-second busy timeout. Connections are short-lived and closed in finally blocks. Write errors roll back; multi-read snapshots end via rollback. Model calls hold no database transaction. The sidecar instance lock uses a separate sqlite3 connection with no relational data/FKs; it is not an exception to application referential integrity.

WAL's returned mode and synchronous value are not explicitly verified like foreign keys. Current local tests exercise WAL behavior; alternate/ineligible filesystem durability is not established. Busy timeout failure reports storage unavailability rather than silently queueing a new accepted message. No network-primary-storage or power-loss claim is justified.

Migrations are sequential numbered resources with checksums, per-migration explicit transactions, refusal of changed applied files and unknown future versions, and rollback on failed migration. Guard acquisition precedes migrate/owner/recovery in supported startup. The migration metadata bootstrap is outside an individual migration transaction; an interrupted fresh creation is recoverable by the current runner. The runner is not a general corrupt-schema repair system, nor should it silently reset a damaged dataset.

The Mac experiment has `fx_*` tables, different state labels, frontier/provenance/access fixtures and a conversation counter. Slice 0A has its own versioned users/conversations/messages/model_runs/submissions schema and explicit documented choices. It was not simply installed as the production schema. Shared techniques such as immediate transactions and a partial unique admission index were deliberately carried forward; they do not finalize SQLite selection.

A path-derived sidecar cannot be treated as proven exclusion across aliases/copies or remote filesystems. That limitation is already disclosed in the plan/InstanceGuard and belongs to ADR-0011/0012 evidence, not a newly invented production guarantee. Default same-path second-process refusal passes.

## 9. API, frontend and timestamps

API behavior is internally coherent for supported inputs: create 201; new accepted send 201; replay 200; malformed canonical identifiers 400; missing conversation 404; busy/content-binding conflicts 409; invalid/empty/oversized message 422; storage failures/unknown 503. Generation failure is a 201 accepted submission with `run.status=failed`, preserved user and no assistant. DTOs forbid extra fields and expose server-owned history, run and provenance state. Validation/storage/unexpected error handling avoids raw submitted values/vendor details in the tested cases. Routing-level 404/405 responses need not have the custom domain envelope; the client provides a generic fallback for error bodies it cannot interpret.

Successful JSON is TypeScript-cast, not runtime shape-validated. Malformed JSON is treated as unknown server response; syntactically valid but structurally invalid success JSON could break rendering. The bundled server's response models substantially constrain this today. Add focused contract/error tests as the API evolves; this is not evidence of a current valid server response mismatch.

Frontend success is based on rereading saved history, not optimistic fabricated canonical messages. Pending text has no invented commit timestamp. Failure text distinguishes a saved user from absent response. Text is rendered inertly through React, without rich HTML or external media fetching. Enter sends, Shift+Enter preserves a newline, and the composing check prevents a normal IME Enter from submitting. Double-click inhibition passed. Full browser IME/touch/accessibility behavior was not independently exercised.

Refresh during generation loads durable user/run facts and pauses sending; completion still requires another authoritative read if the original request was lost. There is no polling promise. Pending IDs exist only in memory; refreshing the whole browser loses unconfirmed interaction state, but server-saved history and blocking run state remain. This slice has no persistent client outbox. Reentering identical text after losing local correlation is a new intent, not evidence that content hashes globally deduplicate messages.

All three unsettled statuses currently share a “being generated or unresolved” explanation. This avoids asserting completion, but lacks an actionable distinction between an active run and an indeterminate run that Refresh can never resolve in 0A. Address this alongside R6; do not present Refresh as a recovery mechanism for permanently blocked state.

Message instants are server-assigned aware UTC values stored/wired as fixed-width absolute strings. They survive reads, replay and process restart. Client-local timezone affects formatting only; message order remains the server-provided sequence by position. Each message has visible `<time>` text beside authorship; the full date/time/zone is in `title`, with `dateTime` preserving the wire instant. Unit tests cover timezone/date boundaries and backward/equal clock ordering. Tooltip-only full detail is permitted by FR-15, while touch access and actual supported-device rendering remain future acceptance evidence. R7 limits the commitment-instant claim.

## 10. Development security assessment

**Acceptable as the stated synthetic, loopback-only development boundary, with R5 corrected; not production authentication.**

The supported CLI defaults to 127.0.0.1 and refuses 0.0.0.0/non-loopback before touching storage. Vite defaults to 127.0.0.1. No public listener, external model path, tools, analytics, cloud fallback or secret credential default was found. Host filtering meaningfully blocks foreign DNS names; present foreign/null Origins fail closed against a fixed allowlist. No-Origin CLI clients are deliberately permitted, so these checks are containment rather than authentication. The dev-origin allowlist does not authorize general websites. R5 is overly restrictive IPv6 handling, not wider access.

Responses have no-store, nosniff, referrer protection and CSP on the normal guarded paths. React displays source/model strings as text. Uvicorn access logging is disabled by the CLI; sanitized application codes/IDs identify failures. No marker-leak result or blanket penetration-test claim is inferred beyond the inspected/tested paths. Raw host administration and local processes remain trusted/exposed within the documented development posture.

The health endpoint, banner, README and implementation plan disclose absent auth. The dev owner is distinct from a device/session identity; it does not pretend to implement ADR-0010 provisioning. ADR-0005/0009/0010 are explicitly unsatisfied and must precede protected private/remote use. Nothing found warrants prioritizing the entire production access system before a bounded synthetic local-runtime slice.

## 11. Test quality and adversarial coverage

Original tests have substantial useful coverage: real SQLite behind application services, HTTP integration, immutable rows, FK enforcement, a trigger-induced rollback between publication statements, alternate ModelPort implementations, source-prefix isolation, process restart and sanitized failures. These are not all mocks asserting their own behavior.

Important limits:

- `FaultyExecutionStore` throws before the underlying method. Its “unknown” test does not simulate a real commit followed by lost confirmation. The new wrapper tests both actual COMMIT sides.
- Original process restart does not interrupt active inference. The new process test does.
- Original UI switching is sequential and its transport fake does not implement real admission/dispatch lifecycles. Controlled history-response reordering exposes R1, but fake-backend UI tests do not replace backend transaction tests or real-browser acceptance.
- The original model-state helper test cannot prove SQL update predicates enforce transitions. Those predicates were inspected and exercised independently through adapter tests.
- Architecture tests inspect imports rather than every dynamic dependency. Manual inspection found no hidden vendor/SQLite use in domain/application.
- No broad mutation testing was repeated. The plan's historical four mutation spot-checks were not taken as fresh evidence.

| Required adversarial case | Result / evidence |
| --- | --- |
| 1. Concurrent identical submission | Pass: 8 HTTP requests, one run/model invocation and one saved pair. |
| 2. Concurrent conflicting submission | Pass: one acceptance, seven conflicts, no extra effect. |
| 3. Double-click equivalent | Pass: UI double-click emits one submission. |
| 4. Response lost after successful commit/replay | Pass for same-ID replay; real after-COMMIT wrapper and UI lost acknowledgment. R2 exposes the discard alternative. |
| 5. Generation failure | Pass: original API/application tests and review failed settlement cases; user survives. |
| 6. Pending run/process restart | Pass: fresh real server reads pending fixture and settles failed, without response. |
| 7. Active run/process restart | Pass: SIGKILL during ten-second fake inference; indeterminate and admission closed after restart. |
| 8. Equal timestamps | Pass: review frozen-clock concurrency/transaction fixtures; original decreasing-clock tests also pass. |
| 9. Malformed conversation ID | API passes baseline rejection; malformed URL hash fails in client, R3. |
| 10. Stale/nonexistent conversation | API 404 tested; stale UI responses fail, R1. No append against a nonexistent target. |
| 11. Backend unavailable frontend | Network-loss/retry baseline passes; initial HTTP 503 recovery fails, R4. |
| 12. Switch conversations during active request | Fails, R1, with deterministic deferred send completion. |
| 13. Storage commit failure | Eight before/after-COMMIT cases pass preservation/dedup/restart expectations; full live resolution remains R6. |
| 14. Model failure immediately after dispatch | Pass: review model throws on entry; user retained and no response; settlement errors also probed. |
| 15. Publication failure after output exists | Pass for atomic rollback and failure disposition; unknown outcome stays blocked, R6. |

Extra checks: every admission insert abort, publication second-statement abort, stale refresh, malformed hash, IPv6 Origin, same-ID failed-send replay, delayed-commit timestamp characterization. Review totals: **25 cases, 19 passing and 6 failing assertions**, representing five current bugs. No tests skipped.

## 12. Recommended fix order and re-verification

1. **Claude: R1.** Make conversation selection, detail freshness, pending completion, restored drafts and composer targets agree. Cover cross-selection and same-selection response races.
2. **Claude: R2.** Preserve correlation through uncertain-send recovery; remove the implicit fresh resend from Discard and reload. Do not fix it by content-based deduplication or server history mutation.
3. **Claude: R3, R4, R5.** Safe hash parsing, visible retries for initial HTTP errors, and consistent supported loopback origins.
4. **Claude: R7 evidence/wording.** Reconcile timestamp acceptance claims with measured delayed-commit behavior. Surface any semantic decision instead of quietly changing requirements.
5. **Codex: independently re-verify these bounded repairs**, retaining the original baseline checks and strengthening regression probes as necessary. Do not turn failing review tests green merely by deleting assertions or marking expected failures.
6. **Separate minimal LD-04 design task (R6)**, then explicit implementation authorization for 0B: real local runtime behind the Anonymous-owned model boundary. Resolve supervision, termination evidence, publication uncertainty, retry eligibility and required port capabilities before long-running inference. Add context-limit decisions needed for the chosen runtime without starting Memory or unrelated features.

Re-verification checklist:

- All 95 original backend/19 frontend cases, mypy, ruff, TypeScript and build still pass; record new counts if tests are legitimately added.
- All six currently failing review assertions pass. Preserve both R1 race variants and test late errors/rapid selection changes; compare displayed conversation and actual POST target.
- Lost acknowledgment followed by same-ID replay, Refresh, discard, reconnection and explicit fresh send have distinct outcomes with no accidental duplication.
- Concurrent identical/conflicting requests, active-run replay and failure replay still call the model at most once per accepted intent.
- Fault admission/dispatch/publication/settlement before and after actual COMMIT. Confirm source preservation and no false success; do not release unresolved admission.
- Repeat real-process active SIGKILL, pending startup, completed restart and second-instance refusal.
- Test IPv4/localhost/IPv6 origins and hostile/null Origins at configured ports; maintain loopback default/refusal.
- Exercise malformed hashes on load and hashchange; initial network failure and HTTP 503 each offer usable recovery.
- Record delayed-commit timestamp evidence separately from timezone/order tests and update claims honestly.
- Run a fresh real-browser smoke when browser access is available; Windows/iPhone acceptance remains separate.

No architectural rewrite is recommended for R1–R5. R6 needs an explicit design decision and likely an ADR plus updates to the execution/persistence/API contracts before 0B. R7 may need documented agreement about timestamp precision/meaning; no semantic change was accepted during this review. No existing ADR or product file was edited.

## CHATGPT HANDOFF SUMMARY

1. **Completed:** Independent Codex review of Anonymous V0 Slice 0A, including required documents, all server/client production code, original tests, baseline execution, real SQLite fault injection, concurrent HTTP calls and real-process recovery.
2. **Files created:** `docs/reviews/slice-0a-codex-review.md`; `.agent/plans/2026-10-07-slice-0a-independent-review.md`; `server/review_tests/test_slice0a_review.py`; `client/review-tests/slice0a.review.tsx`; `client/review-tests/vitest.config.ts`. No original product/source/test/config/doc files changed. Build/cache outputs were regenerated by checks.
3. **Baseline:** Backend 95 passed; frontend 19 passed; mypy clean in 49 files; ruff lint/format clean; TypeScript and Vite build passed. No baseline skips/warnings. Used existing Python 3.12.14 and fnm Node 24.21.0; no dependency installs/updates. Frontend linter is not configured.
4. **Architecture:** Domain/application remain independent of SQLite, FastAPI and fake runtime details. Owned persistence/model ports and explicit ContextBuilder are coherent. Real supervised-runtime replacement needs R6/LD-04 work; simple synchronous adapter substitution is not proof of that stronger guarantee.
5. **Persistence:** Admission, dispatch, publication and failure settlement preserve tested transaction guarantees. Actual pre/post-COMMIT injections caused no partial saved success, source loss or duplicate response. Unknown outcomes are conservative; replay may return an unresolved stored state rather than resolve it.
6. **Idempotency/concurrency:** Eight identical concurrent HTTP submissions produced one model call/pair/run; eight conflicting submissions produced one acceptance and seven conflicts. Owner key plus conversation/content binding works. Same-ID replay of success/failure/active/indeterminate never launches new inference.
7. **Ordering/timestamps:** Positions allocate inside the immediate write transaction and survive equal/backward clocks. UTC instants persist and client timezone only formats them. Full FR-15 delayed-commit meaning remains unproven: timestamps are sampled before actual COMMIT (R7).
8. **Restart:** New real SIGKILL-during-inference test preserves user history and yields indeterminate/closed admission on restart. Fresh process over pending fixture yields failed-before-dispatch. No automatic replay. Indeterminate remains intentionally unresolved in 0A.
9. **API/frontend:** Backend error/status semantics are coherent for tested paths. Five bugs found: R1 stale response/view-target race; R2 discard recovery can cause a fresh duplicate send; R3 malformed hash crashes; R4 initial HTTP 503 has no in-app retry; R5 advertised IPv6 same-origin requests are rejected.
10. **Security:** Honest synthetic loopback-only no-auth development posture; no concrete finding demands full production security before 0B. Auth/device/session/private transport gates remain mandatory before private/remote use. No external model/tool/analytics path found. R5 is excessive rejection, not unauthorized access.
11. **New tests:** Opt-in backend suite: 17 pass, 1 fail. Opt-in frontend suite: 2 pass, 5 fail. Six failing assertions represent five bugs; two failures demonstrate R1. Tests intentionally retain failing requirement assertions, with no skips/xfails. Browser visual smoke was blocked by unavailable browser connections/pending Computer Use permissions; real HTTP built-asset/send/replay/failure smoke passed.
12. **Severity:** CRITICAL none. HIGH: R1 BUG and R6 DESIGN_GAP. MEDIUM: R2/R3 BUG and R7 TEST_GAP. LOW: R4/R5 BUG.
13. **Classification:** Current bugs are R1–R5. R6 is a real-runtime lifecycle design gap, not a demand to implement all recovery in 0A. R7 is missing full timestamp acceptance evidence plus a precision/meaning question. Production auth, explicit generation retry, context budgets, full recovery, pagination, Windows/iPhone evidence and backup are DEFERRED_BY_SCOPE, not bugs solely for being absent.
14. **Exact vertical-slice verdict: PASS_WITH_REQUIRED_FIXES.** Server foundation is sound within tested 0A scope; client/API defects require bounded repairs before real model attachment.
15. **Claude fixes:** R1 selection/freshness/target agreement; R2 safe correlation-preserving discard/reconciliation; R3 safe hash parsing; R4 usable HTTP-error retry; R5 exact IPv6 origin support or removal of the unsupported advertised mode. Address R7 acceptance evidence/claims without silently weakening FR-15. Do not alter saved history or introduce text-based global deduplication.
16. **Codex re-verification:** Run original checks and both opt-in suites; require all six failing assertions to pass. Recheck late selection/refresh/errors, discard and lost-ack behavior, concurrent replay/conflict, all four transaction fault windows, active/pending process recovery, hostile/loopback origins and delayed-commit semantics. Obtain fresh browser smoke when accessible.
17. **LD-04:** Must be resolved before long-running real ModelPort integration. Define runtime correlation/supervision, known termination versus uncertain transport failure, finalization/publication reconciliation and explicit eligible retry on the same saved user message with a new run.
18. **Architecture/ADRs:** No broad rewrite needed for current bugs. R6 merits an explicit lifecycle/port design decision, likely ADR and affected-document updates. R7 needs explicit treatment if timestamp semantics change. This review accepted no new architecture and changed no ADR.
19. **Scope confirmation:** Codex did not fix product code or implement real models, production auth, Memory, branches, merges, or unrelated features. All review data was synthetic/local; original tracked-intent files were preserved by hash comparison.
20. **Next bounded task:** Claude repairs accepted R1–R5 findings and addresses R7 evidence/claims; Codex independently re-verifies; then resolve minimal LD-04 and authorize Slice 0B with a real local runtime adapter. Stop this task at the independent review.
