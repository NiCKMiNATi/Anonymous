# Anonymous — V0 Logical Data Model & Persistence Semantics v0.1

**Status:** Logical baseline v0.1; semantic decisions below are accepted for this baseline. Physical persistence design, security/API mechanisms, implementation, runtime evidence, and release acceptance remain pending.  
**Date:** 2026-10-03.  
**Ownership:** Data & Memory, coordinated against Architect boundaries; focused author reviews recorded in section 17.

## 1. Purpose, authority, and scope

This document defines what persistent V0 information means, the relationships Anonymous must preserve, and the coherent outcomes applications and clients may observe. It does not prescribe how a storage engine represents or coordinates those facts.

Authority: [Project Definition](00-project-definition.md) (PD), [Domain Model](01-domain-model.md) (DM), [Requirements Baseline](02-requirements.md) (RB), [V0 Scope](03-v0-scope.md) (V0), and [Architecture Baseline](04-architecture.md) (AB). The [ExecPlan](../.agent/plans/2026-10-03-v0-logical-data-model.md) records this work. Draft/provisional source meanings remain meaningful. V0 selects subsets; this document does not implement deferred features or change their requirements.

The accepted ADRs remain binding: [shared server ownership](adr/0001-shared-server-and-canonical-ownership.md), [one modular application](adr/0002-modular-monolith-server.md), [owned context/runtime boundary](adr/0003-context-and-model-execution-boundary.md), [owned persistence contracts](adr/0004-persistence-port-boundary.md), and [layered private access](adr/0005-layered-private-access.md). [ADR-0006](adr/0006-preserved-message-facts-and-historical-boundaries.md) records the logical preservation and historical-boundary decision made here.

One authoritative server owns history, access state, and execution/reconciliation evidence. Windows, macOS, and iPhone clients hold authorized views; Windows co-hosting confers no privilege. Logical consistency applies across C03 access, C04 conversation, C05 execution, C06 context, C07 runtime evidence, C08 persistence, C09 domain rules, and C10 lifecycle. It does not introduce another service or reverse AB's dependency directions.

No tables, collections, document layouts, datatypes, key encodings, indexes, database family/product, ordering algorithm, transaction syntax, framework, API route, authentication protocol, or transport mechanism is selected. Names such as “Submission” and “State Boundary” identify concepts; they do not require separately stored first-class entities. Explicit identities are required only where their meaning must remain distinguishable.

**Interpretation of uncertainty:** The requested retry coverage includes uncertain outcomes, but V0-D04 forbids launching a new generation while uncertainty remains. Reconciliation resolves the earlier operation; only then can an explicit eligible retry create a new attempt. No conflict requires changing a source baseline. Runtime completion, durable response publication, and what a client knows about either are distinct.

## 2. Data classifications and preservation

These categories distinguish authority and recovery obligations, not fixed storage containers. “Authoritative” here means trustworthy evidence of what Anonymous accepted or recorded, not a claim that every user statement or model answer is factually true. System-managed access and execution facts are authoritative within their responsibilities without becoming user-authored knowledge.

| Category | Examples and authority | Preservation / regeneration | Loss and recovery implications |
| --- | --- | --- | --- |
| Authoritative source data | Committed user messages; explicit user corrections expressed in chat; user ownership; explicit device-approval/revocation decisions. Future uploaded originals and manual knowledge entries. | Retain accepted source content and stable identity. A model cannot regenerate the original user's statement. V0 has no destructive edit, deletion or pruning operation. | Loss of a source message alters authoritative user history. Loss of access facts makes authority unknown, not permissive. Recovery needs retained evidence, not guessed facts. |
| Generated persistent conversation history | Committed assistant response, authored as generated content, associated with its producing attempt. | Preserve the exact committed response as historical output. It is not disposable derived state. A later generation is a different execution, not restoration of these historical bytes. | Losing it changes the recorded conversation even though it is not explicit user knowledge. Re-running inference cannot claim to recover it identically. |
| Execution/audit/provenance data | Submission associations; admitted work; attempt/model/runtime identities; actual source contributions; historical boundaries; outcomes; reconciliation dispositions. Access/session state is operational authority with its own lifecycle. | Preserve minimum V0 run/source/correlation evidence with the dataset. Known facts must not be overwritten by an invented outcome. Current operational views can change coherently as facts become known. No complete event log is required. | Losing these facts may leave message content readable but destroys attribution or safe recovery/deduplication. Do not claim complete recovery or release unresolved admission merely because text survives. Diagnostic logs are not the canonical substitute. |
| Derived/rebuildable data | Future summaries, canonical/compressed state, embeddings, search indexes, inferred Memory; disposable read caches where offered. | May be rebuilt only where a supported derivation and eligible retained sources exist. Preserve provenance and distinguish replacements. Derived knowledge cannot override explicit correction. | Their loss need not alter source or generated historical messages. Functionality may degrade until recovery. Rebuilding AI output need not be byte-identical; capability/quality must be assessed separately. |
| Ephemeral/transient data | Unsaved client drafts; constructed model context; partial generated output; transport buffers; client formatting/cache state. | May be discarded within the supported flow. V0 does not require saving partial responses or full prompt copies. Persisted contributing-message evidence is a separate obligation. | Loss may interrupt work but cannot erase committed history. Reconstruct eligible context for a later explicit attempt; do not reconstruct a past saved assistant message by generation. Unsaved drafts may be lost. |

All V0 payloads, generated output, context and provenance remain PRIVATE. A category change or derivation grants no export permission. References can themselves disclose private activity; access checks apply to them too. Ordinary diagnostics retain sanitized operational evidence and exclude credentials/raw private payloads.

Diagram 1 — classification and preservation (arrows show construction, not promotion of authority):

```text
Authoritative source ----+----> ephemeral constructed context
                        |                    |
Generated saved history +                    v
                        |             model execution
                        |                    |
                        |          provisional assistant output
                        |                    |
                        |         coherent durable publication
                        |                    v
                        |          generated saved history
                        |
                        +----> future derived/rebuildable views

Execution/provenance facts record source contributions and production.
Losing a transient/derived view does not authorize replacing its sources.
```

## 3. Logical concepts, identity, and relationships

The following are required information meanings, not a fixed field list. “Retain” permits a reliable relationship/reference; it does not require copying data. Names, addresses, runtime handles and formatted times are not persistent identity authorities.

