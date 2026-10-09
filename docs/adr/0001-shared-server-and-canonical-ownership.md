# ADR-0001 — Shared server boundary and canonical ownership

**Status:** Accepted for Architecture Baseline v0.1 by this architecture task.
**Date:** 2026-10-03.

## Context

PD §§4.4–4.5, 5, 9–12 and DM §§3–6, 8–9 require client-independent identity/history and server responsibility. V0 includes simultaneous Windows, Mac, and iPhone sessions, protected remote access, and reconnect without manual history transfer. Windows initially hosts both client and server.

## Decision

All clients use the same logical Anonymous application contract and authentication/authorization boundary. The server owns canonical persistent application state, including identity, conversation history, and minimal execution evidence. Clients own presentation and temporary interaction state. The co-hosted Windows client cannot bypass the application to reach storage or the runtime.

Canonical ownership means authority over saved records; it does not introduce the deferred generated canonical/compressed-state feature. The initial host can be replaced without redefining identities or ownership.

## Alternatives considered

- Client-owned histories with export/import cannot satisfy seamless shared continuity.
- Peer synchronization introduces disconnected-write and conflict semantics excluded from V0.
- A direct local model/database path would create a second policy and persistence boundary.
- Shared server authority meets current needs without committing to a concrete transport or client framework.

## Consequences

Client data loss does not erase saved server history. Remote clients require server reachability; disconnected editing is not promised. The server is a single availability boundary. Host replacement still needs later deployment/data-transition design. All supported clients need explicit approval and a valid authorized session, including Windows.

## Affected documents

[Architecture](../04-architecture.md) §§3–5, 7–11; [V0 scope](../03-v0-scope.md) V0-D03–V0-D06 and V0-AC-01–V0-AC-05; [requirements](../02-requirements.md) FR-01–FR-03, FR-14, NFR-03–NFR-05, DATA-01–DATA-03. These source documents are not changed by this ADR.
