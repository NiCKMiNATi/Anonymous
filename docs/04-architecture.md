# Anonymous — Architecture Baseline v0.1

**Status:** High-level architecture baseline; decisions recorded below are accepted for this baseline. Implementation, technology selection, detailed design, and release evidence remain pending.
**Date:** 2026-10-03.

## 1. Purpose, authority, and decision boundary

This baseline assigns the selected V0 behavior to components and boundaries. It defines topology, ownership, dependencies, trust, execution, failure responsibilities, and replacement seams. It does not define storage schemas, concrete API contracts, credential mechanisms, Memory algorithms, or application code.

Authoritative inputs are [Project Definition](00-project-definition.md) (PD), [Domain Model](01-domain-model.md) (DM), [Requirements Baseline](02-requirements.md) (RB), and [V0 Scope](03-v0-scope.md) (V0). PD/DM establish intent and domain invariants; RB supplies requirement IDs; V0 supplies selected subsets, V0-D01–V0-D06, and release scenarios. Source draft/provisional status is preserved. This document does not expand V0 or globally settle its deferred questions. The [ExecPlan](../.agent/plans/2026-10-03-architecture-baseline.md) records execution and review.

The candidate architecture is compatible with these sources. A single server deployment and modular monolith fit the personal, existing-hardware scope and avoid unnecessary distributed coordination. Equal clients, canonical ownership, and model independence follow PD §§4, 9–12 and DM §§3–6, 8–9, 18–19, 31–33. Conceptual domain aggregates do not require separate services. One live local runtime path is sufficient for V0; replaceability still requires the controlled substitution evidence in V0-AC-11.

Completing this baseline does not close V0 §10's implementation/security/benchmark gates. Where that section says “architecture before implementation,” the remaining detailed architecture work in section 12 is still required; the narrower high-level task does not waive it.

## 2. Decisions and evaluated alternatives

| Decision | Chosen boundary and reason | Alternatives considered | Record |
| --- | --- | --- | --- |
| Shared server and canonical ownership | All clients use the same logical application contract. The server owns persistent application state. Windows co-hosting grants no client privilege. | Client-owned histories and peer synchronization add conflict/ownership work outside V0; direct local database/model access bypasses the common policy boundary. | [ADR-0001](adr/0001-shared-server-and-canonical-ownership.md) |
| One modular application | One active authoritative server application instance for V0, with internal domain/application/infrastructure boundaries. | Microservices add deployment/distributed failure costs; an undifferentiated monolith hides replacement and policy boundaries. | [ADR-0002](adr/0002-modular-monolith-server.md) |
| Owned context and model boundary | Context Builder constructs eligible input. Application-owned model contracts isolate local runtime adapters and runtime identity. | Provider-managed history/context would surrender source/privacy ownership; direct vendor calls spread coupling. | [ADR-0003](adr/0003-context-and-model-execution-boundary.md) |
| Owned persistence boundary | Application use cases depend on purpose-specific persistence contracts; adapters supply storage operations and reliable outcome evidence. | Concrete storage access throughout the application couples semantics to an engine; a universal repository obscures the guarantees needed by each use case. | [ADR-0004](adr/0004-persistence-port-boundary.md) |
| Layered private access | Private protected reachability, device approval, session authentication, resource authorization, and delivery checks are separate controls. | LAN/overlay membership alone and localhost exceptions cannot satisfy V0-D05; a public application ingress is unnecessary. | [ADR-0005](adr/0005-layered-private-access.md) |

These are architecture decisions made in this task, not independent specialist approvals or claims that a technology has been verified.

## 3. System context view

```text
Primary user / authorized owner
        |
        +--> Windows client --+
        +--> Mac client ------+--> protected private access --> Anonymous server
        +--> iPhone client ---+                                  |          |
                                                                v          v
                                                        local runtime   persistent state

Unknown LAN/public peers --> no implicit trust or application access
WEB / cloud AI / tools / external reporting --> no V0 application payload path
```

The user can have multiple devices and simultaneous sessions; User, Device, and Session remain distinct. Owner provisioning, approval, revocation, and recovery are protected operations of the server's access responsibility. Their supported operator interaction need not be a mobile administration interface. A reachable device is not thereby approved, and an approved device still needs a valid session and permission for the requested resource.

Remote authorized clients are part of the private environment. Local-first permits network-dependent remote access; it does not imply disconnected writes, peer synchronization, or mobile inference. A network outage may prevent a remote client from reaching the server while the provisioned local path remains usable.

## 4. V0 runtime and deployment view

```text
Existing Windows desktop: initial trusted host
  +---------------------------------------------------------------+
  | Ordinary Windows client                                       |
  |      | same logical contract and access checks as remote peers |
  |      v                                                        |
  | Anonymous server: ONE active authoritative application instance|
  |  transport | access | conversation/execution | Context Builder  |
  |  domain rules | model adapter | persistence adapter | lifecycle|
  |                          |                 |                  |
  |                          v                 v                  |
  |  separate local model runtime     server-private durable store |
  +---------------------------------------------------------------+
                   ^
          protected private transport
                   |
          MacBook / iPhone clients
```

