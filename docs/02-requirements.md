# Anonymous — Requirements Baseline v0.1

**Status:** Draft baseline v0.1; not an implementation or a V0 commitment.
**Date:** 2026-10-03.
**Role:** Architect; separate Architect, Security, Data & Memory, and QA review passes recorded below.

## 1. Purpose and scope

This baseline translates established project intent and domain semantics into required product behavior and qualities. It covers the product across its intended evolution. Inclusion does not select a capability for V0. Conditional requirements apply when their named capability is offered; selecting that capability brings its associated integrity, privacy, security, and recovery guarantees with it.

Normative product obligations appear only in the numbered records in sections 5–10. **Shall** denotes an obligation within this draft baseline. Scenarios, examples, questions, and review notes explain the requirements without creating additional unnumbered obligations. IDs remain stable across revisions; retired IDs are retained as retired rather than reused.

Each record includes a title, statement, source/rationale, acceptance criteria, and status. **Draft — source-derived** identifies a translation of established intent. **Draft — derived safeguard** identifies a concrete consequence of that intent that the sources do not spell out verbatim; it is visible for review rather than represented as an already accepted design decision. Neither status means implemented, tested in software, or separately approved by the user. **Draft — user-directed** identifies an explicit product requirement added by the user; it does not mean implemented or tested. FR-15 records the user’s 2026-10-03 timestamp requirement, selected for V0 in [V0 Scope](03-v0-scope.md).

Acceptance criteria describe future black-box, controlled-fixture, or design-review checks. Inspection of context/provenance does not require a public inspection API or permanent full-prompt logging. Test examples use synthetic information. No numerical latency, capacity, availability, retention, or recovery target is invented. Missing targets and incomplete product policies appear as questions, not vague requirements that claim to be testable.

Application code, frameworks, dependencies, schemas, concrete API endpoints, deployment configuration, technology selection, and V0 scoping are outside this task.

## 2. Authoritative source documents

| Reference | Document | Authority |
| --- | --- | --- |
| PD | [Project Definition](00-project-definition.md), Draft v0.1 | Project intent, constraints, privacy/security principles, provisional directions, and deferred capabilities. |
| DM | [Domain Model](01-domain-model.md), Draft v0.1 | Domain meanings, relationships, provisional invariants, and deliberate open questions. |

`PD §x` and `DM §x` refer to numbered source sections; `DM §48.n` means question n in section 48, not a separate source heading. `INV-*` refers to DM §46. Each requirement has source traceability; section 11 adds scenario and invariant coverage. DM depends on PD; apparent tensions are recorded rather than resolved through unstated precedence.

[AGENTS.md](../AGENTS.md), [ExecPlan guidance](../.agent/PLANS.md), and [specialist responsibilities](agents/README.md) govern repository work. They do not turn technology candidates into product constraints. Both authoritative documents already use Anonymous; neither was rewritten for this baseline.

## 3. Actors and operating contexts

| Actor/context | Meaning and boundary |
| --- | --- |
| Primary user | One human initially; persistent ownership still has user identity. Multi-user product behavior is deferred (PD §15; DM §4). |
| Authorized client/device | Windows desktop, macOS/MacBook, or iPhone presenting the user's environment. Device, session, and network location are distinct (PD §§4.4, 9; DM §§5–6). |
| Anonymous system/server | Coordinates persistent state, context construction, execution, and policy. A client is not the sole canonical owner (PD §§4.4, 10). |
| Model/runtime | Replaceable computational dependency, not the authority for privacy policy. Model and runtime identity differ (PD §§3, 11; DM §§31–33, 46). |
| Tool/external service | A capability or destination with a trust/privacy boundary; model access does not imply trust (DM §§34–35). |
| Unauthorized peer | An unknown LAN peer, unapproved device, or caller lacking authority; proximity is not trust (PD §8). |
| User operating the local system | The same primary user maintaining/restarting the host, not a new administrative role or privilege hierarchy (PD §§14, 16, 19). |

Conditions include one Windows machine acting as both client and initial server, another client reconnecting, ordinary IP changes, external-service outages, finite model context, server restart, unavailable derived data, and optional external activity alongside private information. Local-first does not establish disconnected-client editing/synchronization requirements (Q-20).

## 4. Core user/system scenarios

These are product scenarios, not a V0 selection. Failure variations accompany successful flows.

| ID | Preconditions/action | Expected observable outcome | Principal requirements |
| --- | --- | --- | --- |
| SC-01 | Authorized user creates a conversation, sends a message, receives a response, and continues. | Stable identity, recoverable content/authorship, and continued logical context; failure distinguishable from success. | FR-01, FR-02, FR-12, FR-14, FR-15, DATA-01, DATA-02, REC-02, REC-03 |
| SC-02 | Same user reconnects from another authorized client. | Same saved history and identity without dependence on the first client's state; unauthorized access denied. | FR-03, FR-15, NFR-03, NFR-05, SEC-01, SEC-02 |
| SC-03 | Saved conversation exists; server stops normally and restarts with storage intact. | Saved records, identity, and ancestry remain available. Unfinished writes/storage loss are separate questions. | FR-15, DATA-01, DATA-02, REC-01 |
| SC-04 | User branches at an identifiable point and continues both paths. | Original survives; divergence and each path's ancestry remain identifiable. | FR-04, DATA-02, DATA-07, REC-06 |
| SC-05 | Two or more conversations, including unrelated ones, merge; sources later evolve. | New identity, retained ancestry/historical boundaries, unchanged sources. Exact merge content remains open. | FR-05, DATA-04, DATA-06, DATA-07, REC-06 |
| SC-06 | User explicitly corrects an inference. | Historical inference remains traceable but no longer treated as current truth within the corrected scope. | FR-06, FR-07, DATA-05 |
| SC-07 | Request uses recent history plus scoped persistent/derived information; lifetime history exceeds model context. | Bounded constructed context, retrievable evidence, and preserved source history outside the request. | FR-08, FR-09, FR-10, DATA-03, PRIV-03 |
| SC-08 | Web/cloud/tool activity is requested while private messages, memories, and files exist. | General web permission does not export private context; any supported explicit release stays within its scope. | PRIV-01–PRIV-06, SEC-07, SEC-08 |
| SC-09 | Approved device changes IP; unknown/revoked device uses an old address. | Address change alone neither changes established identity/trust nor grants it to another device. | SEC-03, SEC-04, SEC-05, SEC-06 |
| SC-10 | Derived summaries/indexes become unavailable; recovery is attempted and may fail. | Sources survive, limitations are exposed, supported representations can be rebuilt without promising identical AI output. | DATA-03, DATA-04, REC-04, REC-05 |
| SC-11 | Model/runtime is replaced or becomes unavailable. | History and identity remain usable; execution is attributable, and failure is visible. | NFR-02, FR-12, DATA-08, REC-03 |
| SC-12 | Artifact is retained and later retrieved or used as evidence. | Identity, content reference, ownership, and provenance remain distinguishable; privacy still applies. | FR-11, DATA-04, DATA-09, SEC-02, PRIV-03 |