| Concept | Logical identity and required meaning | Relationship / scope |
| --- | --- | --- |
| User | Stable human owner identity even with one primary user. | Owns conversations and authorized access relationships. Changing client or host preserves ownership. No multi-user management feature. |
| Device | Stable recognized client identity plus authoritative approval/revocation condition and owner-authorized changes. | Distinct from network address, user and session. V0 associates access with the primary user; address reuse cannot revive trust. |
| Session | Distinguishable authenticated interaction, associated user/device, and enough authority/lifecycle facts to enforce finite validity, logout and device-wide revocation. | Multiple sessions may belong to a device. After restart, invalidated/expired sessions cannot become valid through loss of transient state. This does not select credentials or require indefinite retention of expired-session records. |
| Conversation | Stable owned logical context whose retained history evolves. | Has committed messages and execution activity. Existence/ownership survive reconnect/restart and runtime replacement. No V0 archive/delete/rename product is added. |
| Message | Stable identity for one committed conversational record; owner/conversation, authored content, role/source, authoritative position and commit instant. | Every V0 message belongs to one conversation; future shared ancestry need not duplicate it. Uncommitted identity reservations, if used, are not saved history. |
| Author / role | Attribution distinguishing user-authored source from assistant-generated content; explicit user identity for user input and producing execution for assistant output. | Role is a semantic classification, not a human/device/model identity. The DM role examples do not become a fixed enum. V0 needs user and assistant; system instructions need not be persistent chat messages. |
| Authoritative position/order | A message's relation to other committed records in the conversation history. | V0 has an unambiguous linear order; position is neither message identity nor commit time. Future ancestry is separately constrained. |
| Commit instant | The server's recording time for a committed message: an absolute instant sampled within the committing transaction after it obtained write authority and before its commit attempt (FR-15). Authoritative only if that transaction commits; not guaranteed equal to the storage engine's physical commit-completion instant. | Required for every persisted user/assistant message. Stable across reads, retry/reconciliation and timezone rendering; distinct from execution timings. |
| Revision/edit relationship | Future explicit relation between preserved prior content and an edited/replacement representation. | Conceptually supports recoverable historical forms and their sources. No V0 edit, revision-identity format, or branch-on-edit policy. |
| Historical State Boundary | Fixed referenceable meaning of the committed conversation history used at an operation, including exact message occurrences/forms and established order. | For V0, a fixed committed prefix; not necessarily a new entity or copied snapshot. An operation's selected contributions may be a subset. See section 6. |
| Model | Stable historical model identity sufficient to distinguish the model used by an attempt. | Display alias alone cannot silently relabel earlier runs when changed. Exact artifact/version metadata depth remains design work under V0-D03. |
| Model Runtime | Identity of the execution system used, separate from Model and the Anonymous server host. | Replacing a runtime preserves past attribution. Vendor handles are supplementary correlation, not domain identities. |
| Generation intent / Submission | One distinguishable logical user operation, its kind, authorized owner/conversation, submitted meaning, and durable acceptance/outcome association where accepted. | Distinguishes new-message intent from retransmission and generation-retry intent. No separate User Request entity or token format is mandated. |
| Model Run / Generation Attempt | Stable identity for one accepted attempt to execute a generation intent, with lifecycle evidence. “Run” does not assert dispatch actually happened. | Associated with exactly one triggering committed user message, one conversation/owner, and selected model/runtime before dispatch. A user message may have several attempts over explicit retries. |
| Provenance / source reference | Traceable link to an identified source and, where history can evolve, the historical source boundary/form actually used. | Contributions, production, request association and future derivation are different relationships. Missing evidence is a limitation, never an invented link. |
| Reconciliation disposition | Authoritative resolution of previously uncertain work, supported by retained facts. | Refines knowledge and controls admission/publication. It cannot change an already committed message or make a new inference appear to be the old run. |

Diagram 2 — logical relationships (`-->` means the labeled relation; it is not a storage foreign key or a universal derivation edge):

```text
User --owns--> Conversation --contains--> Message
                                            |
                                            +--has--> identity / order / commit instant
User --authorizes access via--> Device --has--> Session
Session --current permitted access--> Conversation

Submission --accepted as--> committed user Message
     |                              |
     +--correlates--> Generation Attempt --uses--> Model + Model Runtime
                             |
                             +--input evidence--> State Boundary + selected Messages
                             |
                             +--produces--> committed assistant Message (zero or one)
```

V0 cardinality constraints: one new-message intent maps to at most one committed user message; one retry intent to at most one additional attempt; one attempt to at most one committed assistant response. Each committed assistant message has exactly one producing attempt. Under V0's no-successful-regeneration rule, one user message can have multiple unsuccessful attempts but at most one successfully committed assistant response. Lookup links in both directions do not themselves constitute derivation cycles.

## 4. Conversation and message lifecycle; preservation decision

A conversation becomes persistent once its creation/owner/identity is coherently confirmed. Listing/opening exposes the same conversation and its saved history. Failure to read must not fabricate an empty history. No message need exist in a newly created conversation. The title, if present, is presentation metadata and not identity; this model introduces no title-generation or rename feature.

A user's draft/submission is not committed history. On accepted durable publication it becomes a source message. A generated partial/final buffer is not committed history until the full assistant-response publication boundary in section 11 is satisfied. Optional streaming remains provisional. A save acknowledgment reports a durable fact; receiving an acknowledgment is not the event that defines commit time.

**LM-01 — Preserve committed message facts.** Accept the candidate invariant: once a message is committed to persistent conversation history, its prior committed content is not silently mutated in place. Preserve its identity, source authorship, established history position, original commit instant and required production/source associations across V0 operations. This follows DATA-01/02/03/08, FR-15 and DM §9; it does not settle whether a future user-visible logical message has revisions, replacements or branches.

A future edit must expose an explicit relationship to a recoverable prior committed form, preserving references made before the edit. It cannot silently change what an earlier operation used. Whether edited forms share a logical parent identity or get distinct first-class identities remains open. V0 implements no edit endpoint, revision store, history rewrite, deletion or regeneration of a successful answer.

Explicit user correction in V0 is a new user-authored message. It does not mutate the earlier user/assistant statement and does not implement a Memory supersession workflow. Future inferred Memory may be superseded by an explicit correction while preserving provenance (INV-007/INV-013).

V0 retains saved source/generated history and minimum run/source/correlation evidence for the life of its dataset (V0-D03). Resource exhaustion yields a visible failure, not pruning. This is not an eternal-retention policy for future releases; section 14 leaves deletion implications open.

## 5. Identity, order, and FR-15 commit time

**LM-02 — Server-authoritative order.** The authoritative server determines and preserves a single order of committed V0 message history in a conversation. Committing another message extends that history; it does not insert a delayed request into an earlier position or reorder already committed records. All authorized clients and context construction use this authority. There is no required total ordering across different conversations.

Message identity answers **which record**; position answers **where it belongs in that conversation's history**; commit instant answers **when the server recorded it as persistent history** (FR-15). None substitutes for the others. This selects no integer sequence, event offset, ID sorting, clock sorting or storage coordination technique.

**LM-03 — Absolute commit instant.** Every persisted user and assistant message has an authoritative server commit-time timestamp represented as an absolute instant independent of client timezone. Commitment establishes its meaning, not composition/send, runtime start/finish, first streamed token, delivery, or reconnection. The instant is sampled within the committing transaction after it obtained write authority and before its commit attempt, becomes authoritative only if that transaction commits, and carries no guarantee of equality with, or a bounded difference from, the storage engine's physical commit-completion instant (FR-15). A write that committed before its acknowledgment was lost retains the original instant upon reconciliation; an attempt that did not commit establishes none, and a later successful operation samples its own. A retry of generation cannot retimestamp its triggering message; a newly committed response has its own instant.

