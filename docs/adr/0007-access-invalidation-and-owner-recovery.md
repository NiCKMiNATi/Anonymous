# ADR-0007 — Access invalidation and controlled owner recovery

**Status:** Accepted logical policy for V0 Security Design & Threat Model v0.1. Proof, credential, storage and transport mechanisms remain open.  
**Date:** 2026-10-03.

## Context

V0-D05 and ADR-0005 require controlled provisioning, finite sessions, explicit device restoration and effective revocation before acknowledgment. LM CB-07 rejects permission inferred from historic activity. Three ambiguities need durable resolution: whether restoring trust revives old sessions; whether missing access state permits first-owner setup; and whether replaying approval can override later revocation.

## Alternatives considered

- Reuse old sessions after device reapproval. Stolen invalidated material could regain authority without fresh authentication.
- Treat missing access records as a fresh installation. Storage/read/configuration failure could permit ownership takeover.
- Reapply old approval requests as new changes. Retransmission could undo a subsequent owner decision.
- Erase all device trust/ownership at every restart. This unnecessarily redefines persistent identity; conservative session invalidation does not require it.
- Preserve identity/history while making session invalidation final and requiring controlled current owner intent for new authority. This retains continuity without resurrecting old permissions.

## Decision

A session invalidated by logout, expiry or device revocation cannot become valid again. Reauthentication establishes fresh session authority; device restoration does not revive old invalidated session material. The device may retain its stable identity.

First-owner provisioning requires positive establishment of an intended new dataset and controlled owner proof. Failed/ambiguous access-state reads or missing existing-dataset state do not open enrollment. Coherent first-owner establishment closes ordinary registration; replay/lost acknowledgment reconcile that operation.

Trust management binds explicit owner intent to current target state. Old approval/restoration replay cannot undo later revocation. All-devices-lost recovery requires a separately verified owner ceremony and preserves user/conversation identities and history. Replacement of compromised authenticators invalidates dependent old authority; exact scope/proof needs detailed design.

Admission and delivery coordinate with invalidation under ADR-0005. Earlier receipt without admission confers no authority. Already admitted coherent work may finish privately; delivery still needs current permission. No invalidation success is acknowledged until durable state and enforcement agree. Previously released transport bytes cannot be recalled; application buffering cannot bypass the boundary.

## Consequences

Tests cover provisioning races, missing state, old approval after revocation and restored devices carrying invalid sessions. Clients distinguish lost confirmation from known failure and reauthenticate without duplicating messages. Access changes preserve content, provenance, order and original commit instants.

Proof custody, validity/renewal, restart/clocks, management correlation and durable admission/delivery mechanisms require decisions before access-capable implementation. No automatic bootstrap, localhost-client bypass or stale allow-cache fallback is permitted. Host administration remains trusted operational authority, not a Windows client privilege.

No authentication technology, hardware attestation, database representation or public registration is selected. Protection from a fully compromised host is not claimed. Recovery usability/credentials remain explicit gates, not implemented capabilities.

## Affected documents

- [Security design](../07-security.md), sections 5–8 and 14–16.
- [Security ExecPlan](../../.agent/plans/2026-10-03-v0-security-design.md).

[V0 scope](../03-v0-scope.md), [Architecture](../04-architecture.md), [Logical data model](../05-data-model.md), [ADR-0005](0005-layered-private-access.md) and [ADR-0006](0006-preserved-message-facts-and-historical-boundaries.md) remain unchanged. Their logical access outcomes are refined without globally closing mechanism questions.