## 5. Functional requirements

### FR-01 — Create and reopen a conversation

- **Statement:** Anonymous shall allow an authorized user to create a persistent conversation and reopen it after leaving the interaction.
- **Source/rationale:** PD §§5.1, 14; DM §§4, 8: a durable logical context.
- **Acceptance criteria:** Create two conversations, record distinct identities, leave, and reopen each. Each retains its identity and its own saved content; reopening does not create a replacement conversation.
- **Status:** Draft — source-derived.

### FR-02 — Continue conversational interaction

- **Statement:** Anonymous shall let an authorized user add messages and receive model-generated responses within an existing conversation while retaining the distinction between message authors.
- **Source/rationale:** PD §§5.1–5.2, 14; DM §§8–10, 33.
- **Acceptance criteria:** Complete two exchanges and reopen the conversation. Recover both user messages and completed assistant responses with correct authorship and conversational relationships. Failed execution follows REC-03.
- **Status:** Draft — source-derived.

### FR-03 — Continue from another authorized client

- **Statement:** Anonymous shall make saved conversations available for continuation from another authorized client without redefining user or conversation identity.
- **Source/rationale:** PD §§4.4, 9, 21; DM §46 INV-009.
- **Acceptance criteria:** Save an exchange on client A, disconnect A, authenticate the same user on B, and continue it. Identity/history remain intact; no transfer from A is needed for those saved records.
- **Status:** Draft — source-derived.

### FR-04 — Branch at an identifiable origin

- **Statement:** Anonymous shall support divergence from an identifiable conversational state and continuation of both paths without destructively modifying the original path.
- **Source/rationale:** PD §5.3; DM §§10–12; INV-003. Persistent Branch identity remains open.
- **Acceptance criteria:** Branch at an intermediate fixture point and add different messages on each path. Identify the divergence and correct ancestry for each; previously saved source content is unchanged.
- **Status:** Draft — source-derived.

### FR-05 — Create a derived merge

- **Statement:** Anonymous shall support combining context from two or more source conversations, including unrelated ones, into a new derived conversation with its own identity and source ancestry, preserving each source.
- **Source/rationale:** PD §5.4; DM §§13–16; INV-004, INV-005. Synthesis/presentation remain Q-04/Q-05.
- **Acceptance criteria:** Merge two unrelated fixtures, then a fixture with three sources. Results have new identities and identify all sources; source content/identities are unchanged. Check historical boundaries using DATA-06. Synthesis quality is not claimed by these integrity checks.
- **Status:** Draft — source-derived.

### FR-06 — Maintain scoped knowledge independently of message order

- **Statement:** When maintaining memory, Anonymous shall retain knowledge independently from raw conversational ordering and distinguish its applicable scope.
- **Source/rationale:** PD §6; DM §§20–24. Scope examples do not finalize Workspace/Project concepts.
- **Acceptance criteria:** Retain an item in a supported scope, add unrelated messages, and retrieve the item in its applicable scope. Retrieval in a known non-applicable scope does not treat it as generally applicable knowledge. Complete scope/class behavior remains Q-06/Q-09.
- **Status:** Draft — source-derived.

### FR-07 — Apply explicit user corrections

- **Statement:** Anonymous shall allow an explicit user correction to supersede conflicting AI-inferred knowledge within the correction's scope while retaining historical provenance.
- **Source/rationale:** PD §20; DM §§25–27; INV-013.
- **Acceptance criteria:** Correct an identified fixture inference in a specified scope. Subsequent current-knowledge retrieval/context uses the correction instead of treating the old inference as current truth. Historical inspection still identifies both. Natural-language correction detection is not prescribed.
- **Status:** Draft — source-derived.

### FR-08 — Construct context for each model invocation

- **Statement:** Anonymous shall construct model invocation context from eligible persistent and/or derived information within the target invocation's input limits and applicable scope/privacy constraints, without treating that request view as the authoritative database.
- **Source/rationale:** PD §§6.3, 10; DM §§18–19, 50; INV-015.
- **Acceptance criteria:** For a controlled request whose specified input is a retained message excerpt plus an applicable memory, provide sufficient input capacity and inspect the constructed context: both contributions are present and within the invocation limit. Add prohibited private material for an external destination; it is excluded. Altering the request view leaves sources unchanged. Unfulfillable input constraints follow REC-04; general selection/ranking policy remains open.
- **Status:** Draft — source-derived.

### FR-09 — Retrieve retained source detail beyond current context

- **Statement:** Anonymous shall support retrieval of retained conversation/source detail absent from the current model context or compressed representation.
- **Source/rationale:** PD §§2, 6.3; DM §§18–19, 28, 50.
- **Acceptance criteria:** In history larger than the test model's context, retrieve a known omitted detail through a supported lookup, identify its source, and make it eligible for a permitted subsequent context. Ranking/recall targets remain Q-19.
- **Status:** Draft — source-derived.

### FR-10 — Maintain canonical state as derived information

- **Statement:** When offering canonical/compressed state, Anonymous shall allow its regeneration or supersession while keeping source history recoverable and distinct.
- **Source/rationale:** PD §§6.3, 18; DM §§17, 44; INV-006.
- **Acceptance criteria:** Generate state, update its source, and supersede the state. Recover original messages unchanged; each available state is identifiable as derived. Replacing current state does not replace sources.
- **Status:** Draft — source-derived.

### FR-11 — Retain user-accessible artifacts

- **Statement:** When artifacts are supported, Anonymous shall retain their logical identity and authorized means of accessing associated content separately from conversational message identity.
- **Source/rationale:** PD §§1, 10; DM §§28–30.
- **Acceptance criteria:** Retain a synthetic uploaded artifact, leave/reopen its owning context, and access the same content under the same artifact identity. A referencing message remains a distinct record. Availability of linked external bytes is not guaranteed.
- **Status:** Draft — source-derived.

### FR-12 — Distinguish model execution from model identity

- **Statement:** Anonymous shall distinguish individual model invocations and outcomes from the model and runtime identities used to execute them.
- **Source/rationale:** PD §§3, 11, 19; DM §§31–33.
- **Acceptance criteria:** Execute two successful and one failed fixture invocation with a known model/runtime. Distinguish all three runs and outcomes without treating them as three new models. Retained fields/duration remain Q-13.
- **Status:** Draft — source-derived.

### FR-13 — Account for tool execution