Timestamps alone never establish canonical order. Equal timestamps and clock adjustments that produce decreasing timestamps cannot change established message order, identity or ancestry. Clients render the instant in the selected/local timezone without changing it. FR-15 additionally requires continuously visible time near message actions without hover; that is C01 presentation responsibility, not a second persisted instant. Optional full date/time detail must agree with the same instant. Physical timestamp datatype, precision, serialization and clock implementation remain undecided.

An illustrative history can therefore contain `user U before assistant A` with equal displayed times, or a clock-adjusted instant for A earlier than U's recorded instant. Their established order still remains `U before A`. No silent timestamp normalization rewrites historical facts to make a sort convenient.

## 6. Historical State Boundary and selected context

**LM-04 — Fixed historical boundary.** A Historical State Boundary identifies the exact committed conversation history relevant to an operation at a point in its evolution. In V0 this is a fixed prefix of committed messages, with their identities, committed content/forms and order. Resolving an already recorded boundary must not include later messages or substitute future edited forms. The logical meaning is fixed even if represented without a separately stored boundary object.

This is a **history-state** boundary, not a snapshot of every mutable property in Anonymous. It does not freeze current device/session authorization, titles, or global settings. If a future operation depends on other changing state, it must identify that state explicitly; the broader Conversation State Version scope remains a future decision. Historical permission evidence never authorizes a current read.

Before dispatch, an accepted attempt fixes its input history boundary including its triggering user message and identifies the retained messages selected for invocation in their authoritative order. Section 7 distinguishes this prepared view from evidence of actual invocation. When the whole conversation fits, include its conversational messages as required by V0-D01. If earlier history is omitted, retain the boundary and actual contribution distinction so omission is observable. The newest user message is never silently clipped. An unfulfillable request is refused without deleting a previously saved user message.

The input boundary excludes the response produced from it. A run's source association cannot be a moving “latest conversation” reference. Recording a boundary alone is insufficient to identify which messages were selected from it; selected-message evidence alone is not a complete definition of general future conversation state. Full prompt copies, system-instruction versions, token accounting and exact stochastic replay are not required by V0-D03. Their absence limits exact reproducibility and remains explicit.

Diagram 3 — fixed boundary versus selected contributions:

```text
Conversation A, before attempt R:
  U1 --> A1 --> U2 --> A2 --> U3   | B: fixed history boundary
                      [A2, U3] ---+--> selected contributions for R
                                 |    (illustrative bounded subset)
                                 v
                           attempt R --> A3 committed later

Later current history:
  U1 --> A1 --> U2 --> A2 --> U3 --> A3 --> U4
  B resolves exactly [U1, A1, U2, A2, U3] in that order.

B still ends at U3. R's sources do not acquire A3 or U4 later.
B is not the same thing as R's selected contribution set.
```

The subset above illustrates provenance, not a context-selection algorithm. Boundary representation, general frontier cardinality after branching, and whether a boundary receives its own stable first-class ID remain open. A future multi-source operation needs a fixed boundary for each source and acyclic ancestry; current V0 does not create such operations.

## 7. Request, attempt, response, and provenance

Diagram 4 — production and correlation:

```text
New-message intent S --coherent commit--> user message U in conversation C
U --triggers--> attempt R1 (settled failure)
U --triggering message for--> attempt R2 <--new attempt-- eligible retry intent T
                                  |
                            runtime output
                                  |
                     coherent response publication
                                  v
                         assistant message A

A --produced by--> R2 --triggered by--> U
R2 --used--> Model M / Runtime V / B / actual contributing messages
R1 remains distinguishable; U is not duplicated or retimestamped.
```

Minimum retained meanings for each accepted attempt are its stable identity, owner/conversation, triggering user message, initiating operation association, lifecycle/outcome evidence, and any response. Before dispatch, retain selected model/runtime identity and the fixed input boundary/selected-message associations. Retain enough dispatch association/uncertainty information to avoid losing track of work if the application dies at the dispatch boundary. A provider handle is optional evidence, not the identity foundation; concrete correlation capability is a pre-implementation gate.

Prepared input associations identify the fixed view intended for dispatch; they do not prove those messages reached a model. Retained invocation evidence distinguishes not-invoked, possibly-invoked and actually supplied input. For known invocation, C07 must establish faithful use of the supplied view or expose an incompatibility; detected truncation or model/runtime substitution cannot silently retain a false successful attribution. Persist the producing identities actually established, without relabeling historical runs through a changed current alias. Exactly how runtime evidence establishes this remains LD-04/LD-06/LD-13.

The committed response must resolve to its producing run, model/runtime, and actual contributing conversation messages. Referenced sources must be the authorized current conversation's committed records within the fixed boundary. System instructions and transient context remain distinguishable from user-authored statements. A future external/tool source needs explicit origin and policy evidence before its capability exists; merely adding a source type cannot authorize external work.

Provenance includes different edge meanings: **triggered by**, **contributed to**, **produced by**, and future **derived from / revises / supersedes**. Only actual derivation ancestry is constrained as a DAG. Symmetric navigation or a request/response lookup does not mean a source was derived from its descendant. A response cannot be a source of its own producing attempt; future derivation cannot make an object its own ancestor.

Generated assistant history is evidence of a model's output, not an explicit user fact. Future extraction must preserve this distinction; confidence cannot manufacture source authority. Replacing model/runtime configuration for later attempts must leave earlier attribution meaningful. Minimum identity retention does not require keeping every old model binary or guaranteeing reproducible sampling.

## 8. Model Run / Generation Attempt lifecycle

The names below are logical conditions, not a required persisted enum or protocol state machine. Three dimensions must remain distinguishable: **what work is known to have happened**, **what history was committed**, and **whether evidence establishes the outcome**. A caller's lost connection does not necessarily change the server's known outcome.

| Condition | Required meaning and durable evidence | Admission / next legitimate outcome |
| --- | --- | --- |
| Requested/pending | An accepted operation has a triggering committed user message and recoverable work intent. Preconditions/context may still be evaluated. Invocation is not yet asserted. | Reserve the conversation against conflicting new admission. Dispatch only after required input/model/runtime associations are durably confirmed; otherwise expose precondition failure. |
| Dispatch unresolved | Dispatch may have happened, but available evidence cannot establish whether work began/ended. A stored intent is not proof of execution. | Reconcile or safely terminate possible work; no fresh inference or conflicting continuation. |
| In flight | This distinct attempt is known to be executing or supervised as active. Partial output is provisional. | Keep exclusive generation admission. Completion, known interruption/failure, or loss of knowledge may follow. |
| Output received / finalization pending | Runtime completion/output is known but coherent assistant-response publication has not yet been confirmed. Retain that known execution distinction. | Publish the same attributable result if valid and available, or reconcile the save; do not claim saved success or admit a conflicting operation yet. |
| Complete and saved | Final assistant content, identity/order/instant, run link, input provenance and successful publication agree durably. | Release generation admission when execution is also known ended. Later authorized reads resolve the same result; V0 successful regeneration is ineligible. |
| Failed/interrupted, settled without response | Preconditions failed, execution failed/was stopped, or finalization could not complete; no assistant response committed and no runtime work can still produce a publishable completion. The reason and known execution outcome remain distinguishable. | Once disposition is durable/coherent, release admission. Explicit retry is allowed only under section 9 eligibility; a new user message may instead continue. |
| Outcome indeterminate | Server cannot establish dispatch, execution termination, or publication outcome. Preserve known facts and the unresolved question; do not overwrite it as failure. | Reconciliation gate stays closed to conflicting work. Existing confirmed history remains readable under current permission. |

