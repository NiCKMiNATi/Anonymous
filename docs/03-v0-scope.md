# Anonymous — V0 Scope v0.1

**Status:** Product scope v0.1; release acceptance specification, not evidence that V0 is implemented or releasable.
**Date:** 2026-10-03.

## 1. Objective and authority

> Prove that Anonymous is a persistent, secure, model-independent local AI conversation system accessible from the user's intended devices.

This objective is consistent with [Project Definition](00-project-definition.md) (PD §§3–4, 8–9, 14) and [Domain Model](01-domain-model.md) (DM §§3–6, 8–9, 18–19, 31–33). No conflict was found. It selects a small release from the broader product rather than redefining Anonymous as only linear chat.

[Requirements Baseline v0.1](02-requirements.md) (RB) supplies the requirements, including the user-directed FR-15 timestamp addition. Requirement IDs and Q-01–Q-24 below refer to RB. This document selects release applicability and resolves only minimum V0 product semantics. It does not change baseline requirement meanings, globally close questions, or select their implementation representations.

PD/DM domain invariants remain binding even where their associated feature is deferred. The later architecture needs to preserve those meanings without implementing every future capability. Nothing here selects a database, schema, endpoint, framework, authentication mechanism, inference product, or network product. The [task ExecPlan](../.agent/plans/2026-10-03-v0-scope.md) records the work.

## 2. Evaluated capability boundary

### Included

| Capability | V0 boundary and reason |
| --- | --- |
| One primary user | Persistent user ownership, recognized devices, and distinct sessions. Sufficient for the initial personal environment (DM §§4–6). |
| Core text conversation flow | Create, list, open, read saved history, send a user message, receive a response, leave/reconnect, and continue. Listing is the minimum means of finding an existing conversation under FR-01/FR-03, not advanced search. |
| Persistent message timestamps | Every saved user and assistant message retains its server-authoritative commit timestamp (sampled within the committing transaction after write authority and before the commit attempt; authoritative only if it commits); all V0 clients continuously show its selected/local time near the message action area without hover (FR-15). |
| Stable identities and source history | Saved conversations/messages retain identity and authorship across client changes, execution failure, and restart. Display naming does not define identity; a rename feature is not required. |
| One local execution path | One working local model path with observable runs and a replaceable model/runtime boundary. No dynamic router UI, multi-model product, or second production integration is required. Replacement evidence is still a release gate. |
| Current-conversation context | Construct bounded input from the current conversation's retained messages plus necessary system instructions. No automatic cross-conversation knowledge, extraction, summaries, or Memory subsystem. |
| Minimum execution provenance | Attribute saved assistant output to the producing run, model/runtime, and contributing conversation messages; preserve outcome distinctions. See V0-D03. |
| Protected multi-device access | Explicitly authorized devices and authenticated/authorized user sessions, protected communication, address-independent trust, and revocation. Remote/mobile access is included, not just same-LAN operation. |
| Private-only application behavior | Conversation content, generated output, context, and provenance remain inside the private Anonymous environment. No application web/cloud/tool execution or private-data release feature. |
| Failure observability | Distinguishable saving, completion, failure, and uncertain outcomes; persistent history survives failures within the stated recovery boundary. |

### Not selected

Branching, merging, the Memory subsystem, automatic extraction, canonical summaries, embeddings/semantic retrieval, files/artifacts, WEB/cloud models, tools/plugins, graph visualization, agents, voice, native mobile applications, multiple users, distributed inference, and cloud sync are deferred. Message editing, regenerating a successful response, conversation lifecycle actions, and disconnected-client writes are also outside the minimal release. Section 8 records surviving invariants for each group.

This boundary is selected because each included item is needed for continuity, private authorized access, or verifiable local execution. The deferred capabilities are valuable product directions but do not prove an additional necessary part of PD §14's initial lifecycle. Their omission is not permission to erase source history, conflate user/model identity, or couple history to one runtime.

## 3. Pass A: V0 product decisions

These are explicit V0 decisions made within this scoping task. They are not global answers to all RB questions or architectural ADRs. Each decision's observable behavior is exercised by the release scenarios in section 9.

### V0-D01 — Scope and current-conversation context

**Questions:** Q-20, the V0 portions of Q-14/Q-24. **Trace:** FR-01–FR-03, FR-08, FR-09, DATA-02, DATA-03; PD §§6.3, 14; DM §§18–20.

V0 uses persisted conversation history to build request context. That is not the future Memory subsystem: no extracted facts, confidence scores, conflict resolution, scoped long-term knowledge, or cross-conversation retrieval is created.

Within the supported input budget, the current user message and relevant current-conversation history are eligible input. When the whole current conversation fits, its prior conversational messages are included in their established order and with authorship preserved. When it does not fit, older content may be omitted, but source history is retained and the user is informed that the model does not receive the full history. The full current user message is never silently cut; if it alone cannot fit, generation is refused visibly without deleting a message already confirmed saved. Exact budget calculation and earlier-message selection are design work.

Users can browse retained older messages even when those messages are outside the current model input. Automatic recovery/reinsertion of an old fact into a future prompt is not a V0 guarantee. Reconstructing request context after failure does not regenerate saved assistant messages or rewrite their original content.

### V0-D02 — Private-only access boundary

**Questions:** Minimum Q-10/Q-17 disposition. **Trace:** SEC-01–SEC-06, SEC-08, PRIV-01, PRIV-03–PRIV-05; PD §§4.2, 7–8; DM §§38–39.

All V0 conversation content, assistant output, context, and provenance is handled as PRIVATE. This is a V0 operating profile, not the final product classification taxonomy. No control or model-generated instruction can authorize a cloud/web/tool/private-release operation in V0. Missing/uncertain permission cannot enable one. There is no silent cloud fallback if the local runtime fails.

Protected delivery to the user's authorized remote clients is inside the private environment, not permission to send content to an external model/service. Private access may depend on network connectivity; any transport infrastructure is not granted application-level access to conversation content. No new public server/runtime/storage/administration exposure is a prerequisite. Confidentiality and integrity on untrusted networks, application authentication, and authorization remain separate obligations; a private network alone is insufficient.

V0 does not send conversation payloads, private provenance, or credentials to external analytics, crash reporting, or other application services. Ordinary diagnostic output uses sanitized operation/error evidence rather than raw secrets or conversation bodies. This does not claim that all network metadata is hidden or choose a transport system. Transport trust/metadata exposure remains a security-design gate before remote access is enabled.

### V0-D03 — Minimum execution evidence and retention

**Questions:** V0 portions of Q-12/Q-13/Q-15/Q-24. **Trace:** FR-12, DATA-01, DATA-03, DATA-08, SEC-08; DM §§18, 31–33, 44–45.