- **Statement:** When tools are supported, Anonymous shall distinguish capabilities from individual executions and make execution outcomes attributable to the tool invoked.
- **Source/rationale:** PD §§10, 19; DM §§34–35.
- **Acceptance criteria:** Execute a permitted tool successfully and with a controlled failure. Identify the tool and distinguish both outcomes. Availability grants no extra authority under SEC-07; retention remains Q-13.
- **Status:** Draft — source-derived.

### FR-14 — Retain user ownership identity

- **Statement:** Anonymous shall associate persistent user-owned information with a user identity even when operating for one primary user.
- **Source/rationale:** DM §§4, 8, 30; PD §4.4.
- **Acceptance criteria:** Determine the owning user for saved conversations and supported memories/artifacts. Access through another authorized device does not change ownership. This does not require a multi-user feature.
- **Status:** Draft — source-derived.

### FR-15 — Persist and continuously display message timestamps

- **Statement:** Every committed user and assistant message shall have a server-assigned absolute timestamp, designated its **commit timestamp**, stored and represented as an absolute instant independent of client timezone. The commit timestamp shall be sampled within the transaction responsible for committing the message, after the transaction has obtained the required write authority and before its commit attempt. The sampled timestamp becomes authoritative only if the corresponding message is successfully committed. If the transaction outcome is uncertain, the system shall not present the message or its timestamp as confirmed solely on the basis of that attempt, and shall not discard the possible original timestamp. Reconciliation must determine whether the original operation committed. If it did, the originally persisted timestamp shall be preserved; if it did not, a subsequent successful operation may establish a new timestamp. The commit timestamp represents the server's recording time for the committed message. It does not guarantee exact equality with the storage engine's physical commit-completion instant, millisecond accuracy, or any unconditional wall-clock bound on the difference. Message identity, authoritative order and commit timestamp are independent. Equal timestamps, clock adjustments or non-monotonic wall-clock readings must never alter established message order; timestamps shall not be the sole source of conversation ordering. V0 chat clients shall render the authoritative timestamp in the selected timezone, or the client's local timezone by default, continuously near the message action area and content whenever the message is displayed, without requiring hover. A precise full date/time shall remain available as secondary detail and does not replace the continuously visible time.
- **Source/rationale:** Explicit user requirement dated 2026-10-03; consistent with PD §§4.4, 5.1–5.2, 9, 14 and DM §§9–10. Commitment to persistent history establishes the timestamp's meaning; client rendering does not establish or change that instant. This defines behavior, not a timestamp encoding, physical field, or ordering mechanism. The Statement was revised on 2026-10-11 by the accepted owner contract, resolving review finding R7; it supersedes "representing when that message is committed to persistent conversation history". The original display requirements (continuous visibility near the message action area, no hover, selected/local timezone, secondary full date/time) are retained, not weakened.
- **Acceptance criteria:** Save both user and assistant messages and verify, by instrumenting the transaction, that each commit timestamp is read inside the committing transaction after it obtained write authority and before its commit attempt. Delayed-commit fixtures: a commit delayed by waiting for write authority, and an assistant message published after slow generation, carry the reading taken at that later point, not request arrival, generation start or client time. Verify that a timestamp read for an attempt known not to have committed is not retained, and that after an attempt with an uncertain outcome nothing is assumed either way and the message is not presented as confirmed: reconciliation determines whether it committed; if so the originally persisted timestamp is kept and returned unchanged, otherwise a subsequent successful operation establishes a new timestamp. No equality with, or numeric or wall-clock bound on the difference from, the storage engine's physical commit-completion instant is required or asserted. Reopen, reconnect, and restart with storage intact: the same messages retain the same instants. On Windows, macOS, and iPhone, inspect displayed messages without hover: each shows its time continuously near the message action area. Render the same saved messages in different selected/local timezones, including across a date boundary: displayed values reflect the chosen timezone while stored instants remain unchanged. Any secondary full date/time agrees with that instant and does not replace the continuously visible time. Equal timestamps or a clock adjustment that produces non-monotonic timestamps do not change established conversational order. Provisional output or an uncertain save is not presented as confirmed committed history merely because a time is displayed (REC-02/REC-03).
- **Status:** Draft — user-directed; Statement and acceptance criteria accepted by the owner 2026-10-11; REQUIRED_V0 selection is recorded in V0 Scope. Platform acceptance on Windows, macOS and iPhone is not yet recorded.

## 6. Non-functional requirements

### NFR-01 — Local operation without mandatory cloud availability

- **Statement:** Anonymous shall support the basic local conversation lifecycle without requiring cloud availability when the local server, authorized client connection, storage, and local model are available.
- **Source/rationale:** PD §§4.1, 14, 16. Disconnected-client operation is not implied.
- **Acceptance criteria:** Deny external-service access while preserving authorized local reachability. Create, continue, persist, reopen, and read a conversation. Unavailable external-only capabilities do not block that lifecycle.
- **Status:** Draft — source-derived.

### NFR-02 — Replace models/runtimes without losing continuity

- **Statement:** Anonymous shall preserve user data and conversation identity across supported model/runtime replacement without requiring redesigned client interaction semantics.
- **Source/rationale:** PD §§3, 4.3, 11; DM §§8, 31–33; INV-008.
- **Acceptance criteria:** Continue a conversation using two compatible test runtimes in sequence. History, ownership, identity, and client conversation operations remain intact; existing supported memories/artifacts remain accessible with the same content and identity. Output wording and model capabilities need not be identical.
- **Status:** Draft — source-derived.

### NFR-03 — Canonical ownership independent of a particular client

- **Statement:** Anonymous shall keep core persistent information and context responsibilities independent of any one client, so loss of client-local interaction state does not erase server-saved data.
- **Source/rationale:** PD §§4.4, 9–10; DM §§19, 50.
- **Acceptance criteria:** Save a conversation, remove a test client's local state, and recover the conversation/ownership through another authorized client. Design review locates canonical persistence/context responsibility outside client-only presentation state.
- **Status:** Draft — source-derived.

### NFR-04 — Host-independent domain semantics

- **Statement:** Anonymous shall preserve identity, ownership, trust, and conversation semantics regardless of whether a client shares the initial Windows server host.
- **Source/rationale:** PD §§4.4–4.5, 17.
- **Acceptance criteria:** Equivalent co-hosted and remote-client fixtures have the same authorization and persistence outcomes. Domain definitions grant no special authority solely for being the Windows hosting client. Immediate support for every server OS is not implied.
- **Status:** Draft — source-derived.

### NFR-05 — Essential interaction across intended clients

