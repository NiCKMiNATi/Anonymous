# ADR-0005 — Layered private access with server-enforced authority

**Status:** Accepted for Architecture Baseline v0.1 by this architecture task.
**Date:** 2026-10-03.

## Context

PD §§4.2, 7–8 and DM §§4–6, 38–39 distinguish private reachability, device identity, sessions, and privacy boundaries. V0-D02 permits only private application paths. V0-D05 requires owner-controlled device approval, finite sessions, logout, and effective revocation during ongoing delivery.

## Decision

Separate protected private network reachability from Anonymous device approval, session authentication, operation/resource authorization, and current response-delivery permission. All clients, including co-hosted Windows, pass these checks. The access responsibility owns trust/session lifecycle; transport and application entry points enforce its decisions.

Revocation is acknowledged only once authoritative state and subsequent operation/delivery gates enforce it across the device's sessions. In-flight execution may finish privately but cannot continue protected delivery to the revoked client. Unknown authority fails closed. Owner bootstrap/recovery is controlled rather than open registration.

No V0 core service requires direct public Internet exposure. The runtime and store remain server-private. PRIVATE content cannot leave through cloud/tools, arbitrary model destinations, telemetry, or unsafe rendering of generated content. Privacy is enforced by application/deployment boundaries, not a model instruction.

## Alternatives considered

- LAN/overlay membership alone does not authenticate the application interaction or constrain resources.
- Ordinary IP allowlists fail roaming/address-reuse requirements.
- A localhost bypass violates equal clients and creates a second security model.
- A public application endpoint adds exposure unnecessary to the selected private-access scope.

## Consequences

Multiple sessions can coexist without conflating user/device/session identities. Revocation needs coordination between access state and output delivery, not merely a login-time check. Already delivered data cannot be recalled. Exact credential storage, bootstrap/recovery, session parameters, transport protection, browser protections, delivery races, and network metadata trust require security design before access-capable use. No Tailscale or authentication technology is selected. Existing provisioned local access cannot require cloud availability.

## Affected documents

[Architecture](../04-architecture.md) §§3–9, 12; [V0 scope](../03-v0-scope.md) V0-D02/V0-D05 and V0-AC-04/05/09/10/12/14; [requirements](../02-requirements.md) SEC-01–SEC-06, SEC-08, PRIV-01, PRIV-03–PRIV-05.