For each accepted generation attempt, retain enough information to identify its distinct execution, owning conversation/requesting user message, model identity, runtime identity, outcome, and any saved assistant response. Record which retained conversation messages contributed to the invocation, so omission from bounded context is observable. These are information requirements, not fields in a proposed schema.

Successful, failed, and interrupted attempts remain distinguishable. If no invocation occurred because preconditions failed, do not fabricate a successful model run. A retry is a new execution associated with the same saved user message, not a replacement of historical execution evidence.

Saved history and the minimal run/source associations remain available for the life of that V0 dataset; V0 performs no automatic age-based purge, pruning of source messages, or erasure feature. A storage limit produces a visible failure rather than silent history deletion. Detailed lifecycle/deletion behavior remains open before those features are introduced; this is not an eternal-retention policy for later releases.

Permanent duplicated full prompts, chain-of-thought, complete sampling metadata, token accounting, replay-perfect output, and tool-run records are not V0 requirements. Current request context can be transient; the minimum associations above survive restart. Exact byte-for-byte reproduction of a stochastic response is not promised. Saved assistant text is a preserved record of what the model produced, but is never relabeled as an explicit user fact. Each dispatched attempt additionally retains the application, model, runtime, context-configuration and behavior-configuration identities it used — a label plus a verifiable identity and its verification state where available (NFR-08, ADR-0014, proposed); earlier attempts are never relabeled.

### V0-D04 — Saving, retries, and concurrent activity

**Questions:** Minimum Q-16. **Trace:** FR-02, FR-12, FR-15, DATA-02, DATA-08, REC-02–REC-04.

A user message is reported saved only after Anonymous confirms durable recording; model generation starts only after that confirmation. A model failure does not roll back the saved user message. A response is reported complete-and-saved only after its final content and producing-run association are confirmed saved. “Generating,” “saved,” “failed,” and “outcome not yet confirmed” are distinguishable, without prescribing UI labels or protocol states.

Each user and assistant message retains a server-authoritative commit timestamp (FR-15), stored and represented as an absolute instant independent of client timezone. It is sampled within the committing transaction after the required write authority is obtained and before the commit attempt; it is authoritative only if the message commits, and is not guaranteed equal to the storage engine's physical commit-completion instant or bounded by any unconditional wall-clock difference. When the outcome is uncertain nothing is claimed either way: reconciliation decides, and if the original operation committed its original timestamp is preserved. Reopening, reconciliation, or retry does not retimestamp an existing saved message. Timestamps are not the sole source of conversation ordering; equal or non-monotonic instants must not disturb established order.

Incremental display is optional. Any partial response is visibly provisional; on confirmed execution failure before a response was saved, it does not become a completed saved assistant message. V0 is not required to retain the partial generated text. The failed/interrupted attempt is recorded under V0-D03, and confirmed failure is distinguished from an uncertain save. When persistence confirmation is unavailable, neither “saved” nor “nothing was saved” is asserted until reconciliation establishes the outcome. Failure-record persistence is likewise not claimed before it is confirmed.

Loss of a client connection does not itself prove server-side failure. On reconnect, inspect the authoritative saved outcome before offering a retry. Repeated delivery/reconciliation of the same submission cannot silently create duplicate user messages or successful responses. Do not automatically start new inference to resolve uncertainty; an explicit retry of a confirmed failed/interrupted attempt creates a distinct run and leaves the original user message intact. Retry applies only to the latest saved user message while no later message has been accepted. A still-running, already successful, or historically superseded attempt is not retryable as a new generation in V0; the user can send a new message instead. This avoids introducing historical regeneration or implicit branching. Request correlation and duplicate prevention mechanisms remain design work.

Only one generation is active per conversation. Additional sends to that busy conversation are refused visibly without being appended or queued silently. Cross-device reading remains possible; after completion/failure and refresh, a new send can proceed from the current saved state. No collaborative editing or concurrent branch creation is implied. Parallel scheduling between different conversations is not required.

### V0-D05 — Authorized devices and session lifecycle

**Questions:** Minimum Q-21 and the access portion of Q-20. **Trace:** SEC-01–SEC-06; FR-03, FR-14; DM §§4–6.

Only the primary user can authorize a new device or restore revoked device trust through an already authorized context or a controlled owner bootstrap/recovery process. Unapproved devices cannot self-enroll merely by reaching the service or using a previously trusted IP address. Establishing the first owner/device is a required provisioning outcome; the bootstrap mechanism is left to security/architecture design and cannot rely on open public registration.

A recognized device still needs a valid authenticated and authorized interaction. Logout invalidates the selected session, not the device identity or another valid session. Expired sessions deny protected operations and require reauthentication. Sessions have a finite validity policy; exact lifetime/renewal parameters require security review before an access-capable build, not after release.

Device revocation invalidates that device's sessions. Once revocation is acknowledged, it receives no new protected reads, writes, or response deliveries, including further delivery from work already in flight. Already delivered data cannot be recalled. An in-flight local run may finish without delivering to the revoked client; source history is not destroyed as a revocation side effect. Reauthorization requires an explicit owner action, never address reuse.

Ordinary network changes preserve device identity/trust. They may require reconnection or reauthentication if a session is no longer valid; they do not require treating the same device as a new device. Owner recovery mechanics, credential choice, and secret storage are architecture/security work with explicit pre-release gates in section 10.

### V0-D06 — Failure/recovery boundary

**Questions:** V0 portions of Q-18/Q-14. **Trace:** REC-01–REC-05, DATA-02, DATA-03; PD §§14, 18–19.

Confirmed-saved records and their minimal execution evidence survive orderly restart and abrupt termination of the server process when the underlying persistent storage remains intact and accessible. The abrupt-process check is a V0 strengthening of the normal-restart minimum, not a hardware power-loss guarantee. After restart, incomplete attempts are distinguishable from completed saved responses; pending work is not silently replayed into duplicate history.

Known persistence, runtime, context, or access-policy failures are visible; previously saved history remains intact. Losing transient context affects that attempt, not source records. A subsequent explicitly requested attempt can reconstruct context from retained history.

Recovery from destroyed/corrupt storage, hardware power loss, backup restoration, disaster recovery, and quantified loss/time tolerances are not V0 release guarantees. Their absence is documented, not disguised as proven reliability. No recovery mechanism, storage engine, or backup design is chosen here.

## 4. Supported clients and quality boundary

This resolves Q-19's platform/capability boundary. The user supplied the hardware inventory in section 5; exact OS/client versions and quantitative runtime targets remain evidence prerequisites with deadlines below. No unprovided software version is claimed.