- **Statement:** Anonymous shall support creating, reading, and continuing conversations in the intended Windows, macOS, and iPhone client contexts without requiring full mobile administrative parity.
- **Source/rationale:** PD §§4.4, 9, 14.
- **Acceptance criteria:** Run create/read/continue/reconnect on an agreed supported configuration for each target and access the same saved conversation. Versions, accessibility targets, and release support matrix remain Q-19. Native applications are not required.
- **Status:** Draft — source-derived; acceptance environment pending Q-19.

### NFR-06 — Respect existing resource constraints

- **Statement:** Basic Anonymous functionality shall not depend on substantial new hardware purchases or mandatory recurring external-service fees beyond the user's existing environment.
- **Source/rationale:** PD §16. Optional paid external services and ordinary electricity/network costs are not prohibited.
- **Acceptance criteria:** Review prerequisites and execute the basic local lifecycle against an agreed existing-hardware inventory. No substantial new purchase or paid recurring external service is required. Inventory and the meaning of substantial remain Q-23; performance is not specified.
- **Status:** Draft — source-derived; acceptance bounds pending Q-23.

### NFR-07 — Replaceable dependencies and bounded responsibilities

- **Statement:** Anonymous shall preserve domain meanings independently of storage, model, networking, and presentation choices, with identifiable responsibilities maintainable as a modular application without requiring premature distributed services.
- **Source/rationale:** PD §§12, 16–17; DM §§1, 47. This carries forward a source constraint, not a deployment design.
- **Acceptance criteria:** Design review maps responsibilities/dependencies and walks through replacement of each technology class. Identity/history/privacy meanings remain unchanged; integration changes are identifiable. No domain requirement demands microservices merely because aggregates differ.
- **Status:** Draft — source-derived.

## 7. Security requirements

### SEC-01 — Authenticate independently of network presence

- **Statement:** Anonymous shall require authenticated access to protected information/capabilities independently of mere network access.
- **Source/rationale:** PD §§8, 8.3; DM §6. Mechanism remains open.
- **Acceptance criteria:** A reachable caller without valid authentication cannot read a saved conversation or invoke a protected capability. A valid context proceeds to authorization checks; network membership alone does not authenticate it.
- **Status:** Draft — source-derived.

### SEC-02 — Authorize protected operations

- **Statement:** Anonymous shall authorize protected data/capability access separately from establishing an authenticated interaction.
- **Source/rationale:** PD §§8, 10; DM §4.
- **Acceptance criteria:** An authenticated fixture caller lacking the applicable permission is denied a protected read/mutation; an authorized caller succeeds. Denial leaves sources unchanged. Role/permission mechanics remain open.
- **Status:** Draft — source-derived.

### SEC-03 — Device trust independent of ordinary IP addresses

- **Statement:** Anonymous shall preserve device identity and established trust across ordinary IP changes without granting trust to another device using an old address.
- **Source/rationale:** PD §8.1; DM §§5, 46 INV-010.
- **Acceptance criteria:** Change an approved device's address while retaining valid identity/credentials: identity/trust is unchanged. A different unauthenticated device at the old address inherits no trust. Authentication expiry may still require reauthentication.
- **Status:** Draft — source-derived.

### SEC-04 — Address reuse does not revive revoked trust

- **Statement:** Anonymous shall prevent a revoked device from regaining device-trusted access merely through reuse of a previous or newly assigned address.
- **Source/rationale:** DM §5; PD §8.1. Active-session effects remain Q-21.
- **Acceptance criteria:** Given a revoked-device fixture, attempt new device-trusted access at old and new addresses without trust restoration. Both fail and revocation remains in effect.
- **Status:** Draft — source-derived.

### SEC-05 — Separate devices and authenticated sessions

- **Statement:** Anonymous shall distinguish a recognized device from its associated authenticated sessions.
- **Source/rationale:** DM §§5–6.
- **Acceptance criteria:** Represent two test sessions for one device; distinguish their authenticated contexts and association without duplicating device identity. Session termination/revocation propagation remains Q-21.
- **Status:** Draft — source-derived.

### SEC-06 — Protected communication without required public exposure

- **Statement:** Anonymous shall support authorized client/server communication protected against untrusted network peers without requiring direct public exposure of server, model, storage, or administration interfaces.
- **Source/rationale:** PD §§8–8.3 calls for encrypted private communication; no network product is selected.
- **Acceptance criteria:** Perform the basic lifecycle without direct public ingress to those services. An untrusted network observer cannot read application payloads or successfully alter accepted requests in transit; an unknown LAN peer gains no protected access from proximity alone.
- **Status:** Draft — source-derived.

### SEC-07 — Tool requests confer no implicit authority

- **Statement:** When tools are supported, Anonymous shall enforce applicable access/privacy rules independently of a model's request to invoke them.
- **Source/rationale:** DM §§34–35, 46 INV-012; PD §§7–8.
- **Acceptance criteria:** A model fixture requests an unauthorized tool effect or prohibited transfer. It is denied before that effect/transfer occurs. A permitted fixture succeeds without broadening later authority.
- **Status:** Draft — source-derived.

### SEC-08 — Protect secrets in diagnostics and context

- **Statement:** Anonymous shall prevent credentials/authentication secrets from appearing in ordinary diagnostics or unrelated model/tool context; any necessary credential use shall remain confined to its authorized protected operation.
- **Source/rationale:** PD §§7–8, 19; DM §39; AGENTS.md secret-handling rule. This concretizes the source privacy/security intent without choosing storage mechanics.
- **Acceptance criteria:** Exercise success/failure paths using synthetic secrets. Ordinary diagnostics and unrelated requests contain no secret markers. A credential used in its intended authentication operation does not appear in error output or unrelated model/tool requests.
- **Status:** Draft — derived safeguard.

## 8. Privacy requirements

### PRIV-01 — No implicit PRIVATE-to-external transfer

- **Statement:** Anonymous shall prevent PRIVATE information from entering WEB, cloud-model, external-API, or other external-service requests without explicit permission covering that transfer; general external access alone is insufficient.
- **Source/rationale:** PD §§4.2, 7; DM §§38–39.
- **Acceptance criteria:** Seed private fixture messages, memories, and an artifact. Permit web access without private release; outbound requests contain neither the seeded private facts nor their derived private content. Repeat with cloud-model and external-tool destinations.
- **Status:** Draft — source-derived.

### PRIV-02 — Bound explicit releases

- **Statement:** When private-data release is supported, Anonymous shall limit transfers to the information and external use covered by explicit user permission, without extending it to unrelated data or destinations.
- **Source/rationale:** PD §7; DM §39. Permission lifecycle remains Q-17.
- **Acceptance criteria:** Authorize item A to destination X for one specified operation. That operation can transfer A; item B, destination Y, and unrelated later operations remain unauthorized without further applicable permission.
- **Status:** Draft — source-derived.

### PRIV-03 — Derivation does not authorize disclosure