“Failed/interrupted” at the application level is not a claim that the runtime failed if runtime completion was observed. For example, successful inference followed by confirmed inability to save and loss of the output is an unsuccessful **publication** with preserved knowledge of runtime completion. If a final write may have committed, it remains indeterminate until resolved; no-response certainty cannot be inferred from missing acknowledgment.

V0 does not require a user-facing cancellation action. Administrative/runtime stop and process interruption must be representable. A stop request is not proof that work stopped; an unconfirmed stop remains unresolved. Pending work that never reached the runtime may be settled as not invoked/interrupted, without inventing a model completion.

Diagram 5 — lifecycle; `?` marks unresolved evidence, not an automatic retry:

```text
accepted intent + committed user message
                  |
               pending ----known precondition failure----> settled without response
                  |
          dispatch association durable
                  |
            in flight ----known failure/confirmed stop---> settled without response
                  |
          output / finalization pending ----confirmed loss/no commit--> settled without response
                  |
          coherent response publication
                  v
           complete and saved

pending / dispatch / in flight / finalization --evidence gap--> indeterminate ?
indeterminate --reconcile evidence--> pending, in flight, finalization,
                                    complete and saved, or settled without response

Only settled eligible failure + explicit new retry intent creates a NEW attempt.
```

Reconciliation does not dispatch pending work automatically after restart. A definitely undispatched interrupted attempt is settled without a response; any subsequent eligible generation requires explicit user intent. Refining uncertain evidence to in-flight/finalization refers to the existing attempt and never invents another one.

## 9. Retry, idempotency, and duplicate submissions

**LM-05 — Preserve one logical operation across delivery retries.** Distinguish intent from transport delivery. An accepted new-message operation has enough stable correlation to recover the same message and attempt outcome after retransmission or acknowledgment loss. Accepted retry intent similarly recovers its existing additional attempt. Identical text is not proof of identical intent; deliberate new messages with identical text can be distinct.

Correlation is scoped to the authorized owner, conversation and operation meaning. It is not an authentication credential or permission bypass. Reusing an earlier identity with a different operation, message content, or target must not mutate the original or dispatch additional work; expose a mismatch/conflict. Key format, transport binding, lifetime mechanics and storage uniqueness mechanism remain open. V0 must retain enough accepted-operation associations to prevent duplicates for supported reconnect/retransmission throughout the retained dataset; exact replay of old transport responses is not required.

| Interaction | Logical outcome |
| --- | --- |
| New user message | New intent; if admitted and durably committed, one new user identity/position/instant. Does not reuse a prior message just because content matches. |
| Same submission retransmitted | After current authorization, resolve original acceptance/outcome, including indeterminate saving if necessary. No duplicate message or fresh run. Deduplication resolution is distinct from admission of genuinely new work. |
| Duplicate delivery of an explicit retry | Resolve the same retry attempt. Does not create another retry or another user message. |
| Reconcile uncertain attempt | Establish the existing outcome; do not run inference again to find out what happened. Saved success returns its prior identity/instant; active/unknown work stays non-retryable. |
| Explicit retry after settled failure/interruption | New distinct attempt on the same saved user message, only if it is the latest saved user message and no later message has been accepted; no active/unsettled competing work. Preserve original attempt and message facts. |
| Retry after successful, active, uncertain or superseded attempt | Refuse new generation with an observable reason/current permitted state. A later new user message is distinct from historical regeneration. |
| Request refused while conversation busy | No new message, queued intent, or accepted generation is silently created. A later explicit send is evaluated anew against current state. Rejected-request retention/transport retry details remain contract design. |
| Future deliberate regeneration | Out of V0; must later define alternate-output/branch semantics without overwriting successful history. |

V0 needs at-most-one committed effect per accepted intent/attempt, not a claim of exactly-once delivery or exactly-once physical model computation. The server must not deliberately create a second execution to resolve an uncertain first one. Late or duplicated completion notifications must resolve the producing attempt's current disposition: duplicate successful notification returns/identifies the same saved result; output arriving after a coherently closed unsuccessful attempt cannot append a competing response. Contradictory runtime evidence is an observable fault, not permission to revise established history.

## 10. Multi-client concurrency and current authority

**LM-06 — Admission survives loss of process-local state.** One conversation can have at most one generation whose execution/publication is active or unresolved. Prevent conflicting new admission while a just-accepted user operation is pending as well as while inference runs. Enough persistent evidence must exist to reconstruct this obligation after restart; an in-memory busy flag alone is insufficient. This is a logical obligation, not a selected lock, lease, counter, or reservation entity.

Multiple clients may read committed history while generation runs. Reads must expose coherent committed records and distinguish pending/uncertain activity; provisional text is labeled separately. A previously read view can be old, but no client can promote its cached order, time or outcome into canonical truth. Refresh/reconnect uses current authoritative state under current permission. Pagination/snapshot-token consistency mechanisms remain contract/persistence design.

Nearly simultaneous new sends are decided by the same server authority. If one remains admitted and pending/active/unresolved when the other is evaluated, the latter is visibly refused without append/queue. If the first is fully settled before the second is considered, a later admission may follow in current server order. Which network request wins is not specified. Duplicate delivery is resolved as the already accepted operation before treating it as competing new work, after authorization.

For stale state, evaluate prerequisites against current server history. A new append, if accepted, follows the current boundary, never the client's old position. A retry whose target was superseded is refused. A client operation explicitly dependent on an earlier state cannot silently change its intended target; it must refresh/reconcile or receive a visible refusal when that prerequisite no longer holds. This model does not require every new send to carry an expected-frontier token or settle the later UI policy for warning about intervening messages.

After another client continues the conversation, delayed delivery of an already committed response still identifies its original message/run/order/instant; it is not a fresh append at receipt time. Late uncommitted output cannot bypass the producing attempt's closed state. If another client revokes the recipient device, new protected delivery is denied after acknowledged revocation even when the run may finish and save privately. Historical authorization or correlation identity is insufficient for delivery.

Diagram 6 — shared admission and repeated delivery:

```text
Client A: new intent S ------> authoritative admission ---> U / attempt R pending or active
Client B: retransmit S ------> resolve S -----------------> same U / R outcome
Client B: distinct intent T -> current admission ---------> visible busy refusal; no append
                                     |
                              R coherently settles
                                     |
Client B: later explicit T2 -> current admission ---------> new accepted intent, if authorized

Client-local timestamps/order never arbitrate the server's committed history.
Current device/session/resource permission applies to each protected interaction.
```

## 11. Application-level consistency boundaries

“Coherent publication” means the rest of Anonymous cannot treat a partial combination as confirmed authoritative success. Storage may use multiple steps, but incomplete work must stay distinguishable and recoverable. This is not a demand for one transaction spanning inference, transport and storage, and it does not require every listed operation to share one physical mechanism.