The separate local runtime is a failure and replacement boundary, not a second owner of application history. Its endpoint and the store are server-private; clients cannot call either directly. One application instance may supervise ongoing executions without tying them to client connections. Multiple independent application workers with separate in-memory admission decisions are outside this deployment decision. Enforcing single authority and startup coordination is a detailed lifecycle gate, not permission to assume a launcher can never start twice.

The store is local durable infrastructure under server control; embedded storage versus a separate local storage service remains open. Static client delivery, executable packaging, process supervision, transport termination, and private-network implementation are also open. These are deployment mechanisms, not changes to client or domain authority.

The initial host is the user-reported Ryzen 7 5700X desktop with RTX 3070 8 GB VRAM, 32 GB RAM, and 1 TB NVMe. Clients include the M1 Pro MacBook Pro (2021), 16 GB RAM/512 GB SSD, and iPhone 17 Pro Max (2025), 256 GB. These facts are inventory, not measured feasibility. OS/browser versions, available capacity, model limits, and performance evidence remain gates from V0 §§4–5. No new compute hardware, mandatory paid AI/database service, or new required recurring subscription is assumed.

Local authentication and the local conversation lifecycle for an already provisioned device must work without external application services. Any selected remote transport may fail independently; that cannot introduce a cloud dependency into the functioning local path.

## 5. Logical component view and ownership

Component IDs below identify responsibilities, not packages, processes, tables, or mandatory interfaces between every pair of modules.

| ID / responsibility | Owns | Boundary / does not own |
| --- | --- | --- |
| C01 — Clients | Presentation, text input, temporary interaction state, protected server interaction, reconnect/reconciliation display, accessible pending/failure/authorship states. | No canonical history, authorization decisions, model invocation, or store access. Clearing local state cannot erase saved server data. Credentials/local caching need later security design. |
| C02 — Transport boundary | Validate inbound shape/size, resolve authenticated interaction through C03, dispatch application use cases, project results/errors, and gate protected delivery through C03. | No vendor model or storage semantics. No concrete protocol, routes, or streaming contract selected here. |
| C03 — Identity and access | Persistent user/device/session distinctions; owner-controlled bootstrap/approval/recovery; finite sessions, logout, revocation, operation/resource authorization, and V0 PRIVATE-only policy. | Network presence and IP addresses are not identity. No public self-enrollment. Credential/crypto details remain a security gate. |
| C04 — Conversation application service | Create/list/open/history use cases, ownership checks, and routing conversation interaction into C05. | Does not perform inference, choose runtime details, or treat client history as authoritative. |
| C05 — Execution coordinator | Per-conversation admission, submission reconciliation, eligible retry, saved user input, run/input/output associations, execution supervision, outcome finalization, and recovery. | Does not construct the context itself or place runtime/storage technology logic in domain behavior. No automatic uncertain-work replay. |
| C06 — Context Builder | Construct the authorized current-conversation view, preserve order/authorship, enforce the supported input budget, identify actual contributing messages and omissions. | No source mutation, direct inference, cross-conversation Memory/retrieval, or authority to release private content. |
| C07 — Model integration boundary | Anonymous-owned execution/capability contracts plus concrete adapter translating to the selected local runtime; distinguish model identity, runtime identity, and attempt outcomes. | Provider objects do not become domain identities. Runtime has no authority to read the database, select clients, authorize tools, or choose cloud fallback. |
| C08 — Persistence boundary | Application-owned contracts for history, access state, execution evidence, and outcome reconciliation; concrete adapters implement durable storage and report confirmed/failed/uncertain results. | No schema/engine selected. Adapter does not invent product retry, retention, ownership, or privacy policy. |
| C09 — Domain concepts and rules | Stable identities, ownership, authorship/source distinctions, preserved history, and valid derivation relations for supported operations. | No framework, database, runtime, network, or client dependency. Future domain invariants constrain design without implementing their deferred features. |
| C10 — Composition, lifecycle, diagnostics | Wire concrete dependencies, provide approved private configuration, supervise application lifecycle, invoke recovery before readiness, and emit sanitized operational evidence. | No alternate business-policy path, raw prompt logging, or externally exported private diagnostic payloads. |

Application persistence authority belongs to C03/C04/C05 under C09 rules, through C08. C06 has read-only access to eligible source information. C01 holds a view; C07 receives only constructed invocation input. Modules may share a backing store but do not reach into another module's concrete storage details.

For FR-15, C05/C08 establish and preserve each user and assistant message’s authoritative timestamp at commitment to persistent history as an absolute instant independent of client timezone. C04 exposes the retained history; C01 renders each displayed message’s time continuously near the message action area without hover in the selected/local timezone, with optional precise full date/time as secondary detail. C09 ensures timestamps are not the sole source of conversational ordering. These responsibilities select no physical representation or API.