- **Statement:** Anonymous shall apply applicable privacy restrictions to derived state, memory, summaries, retrieval results, and artifacts so transforming or combining PRIVATE sources does not itself authorize disclosure.
- **Source/rationale:** PD §§5.5, 6.3, 7; DM §§19, 38–39, 44. Exact propagation taxonomy remains Q-10.
- **Acceptance criteria:** Derive a paraphrase and combined summary containing a private fixture fact. Neither exports that fact without applicable release. Repeat with retrieved memory/artifact content; matching only the original source wording is insufficient.
- **Status:** Draft — derived safeguard.

### PRIV-04 — Unestablished permission cannot authorize export

- **Statement:** Anonymous shall not export information across a private/external boundary when applicable transfer permission cannot be established.
- **Source/rationale:** PD §§4.2, 7; DM §39. This does not select a default internal classification taxonomy.
- **Acceptance criteria:** Attempt transfers with missing classification, missing permission, and unavailable policy information, where permission cannot be established. No transfer occurs; the limitation follows REC-04. Internal classification/default handling remains Q-10/Q-17.
- **Status:** Draft — derived safeguard.

### PRIV-05 — Privacy independent of model compliance

- **Statement:** Anonymous shall enforce the private/external boundary independently of whether a model obeys privacy instructions.
- **Source/rationale:** DM §46 INV-012; PD §7.
- **Acceptance criteria:** An adversarial fixture model/tool request asks to export prohibited private information and ignores privacy prompts. Observe no transfer. Natural-language instructions to the model alone are not evidence of enforcement.
- **Status:** Draft — source-derived.

### PRIV-06 — Account for permitted boundary crossings

- **Statement:** For supported explicit releases, Anonymous shall make the transferred information's reference, destination/use, and authorizing permission attributable to the operation without requiring raw private payloads in ordinary diagnostics.
- **Source/rationale:** DM §39 says scoped permission should be auditable where practical; PD §§7, 19. This proposes minimum accountability for controlled releases, not unlimited audit retention.
- **Acceptance criteria:** Execute PRIV-02's permitted fixture. Sanitized evidence identifies the operation, permitted information, destination/use, and permission without requiring raw content. Record persistence/duration remain Q-12/Q-13/Q-17/Q-24.
- **Status:** Draft — derived safeguard.

## 9. Data integrity and provenance requirements

### DATA-01 — Stable first-class identities

- **Statement:** Persistent first-class objects shall have stable identities independent of display names; conversation identity shall also remain independent of model/runtime, current summary, and accessing client.
- **Source/rationale:** DM §§3, 8; INV-001, INV-002, INV-008, INV-009; PD §5.1.
- **Acceptance criteria:** Rename representative supported objects where offered; identities and references remain intact. Change a conversation's model/runtime, summary, and client; its identity remains the same.
- **Status:** Draft — source-derived.

### DATA-02 — Preserve authoritative conversation history

- **Statement:** Anonymous shall preserve recoverable source content across branching, merging, summarization, memory extraction, and any offered editing, without silently overwriting previous authoritative content.
- **Source/rationale:** PD §§5.2–5.4; DM §§9, 11, 13, 44; INV-003, INV-004, INV-006.
- **Acceptance criteria:** Recover source content unchanged after each supported operation. Offered edits retain access to prior content and its relationship to the changed version. This is not a prohibition on future explicitly defined hard deletion (Q-15).
- **Status:** Draft — source-derived.

### DATA-03 — Distinguish sources, derived state, and context

- **Statement:** Anonymous shall distinguish authoritative/source records from derived representations and invocation context; replacing derived state shall neither replace sources nor automatically promote generated claims to authoritative user knowledge.
- **Source/rationale:** PD §§6.3, 18; DM §§17–19, 44; INV-006, INV-015.
- **Acceptance criteria:** Correctly classify fixture user messages, summaries, inferred memories, canonical state, and context. Replace derived state/discard context: sources remain recoverable and no generated assertion becomes an explicit user statement.
- **Status:** Draft — source-derived.

### DATA-04 — Preserve available provenance

- **Statement:** Anonymous shall retain available source references for derived knowledge used as current memory/canonical state and for merge ancestry, distinguishing absent evidence from established provenance rather than inventing sources.
- **Source/rationale:** PD §§5.5, 6.1; DM §§15–17, 23, 28. Known-source cases are the testable minimum; broader practical coverage remains Q-24.
- **Acceptance criteria:** Derive a fixture memory/state element from identifiable messages/artifacts and trace it to contributing records. Missing evidence is reported as a limitation, not fabricated provenance. Merge ancestry still satisfies FR-05/DATA-06.
- **Status:** Draft — source-derived.

### DATA-05 — Separate epistemic status from confidence

- **Statement:** Anonymous shall distinguish explicit user information, AI inference, superseded claims, and known unresolved conflicts; confidence shall not replace provenance or override explicit correction.
- **Source/rationale:** PD §§5.5, 6.2, 20; DM §§24–27; INV-007, INV-013.
- **Acceptance criteria:** Distinguish explicit/inferred fixture claims without requiring a numerical confidence for the explicit claim. Mark a known conflict: retrieval does not present it as one settled fact. A correction supersedes inference under FR-07. Automatic detection/resolution remains open.
- **Status:** Draft — source-derived.

### DATA-06 — Reference historical source boundaries

- **Statement:** A merge shall identify the historical source state used for each contribution, and later source evolution shall not silently rewrite that merge's historical derivation.
- **Source/rationale:** DM §§15–16, 43; INV-014; PD §5.4.
- **Acceptance criteria:** Merge A and B at known boundaries, then append to both. Original contributing boundaries remain identifiable and the existing merge does not silently include later content. No snapshot/frontier/event representation is prescribed.
- **Status:** Draft — source-derived.

### DATA-07 — Acyclic derivation ancestry

- **Statement:** Anonymous shall prevent a derived object from becoming its own ancestor through direct or indirect derivation relationships.
- **Source/rationale:** DM §§41–42; INV-011. No graph-database requirement is implied.
- **Acceptance criteria:** Direct self-derivation and multi-step cycle fixtures cannot become valid saved relationships; existing ancestry survives. Acyclic branching/merging with multiple ancestors remains representable.
- **Status:** Draft — source-derived.

### DATA-08 — Attribute assistant output to execution

- **Statement:** Anonymous shall make saved assistant output traceable to its producing model execution, distinguishing the model from its runtime.
- **Source/rationale:** DM §§31–33; PD §§11, 19.
- **Acceptance criteria:** Save outputs from two runs and identify the producing run/model/runtime for each without conflating those identities. Check linkage while records are retained; expiry behavior remains Q-13/Q-15.
- **Status:** Draft — source-derived.