| Target | Required V0 product support | Acceptance configuration |
| --- | --- | --- |
| Existing Windows desktop | Full core text chat: authorized access, create/list/open/read, send/receive, reconnect/continue, and observable failure handling. No privilege from co-hosting the server. | Ryzen 7 5700X / RTX 3070 desktop in section 5; exact OS and supported client/browser version recorded before acceptance. |
| Existing macOS/MacBook | The same full core chat flow and access to the same saved conversations. | MacBook Pro M1 Pro (2021) in section 5; exact OS/client/browser version recorded before acceptance. |
| Existing iPhone | Essential flow: authorized access, create/list/open/read, send/receive, reconnect/continue, and visible failure/access-denial states. Creating a conversation is retained to satisfy NFR-05, beyond the candidate minimum. | iPhone 17 Pro Max (2025) in section 5; exact OS/client/browser version recorded before acceptance. Native app is not required. |
| Other platforms/configurations | Unsupported/best effort; success is not a V0 release prerequisite. | No compatibility claim without separate evidence. |

“Full core” does not promise desktop administration, multi-model controls, editing, Memory, or any excluded capability. Owner provisioning/revocation may use a supported operator interaction rather than a full mobile administration UI. No frontend or native technology is selected.

The acceptance run records one actual supported configuration for each required device class; it does not imply support for every OS/browser version. Until those configurations are recorded and checked for security compatibility, NFR-05's environment evidence is pending and a release cannot be signed off. Unavailable/unsupported devices are surfaced as a blocker or an explicit future scope change, never silently dropped.

Every supported V0 chat client continuously displays the time for each displayed user and assistant message near the message action area without requiring hover (FR-15). Rendering uses the selected timezone, or the client’s local timezone by default, without changing the saved instant. A precise full date/time may be available as secondary detail; it does not replace the continuously visible time.

Minimum interaction checks: desktop core actions are operable by keyboard with visible focus; essential iPhone actions are reachable by touch at its actual viewport without clipping controls; user/assistant authorship and pending/failure states are perceivable without relying only on color. Core controls have discernible names for assistive-technology inspection. These are bounded acceptance checks, not a claim of a particular formal accessibility-conformance level.

Integrity, authorization, privacy, and completion/failure correctness are pass/fail release gates. No latency, throughput, model-size, context-capacity, response-quality score, or availability percentage is invented. During architecture-phase benchmarking, use the recorded hardware/client environment to document the live model, workload, input/output limits, response timings, memory/resource usage, and interruption behavior; then set an explicit finite acceptance envelope before implementation acceptance/release testing. Missing benchmark-derived targets are an open gate, not “any performance is acceptable.” Advanced retrieval and merge quality benchmarks are outside V0.

## 5. Hardware and cost boundary

Q-23 is resolved as a product constraint: the core V0 path uses currently available project hardware, initially the existing Windows desktop as server and the existing clients. No new compute hardware, paid cloud AI service, paid hosted database, or new mandatory recurring infrastructure subscription is required. Existing network/electricity costs are not newly promised away. Optional paid-service conveniences cannot become required for a supported V0 scenario, including remote access.

The user supplied this inventory during the scoping task on 2026-10-03. It is the product's existing-equipment baseline, not an independently measured performance result:

| Device | User-reported hardware | V0 role |
| --- | --- | --- |
| Windows desktop | AMD Ryzen 7 5700X; NVIDIA GeForce RTX 3070 with 8 GB VRAM; 32 GB RAM; 1 TB NVMe SSD | Initial server/local inference host and core client. |
| MacBook Pro (2021) | Apple M1 Pro; 16 GB RAM; 512 GB SSD | Core client; no Mac-hosted inference integration required. |
| iPhone 17 Pro Max (2025) | 256 GB storage | Essential mobile client; no on-device model required. |

Exact OS/client/browser versions, available rather than installed storage/memory, and measured runtime feasibility remain unverified. Record these before architecture-phase benchmarking and freeze the supported configurations before release testing. This task does not inspect or benchmark the machines and does not infer model size or speed from the inventory.

Acceptance requires demonstrating the selected local lifecycle on that recorded existing equipment without the excluded purchases/services. If no suitable model/runtime fits, report the blocker and revisit scope with evidence; do not silently substitute paid cloud inference or require a hardware upgrade. No model, quantization, acceleration library, or latency target is selected now.

## 6. Every baseline requirement: V0 applicability

**REQUIRED_V0:** the requirement applies to V0's supported entities/operations; acceptance needs evidence for its applicable semantics. Conditional examples for capabilities not offered do not force those features into V0.

**PARTIAL_V0:** only the precisely named subset is a V0 release gate; the remainder stays a product obligation for later selection. This is not a claim of full baseline compliance.

**DEFERRED:** implementation and its feature-specific acceptance are postponed; established invariants remain future design constraints.

**NOT_APPLICABLE_V0:** the conditional behavior has no triggering operation in the selected release. This is not a permanent waiver; introducing that operation reactivates its requirements and requires rescoping.