“Canonical persistent application state” means authoritative ownership of saved records. It is distinct from DM's generated canonical/compressed state, which is deferred. Saved assistant text remains preserved evidence of generated output; its model origin does not make it disposable and does not turn it into explicit user knowledge.

### Context Builder boundary

C05 supplies an authorized conversation scope, the current saved user message, and normalized runtime budget/capability information. C06 reads retained eligible messages, includes the whole conversational history when it fits, preserves roles/order, and returns the constructed view plus actual source references and omission information. Necessary system instructions are part of the budget, without exposing credentials. If the full current message cannot fit, C06 refuses generation visibly; a saved user message is retained. Earlier selection and exact budget calculation remain detailed context/benchmark work.

C07 must execute the agreed input faithfully or report incompatibility; silent provider truncation would invalidate source attribution and omission visibility. Capability normalization is adapter work; selection of source information is Anonymous application work. The required selected runtime must support evidence sufficient to validate this boundary.

Later canonical state, scoped Memory, retrieval, and artifacts can supply authorized source contributions to context construction. Privacy eligibility precedes inclusion, and budgeting applies to the combined view. No plug-in framework, Memory taxonomy, retrieval ranking, correction algorithm, or provider signature is designed now. Context never becomes the database; losing it cannot remove source history.

## 6. Dependency-direction view

```text
Compile-time ownership / allowed knowledge

  C01 clients --> logical client/server contract (no server internals)
  C02 transport --> C03 access + C04 conversation application
  C04 conversation --> C03 + C05 execution + C09 + owned persistence contracts
  C05 execution --> C03 + C06 context + C09 + owned model/persistence contracts
  C06 context --> C09 + authorized scope + read-only persistence contract
  C03 access --> C09 + owned access-state persistence contract

  concrete model adapter ------> Anonymous-owned model contracts + vendor interface
  concrete persistence adapter -> Anonymous-owned persistence contracts + store interface
  C10 composition -------------> application modules + concrete adapters
  C09 domain ------------------> no infrastructure

Runtime dispatch (distinct from compile-time ownership)
  application --> owned port [fulfilled by adapter] --> local runtime / durable store
```

Contracts live on the Anonymous side of the boundary; application code does not import concrete adapters, vendor SDK types, query representations, or deployment configuration formats. Infrastructure depends on the contracts it fulfills. Only composition knows which concrete implementations are wired. C07/C08 name each boundary as a whole, not permission to import its adapter from a use case.

C04 may invoke C05; C05 does not call back into C04. It applies domain rules and persistence contracts directly for its execution use case. C06 does not invoke C05 or the runtime. Access checks remain reusable through C03 for reads, writes, admission, and delivery; they are not limited to a controller that another internal entry point could bypass.

Purpose-specific model and persistence contracts protect proven replacement/failure needs. Ordinary internal collaboration needs no interface solely for stylistic symmetry. No distributed event bus, service discovery, general agent framework, or universal repository is required. Protocol and persistence details remain outward-facing adapter concerns.

## 7. High-level trust and security boundary view

```text
untrusted networks and client input
    |
    | protected private reachability (not application authority)
    v
C02 ingress --> C03 device + session + operation/resource permission
    |                       |
    v                       +--> current permission at protected delivery
C04/C05 application --> C06 eligible private context --> C07 local runtime
    |                                                       |
    +--> C08 private store                 untrusted generated text
    |                                                       |
    +<----------------- validated execution outcome ---------+
    |
    +--> C02 delivery gate --> C01 safe presentation

No V0 branch to WEB/cloud/tools/external private-payload reporting
```

1. **Reachability:** Unknown LAN peers and public networks remain untrusted. Protected transport supplies confidentiality/integrity; no core application, runtime, store, or administration service needs direct public Internet ingress. Any network control plane/relay trust and metadata exposure require security design before remote connectivity.
2. **Application authority:** C03 validates distinct device approval and session authority; C04/C05 enforce ownership and operation permission. This includes the co-hosted Windows client. Bootstrap/recovery is controlled by the owner and cannot be open enrollment. Ordinary address changes can require reconnect or reauthentication but cannot redefine device trust.
3. **Session lifecycle:** Logout invalidates the chosen session; expiry denies protected access under a finite policy. Revocation invalidates all sessions of the device. C03/C08 confirm the revocation state and C02/C05 enforce it before acknowledging revocation. Further protected operations and deliveries, including in-flight output, are then denied. Already delivered data cannot be recalled; precise transport race handling is a detailed security/contract gate.
4. **Execution and delivery:** Entry authorization is not perpetual permission to stream or deliver a later result. C02/C03 check current authority for each protected delivery, whether incremental or final. A revoked client's local run may finish and save privately; revocation does not erase history. Another authorized client can inspect permitted saved outcomes.
5. **Private data and model distrust:** All V0 source content, output, context, and provenance remain PRIVATE. There is no runtime-configurable arbitrary cloud destination or model-controlled export/tool action in the supported V0 path. C07 and deployment controls constrain the runtime path; model compliance is not a security control. C01 renders generated content safely without executing instructions or automatically fetching external resources that could disclose private information.
6. **Secrets and diagnostics:** C03 keeps credentials out of unrelated model context; C02/C07/C08/C10 sanitize errors and operational diagnostics. Neither successful nor failed requests authorize exporting raw payloads, private provenance, or credentials through analytics/crash reporting. Private storage and credential protection mechanisms remain mandatory later design.