| Boundary | Facts that must agree at confirmation | Incomplete/uncertain behavior |
| --- | --- | --- |
| CB-01 — Conversation creation | Stable conversation identity, owner and persistent existence; create-request association where needed to reconcile acceptance. | Do not falsely confirm creation or interpret failed lookup as a valid empty dataset. Concrete creation retry contract remains later design. |
| CB-02 — User-message publication and admission | Stable message identity, owning conversation/user, user role/content, authoritative position, original commit instant, submission-to-message association, and recoverable indication of accepted work/admission disposition. | A visible saved user message cannot be mistaken for an unaccepted duplicate after restart. Message commitment need not create a fully prepared Model Run in the same storage step. If work preparation later fails, preserve the user message and settle the pending operation explicitly. No inference before durable confirmation. |
| CB-03 — Prepared execution and dispatch eligibility | Distinct attempt, triggering committed user message, owner/conversation, model/runtime identity, fixed input boundary/selected contributions with invocation evidence distinguished, operation correlation and exclusive admission/dispatch-reconciliation facts. | No invocation while these prerequisites are unconfirmed. Persistence cannot make the external runtime dispatch atomic; the gap must be represented as possible dispatch and reconciled. |
| CB-04 — Assistant-response publication | Exact final response content, new stable message identity, assistant authorship, conversation/authoritative position, commit instant, producing run and required provenance, and coherent successful publication outcome. | No confirmed assistant message with missing run/source association; no confirmed saved success without its message. Earlier user/source history survives. If write confirmation is lost, reconcile the same publication, never mint another response as a substitute. |
| CB-05 — Settling execution / releasing admission | Known or reconciled runtime termination/non-dispatch, response publication or confirmed absence, retained attempt outcome, and the ability to admit later work must agree. | Runtime finish alone is insufficient while response saving is unresolved. Marking failure alone cannot release admission while old work may still run or a response may have committed. |
| CB-06 — Reconciliation and duplicate resolution | Same accepted operation/attempt, recovered committed facts, justified state refinement, no conflicting extra effect, and updated admission eligibility. | Existing committed results take precedence over stale client beliefs. Uncertain facts remain uncertain; knowledge of runtime completion is not discarded merely because saving failed. |
| CB-07 — Access-state lifecycle | Device/session associations, owner-authorized trust changes, finite validity/logout/revocation state and enforcement at operation/delivery boundaries. | Acknowledge revocation only when future protected deliveries/operations are denied as required. State loss fails closed. No need to erase history or guarantee recall of already delivered data. |

Logical uniqueness and referential integrity are outcomes: positions cannot ambiguously order two distinct V0 records; one attempt cannot publish two assistant responses; a source/run link cannot silently resolve to another identity; a committed assistant message cannot lose attribution merely through model/runtime replacement. A partial prepared record can exist internally as incomplete evidence, never as a valid confirmed historical object.

Failure and reconciliation records themselves require durable confirmation before being reported as persisted. If recording a disposition fails or is uncertain, preserve the earlier confirmed facts and keep any affected recovery/admission question unresolved; do not use a diagnostic entry or an in-memory terminal label as proof of settled saving.

## 12. Restart and reconciliation semantics

**LM-07 — Restart recovers facts before admitting conflicts.** A server crash does not prove runtime termination or save failure. Durable source/generated history, accepted-operation correlation and execution/provenance facts survive normal and abrupt application-process restart with intact accessible storage (V0-D06). Hardware power loss, corrupt/destroyed storage, backups and quantified recovery times are not guaranteed here.

Minimum retained evidence needed across the scenario in the request:

- The committed user message, owner/conversation, content/authorship, order and commit instant, plus its accepted submission association.
- The admitted generation intent/attempt and its triggering message, model/runtime and fixed input contribution evidence once prepared.
- A recoverable distinction between known non-dispatch, possible dispatch, observed in-flight work, known completion/failure, and unresolved execution; retain whatever trustworthy correlation evidence the chosen runtime/supervisor makes necessary.
- Any coherently committed assistant response with producing attempt/provenance, original position/instant, and corresponding publication outcome; or the unsettled publication intent/outcome that must be checked.
- Enough per-conversation disposition to keep admission closed when old work or publication cannot yet be ruled out. Current access authority must be reconstructed independently of a client's earlier authenticated connection.

Diagram 7 — crash/restart reconciliation (branches describe evidence, not a polling algorithm):

```text
commit user U --> prepare R/input evidence --> request runtime execution
                                                  |
                                    Anonymous server stops/crashes
                                                  |
                                    runtime may live / stop / finish
                                                  |
                                           server restarts
                                                  |
                             recover history + operation/attempt facts
                                                  |
                               close admission for unsettled conversation
                                                  |
          +----------------------+----------------+---------------------+
          |                      |                |                     |
   response already saved   work known live   no saved response     evidence insufficient
          |                      |            + work known ended         |
   retain original result   supervise or       settle failed/         remain visibly
   and confirm termination  safely stop        interrupted attempt     indeterminate
          |                      |                |                     |
   serve authorized view    reconcile again   explicit eligible       no new inference/
                                              retry or new message    conflicting append
```

A saved response can be rediscovered after its acknowledgment was lost without re-executing inference. Its original identity/order/instant and associations remain unchanged. If a separately surviving runtime is still active, even a discovered publication does not permit conflicting generation until execution is known ended.

If a result is available but not yet published, recovery may complete publication **for the existing attempt** only when attribution, full output, eligibility, source boundary and no-prior-publication can be established. This is completion of interrupted saving, not model re-execution. If only partial output remains, do not call it a completed saved response. When no response committed, output cannot be recovered, and work is definitely ended, settle an unsuccessful attempt while preserving any known runtime-completion fact. A fresh answer requires explicit eligible retry and a new run identity.

If dispatch is uncertain, do not reissue it automatically. If a pending operation is definitely undispatched, preserve its user message and record its interrupted/not-invoked disposition; the next attempt needs explicit intent. If no reliable evidence can establish completion/termination, show an unresolved operation and continue permitted reads of confirmed history; do not unfreeze the conversation by discarding recovery state. Bounded recovery mechanisms and runtime capability remain implementation gates, not permission to leave uncertainty as ordinary success.

Contradictory evidence (such as a late completion for an attempt settled without response) is surfaced for investigation and cannot silently change canonical order or create duplicate history. Any corrective workflow for a genuinely corrupted dataset is outside this V0 intact-storage guarantee.

## 13. Future branching, merging, Memory and derived data

The compatibility obligations apply now; the features remain deferred.

