# Anonymous — Project Definition

**Status:** Draft v0.1  
**Project type:** Local-first personal AI system and conversation workspace  
**Primary user:** Single-user system initially  
**Development approach:** Iterative, architecture-first, privacy-first

---

## 1. Vision

Anonymous is a **local-first personal AI system** that provides a persistent, private, evolving workspace for conversations, knowledge, memory, files, tools, and future AI capabilities.

It is not merely a chat interface around a local language model.

Anonymous should provide a stable personal AI layer that can survive changes in:

- AI models
- model providers
- computers
- databases
- client devices
- operating systems
- storage systems
- network environments

The user's accumulated history, knowledge, structure, and workflows should belong to the user rather than to any single model or vendor.

---

# 2. Core Problem

Normal AI chat systems largely treat conversations as isolated or semi-isolated streams.

As the number and length of conversations increases, several problems appear:

- relevant information becomes difficult to recover;
- context windows cannot contain the user's entire history;
- branching discussions become difficult to manage;
- unrelated conversations cannot easily be combined;
- summaries may lose provenance;
- model-generated assumptions can become confused with explicit user facts;
- changing models may disrupt continuity;
- local/private information can become mixed with cloud or web services;
- conversations become dependent on the application that created them.

Anonymous is intended to solve these problems by treating AI conversations as **persistent structured data**, rather than disposable chat transcripts.

---

# 3. Fundamental Principle

The AI model is **not Anonymous**.

A model is a replaceable computational component used by Anonymous.

Conceptually:

User  
↓  
Anonymous  
↓  
Model Router  
↓  
Local Model / Future Model / Optional Cloud Model

Changing the model should not destroy or redefine the user's Anonymous environment.

---

# 4. Core Architectural Principles

## 4.1 Local-first

Anonymous should operate locally wherever reasonably possible.

Core personal data should remain under the user's control.

Cloud services may be supported, but they must not be assumed to be permanently available or trusted with all information.

---

## 4.2 User-controlled external access

Sending information outside the private Anonymous environment must be deliberate.

Anonymous must distinguish between at least:

- **PRIVATE context**
- **externally accessible / WEB context**

Private information must not silently cross this boundary.

---

## 4.3 Model independence

Conversation history, memory, files, identities, and project state must not depend on one particular LLM.

Anonymous should be able to replace:

- Ollama
- a specific local model
- a remote API
- an inference server

without redesigning the client applications or losing user data.

---

## 4.4 Client/server separation

User interfaces are clients of Anonymous.

Clients must not directly own the core intelligence, memory, or canonical data.

Initial expected clients include:

- Windows desktop
- MacBook
- iPhone

Initially, the Windows desktop may simultaneously host the Anonymous server and run a Anonymous client.

Its dual role must not make Windows architecturally special.

---

## 4.5 Hardware independence

The first server is expected to run on the existing Windows desktop.

This is an implementation circumstance, not a permanent architectural requirement.

Future migration to:

- another desktop,
- dedicated AI server,
- NAS-related infrastructure,
- additional compute nodes,
- or some combination

must not require redesigning the entire Anonymous system.

---

# 5. Conversation Principles

## 5.1 Conversations are persistent objects

A conversation is more than rendered chat text.

It has identity, state, relationships, metadata, history, and provenance.

---

## 5.2 Raw history is preserved

Original conversation content should not be destructively rewritten merely because Anonymous creates:

- summaries,
- branches,
- merges,
- compressed state,
- memories,
- embeddings,
- alternate representations.

Derived representations may change.

Source history remains recoverable.

---

## 5.3 Branching is non-destructive

Creating a branch does not overwrite the source conversation.

Conceptually:

A  
├── B  
└── C

A remains valid.

B and C record their relationship to A.

---

## 5.4 Merging is non-destructive

If conversations A and B are merged into C:

A + B → C

then:

- A survives;
- B survives;
- C is a new derived conversation/state;
- C records its sources;
- creating C must not silently rewrite A or B.

This applies even when A and B originated from unrelated conversation trees.

---

## 5.5 Derived state must know where it came from

Whenever Anonymous creates information from other information, provenance should be retained where practical.

Examples:

- summary derived from messages;
- memory extracted from a conversation;
- merge generated from conversations A and B;
- conclusion derived from a document;
- inference created by an AI model.

Anonymous should be able to distinguish:

> The user explicitly stated this.

