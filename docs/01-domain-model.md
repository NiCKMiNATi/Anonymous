# Anonymous — Domain Model

**Status:** Draft v0.1  
**Depends on:** `00-project-definition.md`

---

# 1. Purpose

This document defines the conceptual entities, relationships, invariants, and terminology used by Anonymous.

The purpose is to define **what the system means** independently of:

- database technology;
- programming language;
- API representation;
- frontend implementation;
- model provider;
- storage engine.

These definitions should remain meaningful even if the implementation changes completely.

---

# 2. Fundamental Model

Anonymous is not fundamentally modeled as a collection of chat transcripts.

Its underlying domain is better understood as a collection of:

- identities;
- immutable or append-oriented records;
- conversations;
- relationships;
- derived states;
- memories;
- artifacts;
- execution records;
- provenance links.

The user-facing concept of a “chat” may therefore be a **view over richer underlying structures**.

---

# 3. Identity

Every persistent first-class domain object should have a stable internal identifier.

Examples:

- Conversation ID
- Message ID
- Memory ID
- Artifact ID
- Device ID
- Model Run ID

Identifiers should not derive their meaning from display names.

For example:

`conversation_7f92...`

may be displayed as:

> Local AI Architecture

Renaming the conversation must not change its identity.

---

# 4. User

A **User** represents a human identity using Anonymous.

V0 assumes one primary user.

This does not mean user identity should be absent from the domain model.

## Responsibilities

A User may own or have access to:

- conversations;
- memories;
- workspaces;
- artifacts;
- devices;
- sessions;
- settings.

## V0 invariant

Anonymous may optimize for one user, but persistent data should not rely on the assumption that no user identity exists.

This avoids making future multi-profile support unnecessarily destructive.

---

# 5. Device

A **Device** represents a recognized client machine or endpoint.

Examples:

- Windows desktop
- MacBook
- iPhone

A Device is not synonymous with an IP address.

## Possible attributes

- stable ID;
- display name;
- platform;
- trust status;
- registration time;
- last activity;
- capabilities;
- revocation state.

## Invariants

A change in network address does not create a new Device.

A revoked Device must not automatically regain trust merely because it later uses an old IP address.

---

# 6. Session

A **Session** represents an authenticated interaction context between a client/device and Anonymous.

A Device and Session are different concepts.

Example:

```text
Device
Nikhil-MacBook

Sessions
├── session A
├── session B
└── session C
```

Revoking a session need not revoke the device.

Revoking a device may invalidate its sessions.

Exact authentication mechanics remain an implementation decision.

---

# 7. Workspace

A **Workspace** is a logical organizational boundary containing related user activity.

Potential examples:

- Personal
- Anonymous Development
- Career
- Music
- Finance

Workspaces are optional from a V0 UI perspective but useful as a conceptual domain boundary.

A workspace may contain:

- conversations;
- artifacts;
- memory scopes;
- projects.

Whether Workspaces and Projects remain separate concepts will be evaluated later.

---

# 8. Conversation

A **Conversation** is a persistent logical interaction context.

It has stable identity independent of:

- title;
- model;
- client device;
- runtime;
- current summary;
- current branch.

A Conversation is not defined merely as an array of messages.

## Possible properties

- ID;
- owner;
- title;
- created time;
- updated time;
- state;
- workspace;
- privacy classification;
- source relationships;
- metadata.

## Important distinction

A Conversation describes a logical conversational context.

Messages describe events/content within or associated with that context.

---

# 9. Message

A **Message** is a persistent conversational record.

Possible authors include:

- user;
- assistant/model;
- system;
- tool;
- future agent.

## Possible attributes

- stable ID;
- conversation ID;
- role;
- content;
- commit-time timestamp (required for persisted user and assistant messages under FR-15 below);
- parent relationship;
- provenance;
- model-run association;
- attachments;
- metadata.

## Message identity, conversation ordering, and commit time