| Future concern | Constraint preserved by this model | Decision not made |
| --- | --- | --- |
| Branch | New continuation references an identifiable fixed source boundary without modifying the source. Shared message history need not be copied. | Separate Branch entity versus relationship; independent naming/identity and workflow. Not required by today's linear V0 behavior. |
| Merge | A new result has its own identity, intact sources, source-specific fixed historical boundaries, provenance and acyclic derivation. Later source changes do not silently change it. | Whether a first-class persistent Merge operation/record is needed in addition to provenance; synthesis content/conflicts/presentation. No V0 Merge entity is required. |
| Edited history | Explicit relation to preserved prior content; earlier boundaries continue to resolve the forms actually used. | Revision identity and branching/replacement policies; physical immutability mechanism. |
| Canonical state / summary | Derived view, not authoritative message replacement; associated with actual sources/boundaries and generation evidence where appropriate. | State contents, automatic rebuilding, quality criteria or storage layout. |
| Memory and correction | Explicit user information, inference and uncertainty remain distinguishable; correction can supersede inference with provenance retained. | Taxonomy, scopes, confidence representation, extraction or conflict algorithms. V0 ordinary corrective chat is not a Memory update. |
| Search / embeddings | Index/vector artifacts reference authoritative sources and may be recreated where their recipe/dependencies exist. | Index types, vector storage, embedding model, search/retrieval design. |
| External/tool information | Source origin and authority distinct from user/model content; privacy crossing requires new scoped behavior and enforcement. | Source taxonomy, tool-run design and consent/audit protocol. No V0 external capability. |

**Rebuildable** means a supported representation can be regenerated from retained eligible sources and required derivation dependencies, or recovery can explicitly explain a missing dependency. It does not promise deterministic AI text or recovery after all sources are erased. Losing an index must not delete the messages it referenced.

**Stale** means a view is no longer suitable as the current representation for its intended scope because its relevant source boundary, policy or derivation assumptions changed. A historical summary is not incorrect merely because new messages exist; it can remain valid as a summary of its stated historical boundary. Staleness must not silently widen that boundary.

**Superseded** means a newer explicitly associated interpretation/representation is used as current, while the prior representation and its provenance remain historically distinguishable under the applicable retention policy. It does not mean in-place source mutation or automatic deletion. Future hard deletion may require a different policy, to be decided before offering it.

Future Memory is not uniformly derived: an explicit manually entered fact can be authoritative source information, while an extracted inference or summary is derived. Classification follows origin and preservation obligations, not merely membership in a future Memory subsystem.

The model requires neither explicit Branch/Merge entities today nor a global graph persistence system. It must permit later relationships without redefining V0 source identities or reinterpreting timestamps as ancestry. INV-003/004/005/011/014 constrain those designs; the representation questions in DM §48 remain open beyond the bounded history semantics established here.

## 14. Security-related data and lifecycle/deletion limits

C03 owns the authoritative link among User, Device and Session, device approval/revocation state, and finite session validity/logout consequences. C04/C05 reference permitted owners and operations; possession of a message/run/submission identifier never grants access. A new IP neither invalidates identity by itself nor grants trust to another peer. Device revocation invalidates its sessions; logout affects the selected session. Current permission gating applies to reconciling or reading a previously accepted operation as well as new requests.

Enough access state must survive restart or be conservatively invalidated to prevent logged-out, revoked or expired contexts from becoming authorized again. Continued validity after restart is not promised by remembering an old client connection. Exactly how validity, expiry, owner recovery, clock changes and secret storage are implemented belongs to [Security design](07-security.md). The commit-time clock is not selected as the authority for security expiry, and this task designs no authentication mechanism.

Session/operational retention must preserve required invalidation and ownership outcomes while minimizing unnecessary secret or private activity retention. V0-D03's dataset lifetime guarantee applies to history and minimum execution evidence, not an invented permanent full session-access audit. Rich audit trails, sensitive source-reference exposure, at-rest access, backup protections and erased-data propagation require dedicated decisions.

V0 provides no hide/archive/supersede/delete/physical-removal feature and no automatic history pruning. Future **archive** concerns visibility/activity while retaining history; **supersession/correction** concerns which interpretation is current; **hard deletion** concerns removal and may conflict with previously available provenance/rebuildability. These are distinct effects, not implemented operations. Before a deletion feature, decide authority/scope, retained references or explicit gaps, derivative/cache/vector cleanup, backup/export copies, run/source attribution after removal, and the interaction with pending work and historical boundaries. Do not claim a deleted source can always be rebuilt from a summary.

## 15. Open decisions and implementation-planning gates

The table is the register for unresolved choices in this document. “Blocks” means the dependent implementation cannot responsibly be planned as settled; requirements-level planning can continue. No row authorizes starting its later phase. Original RB question IDs remain unchanged; this task resolves only bounded logical meanings.

| ID / related questions | Deliberately unresolved issue and why | Later owner/document/phase | Blocks implementation planning? |
| --- | --- | --- | --- |
| LD-01 / Q-03, Q-11 | Physical identity, ordering, timestamp/clock representation and retention mechanics; several mechanisms can preserve LM-01–LM-03. No datatype, key format, sequencing, event-sourcing or storage family chosen. | Detailed persistence/backend design; selection ADR only with evidence. | Yes, saving/recovery implementation details. |
| LD-02 / Q-02 | Boundary representation and whether separately identified; broader state beyond conversation history and future multi-frontier ancestry remain undefined by V0 needs. Logical fixed-history meaning is settled. | Detailed persistence design for V0 representation; later branch/merge/state design for broader semantics. | Yes for representation; broader feature choices do not block V0. |
| LD-03 / Q-12, Q-13, Q-16, Q-24 | Concrete correlation/idempotency scope encoding, rejected-request behavior, dedup retention representation, run/source storage, coherent publication/dispatch gap handling, and delivery acknowledgment contract. Semantics here do not choose algorithms. | Backend/persistence design, then [API design](08-api-design.md). | Yes before saving/execution implementation. |
| LD-04 / Q-16, Q-18 | Single-authority enforcement, orphan-runtime observation/termination, final-output recovery, reconciliation and admission-release mechanism; runtime feasibility is unmeasured. | Backend/lifecycle design informed by [runtime feasibility evidence plan](evidence/runtime-feasibility-plan.md). | Yes before execution/restart implementation; no benchmark is run here. |
| LD-05 / Q-19, Q-23 | Actual supported OS/client configurations, storage/resource envelope and measured runtime performance; hardware inventory is reported, not verified. | Feasibility/benchmark task and later deployment/persistence selection. | Yes for capacity and operational acceptance; logical modeling can finish. |
| LD-06 / Q-12, Q-19 | Exact context sizing/selection and template accounting; sources/omission meaning settled, runtime limits unmeasured. Rich prompt/version replay evidence remains outside the minimum. | Context/backend design and runtime evidence; richer audit scoped separately. | Yes for C06 implementation; replay extras do not block V0. |
| LD-07 / Q-21 | Credentials, provisioning/recovery, session lifetime/renewal, expiry clock behavior, revocation races, current delivery authorization, at-rest/private-reference protections and necessary access-state retention. These need threat modeling. | [Security design](07-security.md), then API/backend/persistence integration. | Yes before an access-capable build or real private/remote use. |
| LD-08 / Q-16, Q-19, Q-20 | Pagination/read snapshot mechanics, stale-view warning/precondition contract, reconnect/presentation details; no client sorting or silent retargeting is allowed. | API/frontend design with Backend/Security. | Yes for client/API implementation; no new V0 disconnected writes. |
| LD-09 / Q-01, Q-03–Q-05 | Branch/Merge entity choice, edit/revision identity, regeneration workflow, merge product/conflict handling. No V0 capability needs them. | Future branch/merge/edit requirements and architecture; ADR if architectural. | No for V0; yes before those features. |
| LD-10 / Q-06–Q-09, Q-14, Q-24 | Memory taxonomy, confidence, scopes/corrections, derived freshness/rebuild policies and quality; distinction/provenance alone do not define the subsystem. | [Memory design](06-memory-design.md) when separately scoped. | No for V0; yes for those features. |
| LD-11 / Q-10, Q-17, Q-22 | Rich privacy classes, tools/external sources, release consent/audit and multi-user roles; V0 is PRIVATE-only and single-user. | Future requirements/scope plus Security/Memory/API design. | No for V0; yes before expanding access/capabilities. |
| LD-12 / Q-15, Q-18 | Hide/archive/deletion semantics, erasure propagation, backup/export workflows and disaster recovery guarantees/targets. Preserved history does not settle later removal or corrupted-storage recovery. | Future lifecycle/recovery design with Data & Memory/Security. | No for declared V0 intact-storage guarantee; yes before such capabilities or stronger claims. |
| LD-13 / Q-13, Q-24 | Historical model/runtime version/artifact detail beyond sufficient identity, telemetry breadth, rich audit retention and diagnostic format. No full replay is required. | Backend/persistence/security contract design; richer evidence requires scope. | Minimum attributable identities and sanitized diagnostics: yes; optional replay/detail: no. |

