# ADR-0003 — Anonymous-owned context construction and model execution port

**Status:** Accepted for Architecture Baseline v0.1 by this architecture task.
**Date:** 2026-10-03.

## Context

PD §§4.3, 6.3, 10–11 and DM §§18–19, 31–33 distinguish persistent conversation, constructed context, model, runtime, and execution. INV-008/INV-012/INV-015 require runtime-independent identity and model-independent privacy. V0-D01 selects current-conversation context; V0-D03 requires actual contributing-message attribution.

## Decision

Make Context Builder an explicit server application responsibility. It constructs authorized current-conversation input using retained history, necessary instructions, and normalized runtime budget information. It preserves roles/order, reports omissions, and rejects a newest message that cannot fit without deleting saved history.

Execution depends on an Anonymous-owned model port fulfilled by a concrete local adapter. The adapter translates capabilities, input, output, and failures without leaking vendor types into domain/application concepts. It must execute the agreed input faithfully or fail visibly; silent truncation invalidating provenance is unacceptable.

Context Builder does not invoke the model, mutate sources, or decide release permission. It can later incorporate authorized canonical state, Memory, retrieval, or artifacts after those features are scoped/designed.

## Alternatives considered

- Provider-managed conversation/context makes continuity, privacy, and attribution dependent on a runtime.
- Direct vendor integration throughout application services spreads replacement work.
- A general model/agent plug-in framework adds capabilities and abstractions unnecessary for one V0 local path.

## Consequences

One live runtime integration plus a controlled substitution fixture can demonstrate the V0 replacement boundary. Model/runtime identities remain in historical run evidence after replacement. No external fallback or tools are authorized by this port. Runtime lifecycle/correlation, budget calculation, context selection, and real hardware feasibility require later design/benchmark evidence. The port is conceptual here; no method signatures, SDK, Ollama selection, or Memory algorithm is finalized.

## Affected documents

[Architecture](../04-architecture.md) §§5–10, 12; [V0 scope](../03-v0-scope.md) V0-D01–V0-D03 and V0-AC-08/09/11/13; [requirements](../02-requirements.md) FR-08, FR-12, NFR-02, PRIV-05, DATA-03, DATA-08, REC-03–REC-05.