| Requirement | Classification | Exact applicability / deferred remainder | V0 evidence |
| --- | --- | --- | --- |
| FR-01 | REQUIRED_V0 | Create, list/open, and reopen persistent conversations. | V0-AC-01, V0-AC-03 |
| FR-02 | REQUIRED_V0 | Text exchanges, retained authorship, continued conversation. | V0-AC-01, V0-AC-06 |
| FR-03 | REQUIRED_V0 | Same user's continuation from another authorized client. | V0-AC-03, V0-AC-04 |
| FR-04 | DEFERRED | No branch creation; origin/non-destructive invariants retained. | Future branch acceptance; section 8 |
| FR-05 | DEFERRED | No merge creation; new identity/ancestry/source survival retained. | Future merge acceptance; section 8 |
| FR-06 | DEFERRED | No persistent scoped Memory subsystem. | Future Memory acceptance |
| FR-07 | DEFERRED | No inference-store correction/supersession workflow. Ordinary corrective user messages remain possible, without claiming this full behavior. | Future Memory acceptance |
| FR-08 | PARTIAL_V0 | Current-conversation messages and system instructions only; bounded construction and privacy apply. Memory/artifact/retrieval/external-context contributions are deferred. | V0-AC-08, V0-AC-09 |
| FR-09 | PARTIAL_V0 | Browse/read retained older raw messages and identify their conversation/record independently of the active context. Automatic lookup/ranking and guaranteed reinsertion into model context are deferred. | V0-AC-08 |
| FR-10 | DEFERRED | No canonical/compressed-state feature. | Future canonical-state acceptance |
| FR-11 | DEFERRED | No uploaded/linked/generated artifact management. | Future artifact acceptance |
| FR-12 | REQUIRED_V0 | Distinct local runs, model/runtime identities, outcomes, and retained minimum evidence under V0-D03. | V0-AC-01, V0-AC-06, V0-AC-11 |
| FR-13 | DEFERRED | No tool execution or tool-run management. | Future tool acceptance |
| FR-14 | REQUIRED_V0 | Primary-user ownership of supported conversations/messages/execution evidence; no multi-user management implied. | V0-AC-01, V0-AC-03 |
| FR-15 | REQUIRED_V0 | Server-authoritative commit timestamps for user and assistant messages as absolute instants (sampled in the committing transaction; authoritative only on commit; original preserved on reconciliation); continuous selected/local time near the message action area without hover on every V0 client. Ordering does not depend solely on timestamps. | V0-AC-01, V0-AC-02, V0-AC-03 |
| NFR-01 | REQUIRED_V0 | Local core path works with external services unavailable and private local connectivity intact. | V0-AC-12 |
| NFR-02 | PARTIAL_V0 | Preserve V0 data/client semantics through a controlled execution-boundary replacement demonstration; only one live local integration ships. Full two-runtime product integration and deferred data classes are outside V0 acceptance. | V0-AC-11, V0-AC-15 |
| NFR-03 | REQUIRED_V0 | Canonical saved state/context responsibility does not depend on one client. | V0-AC-03, V0-AC-15 |
| NFR-04 | REQUIRED_V0 | Co-hosted Windows client has no special domain/authorization semantics. | V0-AC-05, V0-AC-15 |
| NFR-05 | REQUIRED_V0 | Windows/macOS/iPhone core flow using the recorded matrix in section 4. | V0-AC-03 |
| NFR-06 | REQUIRED_V0 | Existing-equipment/no-required-new-hardware-or-paid-services boundary in section 5. Evidence requires the actual inventory. | V0-AC-12 |
| NFR-07 | REQUIRED_V0 | Technology-independent meanings and bounded modular responsibilities remain architecture/release review gates; no decomposition is designed here. | V0-AC-15 |
| NFR-08 | PARTIAL_V0 | Data preservation across upgrades/migrations, and per-run provenance of application, model, runtime, context-configuration and behavior-configuration identity (label, verifiable identity where available, verification state) recorded before invocation (explicit "none"/`unspecified`, never guessed), and a persisted conversation-to-configuration binding that an upgrade does not silently change (ADR-0014, proposed). Persona, preferences, workflows, persistent memories and user-editable versioned configurations are deferred to those capabilities; behavioral equivalence between models is not promised. | V0-AC-01, V0-AC-11, V0-AC-15 |
| SEC-01 | REQUIRED_V0 | Protected operations require authentication independently of network access. | V0-AC-05 |
| SEC-02 | REQUIRED_V0 | Primary-user/device/session authorization for supported reads, sends, and trust operations. No general role-management feature. | V0-AC-05, V0-AC-10 |
| SEC-03 | REQUIRED_V0 | Ordinary IP changes do not redefine device identity/trust. | V0-AC-04, V0-AC-05 |
| SEC-04 | REQUIRED_V0 | Revoked-device rejection at old/new addresses; V0-D05 additionally settles active-session consequences. | V0-AC-10 |
| SEC-05 | REQUIRED_V0 | Multiple distinguishable sessions for one device, logout/expiry/revocation semantics. | V0-AC-10 |
| SEC-06 | REQUIRED_V0 | Protected local/remote access, no required direct public service exposure, no implicit LAN trust. | V0-AC-04, V0-AC-14 |
| SEC-07 | NOT_APPLICABLE_V0 | No tool-execution capability exists; the conditional tool-authority check activates before tools can be added. Generated tool-like text never executes. | Exclusion verified in V0-AC-09 |
| SEC-08 | REQUIRED_V0 | Protect credentials in supported diagnostics/context/authentication paths. | V0-AC-14 |
| PRIV-01 | REQUIRED_V0 | No private application content goes to an external destination; unsupported modes cannot bypass this invariant. | V0-AC-09 |
| PRIV-02 | NOT_APPLICABLE_V0 | Explicit private-release capability is absent, not broadly permitted. | Exclusion verified in V0-AC-09 |
| PRIV-03 | PARTIAL_V0 | Generated assistant text, current context, and any diagnostic/provenance copies retain V0 PRIVATE treatment. Memory/summary/artifact classification propagation is deferred. | V0-AC-09, V0-AC-14 |
| PRIV-04 | REQUIRED_V0 | Missing/uncertain authority cannot enable unsupported external transfer. | V0-AC-09 |
| PRIV-05 | REQUIRED_V0 | No model text/instruction can override the no-external-transfer boundary. | V0-AC-09 |
| PRIV-06 | NOT_APPLICABLE_V0 | No permitted private-boundary release operation requiring a release audit exists. This does not remove local model-run provenance. | Exclusion verified in V0-AC-09 |
| DATA-01 | REQUIRED_V0 | Stable supported user/device/conversation/message/run identities, independent of names/client/model. No rename UI required. | V0-AC-01, V0-AC-03, V0-AC-11 |
| DATA-02 | PARTIAL_V0 | Preserve saved raw user/assistant records through supported context and execution operations. Branch/merge/edit/extraction/summarization-specific tests await those capabilities. | V0-AC-01, V0-AC-07, V0-AC-08 |
| DATA-03 | PARTIAL_V0 | Distinguish user-authored source statements, generated response records, and transient request views. No memory/canonical-state classes implemented. | V0-AC-01, V0-AC-08, V0-AC-13 |
| DATA-04 | DEFERRED | Memory/canonical-state/merge provenance features absent. Execution provenance remains separately required by DATA-08. | Future knowledge/merge acceptance |
| DATA-05 | PARTIAL_V0 | Preserve explicit user versus generated assistant origin; do not promote generated text into user facts. No confidence scoring, conflict store, or memory supersession. | V0-AC-01, V0-AC-08 |
| DATA-06 | DEFERRED | No merge historical-state product; source-boundary invariant retained for later merges. | Future merge acceptance |
| DATA-07 | PARTIAL_V0 | Derivation ancestry for V0 saved outputs remains noncyclic; bidirectional record lookup is not itself derivation ancestry. General branch/merge cycle cases await those features, without weakening their invariant. | V0-AC-15 |
| DATA-08 | REQUIRED_V0 | Every completed saved assistant response identifies its retained producing run/model/runtime. | V0-AC-01, V0-AC-02, V0-AC-06, V0-AC-11 |
| DATA-09 | DEFERRED | No artifact storage/relocation. | Future artifact acceptance |
| DATA-10 | NOT_APPLICABLE_V0 | No hide/archive/supersede/delete/physical-removal feature. No automatic source pruning either. | Exclusion verified in V0-AC-01, V0-AC-07 |
| REC-01 | PARTIAL_V0 | Saved chat identities/history/provenance survive restart; branch/merge ancestry cases await implementation. V0-D06 adds an intact-storage process-termination check. | V0-AC-02 |
| REC-02 | REQUIRED_V0 | Failed/uncertain saving is distinct from confirmation; no damage to earlier saved content. | V0-AC-07 |
| REC-03 | REQUIRED_V0 | Local execution failure is distinguishable from completion without erasing saved history. | V0-AC-06 |
| REC-04 | PARTIAL_V0 | Context/history-loading and access/privacy-check failures are exposed without false success or external fallback. Memory retrieval/tools/external-service execution remain absent. | V0-AC-08, V0-AC-09, V0-AC-13 |
| REC-05 | PARTIAL_V0 | Loss of transient request context cannot destroy saved sources; the next requested attempt can reconstruct context. No index/summary/canonical-state rebuilding promised. | V0-AC-13 |
| REC-06 | DEFERRED | No branch/merge operation to interrupt; source-preservation invariant survives. | Future branch/merge acceptance |