The owner-controlled host and its administration are within the trusted computing boundary. The architecture does not claim protection against a fully compromised host or recall of data already received by an authorized client. Runtime/package trust, OS permissions, local secret storage, and browser attack protections must be assessed in the later security design; this boundary is not evidence those mechanisms already exist.

## 8. Main V0 request flow and multiple sessions

```text
C01 client
  -> C02 ingress -> C03 authenticate/authorize -> C04 conversation
  -> C05 admission/reconciliation
  -> C08 durable user-message confirmation
  -> C06 context construction (authorized retained history + budget)
  -> C08 retained accepted-attempt/input association
  -> C07 owned model port -> local runtime
  <- provisional output / outcome
  -> C08 final assistant content + producing-run association confirmed
  -> C02 + C03 current delivery permission
  -> C01 complete-and-saved view
```

The ordering identifies semantic checkpoints, not transactions, fields, or a fixed protocol state machine.

1. Create/list/open/history requests pass C02/C03 and C04 to C08. Every target returns the same authoritative conversation identity, owner, and retained history.
2. For a send or explicit eligible retry, C05 checks current ownership, existing submission outcome, and conversation admission before accepting new input. A busy conversation rejects additional sends visibly without appending or silently queuing them. Simultaneous sessions share this single authoritative decision; a client-side disabled button is insufficient.
3. For a new accepted submission, C05 confirms the user message is durably recorded before model dispatch. A retry references the same saved user message and creates a distinct attempt. It is eligible only after a confirmed failed/interrupted attempt for the latest saved user message, with no later accepted message; running, successful, superseded, or uncertain attempts are not silently retried.
4. C06 builds the current-conversation view. Invalid input capacity or failed history loading prevents dispatch and leaves saved sources intact. C05 exposes the precondition failure without fabricating successful execution evidence.
5. Before dispatch, C05 retains enough accepted-attempt, model/runtime, and input-source association information through C08 to support V0-D03/D06 recovery. If this prerequisite cannot be confirmed, inference does not start. Detailed dispatch/recovery correlation remains a design gate; storing an intention alone does not prove invocation occurred.
6. C07 invokes the configured local runtime. C05 supervises the activity independently of the client socket. Optional incremental output is provisional and passes the current delivery guard. Runtime failure has no cloud fallback.
7. C05 reports completion-and-saving only after final assistant content and its producing-run association are durably confirmed. Failure evidence also requires confirmation before being described as persisted. A completed runtime call by itself is not a saved assistant message.
8. C02/C03 authorize result delivery at that time. C01 displays known saved/failed/in-progress/uncertain distinctions and context omissions. On reconnect it consults C04/C05's authoritative state before permitting retry; missing acknowledgment means neither success nor definite absence.

Repeated submission delivery or reconciliation must not create duplicate messages or successful responses. Correlation and durable reconciliation mechanisms are deferred to detailed design, with C05/C08 as owners. The application enforces one active generation per conversation, including across recovery; scheduling across different conversations is not promised. Reads can continue while a conversation generates when storage and authorization are available. Clients may refresh/reconnect; no particular push technology is implied.

## 9. Main failure-path view

```text
Request checkpoint
  +-- access denied/unknown --------> no protected operation or delivery
  +-- busy or ineligible retry -----> visible refusal; no appended submission
  +-- save/context prerequisite ----> stop before dispatch; retain known sources
  +-- runtime failure -------------> preserve user input; record known outcome
  +-- final save unconfirmed ------> uncertainty; reconcile; no false completion
  +-- client disconnected ---------> server outcome independent; reconnect/read
  +-- server restarted ------------> recovery gate before conflicting new work
```