### DATA-09 — Artifact identity independent of storage location

- **Statement:** When artifacts are supported, Anonymous shall distinguish logical identity from content storage references so relocation need not redefine the artifact.
- **Source/rationale:** DM §§29–30; PD §§4.3, 17.
- **Acceptance criteria:** Relocate fixture content through a supported maintenance operation or equivalent design fixture. Identity, ownership, provenance, and message references remain unchanged; content access resolves to the new location. No storage layout is prescribed.
- **Status:** Draft — source-derived.

### DATA-10 — Distinguish lifecycle actions by effect

- **Statement:** When lifecycle actions are offered, Anonymous shall distinguish hiding, archiving, superseding, recoverable deletion, and physical removal by their actual effects rather than treating them as interchangeable.
- **Source/rationale:** DM §§26, 45; PD §§5.2, 20. Not all actions are required.
- **Acceptance criteria:** For each offered action, observed visibility/recoverability matches its stated effect. Hiding/archiving does not silently physically remove content; supersession retains its historical relationship. Detailed erasure/retention semantics remain Q-15.
- **Status:** Draft — source-derived.

## 10. Recovery/failure requirements

### REC-01 — Retain saved state across normal restart

- **Statement:** Anonymous shall retain source conversation records reported saved, their identities, and established ancestry across normal server stop/restart with storage intact.
- **Source/rationale:** PD §§5.1–5.2, 14; DM §§8–9, 43–44. Persistence does not imply an invented crash-loss tolerance.
- **Acceptance criteria:** Save a conversation and supported branch/merge relationships, stop normally, restart, and reconnect. Saved content/identities/ancestry match pre-stop state. Abrupt power loss, corruption, and backups remain Q-18.
- **Status:** Draft — source-derived.

### REC-02 — Distinguish persistence failure from confirmed saving

- **Statement:** Anonymous shall expose known persistence failure or uncertain saving without reporting the operation as confirmed saved or altering prior saved source history as a side effect.
- **Source/rationale:** PD §§5.2, 19; DM §§9, 44. This concretizes observable failure.
- **Acceptance criteria:** Inject a storage failure and separately lose write confirmation. Neither is falsely presented as saved; failure/uncertainty is distinguishable from success and earlier records remain unchanged. Acknowledgment, retry, and deduplication policies remain Q-16.
- **Status:** Draft — derived safeguard.

### REC-03 — Expose inference failure and preserve history

- **Statement:** Anonymous shall distinguish model/runtime failure from a completed response and preserve previously saved conversation data when inference fails.
- **Source/rationale:** PD §§5.2, 19; DM §33.
- **Acceptance criteria:** Make the runtime unavailable or interrupt generation. Failure/incompletion is distinguishable from completion; saved messages remain readable after recovery. Partial-output persistence/presentation remains Q-16.
- **Status:** Draft — source-derived.

### REC-04 — Expose context, retrieval, tool, and policy failures

- **Statement:** Anonymous shall expose failures in context construction, retrieval, tools, or privacy enforcement that prevent requested guarantees, without treating missing evidence as success or bypassing privacy constraints.
- **Source/rationale:** PD §§7, 19; DM §§19, 35, 39.
- **Acceptance criteria:** Inject each supported failure. Identify the operation as failed/limited with sanitized information locating the failing responsibility; do not present it as fully successful. Privacy-check failure transfers nothing under PRIV-04. No particular fallback is selected.
- **Status:** Draft — derived safeguard.

### REC-05 — Recover derived data without sacrificing sources

- **Statement:** Derived-data loss shall not itself cause authoritative-history loss; for representations designated rebuildable, Anonymous shall support regeneration from retained available sources or expose why regeneration cannot complete.
- **Source/rationale:** PD §18; DM §§17, 44. Coverage and automatic triggers remain Q-14/Q-24.
- **Acceptance criteria:** Remove a derived fixture, verify source recovery, and regenerate a supported rebuildable representation with provenance. For a supported search index, the known source detail is again retrievable; for supported summary/state rebuilding, the fixture's required source facts and their references are present. Repeat with a missing dependency: failure is visible and sources survive. Byte-identical AI output is not required; broader quality targets remain Q-19.
- **Status:** Draft — source-derived.

### REC-06 — Preserve sources during incomplete derivation

- **Statement:** Failed/interrupted branch or merge creation shall preserve sources and shall not present an incomplete destination or ancestry as a successfully completed derivation.
- **Source/rationale:** PD §§5.3–5.4, 19; DM §§11, 13, 15–16. No transaction/cleanup mechanism is prescribed.
- **Acceptance criteria:** Inject failures during branch/merge creation. Sources remain recoverable unchanged; attempted results are absent or clearly failed/incomplete, never complete with missing required ancestry. Retry behavior remains Q-16.
- **Status:** Draft — derived safeguard.

## 11. Requirement traceability

Each record's source field is the requirement-to-source map. SC-01–SC-12 provide scenario-to-requirement coverage. The following tables give reverse source/invariant coverage. Numerical ranges are inclusive.

| Source concern | Requirement coverage |
| --- | --- |
| PD §§1–4: continuity, local-first, independence | FR-01–FR-03, FR-14, NFR-01–NFR-04, PRIV-01 |
| PD §5; DM §§8–16: conversations/branching/merging | FR-01–FR-05, DATA-01, DATA-02, DATA-04, DATA-06, DATA-07, REC-01, REC-06 |
| PD §6; DM §§17–27: memory/correction/context | FR-06–FR-10, DATA-03–DATA-05, REC-04, REC-05 |
| PD §7; DM §§38–39: private/external boundaries | PRIV-01–PRIV-06, SEC-07, SEC-08, REC-04 |
| PD §8; DM §§4–6, 34–35: layered trust | SEC-01–SEC-08, FR-13, FR-14 |
| PD §§9–11, 14; DM §§28–35: clients/execution/artifacts | FR-02, FR-03, FR-11–FR-13, NFR-02–NFR-05, DATA-08, DATA-09 |
| PD §§12–13, 16–17; DM §§1, 47: replaceability/constraints | NFR-06, NFR-07; named technology examples impose no selection |
| PD §15; DM §§7, 36–37: future capabilities | Q-09, Q-20, Q-22; no automatic V0 commitment |
| PD §§18–20; DM §§40–45: recovery/correction/lifecycle | FR-07, DATA-02, DATA-03, DATA-05–DATA-10, REC-01–REC-06; Q-11–Q-16, Q-18 |
| PD §21; DM §§49–50: durable structured environment | FR-01–FR-14, NFR-01–NFR-07, DATA-03; overall outcome, not an extra requirement |
| User requirement, 2026-10-03: persistent, always-visible message timestamps | FR-15; V0-AC-01–V0-AC-03 in V0 Scope |