| Classification | Count |
| --- | ---: |
| REQUIRED_V0 | 26 |
| PARTIAL_V0 | 11 |
| DEFERRED | 11 |
| NOT_APPLICABLE_V0 | 4 |
| **Total** | **52** |

## 7. Disposition of every baseline question

“V0 settled” means only this release's product policy; a broader question can remain open. “Gate remains” means measurable facts/design evidence still need to be supplied before the named phase. RB's original question text/classification remains unchanged.

| Question | V0 applicability and disposition | Remaining boundary |
| --- | --- | --- |
| Q-01 | Branch deferred; open. | No Branch object/relationship representation chosen. |
| Q-02 | Merge/state-version feature deferred; open. | Run-to-input message references in V0-D03 do not select a global state-version representation. |
| Q-03 | Message editing deferred; open. | V0 adds records and preserves previous content, without choosing the future revision/event mechanism. |
| Q-04 | Merge synthesis deferred; open. | No synthesis/conflict policy selected. |
| Q-05 | Merge presentation deferred; open. | No decision about exposing merged source messages. |
| Q-06 | Memory classes/scopes deferred; open. | Current-conversation input is not Memory. |
| Q-07 | Confidence representation deferred; open. | Authorship distinction does not require confidence. |
| Q-08 | Memory conflict handling deferred; open. | No claim of automated correction/resolution. |
| Q-09 | Workspace/Project deferred; open. | Primary-user conversations need no final organization model. |
| Q-10 | V0 settled by PRIVATE-only profile, V0-D02. | Full taxonomy and mixed-source propagation remain open. |
| Q-11 | Remains architecture/design work. | No event-sourcing decision in this scope. |
| Q-12 | V0 minimum settled by V0-D03: retained input associations, no required duplicated full prompt or exact replay. | Expanded reproducibility/context retention remains open. |
| Q-13 | V0 minimum settled by V0-D03: local run identity, model/runtime, request/result association, outcome retained with the dataset. | Rich usage/parameter history, tools, and later purge policy remain open. |
| Q-14 | V0 uses ephemeral context reconstruction only, V0-D01/V0-D06. | Automatic Memory/index/canonical-state regeneration remains open. |
| Q-15 | V0 settled as no lifecycle/erasure feature and no automatic pruning, V0-D03. | Actual hide/archive/delete/erase propagation policy remains open before such features. |
| Q-16 | V0 minimum settled by V0-D04: durable confirmation, provisional partial output, explicit reconciled retry, one active generation per conversation. | Correlation, persistence, and coordination mechanisms remain design work; collaborative editing stays deferred. |
| Q-17 | Release feature excluded by V0-D02; no V0 transfer consent can enable it. | External-release consent/audit lifecycle stays open, not waived. |
| Q-18 | V0 recovery boundary settled by V0-D06. | Hardware-power-loss/corruption/backup/quantified disaster recovery remain open beyond V0. |
| Q-19 | Platform/capability/accessibility boundary selected in section 4. | Exact configurations and benchmark-derived quality envelope are explicit architecture/acceptance gates. |
| Q-20 | Capability boundary settled in section 2. | No disconnected writes/sync; broader product capabilities stay deferred. |
| Q-21 | V0 access/logout/revocation semantics settled by V0-D05. | Finite lifetime parameters and secure enrollment/recovery mechanisms gated on security design before remote access. |
| Q-22 | Advanced capabilities deferred; open. | No multi-user, agents, native-client, or plugin semantics selected. |
| Q-23 | Existing hardware supplied by the user and no-new-compute/no-required-paid-services boundary selected in section 5. | Available capacity, software environment, and demonstrated runtime feasibility remain required evidence. |
| Q-24 | V0 requires complete minimal saved-response/run/input attribution, V0-D03; no broader provenance exceptions assumed. | Practical coverage for future knowledge/merge/rebuilding/release-audit features remains open. |

## 8. Explicit exclusions and surviving invariants

| Deferred implementation | Invariant still constraining later architecture and V0 choices |
| --- | --- |
| Branch creation and editing/regeneration alternatives | Existing source history cannot be overwritten; stable identities and identifiable divergence remain domain requirements (INV-001–INV-003). A linear V0 UI does not redefine all conversations as permanently linear. |
| Merge creation and merge UI | New derived identity, intact sources, acyclic ancestry, retained provenance, and stable historical source boundaries remain binding (INV-004, INV-005, INV-011, INV-014). No speculative merge structure is required now. |
| Scoped long-term Memory, extraction, confidence, conflict/correction workflows | User statements and model output remain distinguishable; future correction supersession/provenance must remain possible (INV-007, INV-013). A corrective chat message is not claimed to implement Memory correction. |
| Canonical summaries, compression, embeddings, advanced retrieval | Derived information never replaces source history; context is a view, not the canonical store (INV-006, INV-015). Saved generated assistant history is not disposable merely because it came from a model. |
| Files/artifacts | Future logical identity/content separation and ownership/provenance survive; no storage format or upload capability is introduced now. |
| WEB/cloud models, external tools/plugins, explicit release | Privacy is independent of model compliance (INV-012); no future transfer becomes authorized because it is technically reachable. V0 remains private-only without a consent bridge. |
| Graph UI, autonomous agents, voice, avatar, unrestricted control, automation | Domain identities, execution attribution, and bounded permissions stay distinct; no execution agent or visualization is needed to prove core chat. |
| Multiple users, Workspace/Project management | One primary user still has persistent identity and ownership; device/session/user are not conflated (INV-009, INV-010). No organization schema is selected. |
| Native mobile, cloud sync, disconnected editing, distributed inference | Core server-owned continuity, private access, and model/host independence remain binding (INV-008, INV-009). Local-first is not a promise of disconnected synchronization. |
| Hide/archive/supersede/delete and automatic retention cleanup | These actions remain semantically distinct. Their absence does not authorize destructive side effects or establish later eternal retention. |
| Backup/disaster-recovery product | Existing saved data cannot be knowingly misreported or silently replaced. No tested restore/loss tolerance is claimed for physical storage failure. |

## 9. V0 release scenarios

These are future acceptance checks, not tests run during this task. Use synthetic data, the recorded supported configurations, and a known local execution path. Each scenario records observed evidence and pass/fail. Controlled fixtures may exercise faults or substitution, but they do not replace the required live local-model chat smoke test. No schema, route, or public diagnostic endpoint is prescribed by inspection language.

### V0-AC-01 — Local conversation continuity and attribution