| Failure | Responsible boundary and required behavior | Recovery / remaining mechanism |
| --- | --- | --- |
| Runtime unavailable or interrupted | C07 reports a sanitized failure; C05 preserves saved user/history and retains confirmed attempt evidence through C08. C01 distinguishes failure from completion. | Explicit retry only when V0-D04 eligibility is established. No automatic new inference or cloud fallback. |
| Storage unavailable before confirmation | C08 reports failure or uncertainty accurately; C05 does not dispatch inference without confirmed prerequisites. Reads cannot fabricate empty history when loading fails. | Reconcile the actual durable outcome when storage becomes available. Do not claim either saved or absent while unknown. |
| Storage failure after model output | C05 cannot call the response complete-and-saved; provisional output does not establish durable success. Earlier confirmed records remain intact. | Recover/reconcile output/run association if possible; expose unresolved outcome otherwise. Ordinary logs are not a substitute store. Atomicity/correlation details precede implementation. |
| Client connection loss | C02 loses a delivery path, not ownership of execution. C05 can continue supervised work; C01 shows lost/uncertain connectivity. | Reauthenticate if needed, reopen authoritative state, reconcile the same submission. No implicit resend generating new history. |
| Normal restart or abrupt application termination | C10 invokes C05/C08 recovery. Confirmed history/identity/provenance survive on intact accessible storage. Incomplete attempts are not marked completed or replayed. | A separate runtime may still execute after the server dies. Before admitting conflicting work, establish that prior execution ended or safely stop/reconcile it through C07. If this cannot be established, keep the conversation visibly blocked/uncertain; do not release admission merely because a process restarted. Runtime capability and supervision evidence are a pre-implementation gate. |
| Context construction/view loss | C06/C05 expose the failure and retain raw source records. No model result is fabricated. | A later permitted explicitly requested attempt reconstructs a view from sources. It does not regenerate or replace saved assistant history. |
| Unauthorized, expired, or revoked interaction | C03/C02 deny entry/delivery; C04/C05 cannot bypass permission for protected work. Invalid access does not delete records or revive trust through address reuse. | Owner-controlled authorization/recovery and valid sessions only. If current permission cannot be established, fail closed for protected access. |
| Resource exhaustion or storage limit | C07/C08/C10 surface the affected boundary; C05 does not silently prune history, select cloud execution, or report false saving. | Supported limits and operational recovery are established with the hardware benchmark and persistence design. No physical-disk disaster recovery is claimed. |

V0-D06 guarantees intact-storage process restart behavior, not hardware power-loss, corrupted/destroyed storage recovery, backups, or quantified recovery times. Detailed mechanisms must demonstrate bounded, observable recovery on the selected runtime rather than leaving uncertainty as the normal successful outcome.

## 10. Future replacement and evolution view

```text
New client ------------> same logical server capability boundary
New server host -------> composition/deployment changes; identity/history preserved
New model/runtime -----> adapter/capability integration; same application semantics
New store -------------> persistence adapter + verified data transition
Future domain features -> application/domain additions -> authorized Context Builder inputs
```

Replaceability means identifying and containing change, not claiming every vendor or host can be swapped without integration work. A storage transition still requires later preservation/migration design and evidence; no migration is designed here.

| Future capability/change | Constraint retained now | Deferred decision |
| --- | --- | --- |
| Model/runtime replacement | C07 isolates vendor types; C05 retains historical model/runtime attribution; conversation identity is independent (INV-008). | Additional production integrations, capabilities, routing, and hardware execution. |
| Host/client replacement | C01 owns presentation only; C09 identities do not encode a machine; Windows uses the same access boundary (INV-009, INV-010). | Packaging/relocation procedures, native clients, disconnected sync, and distributed operation. |
| Persistent identities and renaming | C09/C08 preserve stable object identity independently of names (INV-001, INV-002); no rename UI required. | Representation and future rename/lifecycle contracts. |
| Branches and merges | Sources cannot be destructively rewritten; merge results require a new identity, ancestry, acyclic derivation, and stable historical source boundaries (INV-003, INV-004, INV-005, INV-011, INV-014). V0 linear presentation imposes no permanent linear-only domain model. | Branch object versus relation, state versions, merge product/presentation and algorithms. No speculative graph storage or merge schema now. |
| Memory and correction | C09 preserves explicit user versus generated origin; future correction can supersede inference while retaining provenance (INV-007, INV-013). | Taxonomy, scopes, confidence, conflict resolution, organization, extraction and correction mechanisms. A corrective chat message alone is not Memory correction. |
| Canonical/compressed state, retrieval, artifacts | C06 accepts future eligible contributions; source history remains distinct from derived views (INV-006, INV-015). Artifact identity must remain independent of storage location. | Summaries, indexes, retrieval ranking, artifact storage, rebuilding/freshness, and full provenance representation. |
| WEB/cloud/tools/private release | C03 and the server enforce privacy independently of model behavior (INV-012); adding an adapter alone cannot authorize release. | New scope plus explicit release/consent/audit and tool permission design before any external capability. |
| Deletion, retention management, disaster recovery | V0 retains sources/run evidence with the dataset and never silently prunes. | Lifecycle meanings, erasure propagation, backups, restoration, quantitative recovery guarantees. |

The acyclic rule applies to derivation ancestry. Bidirectional lookup between a message and its producing run is not by itself a derivation cycle. Future constraints above are compatibility obligations, not V0 feature implementations.

## 11. Traceability to selected requirements and release scenarios

The matrix assigns every selected RB subset an owner. Applicability and subset meanings remain exactly those of V0 §6; “partial” does not promise deferred remainder. Scenario IDs in V0 remain the acceptance authority. Component ownership is documentation evidence, not a passing implementation test.