Known risks: dispatch and durable recording cannot be assumed to be one atomic cross-runtime act; missing supervision evidence blocks implementation. State boundaries must not be mistaken for current authority or complete prompt replay. Preserving exact output is stronger than preserving “similar” model output. Single-authority semantics require enforcement even though only one server instance is intended. These are explicit design gates, not contradictions resolved by weakening source requirements.

## 16. Traceability and objective validation cases

All 37 selected V0 requirement subsets are mapped below; behavioral subsets remain those of V0 §6. This model supplies persistence meaning, not tests of a nonexistent application. Non-persistence presentation/network obligations retain their existing owners.

| Requirements | Logical coverage | V0 scenarios |
| --- | --- | --- |
| FR-01, FR-02, FR-03, FR-14 | Owned stable conversation/messages; coherent publication, cross-client continuity (sections 3–5, 11–12). | V0-AC-01, V0-AC-02, V0-AC-03 |
| FR-08, FR-09 | Fixed history boundary versus actual contributions; preserved older history and transient context (sections 2, 6–7). | V0-AC-08, V0-AC-13 |
| FR-12, DATA-08 | Distinct run/model/runtime, source/output associations and outcomes (sections 3, 7–8, 11). | V0-AC-01, V0-AC-06, V0-AC-11 |
| FR-15 | Required absolute commitment instant independent of identity/order/client format (sections 4–5, CB-02/04). C01 retains continuous display responsibility. | V0-AC-01, V0-AC-02, V0-AC-03 |
| NFR-01, NFR-06 | Local persistence/access without cloud dependency, practical existing-hardware gates (section 15 and Persistence Technology Requirements). | V0-AC-12 |
| NFR-02, NFR-03, NFR-04, NFR-07 | Host/client/runtime/storage-independent meanings and owned boundaries (sections 1, 3, 7 and Persistence Technology Requirements). | V0-AC-03, V0-AC-05, V0-AC-11, V0-AC-15 |
| NFR-05 | Same retained history/instants and access semantics for all V0 clients; UI/accessibility remains C01's separate acceptance obligation (sections 5, 10). | V0-AC-03 |
| SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06, SEC-08 | Persistent owner/device/session authority, revocation coherence, private references/diagnostics; no transport/credential mechanism (sections 3, 10–11, 14–15). | V0-AC-04, V0-AC-05, V0-AC-10, V0-AC-14 |
| PRIV-01, PRIV-03, PRIV-04, PRIV-05 | PRIVATE categories/references and fail-closed authority; model text cannot grant release (sections 2, 7, 14). | V0-AC-09, V0-AC-14 |
| DATA-01, DATA-02, DATA-03, DATA-05, DATA-07 | Stable facts, preserved source/generated histories, explicit origin/correction and acyclic derivation compatibility (sections 2–7, 13). | V0-AC-01, V0-AC-07, V0-AC-08, V0-AC-13, V0-AC-15 |
| REC-01, REC-02, REC-03, REC-04, REC-05 | Coherent saved/failed/unknown outcomes, non-destructive recovery and context rebuilding (sections 2, 8–12). | V0-AC-02, V0-AC-06, V0-AC-07, V0-AC-08, V0-AC-09, V0-AC-13 |

Deferred requirements FR-04/05/06/07/10/11/13, DATA-04/06/09 and REC-06 impose future compatibility rather than V0 features. Conditional SEC-07, PRIV-02/06 and DATA-10 stay inapplicable under current scope. Every DM invariant is preserved: INV-001/002/008/009 by identity/ownership, INV-003/004/005/011/014 by fixed sources and acyclic future derivation, INV-006/007/013 by classification/provenance/correction, INV-010 by device identity, INV-012 by server-enforced privacy, and INV-015 by the history/context distinction.

Use synthetic fixtures for these future acceptance checks; no runtime tests have run in this task:

| Case | Action / failure point | Objective expected result |
| --- | --- | --- |
| LM-T01 | Fail user commit, then separately lose acknowledgment after a real commit. | Failed/unconfirmed write causes no dispatch. Reconciliation of actual commit finds exactly one user message with original identity/order/instant, not a duplicate. |
| LM-T02 | Inject failure between final content preparation and response/run/provenance publication. | No confirmed orphan assistant message or false saved success; prior source history unchanged. Recovered coherent publication preserves one response. |
| LM-T03 | Equal timestamps, backward clock adjustment, timezone/date-boundary changes across all clients; reopen/restart. | Established order/identities and persisted instants unchanged. Display conversions agree with the same instant; C01's no-hover check remains V0-AC-03. |
| LM-T04 | Repeat accepted message/retry delivery; deliberately submit identical text with new intent; reuse correlation with conflicting content. | Repeated operation has no extra effect; distinct admitted intent can create another message; conflict cannot mutate the original. |
| LM-T05 | Concurrent sends from two clients; replay one accepted submission while its run is active. | At most one newly admitted pending/active generation; other new busy send refused without append/queue; duplicate resolves original outcome. |
| LM-T06 | Retry a settled failed latest message, then try active/uncertain/successful and superseded cases. | Only eligible explicit retry creates a new run on the same user message. All others cause no new inference/history. |
| LM-T07 | Crash before dispatch, during possible dispatch, while runtime survives, and after response commit before acknowledgment; also fail persistence of a terminal disposition. | User facts survive; no automatic inference replay; uncertain/live work blocks conflicts; committed result is recovered unchanged. Proven non-dispatch permits settled interruption, not invented completion or actual input contribution. An unconfirmed failure record is not a durably settled outcome. |
| LM-T08 | Runtime finished but response saving remains unknown; separately confirm no response committed and output is lost. | Unknown publication stays indeterminate. Proven unsuccessful finalization preserves known runtime completion and can settle only after execution ends; any later retry is distinct. |
| LM-T09 | Freeze a boundary and a selected input subset; append later messages; discard transient context. | Old boundary and contribution set remain fixed; sources recover exactly; later context construction does not regenerate old assistant history. |
| LM-T10 | Stale retry target and late/duplicate output after another operation becomes current. | No insertion into old history or second publication; producing-attempt disposition controls the outcome. Saved old results are delivered with original identity/order if authorized. |
| LM-T11 | Revoke a device with two sessions during generation; restart; change ordinary IP; test unrelated session. | Revoked sessions cannot regain authority or receive further protected output after acknowledgment; unrelated valid context remains usable. Saved history survives. |
| LM-T12 | Design fixtures for future branch/merge/edit and inferred correction; try self/indirect derivation cycles. | Sources and referenced historical forms remain recoverable; new merge identity/fixed boundaries; no derivation cycle; correction supersedes inference without relabeling its origin. No V0 feature implementation claimed. |
| LM-T13 | Replace runtime or persistence adapter in a future controlled fixture; separately lose only a read cache/context. | Original IDs/ownership/instants/order/run/source associations preserved. Cache/context loss does not erase or silently re-infer saved history. |
| LM-T14 | Access-policy/read failure, missing source references or diagnostic secret marker. | Fail visibly/closed; no fabricated empty history/provenance, no private release, and no secret in ordinary diagnostics. |