- **Preconditions:** Authorized primary user on a recorded desktop client; local runtime/storage available; an empty test dataset and a short input within the agreed budget.
- **Actions:** Create two conversations, list/open each, complete two real local-model exchanges in one, leave/reopen it, and inspect saved records and execution associations. Use controlled delayed-commit, equal-timestamp, and non-monotonic-clock fixtures to check timestamp meaning and ordering.
- **Expected:** Distinct stable conversation identities; correct list/open behavior; nonempty completed responses through the live local path; exact saved user/assistant content and authorship; unchanged earlier content after continuation; each response identifies its run/model/runtime and contributing messages. Both user and assistant messages retain timestamps representing commitment to persistent history, including after reopening; equal or non-monotonic timestamps do not disturb established conversational order. Generated text is not user-authored knowledge. No edit/regenerate-success/delete/archive feature or source pruning is offered as part of V0. Model factual quality beyond the benchmark-defined smoke workload is not inferred from delivery alone.
- **Requirements:** FR-01, FR-02, FR-12, FR-14, FR-15, DATA-01, DATA-02, DATA-03, DATA-05, DATA-08. Also verifies the DATA-10 exclusion.

### V0-AC-02 — Restart and persisted-history recovery

- **Preconditions:** Known confirmed-saved messages/run evidence; storage remains intact; one additional generation can be placed in progress.
- **Actions:** Stop normally/restart and reopen; then repeat with abrupt server-process termination during generation. Reauthenticate if required and reconnect.
- **Expected:** All previously confirmed-saved content, identity, ownership, message timestamp instants, and run/source associations survive unchanged. Incomplete work is not labeled completed or silently regenerated. A client whose acknowledgment was lost reconciles against saved state. No claim of power-loss/corrupt-disk recovery is made.
- **Requirements:** REC-01, REC-02, REC-03, DATA-01, DATA-02, DATA-08, FR-12, FR-15.

### V0-AC-03 — Cross-device continuation and supported interactions

- **Preconditions:** Recorded Windows, Mac, and iPhone configurations, each explicitly authorized; saved conversation; private connectivity available.
- **Actions:** Create/list/open/send/receive on each target. Continue Windows history from Mac and then iPhone; clear one client's local state and reconnect. Check keyboard/focus on desktops and touch/control visibility on iPhone, accessible names, and non-color-only authorship/error indicators. Inspect user and assistant message times without hover on each target; render the same saved messages in different selected/local timezones, including across a date boundary.
- **Expected:** All targets reach the same saved conversation/owner with no export/import from the original client. No saved data is lost by clearing client-local state. Each displayed user and assistant message continuously shows its time near the message action area without hover; timezone changes affect rendering only, preserving the same saved instant and conversational order. Any secondary full date/time agrees with that instant. Core interactions meet section 4 checks; create is available on iPhone as required by NFR-05. Unsupported platforms are not claimed as tested.
- **Requirements:** FR-01, FR-02, FR-03, FR-14, FR-15, NFR-03, NFR-05, DATA-01.

### V0-AC-04 — Remote/mobile network change

- **Preconditions:** Approved iPhone with valid credentials and a saved conversation; remote private connectivity can reach the server on two ordinary network connections.
- **Actions:** Open remotely, switch between available Wi-Fi/mobile networks so its ordinary address changes, reconnect, and continue. Reauthenticate if validity has expired.
- **Expected:** Same device identity/trust and saved conversation; no new device approval due solely to IP change. Protected communication and normal authorization remain necessary. No direct public exposure of application/runtime/storage/administration is needed.
- **Requirements:** FR-03, SEC-03, SEC-06.

### V0-AC-05 — Unauthorized-device and unauthorized-operation rejection

- **Preconditions:** Approved owner device, unknown device on a reachable LAN, a caller with valid user authentication but an unapproved device, and a signed-out client on the server host.
- **Actions:** Attempt list/read/send/trust-management operations from each unauthorized context; let an unknown device use an old trusted address; repeat an authorized core operation as a positive control.
- **Expected:** Unauthorized reads disclose no saved content and unauthorized mutations change nothing. Network presence, old IP, user authentication alone without required device authority, and Windows co-hosting confer no access. The positive authorized case succeeds. A device cannot approve itself through an unauthenticated bootstrap action.
- **Requirements:** SEC-01, SEC-02, SEC-03, NFR-04.

### V0-AC-06 — Local runtime failure without history corruption

- **Preconditions:** Saved prior exchanges and a newly confirmed-saved user message; known live local runtime path.
- **Actions:** Make the runtime unavailable, then test interruption during generation; recover it and explicitly retry the failed attempt.
- **Expected:** Visible failure/incompletion, preserved exact saved history, no completed response fabricated from partial output, no cloud fallback. Retry uses the existing saved user message and a new attributable run; prior failed-run evidence remains. If a client disconnected but the run actually completed, reconciliation returns that saved completion instead of starting another run.
- **Requirements:** FR-02, FR-12, DATA-08, REC-03, PRIV-01.

### V0-AC-07 — Persistence failure, uncertain delivery, and overlapping sends

- **Preconditions:** Known saved fixture history, two authorized clients on one conversation, and controlled storage/network fault injection.
- **Actions:** Fail a user-message save, fail a final-response save, drop a confirmation after a successful save, redeliver the same submission, and try a second send while generation is active. Restore connectivity and reconcile before retrying. After a later message is accepted, attempt to retry an older failed message.
- **Expected:** No model call for a failed user save; no false saved/completed or false definite-failure claim while saving is uncertain; no prior-history loss. Reconciliation/redelivery of one intent yields at most one saved user message and one completed result for that successful attempt. Busy sends are visibly refused without silent append/queue. Explicit retry of the latest eligible message after confirmed failure creates a new run, not a duplicate user message; retry of an older message is refused without rewriting history. Storage limits do not trigger silent pruning; unsupported lifecycle actions do not appear as recovery substitutes.
- **Requirements:** FR-02, FR-12, DATA-02, REC-02, REC-03. Also verifies the DATA-10 exclusion.

### V0-AC-08 — Current-conversation context, limits, and source retention

- **Preconditions:** Two conversations with distinct synthetic facts; current one has both a short history and a variant exceeding the benchmark-defined input budget.
- **Actions:** Inspect context for a short-history request, then an over-budget history; browse older omitted messages; submit a single message too large to fit; include a user correction of an earlier assistant claim as an ordinary new message.
- **Expected:** Short-history context contains the current message and prior current-conversation messages in order with correct roles, not facts from the other conversation. Over-budget context stays within limits, indicates omitted older history, preserves all saved text, and does not silently truncate the newest message. An impossible input produces a visible generation refusal. Old source records remain readable/identifiable. User corrections retain user authorship; no inferred-memory store is created or claimed. No guarantee of model reasoning correctness is inferred from this context inspection.
- **Requirements:** FR-08, FR-09, DATA-02, DATA-03, DATA-05, REC-04.