| Requirement | V0 classification | Responsible components / architectural obligation |
| --- | --- | --- |
| FR-01 | REQUIRED_V0 | C01/C02/C03/C04/C08/C09: create/list/open stable owned conversations. |
| FR-02 | REQUIRED_V0 | C01/C04/C05/C06/C07/C08: saved-input execution and durable responses. |
| FR-03 | REQUIRED_V0 | C01/C02/C03/C04/C08: authorized cross-device continuation from shared state. |
| FR-08 | PARTIAL_V0 | C03/C05/C06/C07: current-conversation bounded input and source attribution; no Memory. |
| FR-09 | PARTIAL_V0 | C01/C04/C08: browse retained old messages independently of current model input; no semantic retrieval. |
| FR-12 | REQUIRED_V0 | C05/C07/C08/C09: distinct execution/model/runtime identities and outcomes. |
| FR-14 | REQUIRED_V0 | C03/C04/C08/C09: persistent user ownership independent of device/session. |
| FR-15 | REQUIRED_V0 | C01/C04/C05/C08/C09: persistent commitment instants, continuous selected/local time near message actions without hover, and ordering not based solely on timestamps. |
| NFR-01 | REQUIRED_V0 | C03/C07/C08/C10: provisioned local lifecycle has no required cloud dependency. |
| NFR-02 | PARTIAL_V0 | C05/C07/C09/C10: one live path plus controlled replacement fixture; history unaffected. |
| NFR-03 | REQUIRED_V0 | C01/C04/C08: canonical history lives on server; no client export/import prerequisite. |
| NFR-04 | REQUIRED_V0 | C09/C10: host-independent meanings and equal local/remote clients. |
| NFR-05 | REQUIRED_V0 | C01/C02: Windows/Mac core and iPhone essential interactions, including create and bounded accessibility checks. |
| NFR-06 | REQUIRED_V0 | C07/C08/C10: existing hardware/no required new paid infrastructure; benchmark envelope still gated. |
| NFR-07 | REQUIRED_V0 | C03–C10: cohesive responsibilities with inward contract dependencies. |
| SEC-01 | REQUIRED_V0 | C02/C03: application authentication independent of network presence. |
| SEC-02 | REQUIRED_V0 | C02/C03/C04/C05: operation/resource checks and current delivery authorization. |
| SEC-03 | REQUIRED_V0 | C03/C08: stable device trust across ordinary address changes. |
| SEC-04 | REQUIRED_V0 | C02/C03/C05/C08: revoked devices cannot revive trust or continue protected deliveries. |
| SEC-05 | REQUIRED_V0 | C02/C03/C08: distinguish sessions/devices; finite expiry, logout and device-wide revocation. |
| SEC-06 | REQUIRED_V0 | C02/C03/C10: protected private local/remote access, no LAN trust or required public service ingress. |
| SEC-08 | REQUIRED_V0 | C02/C03/C06/C07/C08/C10: secrets excluded from unrelated context and sanitized diagnostics. |
| PRIV-01 | REQUIRED_V0 | C01/C03/C06/C07/C10: PRIVATE payloads remain within supported private paths. |
| PRIV-03 | PARTIAL_V0 | C01/C03/C05/C06/C07/C08/C10: output/context/provenance copies remain PRIVATE; broader propagation deferred. |
| PRIV-04 | REQUIRED_V0 | C03/C07/C10: no uncertain permission can enable export; no release capability. |
| PRIV-05 | REQUIRED_V0 | C01/C03/C07/C10: generated instructions cannot execute or override privacy. |
| DATA-01 | REQUIRED_V0 | C03/C04/C05/C08/C09: stable supported identities unrelated to client/model/display name. |
| DATA-02 | PARTIAL_V0 | C04/C05/C06/C08/C09: preserve saved raw history through supported operations. |
| DATA-03 | PARTIAL_V0 | C05/C06/C08/C09: distinguish source statements, generated history, transient context. |
| DATA-05 | PARTIAL_V0 | C01/C05/C06/C09: preserve authorship; no promotion of generated output to user facts. |
| DATA-07 | PARTIAL_V0 | C05/C08/C09: noncyclic output derivation; future ancestry invariants preserved. |
| DATA-08 | REQUIRED_V0 | C05/C07/C08: durable response-to-run/model/runtime attribution. |
| REC-01 | PARTIAL_V0 | C05/C08/C10: confirmed V0 records survive normal/abrupt process restart with intact storage. |
| REC-02 | REQUIRED_V0 | C01/C05/C08: confirmed/failed/unknown saving distinguished and reconciled. |
| REC-03 | REQUIRED_V0 | C01/C05/C07/C08: visible runtime failure without loss of saved history. |
| REC-04 | PARTIAL_V0 | C01/C02/C03/C05/C06/C08: visible context/history/access-policy failures without false success. |
| REC-05 | PARTIAL_V0 | C05/C06/C08: reconstruct transient context without sacrificing sources; no derived subsystem rebuild. |