Seven plain-text diagrams use explicit labels: containment/access, production, construction and correlation arrows do not all mean derivation. Review each diagram against the concept, lifecycle and coherence tables; cycles are prohibited for ancestry, not for navigation. This keeps diagrams inspectable in version control without a renderer dependency.

## 17. Review record and completion boundary

Focused author reviews are recorded below; they are not independent agent approvals or implementation evidence. The repository's [specialist responsibilities](agents/README.md) guide their concerns. Review outcomes and actual structural checks are also retained in the ExecPlan.

| Review | Findings and disposition |
| --- | --- |
| Architect | Preserved ADR-0001–0005 ownership/dependency boundaries and all source baselines. Restricted fixed boundaries to historical conversation content, not current authorization or a global application snapshot. ADR-0006 records the warranted preservation decision; physical representation and broader state-version scope remain open. |
| Backend | Separated prepared inputs from proof of invocation, runtime completion from saved publication, and terminal labels from durably settled outcomes. Clarified the non-atomic dispatch gap, surviving runtime gate, and duplicate/late-result handling. Concrete supervision, correlation and coherent storage mechanisms remain implementation gates, with no exactly-once physical execution claim. |
| Security | Verified distinct user/device/session identities, current authorization for duplicate resolution and delivery, and revocation across a device's sessions. Provenance is private evidence, not access authority. Limited retention claims to required history/execution evidence; credential, expiry-clock, secret-storage and recovery mechanisms remain for Security design. |
| QA | Mapped all 37 selected requirement subsets and 15 V0 scenarios; specified 14 objective future cases covering failed writes, lost acknowledgments, duplicate/concurrent requests, clock changes, stale clients, surviving runtime, uncertain publication and revocation. Reviewed seven diagrams against the prose/cardinalities. These are document checks and future cases, not passing application tests. |
| Data & Memory | Kept exact saved assistant output distinct from rebuildable derivatives. Clarified that manually entered future Memory can be source data; inferred Memory is derived. Fixed boundaries and actual contributions preserve ancestry without requiring Branch/Merge entities, an edit representation, a Memory taxonomy or a global graph store. |

Documentation validation on 2026-10-03 passed: exact coverage of the 37 selected requirement subsets and 15 V0 scenarios; seven logical guarantees, seven coherence boundaries, 13 fully assigned open decisions and 14 future validation cases; seven fenced text diagrams; local links; and the required final heading. Manual semantic walkthroughs checked diagram relationships and the failure/recovery cases above. File hashes confirmed that only this model, its new ADR/ExecPlan, and README status changed; source baselines, prior ADRs, later placeholders and runtime evidence were preserved. No application test or hardware benchmark was run.

Completion of this logical baseline does not authorize implementation or close physical/security/runtime evidence gates. The final section derives persistence-solution obligations rather than choosing a solution.

## Persistence Technology Requirements

Any future persistence solution and its Anonymous-owned adapters must demonstrate these implementation-neutral properties within the selected V0 scope. “Future” obligations preserve feasibility, not a demand to implement those features now.

| Property | Required capability / proof obligation |
| --- | --- |
| Durability | Confirmed user/generated history and required operation/run/source facts survive orderly and abrupt application-process restart with intact accessible storage. Report known failure and uncertainty accurately; do not claim hardware-power-loss/disaster guarantees without separate scope/evidence. |
| Consistency and coherent publication | Fulfill CB-01–CB-07 so partial user/response/run/provenance/access transitions cannot masquerade as confirmed success. Bridge multi-step operations with recoverable incomplete state; do not assume atomic external inference. |
| Concurrency | Support one authoritative application's shared admission and coherent reads across multiple clients, including duplicate requests, pending/finalizing work and post-restart uncertainty. Do not depend on a single client's disabled control. |
| Stable identity | Preserve user/device/session/conversation/message/attempt/model/runtime distinctions and accepted-operation association independently of names, host, model product or client. A migration must not silently reassign those identities. |
| Provenance integrity | Resolve committed response to producing execution and actual source contributions/boundaries. Preserve known origin and distinguish evidence gaps. Reference reconstruction must not invent history. |
| Authoritative ordering | Preserve established V0 conversation order independent of timestamps and client-local state; permit coherent extension without retroactive insertion. Do not require one global order across conversations or permanently linear future topology. |
| Commit-time meaning | Retain authoritative absolute instants with committed user/assistant records, including lost-ack reconciliation; preserve them across formatting, restart and migration without selecting an encoding here. |
| Restart and reconciliation | Retain enough accepted-operation/dispatch/publication facts to resolve duplicates and prevent conflicting execution after process loss. Expose unresolved outcomes; support bounded recovery once concrete runtime capabilities are established. |
| Local operation and privacy | Operate without a required cloud service/subscription; support private server-owned storage and enforceable access boundaries. Diagnostic evidence must not disclose secrets or private payloads. |
| Backup/export feasibility | Permit later coherent capture/export of related source/generated history, identities, ordering, commit instants, access implications and provenance, with integrity verification. This is a future design capability constraint, not a V0 backup UI/format, automatic schedule or tested restore guarantee. |
| Migration/evolution | Permit a future representation/engine transition with verification of content, identities, order, instants, attribution and lifecycle meaning. Make partial transition/failure observable. No migration library, format or procedure is selected now. |
| Branch/merge compatibility | Allow later non-destructive sharing/reference of history, new derived identities, fixed per-source boundaries and acyclic ancestry without destructive conversion of V0 facts. No Branch/Merge entity or graph product is mandated. |
| Derived/search/vector integration | Allow separately managed derived artifacts to reference eligible source identities/boundaries and be rebuilt/superseded where supported, without making an index/vector result authoritative history. No vector storage, embedding model or index design is selected. |
| Operational practicality | Be maintainable by one primary developer on the reported Windows desktop and future replaceable hosts; expose sanitized durability/capacity/recovery failures. Validate resource use and required capabilities on actual hardware before selection; no benchmark result or performance target is invented here. |