### V0-AC-09 — Private-only behavior independent of model instructions

- **Preconditions:** Private synthetic messages/output/context/provenance; observable application destinations; an adversarial controlled response asking for external/tool execution.
- **Actions:** Attempt cloud/web/tool/private-release operations through all offered interaction/configuration surfaces; repeat with missing/uncertain authority and local model failure. Inspect outgoing application payloads and behavior.
- **Expected:** No external operation or private-payload transfer occurs, no cloud fallback exists, and generated instructions remain text. Content reaches only authorized private clients/local execution/storage responsibilities. External analytics/error reporting receive no private payloads. The absence of tools or release controls is verified; no release consent/audit subsystem is falsely claimed implemented.
- **Requirements:** FR-08, PRIV-01, PRIV-03, PRIV-04, PRIV-05, REC-04. Verifies SEC-07, PRIV-02, PRIV-06 non-applicability.

### V0-AC-10 — Logout, expiry, and device revocation

- **Preconditions:** Owner has an authorized recovery/management context; device A has two sessions; another device remains authorized; finite validity policy is documented.
- **Actions:** Log out one session, exercise controlled expiry on another, reauthenticate, start generation, and revoke A. Attempt new reads/sends and continued delivery using A's old/new addresses and earlier session material.
- **Expected:** Session termination does not rename/revoke the device or unrelated sessions. Expired sessions cannot operate. After acknowledged device revocation all A sessions and further protected deliveries are denied, including in-flight response delivery; the other authorized device can read saved history. Old IP/session material does not restore trust. Explicit owner reauthorization is required; source records remain unchanged.
- **Requirements:** SEC-02, SEC-04, SEC-05, SEC-03.

### V0-AC-11 — Replaceability without a second production integration

- **Preconditions:** A completed real local-model exchange and saved execution evidence; a controlled alternate execution fixture available for acceptance.
- **Actions:** Exercise the same conversation operations with substituted model/runtime identity and output through the chosen implementation's replacement boundary; inspect before/after history and client behavior.
- **Expected:** Conversation/user identity and saved content are unchanged; new output identifies the alternate run/model/runtime and the client still performs the same operations. Only integration-specific work is involved. The fixture proves the V0 boundary contract, not full support for two deployed runtimes; the latter remains outside this partial acceptance.
- **Requirements:** NFR-02, FR-12, DATA-01, DATA-08.

### V0-AC-12 — Existing-hardware local operation without required cloud cost

- **Preconditions:** Verified existing-equipment/configuration inventory and benchmark workload; already provisioned authorized local device; private local connectivity intact.
- **Actions:** Disable external application/service access while retaining the local path. Authenticate locally, run create/send/receive/reopen/continue, and inspect resource/purchase/service prerequisites and benchmark results.
- **Expected:** Live local lifecycle succeeds without new compute hardware, paid cloud AI/database, or a new mandatory subscription. No cloud authentication dependency prevents this already provisioned local use. Evidence meets the subsequently recorded benchmark envelope; missing inventory/targets means this acceptance is not yet complete. Remote transport outages need not permit remote use when there is no network path.
- **Requirements:** NFR-01, NFR-06.

### V0-AC-13 — Loss of transient context and recoverable operation failure

- **Preconditions:** Known saved history and a controlled context/history-loading fault.
- **Actions:** Fail context construction, discard its transient view, restore the dependency, and explicitly request another permitted attempt. Compare saved source records before/after.
- **Expected:** Failure is visible without false completed inference or private-policy bypass. Sources remain identical; later context is reconstructed from them. Saved assistant responses are not regenerated to replace historical text. No index/summary/Memory recovery product is claimed.
- **Requirements:** REC-04, REC-05, DATA-03.

### V0-AC-14 — Protected transport and sanitized diagnostics

- **Preconditions:** Recorded local/remote configurations, an untrusted network observer, synthetic credential/private-content markers, and successful/failing supported operations.
- **Actions:** Observe communication, attempt unauthorized reads/tampering, inspect ordinary diagnostic output and model context, and verify externally reachable service exposure.
- **Expected:** The observer cannot read protected payloads or cause modified payloads to be accepted; application/runtime/storage/administration does not require direct public ingress. Credentials are absent from ordinary diagnostics and unrelated context; raw conversation bodies/private provenance are not exported to reporting services. Sanitized failure evidence identifies the affected operation/responsibility.
- **Requirements:** SEC-06, SEC-08, PRIV-03, REC-04.

### V0-AC-15 — Domain compatibility and boundary review

- **Preconditions:** Future architecture/implementation evidence exists; no architecture is produced by this scope task.
- **Actions:** Map responsibility/technology dependencies, compare co-hosted/remote-client authorization, inspect existing derivation ancestry for cycles, and walk through later model/host/storage/client replacement and branch/merge/Memory introduction against DM invariants.
- **Expected:** Source meanings and stable identity survive proposed replacement; canonical ownership/context is not client-only; no Windows-host privilege exists; derivation ancestry is noncyclic without confusing bidirectional record lookup with ancestry. V0's linear UI does not redefine future ancestry as only linear or require destructive history conversion. Conceptual aggregates do not force microservices, and dependency-specific change areas are identifiable. This is design-review evidence, not implementation of deferred capabilities.
- **Requirements:** NFR-02, NFR-03, NFR-04, NFR-07, DATA-07; checks the surviving invariants in section 8.

## 10. Decision debt and latest resolution gates

An open decision for an excluded feature is not a V0 defect. Missing evidence for a selected capability is a release/design gate. The distinction below prevents deferring actual access security until after use.

