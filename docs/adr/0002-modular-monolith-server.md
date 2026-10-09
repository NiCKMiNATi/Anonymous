# ADR-0002 — One modular-monolith server application for V0

**Status:** Accepted for Architecture Baseline v0.1 by this architecture task.
**Date:** 2026-10-03.

## Context

PD §§10, 16–17 favors maintainability on existing equipment. DM §47's provisional aggregates are conceptual boundaries, not service mandates. V0-D04 requires one active generation per conversation, duplicate reconciliation, and multiple client sessions with shared authoritative outcomes.

## Decision

Use one active authoritative server application instance for V0, structured as cohesive internal responsibilities: transport, access, conversation management, execution coordination, context construction, domain rules, and infrastructure adapters. Composition/lifecycle wiring remains separate from business rules.

The execution coordinator owns admission and recovery and supervises model work independently of client connections. Conversation management may invoke execution; execution does not call back into conversation management. The local model runtime is a separate private process boundary on the initial Windows host, not a separate application-history service.

## Alternatives considered

- Microservices require distributed coordination, more deployment units, and broader failure handling without a V0 product need.
- An undifferentiated monolith makes privacy, execution, and replaceability harder to inspect.
- Multiple active server instances require shared admission/recovery coordination not justified by V0.
- Embedding model execution directly in the application process entangles its lifecycle and vendor dependencies; the separate runtime keeps an explicit replacement/failure boundary.

## Consequences

Internal modules can share deployment and a backing store while respecting owned contracts. Long inference must not prevent supported reads/access enforcement. Single-instance enforcement and bounded supervision remain detailed design gates. A runtime may survive server termination: recovery must reconcile or stop prior execution before permitting conflicting generation. Single-server availability is accepted; high availability is not claimed. Future scaling requires a new decision and preservation evidence, not merely extra processes.

## Affected documents

[Architecture](../04-architecture.md) §§4–6, 8–9; [V0 scope](../03-v0-scope.md) V0-D04/V0-D06 and V0-AC-02/07/15; [requirements](../02-requirements.md) NFR-04, NFR-06, NFR-07, REC-01–REC-04. No language, framework, worker product, or storage engine is finalized.