Inventory: **37 selected subsets = 26 REQUIRED_V0 + 11 PARTIAL_V0**. Remaining **11 DEFERRED** IDs are FR-04, FR-05, FR-06, FR-07, FR-10, FR-11, FR-13, DATA-04, DATA-06, DATA-09, REC-06. The **4 NOT_APPLICABLE_V0** IDs are SEC-07, PRIV-02, PRIV-06, DATA-10. Section 10 preserves their relevant constraints without adding features; exclusion checks remain V0-AC-01/07/09.

| Release scenario | Architectural home and key checkpoint | Evidence still required |
| --- | --- | --- |
| V0-AC-01 — Local continuity/attribution | C01/C04/C05/C06/C07/C08/C09; saved response/run/input association, retained authorship and history. | Live local exchanges and saved-record comparison, including commitment timestamps and equal/non-monotonic timestamp ordering fixtures; excluded lifecycle features absent. |
| V0-AC-02 — Restart | C05/C07/C08/C10; durable confirmation and recovery/admission gate, including surviving runtime work. | Normal and abrupt process termination with intact storage, retained timestamp instants, lost-ack reconciliation. |
| V0-AC-03 — Cross-device interaction | C01/C02/C03/C04/C08; same identity/history, client clearing harmless to saved data. | Recorded three-device configurations and keyboard/touch/focus/naming/state checks; continuous no-hover message times and timezone/date-boundary rendering of unchanged instants. |
| V0-AC-04 — Network changes | C02/C03/C10; protected remote path and IP-independent trust. | Authorized remote/mobile reconnect under actual network changes. |
| V0-AC-05 — Unauthorized peers | C02/C03/C04/C05; deny unapproved devices even with network reachability or user credentials alone. | Unknown LAN, address reuse, local Windows and unapproved-device cases. |
| V0-AC-06 — Runtime failure/retry | C05/C07/C08/C01; saved input survives, distinct eligible retry run. | Controlled runtime failure plus live path recovery; historical evidence unchanged. |
| V0-AC-07 — Storage/concurrency | C05/C08/C01; admission, save confirmation, deduplication and latest-message retry boundary. | Fault/uncertainty injection, busy sends, repeated delivery, and superseded-retry refusal. |
| V0-AC-08 — Context bounds | C06/C05/C07/C04/C01; source-preserving omission, full newest input or visible refusal. | Measured budget, complete-fit/overflow cases, old-history browsing and role preservation. |
| V0-AC-09 — Private-only execution | C01/C03/C06/C07/C10; no cloud/tool/release path, even from hostile output or model failure. | All offered interaction/configuration surfaces and observable application destinations. |
| V0-AC-10 — Logout/expiry/revoke | C02/C03/C05/C08; current ingress/delivery authority across all device sessions. | In-flight delivery denial after revocation acknowledgment, finite expiry, unrelated sessions retained. |
| V0-AC-11 — Replacement boundary | C05/C07/C08/C09/C10; substitute at the owned model contract. | Live exchange first, controlled alternate fixture next; no client/history identity change. |
| V0-AC-12 — Hardware/local cost | C03/C07/C08/C10; local auth and execution without required external service. | Inventory, benchmark envelope, external access blocked, no required purchases/subscription. |
| V0-AC-13 — Context loss | C05/C06/C08; reconstruct from sources after visible failure. | Fault then permitted explicit attempt; exact saved history comparison. |
| V0-AC-14 — Transport/diagnostics | C02/C03/C06/C07/C08/C10; encrypted protected boundary, sanitized evidence. | Untrusted observer/tampering, synthetic markers, diagnostic/context and exposure inspection. |
| V0-AC-15 — Compatibility | C01–C10; dependency rules and section 10 invariant constraints. | This design review plus later implementation dependency/ancestry/replacement inspection. |

All 15 release scenarios have an architectural home. None is claimed to have passed runtime acceptance in this task.

## 12. Technology status and remaining decision gates

No concrete technology is finalized. The accepted choices are architectural boundaries: shared server ownership, one modular application instance, separate local runtime, application-owned ports, explicit Context Builder, and layered access.

