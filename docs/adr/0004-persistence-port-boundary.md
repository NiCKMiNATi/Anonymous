# ADR-0004 — Application-owned persistence contracts

**Status:** Accepted for Architecture Baseline v0.1 by this architecture task.
**Date:** 2026-10-03.

## Context

PD §§5, 12, 17–19 and DM §§9, 33, 44–46 require preserved history, provenance, and observable failures. V0-D03/D04/D06 distinguish durable confirmation from uncertainty, require response/run attribution, and preserve confirmed records through process termination on intact storage.

## Decision

Application use cases depend on Anonymous-owned, purpose-specific persistence contracts for history, identity/access state, and execution/reconciliation evidence. Concrete adapters implement storage and report evidence sufficient to distinguish confirmed, failed, and unknown outcomes. Context Builder reads eligible source information through a read-only contract.

Domain/application rules own identity, authorization, admission, retention, and execution semantics. Adapters fulfill these requirements without dictating them. User input must be confirmed durable before inference; final response and producing-run association must be confirmed before completion-and-saving is reported. Clients and model runtimes have no direct store authority.

## Alternatives considered

- Concrete database calls throughout services couple domain operations to storage/query representations.
- A universal CRUD repository conceals the durability and reconciliation guarantees required by different operations.
- Model/client-owned persistence contradicts common ownership and recovery.
- Event sourcing might later be evaluated, but is not necessary to choose the ownership/dependency boundary.

## Consequences

Storage replacement is contained but still requires preservation and transition evidence; this ADR promises no effortless migration. Detailed consistency, atomicity, correlation, duplicate prevention, and interrupted-dispatch representation are mandatory before implementation. No table, transaction design, SQL/NoSQL choice, or SQLite commitment is made. Diagnostic logs cannot stand in for authoritative records.

Source history and generated historical responses remain preserved. Transient context can be discarded/reconstructed; that does not authorize deleting source records. Branch/version/event-sourcing and lifecycle representations remain open.

## Affected documents

[Architecture](../04-architecture.md) §§5–6, 8–12; [V0 scope](../03-v0-scope.md) V0-D03/D04/D06 and V0-AC-01/02/07/13; [requirements](../02-requirements.md) DATA-01–DATA-03, DATA-08, REC-01–REC-05.