from:

> A model inferred this.

Those are not equivalent.

---

# 6. Memory Principles

Anonymous memory is not simply “old chat messages inserted into the prompt.”

Memory should be treated as its own subsystem.

Potential memory categories may eventually include:

- explicit user facts;
- preferences;
- project decisions;
- temporary state;
- inferred information;
- summaries;
- entities;
- relationships;
- procedures;
- task-specific state.

The final taxonomy remains to be designed.

---

## 6.1 Provenance

A memory should be capable of referencing its origin.

Examples:

- conversation ID;
- message ID;
- uploaded file;
- external source;
- manual user entry;
- system-generated inference.

---

## 6.2 Confidence

Information inferred by AI may carry uncertainty.

Anonymous should support representing confidence or epistemic status rather than treating every stored statement as equally certain.

Possible states may eventually include:

- explicit;
- verified;
- inferred;
- uncertain;
- conflicting;
- outdated;
- superseded.

The exact model remains open.

---

## 6.3 Canonical state versus source history

Anonymous may maintain a compact representation of currently relevant state.

This **canonical state** exists to make current AI interaction practical.

It does not replace raw history.

Conceptually:

Raw History  
↓  
Extraction / Summarization  
↓  
Canonical State  
↓  
Current Context

When more detail is required:

Raw History / Files / Memories  
↓  
Retrieval  
↓  
Current Context

This allows Anonymous to operate even when lifetime history exceeds an LLM's context window.

---

# 7. Privacy Model

Anonymous must assume that some information should remain private even while other tasks use external resources.

Therefore private data and web/cloud activity must not automatically share a common context pool.

Conceptually:

PRIVATE WORLD

- personal conversations
- private memories
- local files
- sensitive project information
- other explicitly private material

and:

EXTERNAL / WEB WORLD

- public web search
- external APIs
- cloud models
- other network services

A controlled bridge may exist between the two.

The bridge must be intentional.

Anonymous should never assume:

> The user allowed web access, therefore all private context may be sent to external services.

---

# 8. Security Principles

Security should use multiple independent layers.

Initial conceptual model:

Device  
↓  
Encrypted private network  
↓  
Device trust / approval  
↓  
Network authorization  
↓  
Anonymous authentication  
↓  
Anonymous authorization  
↓  
Requested capability

No single layer should be assumed to provide complete protection.

---

## 8.1 Device identity over ordinary IP identity

Trusted access should primarily be associated with authenticated devices or users rather than ordinary public/local IP addresses.

Normal IP addresses may change due to:

- Wi-Fi networks;
- mobile networks;
- Pocket Wi-Fi;
- carrier NAT;
- travel;
- DHCP.

Changing network location must not redefine device trust.

---

## 8.2 No unnecessary public exposure

Anonymous services should not require direct public Internet exposure.

Initial architecture should avoid exposing services such as:

- Anonymous API;
- Ollama;
- database;
- administration interfaces

through public router port forwarding.

---

## 8.3 Untrusted local networks

Networks such as shared accommodation Wi-Fi should not automatically be considered trusted simply because the server is physically connected to them.

Anonymous must be designed with hostile or unknown LAN peers in mind.

---

# 9. Client Principles

Clients present Anonymous to the user.

They should contain presentation logic and client-side interaction state, but should avoid owning canonical Anonymous data.

Expected initial client targets:

### Windows

Full desktop/web client.

The same machine may initially host the server.

### macOS

Full client used for development and everyday interaction.

### iPhone

Mobile interface initially optimized around essential interaction rather than complete administrative functionality.

Future native applications remain optional.

A browser-based responsive client may be sufficient initially.

---

# 10. Server Responsibilities

The Anonymous server is expected eventually to coordinate:

- API access;
- authentication;
- authorization;
- conversations;
- messages;
- branching;
- merging;
- memory;
- retrieval;
- files;
- model routing;
- context construction;
- tool execution;
- provenance;
- persistence;
- background processing;
- auditability.

Not all responsibilities need to exist in V0.

The architecture should nevertheless avoid making later separation unnecessarily difficult.

---

# 11. Model Runtime Principle

Anonymous should interact with AI models through an internal abstraction.

Conceptually:

Anonymous Model Interface  
├── Local Ollama model  
├── Future local runtime  
├── Mac-hosted model  
├── Dedicated GPU server  
└── Optional cloud API