| Decision / affected capability | Why safe to leave open at scoping | Latest phase / required gate |
| --- | --- | --- |
| Verify available hardware capacity and record OS/client/browser versions (Q-19, Q-23) | User-reported installed hardware and no-purchase bounds are fixed; available capacity and software versions cannot be inferred. | Record before architecture benchmarking; freeze supported acceptance configurations before release testing. |
| Local model/runtime choice and quality/performance envelope (Q-19, Q-23) | Selection and measured capacity require the real equipment. No arbitrary speed/model-quality number is credible now. | Architecture-phase benchmarking; explicit test workloads/limits and agreed targets before implementation acceptance/release testing. |
| Authentication/authorization, controlled first-owner provisioning, lost-device recovery, protected transport, credential storage, session validity/renewal parameters (Q-21) | V0-D02/V0-D05 settle who can act and revocation outcomes; their mechanisms are architecture/security work. | Resolve and security-review before an access-capable build or any real remote/private-data use; demonstrate V0-AC-05, V0-AC-10, V0-AC-14 before release. No unauthenticated bootstrap workaround. |
| Network/control-plane metadata and private transport threat model (Q-10, Q-21) | Application PRIVATE-only/no-public-service-exposure rules stand without selecting a transport. | Security design before remote connectivity is enabled. Owner must understand any infrastructure trust needed. |
| Persistence confirmation, reconciliation, concurrency, source/run association, diagnostic-retention mechanisms (Q-12, Q-13, Q-16, Q-24) | Product outcomes are fixed by V0-D03/V0-D04; representations are not product scope. | Architecture/data/security design before implementation of saving/execution. No implementation starts by treating these as unspecified behaviors. |
| Message ancestry/versioning and event sourcing (Q-03, Q-11) | Stable/preserved source semantics are fixed; an edit feature is absent. | Decide required V0 persistence representation in architecture before implementation; future edit-specific representation before edit design. No event-sourcing choice made now. |
| Exact context budget/selection method (Q-12, Q-19) | Current conversation, intact newest message, preserved history, omission visibility, and input attribution are fixed. *(v0.1 dev: a narrow character-proxy recent-window policy is recorded in [ADR-0017](adr/0017-bounded-recent-history-context.md); the method is not settled.)* | Architecture benchmarking/context design before implementation; validate V0-AC-08 against the selected budget. |
| Branch identity and historical state-version representation (Q-01, Q-02) | Branch/merge implementations are out; current provenance does not require their finalized representation. | Before branch/merge architecture; review forward compatibility in V0-AC-15 now without choosing it. |
| Merge product/presentation (Q-04, Q-05) | No merge operation is offered. | Before requirements/scope for the first merge release, then design. |
| Memory classes, confidence, conflicts, organization (Q-06–Q-09) | Current history context is explicitly not Memory or Workspace/Project management. | Before requirements/design for each selected Memory/organization capability. |
| Rich privacy taxonomy and release consent/audit (Q-10, Q-17, Q-24) | V0 permits no external release; the safer supported behavior is unambiguous. | Before any WEB/cloud/tool/private-release capability is scoped/designed or enabled. |
| Expanded reproducibility/usage retention (Q-12, Q-13) | Minimum V0 attribution is retained; complete replay/token accounting is not claimed. | Before richer audit/replay/tool-execution requirements/design. |
| Automatic derived-state rebuilding/freshness (Q-14, Q-24) | No persistent summaries/indexes/Memory are required. Context reconstruction is already scoped. | Before requirements/design of the affected derived subsystem. |
| Deletion/erasure, provenance after removal, backup-copy propagation (Q-15) | No V0 lifecycle action or automatic pruning is offered; retention behavior is explicit. | Before adding any deletion/purge/retention-management capability; reassess privacy expectations before real use requiring erasure. |
| Hardware failure, corrupt-storage recovery, backups, quantitative loss/recovery targets (Q-18) | V0 declares intact-storage restart guarantees only, not tested disaster recovery. | Before a release claims such recovery or is scoped for data that requires it; a separate recovery task precedes those claims. |
| Multi-user/agents/native/distributed/offline-sync and other deferred products (Q-20, Q-22) | They are not prerequisites for the selected local connected lifecycle. | Before the corresponding future product scope/requirements task. |

Architecture cannot silently weaken these product choices to accommodate a technology. A discovered incompatibility returns to scope/requirements with evidence; significant architectural choices get ADRs in their own authorized task.

## 11. Review and completion

The scope document can be complete while the software release has outstanding implementation/benchmark gates. Release acceptance requires all applicable scenarios above to pass on the recorded configurations, all selected requirement subsets to have evidence, and the inventory, benchmark, and security design gates to be closed. Unimplemented software has no passing release evidence today.

### Review passes

These are separate author-performed review passes on 2026-10-03, not independent-agent approvals or runtime test results.

| Pass | Findings and disposition |
| --- | --- |
| Architect | Confirmed objective/capabilities against PD/DM/RB and mapped all 51 requirements. Kept one live model path with a separately testable replacement contract, not a runtime-bound identity. Marked full feature tests outside each partial subset explicitly; no database/API/authentication/runtime/network choice was made. Added iPhone creation because NFR-05 includes it. |
| QA | Checked concrete preconditions/actions/outcomes and required evidence for every selected subset. Kept configurations and benchmark-derived numeric limits as explicit gates rather than fabricating them. Corrected uncertain-saving language so missing confirmation implies neither success nor definite absence; bounded retries to the latest eligible message and added the older-retry rejection check. Distinguished live-model evidence from fault/replacement fixtures. |
| Security | Reviewed protected local/remote access, primary-owner provisioning, finite session validity, active-session revocation, old-IP reuse, and local operation during external outages. Required invalidation and denial of subsequent in-flight deliveries after revocation acknowledgment. Private-only behavior includes generated context, provenance, telemetry, and diagnostics; external tooling/consent cannot become a bypass. Concrete secure mechanisms are mandatory before access-capable use, not postponed until after release. |
| Data & Memory | Verified that retained transcript context is not scoped Memory; generated assistant records remain preserved historical output without promotion to user facts. Kept source/run/input association and restart retention, deferred full prompts/replay/lifecycle policies, and prevented retry from becoming historical regeneration/branching. Narrowed cycle checks to derivation ancestry so ordinary bidirectional references are not incorrectly prohibited. |

No contradiction with authoritative intent/domain invariants was found. Explicit V0 refinements include active-session invalidation on device revocation, the confirmed-save/retry policy, and intact-storage server-process recovery. These resolve permitted minimum product choices rather than changing source documents. Architecture/benchmark evidence and deferred-feature decisions remain open as recorded in section 10.

### Document completion checklist

- [x] Proposed objective and candidate capabilities evaluated against PD/DM/RB.
- [x] Q-19/Q-20/Q-23 addressed without fabricated hardware facts or performance targets.
- [x] Every baseline requirement classified once; partial subsets and deferred remainder explicit.
- [x] All baseline questions given a V0 disposition and decision debt has phase gates.
- [x] Six required release scenarios included, plus justified privacy, persistence, context, revocation, replacement, cost, and compatibility evidence.
- [x] Four review passes completed and corrections recorded.
- [x] Counts, source/requirement/scenario references, links, and changed-file scope checked.

Original scope-task documentation verification passed: all 51 RB IDs appear exactly once in the selection matrix; counts match; each selected subset has reciprocal scenario/requirement references; all 15 scenarios have preconditions/actions/outcomes/IDs; all 24 questions have dispositions and decision-debt coverage; all 15 domain invariants remain represented; six product-decision IDs, source-section references, four local links, user-supplied hardware facts, and whitespace checks are consistent. Pre/post file hashes confirm changes only to this document and its ExecPlan, with no deletions. These checks do not constitute software acceptance tests or hardware benchmarks.

The original scope task changed only this document and its ExecPlan; PD, DM, RB, `docs/04-architecture.md`, and later design documents were unchanged by that task. No application, schema, API, framework, dependency, model installation, network configuration, or architecture design is produced by this task.