| DM §46 invariant | Requirement coverage |
| --- | --- |
| INV-001 — Stable identity | DATA-01 |
| INV-002 — Rename preserves identity | DATA-01 |
| INV-003 — Non-destructive branch | FR-04, DATA-02, REC-06 |
| INV-004 — Non-destructive merge | FR-05, DATA-02, REC-06 |
| INV-005 — Merge ancestry | FR-05, DATA-04, DATA-06 |
| INV-006 — Derived data does not replace sources | FR-10, DATA-02, DATA-03, REC-05 |
| INV-007 — Explicit versus inferred | DATA-05 |
| INV-008 — Runtime-independent conversation | NFR-02, DATA-01 |
| INV-009 — Client-independent user/conversation | FR-03, FR-14, DATA-01 |
| INV-010 — IP-independent device identity | SEC-03, SEC-04 |
| INV-011 — Acyclic ancestry | DATA-07 |
| INV-012 — Model-independent privacy | PRIV-05, SEC-07 |
| INV-013 — User correction supersedes inference | FR-07, DATA-05 |
| INV-014 — Stable historical merge | DATA-06 |
| INV-015 — Context is a constructed view | FR-08, DATA-03 |

Coverage does not make illustrative attributes/taxonomies mandatory. Workspaces, agent behavior, event sourcing, all artifact formats, and multi-user management are not requirements merely because they appear in DM.

## 12. Open requirement questions

Each question has one primary timing category. **Blocks requirements** means dependent detailed behavior cannot yet be completely specified/tested, not that this invariant baseline is unusable. **Blocks V0 scope** means release inclusion or acceptance boundaries need a product decision. **Blocks architecture/design** means minimum behavior is clear but its representation/mechanism is open before dependent design. **Deferred** means a future feature can make the question relevant; no current decision is needed.

| ID | Question/source | Classification | Why / affected coverage |
| --- | --- | --- | --- |
| Q-01 | Persistent Branch or derived relationship? DM §48.1, §12. | Blocks architecture/design | FR-04 requires divergence, not independent Branch identity. Naming/management flows may add requirements later. |
| Q-02 | What constitutes a state version? DM §48.2, §§16, 43. | Blocks architecture/design | DATA-06 fixes historical meaning; representation is open. |
| Q-03 | Immutable messages, revisions, or edit events? DM §48.3, §9. | Blocks architecture/design | DATA-02 fixes preservation, not representation. Whether editing is offered is Q-20. |
| Q-04 | What does merge synthesize, including conflicts and selected contributions? DM §48.4, §§14–15. | Blocks requirements | FR-05's integrity checks cannot assess intended synthesis content without its product contract. |
| Q-05 | Does a merge expose source messages or only derived context? DM §48.5. | Blocks requirements | Determines navigation/access beyond FR-05/DATA-06 ancestry retention. |
| Q-06 | Final memory classes and scope behavior? DM §48.6, §§21–24. | Blocks requirements | FR-06/DATA-05 give minimum distinctions, not class-specific lifecycle or a final taxonomy. |
| Q-07 | Confidence representation? DM §48.7, §25. | Blocks architecture/design | DATA-05 forbids substituting confidence for evidence; no scale/enum is needed for that invariant. |
| Q-08 | How are conflicting memories detected/resolved? DM §48.8, §27. | Blocks requirements | Known conflicts stay explicit; automatic detection, precedence, and resolution flows lack an oracle. |
| Q-09 | Distinct Workspace and Project? DM §48.9, §7. | Deferred | Revisit before organizational-feature requirements; FR-06 requires neither entity. |
| Q-10 | Privacy granularity/defaults and propagation through mixed/derived data? DM §48.10, §§38–39. | Blocks requirements | PRIV-01/PRIV-03 prevent implicit release; finer sharing policies remain open. |
| Q-11 | Partial, full, or no event sourcing? DM §48.11, §40. | Blocks architecture/design | Nothing in this baseline selects an event persistence foundation. |
| Q-12 | Which generated context is retained for reproducibility, with what redaction/duration? DM §48.12, §18. | Blocks requirements | Determines post-execution evidence/privacy costs; FR-08 does not require full prompt retention. |
| Q-13 | Model/tool execution detail and retention duration? DM §48.13, §§33, 35. | Blocks requirements | FR-12/FR-13/DATA-08 establish attribution, not expiry/fields or behavior after purging. |
| Q-14 | When does derived data regenerate automatically, and which forms are rebuildable? DM §48.14; PD §18. | Blocks requirements | REC-05 fixes preservation/supported rebuilding, not triggers, freshness, or coverage. |
| Q-15 | Exact deletion semantics across sources, derived copies, provenance, and backups? DM §48.15, §45. | Blocks requirements | DATA-02 concerns ordinary non-destructive operations; DATA-10 does not settle erasure/retention. |
| Q-16 | Confirmed-save boundary, partial responses, uncertain writes, retries, and concurrent changes? PD §§14, 19; DM §§9, 43. | Blocks requirements | REC-02/REC-03/REC-06 prohibit false success without selecting acknowledgment/deduplication/concurrency behavior. |
| Q-17 | Release permission scope, expiry/revocation, evidence, and incomplete-policy handling? PD §7; DM §39. | Blocks requirements | PRIV-02/PRIV-04/PRIV-06 establish minimum boundaries, not a complete consent lifecycle. |
| Q-18 | Abrupt power loss, corruption, storage loss, and backup recovery guarantees? PD §§5.2, 18–19; DM §44. | Blocks requirements | REC-01 covers normal restart only; loss tolerance/restore coverage/time are unspecified. |
| Q-19 | Supported client versions, accessibility, latency/capacity, and retrieval/synthesis quality targets? PD §§9, 14, 16, 21. | Blocks V0 scope | NFR-05 needs a test matrix; quantitative release acceptance needs a workload and selected capabilities. |
| Q-20 | Which capabilities are V0, and is disconnected-client operation needed? PD §§4.1, 14–15; DM §7. | Blocks V0 scope | Local-first does not imply offline editing/sync; no scenario automatically selects release scope. |
| Q-21 | Session expiry and device/session revocation propagation, including active sessions? DM §§5–6; PD §8. | Blocks requirements | SEC-04 stops address-based trust revival; DM says device revocation “may” invalidate sessions, not that it always does. |
| Q-22 | When are multi-user roles, autonomous agents, native clients, and other deferred capabilities needed? PD §15; DM §§4, 36–37. | Deferred | Current identity/tool distinctions preserve compatibility without defining those products. |
| Q-23 | Existing hardware inventory and acceptable purchase/cost envelope? PD §16. | Blocks V0 scope | NFR-06 is a constraint, but “substantial” and its reference environment are unspecified. |
| Q-24 | What provenance/audit/rebuilding cases count as “important” or “practical,” and which evidence gaps are acceptable? PD §§5.5, 6.1, 18; DM §§17, 23, 39. | Blocks requirements | DATA-04/PRIV-06/REC-05 give bounded guarantees, not universal capture/retention or identical regeneration. |