The rest of Anonymous should not need to know the implementation details of each runtime.

---

# 12. Persistence Principle

Anonymous should define its domain and persistence interfaces before becoming tightly coupled to a database product.

SQLite is a strong candidate for V0 because of its simplicity and suitability for a single-user server.

It is not a permanent architectural dependency.

Future alternatives may include:

- PostgreSQL;
- MongoDB;
- specialized search/vector systems;
- combinations of multiple storage technologies.

Database choice must follow domain requirements rather than define them.

---

# 13. Technology Direction

Current provisional technology direction:

### Client

- TypeScript
- React ecosystem
- responsive web application initially

### Server

- Python
- FastAPI as leading API framework

### AI runtime

- local inference first;
- Ollama as leading initial candidate;
- benchmark before permanent commitment.

### Networking

- private encrypted overlay network;
- Tailscale as leading initial solution.

### Persistence

- repository/data-access abstraction;
- SQLite likely for V0.

These are technical decisions, not project identity.

They may be replaced when evidence justifies doing so.

---

# 14. V0 Philosophy

V0 should prove the architecture with the smallest useful end-to-end system.

The target is not:

> Build a miniature AGI operating system.

The target is:

User opens Anonymous  
↓  
client reaches server securely  
↓  
user sends message  
↓  
server builds request  
↓  
local model responds  
↓  
conversation is persisted  
↓  
user can reconnect later  
↓  
conversation remains usable

If this works reliably across the intended devices, Anonymous has a foundation.

---

# 15. Explicitly Deferred Capabilities

The following should not automatically become V0 requirements:

- autonomous agents;
- voice assistant;
- animated avatar;
- unrestricted computer control;
- complex multi-agent systems;
- smart-home automation;
- elaborate graph visualization;
- multi-user support;
- distributed model execution;
- cloud synchronization;
- native mobile applications;
- marketplace/plugin ecosystem;
- automatic business processes;
- advanced self-modification.

These may be designed for architectural compatibility without being implemented early.

---

# 16. Project Constraints

Initial development must respect several practical constraints.

## Hardware

The existing desktop is the initial compute server.

The design should not depend on purchasing substantial new hardware in the near term.

## Development

The system should remain understandable by one primary developer.

Complexity must earn its existence.

## Cost

Prefer local and open technologies where practical.

Recurring infrastructure cost should not become a prerequisite for basic Anonymous functionality.

## Maintainability

A sophisticated feature that makes the entire project impossible to maintain alone is not automatically an improvement.

---

# 17. Design Rule: Separate Concept from Implementation

Throughout the project, Anonymous should distinguish between:

- **what the system means**, and
- **how the current version implements it**.

Example:

Concept:

> A conversation has persistent identity.

Implementation:

> Conversation identity is currently stored as a UUID in SQLite.

The first is part of Anonymous.

The second may change.

This distinction should apply to:

- storage;
- networking;
- models;
- clients;
- authentication;
- search;
- embeddings;
- deployment.

---

# 18. Design Rule: Derived Data Must Be Rebuildable Where Possible

Data generated from authoritative source data should preferably be reproducible.

Examples include:

- embeddings;
- search indexes;
- summaries;
- cached model output;
- compressed context;
- derived graph information.

Where practical, losing derived data should not mean losing the underlying user history.

---

# 19. Design Rule: Failure Must Be Observable

Anonymous should not silently hide important failures.

Future implementations should expose enough information to understand failures involving:

- model runtime;
- context construction;
- memory retrieval;
- database;
- network;
- tools;
- authentication;
- synchronization;
- external services.

Logging and traceability are part of maintainability, not post-launch decorations.

---

# 20. Design Rule: User Overrides AI

Anonymous may infer, summarize, organize, and suggest.

It must not treat its own derived interpretation as more authoritative than explicit user correction.

When the user corrects a stored inference, the system should be capable of representing that correction clearly.

---

# 21. Project Success

Anonymous succeeds if it becomes a dependable personal computing layer in which:

- conversations retain continuity;
- knowledge remains recoverable;
- AI models can be replaced;
- private information remains under user control;
- multiple devices can securely access the same personal AI environment;
- conversations can branch and merge without destroying history;
- memory remains traceable;
- the architecture can evolve without repeated total rewrites.

The goal is not merely to possess a local chatbot.

The goal is to create a durable personal AI system whose accumulated value increases over time.