[FR-15](02-requirements.md#fr-15--persist-and-continuously-display-message-timestamps) requires every persisted user and assistant message to have an authoritative commit-time timestamp. These three concepts have distinct meanings:

| Concept | Logical meaning |
| --- | --- |
| Message identity | The stable identity of a particular conversational record, independent of its content, position, timestamp, or client. A timestamp does not identify a message; distinct messages may have the same commit time. |
| Server-authoritative conversation ordering | The message relationships and order established and retained by Anonymous for the conversation. Clients and context construction use this authority; client clocks, display times, and identity alone do not establish it. V0 presents a linear history; this does not fix the future topology or its representation. |
| Commit time | The authoritative instant when the server commits the message to persistent conversation history. It is retained with the message as an absolute instant independent of client timezone. It does not mean client composition/send time, model generation start/completion, or client receipt/display time. |

Timestamp alone must not define conversation ordering. Equal commit times or non-monotonic timestamps caused by clock adjustments do not change established message order or identity. The mechanism for retaining and enforcing server-authoritative order remains a design decision.

Reopening, reconnecting, restarting with storage intact, reconciling a submission, or retrying inference for an existing saved user message preserves that message's identity and original commit-time instant. A newly persisted assistant response has its own identity and commit time. Provisional output or an uncertain save is not confirmed committed history merely because a time is displayed.

Formatting the instant in a selected or client-local timezone is presentation behavior. Changing timezone or date/time formatting must not alter the persisted instant, message identity, or server-authoritative order. FR-15 defines the V0 visibility requirement. No physical timestamp datatype, precision, serialization, or database-specific representation is selected here.

## Message immutability principle

Once a message becomes authoritative conversation history, edits should not silently destroy its previous content.

User-visible “editing” may eventually be represented as:

- a revision;
- a replacement event;
- a new branch;
- another explicit versioning mechanism.

The exact implementation remains open.

---

# 10. Conversation topology

A traditional chat application models messages as:

```text
M1
↓
M2
↓
M3
↓
M4
```

Anonymous must support branching:

```text
M1
↓
M2
├──── M3A
│      ↓
│     M4A
│
└──── M3B
       ↓
      M4B
```

Therefore the underlying message relationship cannot be assumed to remain a simple linear list.

At minimum, messages require ancestry relationships capable of representing branching.

The identity, ordering, and commit-time distinctions in section 9 apply without reducing this topology to timestamp sorting. Commit time does not establish ancestry or resolve the open Branch/state-version representations.

---

# 11. Branch

A **Branch** represents divergence from an existing conversational state.

A Branch is not required to duplicate the source history.

Conceptually:

```text
M1
↓
M2
↓
M3
├───────────────┐
↓               ↓
M4A             M4B
```

The history M1 → M3 may be shared logically.

## Branch invariant

Creating a branch must not modify the existing branch.

## Branch origin

A branch must be capable of identifying its divergence point.

---

# 12. Is a Branch an object?

This remains an intentional open design question.

Two legitimate representations exist.

### Explicit Branch Object

```text
Branch
├── id
├── conversation_id
├── fork_message_id
└── metadata
```

Advantages:

- clear UI identity;
- easy naming;
- branch-specific metadata.

### Derived Branch

A branch may instead be inferred from message-parent relationships.

Advantages:

- simpler fundamental topology;
- fewer duplicated concepts.

Current direction:

> Treat branching as a fundamental relationship first. Add a persistent Branch entity only if product behavior requires independent branch identity.

This prevents premature schema commitment.

---

# 13. Merge

A **Merge** combines context from two or more existing sources into a new derived conversational context.

Given:

```text
Conversation A
Conversation B
```

a merge may produce:

```text
Conversation C
```

with:

```text
C derives_from A
C derives_from B
```

## Core invariants

A survives.

B survives.

C has its own identity.

C records its provenance.

Creating C does not retroactively rewrite A or B.

---

# 14. Merge is not Git merge

Anonymous merge semantics must not be assumed to behave like text/source-control merging.

A conversational merge may involve:

- source summaries;
- canonical states;
- memories;
- selected messages;
- conflict detection;
- model-generated synthesis.

Therefore the exact merge product must be explicit.

---

# 15. Merge Record

A **Merge Record** represents the operation that created a merged state.

Possible properties:

- merge ID;
- source conversation IDs;
- source state/version IDs;
- destination conversation ID;
- strategy used;
- model run;
- timestamp;
- conflict information;
- user decisions;
- provenance.

This makes merge generation auditable.

---

# 16. Snapshot / State Version

Because source conversations may continue evolving after a merge, Anonymous must distinguish:

> “Conversation A”

from:

> “The state of Conversation A when C was created.”

Without this distinction:

```text
A + B → C
```

becomes ambiguous if A later receives another 500 messages.

Therefore derived operations should eventually be able to reference a **specific source state or version boundary**.

Possible implementations include:

- message frontier;
- event sequence number;
- snapshot ID;
- state version.

Implementation remains open.

The conceptual requirement does not.

---

# 17. Canonical State

**Canonical State** is a compact representation of information Anonymous currently considers relevant to the ongoing context.

It is derived data.

It is not raw history.

Possible contents:

- active objectives;
- established decisions;
- relevant user preferences;
- unresolved questions;
- current entities;
- project state;
- important constraints.

## Invariants

Canonical State must not erase its source history.

It should be possible to identify what evidence contributed to important elements where practical.

Canonical State may be regenerated or superseded.

---

# 18. Context

**Context** is the information assembled for a specific model invocation.

Context is ephemeral relative to canonical persistent data.

It may include:

- recent messages;
- canonical state;
- retrieved memories;
- retrieved raw messages;
- files;
- tool results;
- system instructions;
- task-specific instructions.

Context is not itself necessarily stored as authoritative user knowledge.

---

# 19. Context Builder

The **Context Builder** is the conceptual subsystem responsible for deciding what information is included in a model request.

Conceptually:

```text
Current Request
      │
      ├── Recent conversation
      ├── Canonical state
      ├── Relevant memories
      ├── Retrieved history
      ├── Relevant files
      └── Policy/privacy constraints
              │
              ▼
         Model Context
```

This is a core Anonymous responsibility.

It must not be delegated blindly to the model runtime.

---

# 20. Memory

A **Memory** is a persistent knowledge item maintained independently from raw conversational ordering.

A Memory is not simply a copied message.

Example:

Raw message:

> I own a Yamaha PSR-E383.

Possible memory:

```text
subject: user
predicate: owns
object: Yamaha PSR-E383
source: message xyz
status: explicit
```

The exact representation does not need to be graph-shaped.

The example illustrates semantic separation.

---

# 21. Memory types

The final taxonomy remains open, but Anonymous should anticipate materially different classes.

Potential classes:

### Fact

Relatively stable information.

### Preference

A user's preference or tendency.

### Decision

A decision made within a project or context.

### State

Information likely to change.

### Procedure

A reusable way of performing something.

### Inference

Information concluded by a model rather than explicitly provided.

### Summary

Compressed representation of larger source material.

### Relationship

Association between entities.

The system should not prematurely treat every memory identically.

---

# 22. Memory Scope

Memory may apply at different scopes.

Examples:

```text
Global user memory
Workspace memory
Project memory
Conversation memory
Temporary/session memory
```

A fact useful inside one project should not necessarily pollute every future conversation.

Scope is therefore part of memory semantics.

---

# 23. Memory Provenance

Every important Memory should support provenance.

Potential provenance sources:

- message;
- conversation;
- uploaded artifact;
- user-created entry;
- web result;
- tool output;
- another memory;
- model inference.

One Memory may have multiple supporting sources.

---

# 24. Memory Status

Anonymous must distinguish epistemic status.

Initial conceptual statuses may include:

- explicit;
- observed;
- inferred;
- verified;
- uncertain;
- conflicting;
- superseded;
- outdated.

These statuses are not yet a finalized enum.

---

# 25. Confidence

Confidence applies primarily where uncertainty exists.

An explicit statement from the user should not require pretending that an AI-generated probability is its authority.

Example:

```text
User explicitly says:
"I use a MacBook Pro M1 Pro."

status = explicit
```

versus:

```text
Model concludes:
"The user probably prefers macOS."

status = inferred
confidence = ...
```

Confidence must complement provenance, not replace it.

---

# 26. Correction

A **Correction** occurs when authoritative information invalidates or modifies prior derived knowledge.

Example:

```text
Old inference:
User prefers X.

User:
"No, I don't."
```

The system should preserve historical provenance while ensuring the incorrect inference is no longer treated as current truth.

Anonymous therefore requires a concept of **supersession**, not merely deletion.

---

# 27. Conflict

A **Conflict** exists when two pieces of relevant information cannot both be treated as simultaneously current/true within the same interpretation.

Example:

```text
Memory A:
Preferred database = MongoDB

Memory B:
Preferred database = PostgreSQL
```

This may represent:

- changed preference;
- different scope;
- conflicting evidence;
- stale information.

Anonymous should not blindly ask a model to average contradictions into philosophical mush.

Conflict resolution may involve:

- recency;
- authority;
- explicit user correction;
- scope;
- manual resolution;
- retaining uncertainty.

---

# 28. Source

A **Source** identifies where information originates.

Potential source kinds:

- user message;
- assistant output;
- local file;
- web resource;
- tool output;
- system process;
- external API;
- manually entered record.

A Source provides provenance identity.

---

# 29. Artifact

An **Artifact** is a persistent user-accessible object that is not merely a conversational message.

Examples:

- document;
- PDF;
- image;
- code file;
- dataset;
- generated report;
- audio;
- future application output.

Artifacts may be:

- uploaded;
- generated;
- imported;
- linked.

---

# 30. Artifact Content vs Artifact Record

The logical Artifact and its binary/textual storage should be separable.

Example:

```text
Artifact record
├── ID
├── filename
├── media type
├── ownership
├── metadata
├── provenance
└── storage reference
```

The bytes may live elsewhere.

This allows storage backends to change without redefining artifact identity.

---

# 31. Model

A **Model** represents a model identity/capability known to Anonymous.

Examples may include local or remote models.

A Model should not be confused with the runtime serving it.

---

# 32. Model Runtime

A **Model Runtime** is the system that executes inference.

Examples:

- Ollama;
- another local inference server;
- a remote API.

Conceptually:

```text
Model
   │
served by
   ▼
Model Runtime
```

This distinction enables future routing.

---

# 33. Model Run

A **Model Run** records a single inference execution.

Possible attributes:

- run ID;
- model;
- runtime;
- request timestamp;
- completion timestamp;
- context references;
- parameters;
- output;
- error state;
- resource/usage information;
- provenance.

Model Runs matter because assistant output should be traceable to the execution that produced it.

---

# 34. Tool

A **Tool** is a capability available to an AI or Anonymous service.

Examples:

- web search;
- file lookup;
- calculator;
- code execution;
- future external integrations.

Tools do not become implicitly trusted merely because a model can call them.

---

# 35. Tool Run

A **Tool Run** records execution of a Tool.

Possible information:

- tool;
- request;
- caller;
- timestamp;
- result;
- status;
- security classification.

This provides auditability and enables debugging.

---

# 36. Agent

An **Agent** is an AI execution role capable of pursuing a bounded goal using a model and potentially tools.

This concept should remain separate from:

- Model;
- Conversation;
- User;
- Tool.

An Agent may use different Models over time.

A Model is computational capability.

An Agent is behavior, responsibility, state, and permissions around that capability.

---

# 37. Identity vs Role

Anonymous must avoid conflating identity and role.

Example:

```text
Agent identity:
security-reviewer-01

Role:
Security Reviewer

Model:
Model X
```

The same role may later be fulfilled by another model.

---

# 38. Privacy Classification

Persistent information may require privacy metadata.

Possible conceptual classes:

- PRIVATE;
- LOCAL-SHAREABLE;
- EXTERNAL-ALLOWED;
- PUBLIC.

The actual taxonomy remains open.

The important requirement is that privacy handling must be explicit enough for policy enforcement.

---

# 39. Privacy Boundary

Moving data across privacy boundaries is itself a meaningful operation.

Example:

```text
PRIVATE Memory
      │
      X automatic transfer prohibited
      │
WEB Model Request
```

If the user explicitly permits information to cross the boundary, that permission should be scoped and auditable where practical.

---

# 40. Event

Anonymous may benefit from treating important state changes as **Events**.

Examples:

- message created;
- conversation renamed;
- branch created;
- merge performed;
- memory created;
- memory superseded;
- artifact attached;
- device revoked.

This does **not** mean Anonymous must implement full event sourcing.

The Event concept is useful because it makes mutation/history explicit.

Whether events become the persistence foundation remains undecided.

---

# 41. Tree vs DAG vs Event Graph

Anonymous cannot be modeled completely as a simple tree.

Branching alone can be represented by a tree.

Merging introduces multiple ancestry.

Example:

```text
    A
   / \
  B   C
   \ /
    D
```

D has ancestry through both B and C.

This creates a **directed acyclic graph (DAG)** at the conversation/state relationship level, assuming cycles are prohibited.

Therefore:

> Conversation derivation relationships are provisionally modeled conceptually as a DAG.

This does not require every message to live in one giant graph database.

It is a domain property, not a database decision.

---

# 42. Why cycles should initially be prohibited

Consider:

```text
A derives from B
B derives from A
```

Provenance and state resolution become ambiguous.

Similarly:

```text
A → B → C → A
```

creates recursive ancestry without a clear historical direction.

Anonymous should therefore initially enforce:

> A derived object cannot become an ancestor of itself.

This keeps provenance relationships acyclic.

---

# 43. Conversation vs Conversation State

A Conversation has persistent identity across time.

Its state evolves.

Therefore Anonymous should distinguish:

```text
Conversation Identity
```

from:

```text
Conversation State at T1
Conversation State at T2
Conversation State at T3
```

This becomes essential for reproducible merges, summaries, and model runs.

---

# 44. Authoritative and Derived Data

Anonymous should distinguish two broad classes.

## Authoritative/source data

Examples:

- user messages;
- uploaded files;
- explicit user corrections;
- manually entered settings.

## Derived data

Examples:

- summaries;
- embeddings;
- inferred memories;
- generated titles;
- canonical state;
- merge syntheses.

Derived data may be rebuilt.

Source data should receive stronger preservation guarantees.

---

# 45. Deletion

Deletion requires semantic distinction.

Potential future operations:

### Hide

Remove from ordinary UI.

### Archive

Retain but make inactive.

### Supersede

Keep history but replace current semantic authority.

### Soft delete

Mark deleted while retaining recoverability.

### Hard delete

Physically remove data.

These must not be treated as interchangeable.

Privacy requirements may eventually require true hard deletion.

---

# 46. Invariants

The following are provisional domain invariants.

### INV-001
Persistent first-class objects have stable identities.

### INV-002
Renaming an object does not change its identity.

### INV-003
Branching does not destructively modify its source.

### INV-004
Merging does not destructively modify its sources.

### INV-005
A merge result records its source ancestry.

### INV-006
Derived state does not silently replace authoritative source history.

### INV-007
Important inferred knowledge can be distinguished from explicit user information.

### INV-008
Changing model runtime does not redefine conversation identity.

### INV-009
Changing client device does not redefine user/conversation identity.

### INV-010
Normal IP-address changes do not redefine trusted device identity.

### INV-011
Derivation ancestry must not contain cycles.

### INV-012
Privacy classification must be enforceable independently from model behavior.

### INV-013
A user correction can supersede an AI inference.

### INV-014
A source conversation may continue evolving after a derived merge without silently rewriting the historical merge.

### INV-015
Context sent to a model is a constructed view, not the canonical database itself.

---

# 47. Provisional Aggregate Boundaries

Initial conceptual aggregate areas:

```text
Identity
├── User
├── Device
└── Session

Conversation
├── Conversation
├── Message
├── Branch relationship
├── Merge
└── State version

Knowledge
├── Memory
├── Provenance
├── Conflict
└── Canonical State

Artifacts
├── Artifact
└── Source

AI Execution
├── Model
├── Runtime
├── Model Run
├── Agent
├── Tool
└── Tool Run

Organization
├── Workspace
└── future Project
```

These are conceptual boundaries, not necessarily microservices.

Anonymous should begin as a modular application, not a distributed-services cosplay exercise.

---

# 48. Current Open Questions

The following remain deliberately unresolved:

1. Is Branch a persistent entity or a derived relationship?
2. What exactly constitutes a Conversation State Version?
3. Are Messages immutable, versioned, or append-only with edit events?
4. What exactly does Merge synthesize?
5. Does a merged Conversation expose source messages directly or only derived context?
6. What is the final Memory taxonomy?
7. What confidence representation should inferred knowledge use?
8. How are conflicting memories resolved?
9. Are Workspace and Project distinct?
10. How granular should privacy classifications be?
11. Should Anonymous use event sourcing partially, fully, or not at all?
12. What portions of generated context should be persisted for reproducibility?
13. How much Model Run information should be retained?
14. When should derived data automatically regenerate?
15. What are the exact deletion semantics?

These questions should be answered by requirements and concrete user flows, rather than by choosing technologies prematurely.

---

# 49. Current Structural Conclusion

The conceptual system can currently be summarized as:

```text
User
 │
 ├── Devices / Sessions
 │
 ├── Workspaces
 │      │
 │      └── Conversations
 │             │
 │             ├── Messages
 │             ├── Branch relationships
 │             ├── Merge relationships
 │             └── State versions
 │
 ├── Memories
 │      │
 │      └── Provenance
 │
 └── Artifacts
        │
        └── Sources

Current request
      │
      ▼
Context Builder
      │
      ├── Conversation state
      ├── Relevant history
      ├── Relevant memory
      ├── Relevant artifacts
      └── Privacy policy
              │
              ▼
          Model Router
              │
              ▼
           Model Run
              │
       ┌──────┴──────┐
       │             │
    Message       Tool Runs
       │
       ▼
Persistent history / derived knowledge
```

---

# 50. Provisional Core Insight

Anonymous should not be designed around the idea:

> A conversation is an array of strings sent repeatedly to an LLM.

The more durable abstraction is:

> Anonymous maintains persistent structured state and provenance, constructs context for AI execution when needed, and presents portions of that state to the user as conversations.

This distinction should guide all later architecture.