Q-01–Q-15 correspond one-to-one to DM §48. Q-16–Q-24 expose additional omissions/acceptance dependencies; they do not answer them.

Apparent source tensions and limits:

- PD §5.4 permits a new merged “conversation/state”; DM §13 gives the merged conversation its own identity. FR-05 follows that concrete scenario; broader state-only merge products remain Q-04, without fixing state-version representation.
- PD §6.3 calls compact derived information “canonical state,” while other passages discuss canonical persistent ownership. DATA-03 follows DM §§17, 44: compression does not turn a derived object into source history.
- Preservation (PD §5.2) and possible true deletion (DM §45) concern different operations. Neither establishes eternal retention; deletion propagation and provenance after erasure remain Q-15.
- DM §41 describes the DAG provisionally, while INV-011 prohibits cycles. DATA-07 preserves that current invariant without selecting storage technology.
- PD §8 suggests layered trust; DM §6 leaves revocation propagation open. SEC-04 does not silently promise immediate invalidation of every active session (Q-21).
- Practical-provenance/rebuilding qualifiers and optional auditability do not establish universal retention guarantees (Q-24).
- PD §13 calls technology directions provisional despite also calling them technical decisions. This baseline makes none mandatory.

No irreconcilable conflict prevents stating these minimum guarantees. The questions prevent treating this as a complete release specification.

## 13. Decision-timing matrix

This sequences decisions without selecting V0 or an architecture. Timing names the earliest dependent gate, not an instruction to resolve every question now.

| Classification | Questions | Decision gate | Evidence needed |
| --- | --- | --- | --- |
| Blocks requirements (14) | Q-04, Q-05, Q-06, Q-08, Q-10, Q-12, Q-13, Q-14, Q-15, Q-16, Q-17, Q-18, Q-21, Q-24 | Before completing the affected capability/policy's detailed acceptance criteria. Existing invariant requirements can stand. | Concrete flows, negative/conflicting examples, retention/privacy expectations, failure outcomes, explicit product choices. |
| Blocks V0 scope (3) | Q-19, Q-20, Q-23 | Next project step, before calling its scope/acceptance envelope complete. | Prioritized flows, client/workload matrix, hardware/cost inventory. |
| Blocks architecture/design (5) | Q-01, Q-02, Q-03, Q-07, Q-11 | Before committing to the dependent representation/mechanism when that capability is designed. | Accepted behaviors and alternatives; ADR for significant architectural choices. |
| Deferred (2) | Q-09, Q-22 | When the related future features are proposed. | Demonstrated user need; then new requirements/design decisions as applicable. |

Authentication mechanisms, storage products, networking products, runtime selection, and concrete API design remain future design work. None requires a named technology in this baseline.

## 14. Baseline completion criteria

Completion means a reviewable artifact, not implemented functionality, resolution of all questions, or user approval.

- [x] Fourteen requested sections, identified authoritative sources, and retained provisional status.
- [x] Every normative record has a stable unique ID, title, statement, source, acceptance criteria, and status.
- [x] Ten requested scenarios plus model replacement and artifacts are covered.
- [x] All fifteen invariants map to requirements; all fifteen DM §48 questions remain classified and open.
- [x] No fabricated implementation choices, enums, quality thresholds, or V0 selection.
- [x] Four concern-based reviews completed and findings recorded.
- [x] Structural/reference checks and changed-file scope verification completed.

### Review record

The following are separate concern-based reviews by the author on 2026-10-03, not claims of independent specialist-agent approval.

| Pass | Findings and disposition |
| --- | --- |
| Architect | Reviewed every source mapping and current invariant. Kept behavior independent of Branch/state/message representations and technology candidates; kept conditional capabilities separate from V0 selection. Expanded the runtime-replacement check to cover supported memories/artifacts as well as conversations. No architectural decision or ADR was needed. |
| Security | Reviewed positive/negative authorization, IP changes, revoked trust, untrusted LANs, model-requested tools, and privacy through derived information. Kept permission-failure denial and sanitized release evidence visible as derived safeguards. Recorded active-session revocation, consent lifecycle, and audit retention as unresolved instead of inferring policies. |
| Data & Memory | Checked source preservation, scoped correction, historical merge boundaries, acyclic ancestry, provenance gaps, and incomplete derivations. Kept deletion distinct from ordinary source preservation. Bounded rebuilding/provenance claims with Q-14/Q-24; regeneration does not promise identical model output or universal practical coverage. |
| QA | Checked requirement records for observable pass/fail outcomes and scenario coverage. Tightened FR-08 from checking whatever was selected to a fixture requiring two known contributions within the invocation limit. Replaced REC-05's vague “usable” result with index lookup and required summary/state facts. Flagged NFR-05/NFR-06 acceptance dependencies and left absent quality/policy targets explicit. |

No unresolved contradiction with an established invariant was identified. Remaining limitations are product questions and acceptance dependencies, not completed runtime verification.

Original baseline-task documentation validation confirmed 51 unique requirement records with all required fields, 14 sections, 12 scenario records, 15 invariant mappings, all 24 question classifications, valid requirement/question references and source-section references, and five resolving local Markdown links. A pre/post file-hash comparison confirmed that only this document and the task ExecPlan changed; both authoritative sources and all downstream placeholders stayed unchanged. No runtime tests were possible or attempted.

### Testability limits

All 52 records contain observable minimum semantic or design-review criteria. **NFR-05 and NFR-06 are not fully executable acceptance contracts yet**: the supported client environment and resource bounds await Q-19/Q-23. Conditional checks become executable when the capability and supported fixture exist. No application checks have run.

Open questions contain no normative obligations pretending to be fully specified. Complete acceptance coverage remains open for synthesis quality, conflict resolution, detailed privacy/consent policy, deletion/retention, partial/concurrent writes, abrupt-loss recovery, regeneration timing, and quantitative performance/quality. Minimum invariant tests do not substitute for those missing policies.

### Requirement inventory

| Category | Count |
| --- | ---: |
| Functional (FR) | 15 |
| Non-functional (NFR) | 7 |
| Security (SEC) | 8 |
| Privacy (PRIV) | 6 |
| Data integrity and provenance (DATA) | 10 |
| Recovery/failure (REC) | 6 |
| **Total** | **52** |

No application implementation, dependencies, schemas, API routes, V0 scope, architecture document, or technology selection is produced. Completion does not start the next task.