| Candidate / decision | Status and evidence needed | Latest gate / future document |
| --- | --- | --- |
| TypeScript/React client | Provisional. Validate supported desktop/mobile interactions, safe rendering, credential handling, accessibility, packaging and maintenance cost. | Frontend/security/contract design before client implementation; record configurations before acceptance. |
| Python/FastAPI server | Provisional. Demonstrate coherent supervision, concurrency/admission, private serving and abrupt-process recovery on Windows. | Detailed backend/deployment design before implementation; record selection separately if justified. |
| Ollama / actual local model | Provisional. Validate real input budgeting, faithful invocation, outcome/lifecycle correlation, restart behavior and resource/quality envelope. | Architecture-phase benchmarking on recorded existing hardware before implementation acceptance; lifecycle feasibility before execution implementation. |
| Tailscale / protected transport | Provisional. Validate local/offline path, remote/mobile changes, encryption, no required public service ingress, metadata/control-plane trust and no new mandatory subscription. | [Security design](07-security.md) before remote connectivity or an access-capable build. |
| SQLite / storage engine, SQL versus NoSQL | Provisional. Demonstrate durable confirmations, response/run consistency, duplicate reconciliation, restart behavior and capacity within V0 semantics. | [Data model](05-data-model.md) and detailed persistence architecture before saving/execution implementation; no tables chosen here. |
| Credential type, first-owner recovery, finite session parameters, revocation races, storage/OS protections | High-level owner/enforcement boundaries chosen; mechanisms still open (Q-21). | Security design before any access-capable build or real remote/private-data use, not after release. |
| Correlation, persistence coordination, provenance representation, admission and single-instance recovery | C05/C08/C10 own outcomes; representations and mechanisms remain open (Q-12/Q-13/Q-16/Q-24). Runtime work surviving restart requires explicit handling. | Data model plus detailed backend/lifecycle/security design before implementation; [API contract](08-api-design.md) later expresses these semantics. |
| Message ancestry/version representation and event sourcing | No event-sourcing decision. Stable source semantics do not select a storage history mechanism (Q-03/Q-11). | Data model/detailed architecture before V0 persistence implementation; editing-specific decisions before later editing design. |
| Exact input selection/budget and runtime performance | Current-conversation/omission semantics fixed; capacity and earlier-message selection unmeasured (Q-12/Q-19/Q-23). | Context design and hardware benchmark before implementation; finite agreed acceptance envelope before release tests. |
| Branch/state versions/merge UI and product | Invariants retained; Q-01/Q-02/Q-04/Q-05 unresolved. | Requirements/scope and architecture for the first branch/merge release. |
| Memory, confidence, conflict, Workspace/Project, derived rebuilding | No V0 subsystem (Q-06–Q-09/Q-14); context input seams only. | Future scope and [Memory design](06-memory-design.md), with domain/persistence review. |
| Rich privacy/release audit, richer replay, deletion, disaster recovery, advanced capabilities | V0 subset/exclusions unchanged (Q-10/Q-12/Q-13/Q-15/Q-17/Q-18/Q-20/Q-22/Q-24). | Before the relevant feature or stronger guarantee is selected; separate design tasks. |

Detailed work may identify a candidate's incompatibility with the fixed V0 outcomes. That requires documented reconsideration of the candidate or explicit requirements/scope change, not weakening preservation, privacy, or recovery silently. The linked later documents remain placeholders after this task.

## 13. Review record and completion

Five focused author review passes were performed on 2026-10-03 against the [specialist responsibilities](agents/README.md). They are not independent approvals or implementation verification.

| Review | Finding and disposition |
| --- | --- |
| Security | Network trust cannot replace device/session/resource authority. Included the Windows client, controlled owner provisioning, finite sessions, current delivery checks after revocation, safe model-text presentation, and private diagnostics. Concrete credential/transport/metadata mechanisms remain pre-access gates. |
| Data & Memory | Canonical ownership could be confused with deferred canonical summaries; section 5 distinguishes them. Preserved generated response history, source/input/run associations, authored versus inferred origin, and every invariant. Bounded ancestry checks to derivation, leaving branch/state-version/event-sourcing representations open. |
| Backend | Split conversation management from execution admission/recovery, removed any C05-to-C04 callback dependency, and separated socket lifetime from inference supervision. Added the surviving-runtime restart case and required reconciliation before conflicting work. Detailed durability/dispatch coordination remains mandatory before code. |
| Frontend | All three clients share realistic server capabilities; iPhone includes conversation creation and essential recovery/access states. Clients show provisional versus saved versus uncertain outcomes, omissions, safe generated text, and V0 accessibility checks; they do not own deduplication or canonical history. UI/framework and protocol details stay open. |
| QA | Assigned all 36 selected subsets and 15 scenarios, including busy/duplicate/superseded retries, save uncertainty, active revocation, context loss, hardware evidence and controlled replacement. Distinguished design coverage from runtime proof and retained all outstanding benchmark/security/design gates. |

No conflict with PD/DM intent or domain invariants was found. Their unresolved representations remain unresolved. The main terminology ambiguity is “canonical”: authoritative persistent ownership is required now, whereas derived canonical/compressed state is deferred. Architecture-phase evidence in V0 remains due in subsequent authorized work; this baseline alone is not implementation readiness.

Completion criteria: the eight requested views are present; selected requirements/scenarios have owners; actual decisions have ADRs; all five review passes are recorded; links, ID/classification coverage, invariant coverage, and changed-file scope are checked. Validation results are recorded in the ExecPlan.

Only this baseline, its ADRs, and its ExecPlan are changed. No schema, migration, concrete API route/contract, detailed Memory algorithm, UI design, dependency installation, framework initialization, runtime/network configuration, or application implementation is introduced. Data modeling does not begin without a new task.
