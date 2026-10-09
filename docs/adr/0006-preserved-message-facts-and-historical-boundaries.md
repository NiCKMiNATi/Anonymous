# ADR-0006 — Preserved committed message facts and fixed historical boundaries

**Status:** Accepted for V0 Logical Data Model & Persistence Semantics v0.1 by this design task. Physical representation remains open.  
**Date:** 2026-10-03.

## Context

DM §§9–10, 16, 43–46; RB DATA-01/02/03/06/08 and FR-15; V0-D01/D03/D04/D06; and ADR-0003/0004 require preserved history, actual input attribution, coherent saving and non-destructive future derivation. A conversation continues evolving after an operation uses it. A reference to its current contents cannot by itself identify the history that an earlier run, branch or merge used.

The logical-model task needs to establish the stable meaning of a historical boundary without choosing a snapshot, sequence, event foundation, identifier encoding or storage technology. User-visible editing, branching and merging remain outside V0.

## Alternatives considered

- Refer only to the current conversation. Later appends or edits would silently change historical source meaning.
- Treat timestamps or message identity as ordering/state boundaries by themselves. Equal or adjusted clocks and identity's separate purpose make that meaning insufficient; this also conflicts with FR-15.
- Require a complete copied snapshot or event-sourced history for every operation. Either could eventually implement the semantics, but neither is necessary to define them and both would prematurely choose representation.
- Retain only selected input-message references and call that the entire conversation state. These references identify contributions but do not distinguish selected context from the full historical conversation boundary.
- Preserve committed facts and separately define a fixed history boundary and an operation's actual contributions. This meets current source and execution requirements while leaving representations open.

## Decision

Once a message is committed to persistent history, its prior committed content is not silently mutated. V0 operations preserve its identity, authorship, established position, original absolute commit instant and required provenance. Future editing must retain explicit relationships to recoverable prior committed forms; shared logical identity versus separate revision/replacement identities is not selected.

A Historical State Boundary has fixed, referenceable history meaning. In V0 it resolves the exact committed conversation prefix and committed message forms/order used as an operation's history scope. Later messages do not enter that boundary. It need not be a separate first-class object or a copied snapshot.

Each prepared generation attempt separately retains selected input-message associations within its input boundary, including its triggering committed user message. Preparation alone is not proof of invocation; actual contributing-message evidence must distinguish what is known to have been supplied. The resulting assistant message is outside that input boundary. A boundary does not require full prompt retention or exact model replay.

This boundary covers conversation history, not all application state. It does not freeze current authorization or silently claim to snapshot titles/settings. Operations needing other changing state must identify that dependency explicitly in later design. A future multi-source derivation needs stable boundaries for its respective sources and acyclic ancestry.

## Consequences

Run provenance remains stable as the conversation grows. Retrying an eligible failed generation uses a new attempt while preserving its original user message; reconciliation of already committed history preserves the original facts. Generated saved responses remain historical evidence and cannot be restored merely by re-running inference.

The persistence solution must preserve and resolve the established relationships and historical forms through restart and later evolution. Detailed identity/order/boundary/versioning representation, event sourcing, Branch/Merge entity status, physical consistency and broader Conversation State Version scope remain open. This ADR does not add editing, branching, merging, Memory, or an export/backup product to V0.

## Affected documents

- [Logical data model](../05-data-model.md), sections 3–7, 11–13 and its final persistence requirements.
- [Task ExecPlan](../../.agent/plans/2026-10-03-v0-logical-data-model.md), decision log and validation.

The [Domain Model](../01-domain-model.md), [Requirements](../02-requirements.md), [V0 Scope](../03-v0-scope.md), [Architecture](../04-architecture.md), and accepted ADR-0001–ADR-0005 remain unchanged. Their open physical/future-feature questions are not globally closed by this bounded logical decision.
