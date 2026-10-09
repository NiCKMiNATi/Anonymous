# ADR-0011: V0 access coordinator and protected delivery

**Status:** Accepted protocol design; persistence/transport bindings and runtime evidence pending.  
**Date:** 2026-10-04.

## Context

ADR-0005/0007 and SG-05/06 require effective durable invalidation before acknowledgment, coherent admission, and ongoing authorization for delivery. Closing a socket or checking at stream creation cannot establish this. The modular server is the sole authority, while the runtime may survive its restart.

## Alternatives

Self-contained authorization tokens, independently cached allow decisions, per-worker flags and check-then-queue output cannot ensure timely device-wide invalidation. Holding a global lock across inference or slow network I/O would let stalled work block revocation. Distributed authority/consensus would add unneeded V0 complexity.

## Decision

Use one C03 access coordinator in the authoritative server process. Serialize current-policy decisions, admission transitions, invalidation and bounded protected release. C02/C04/C05 cannot bypass it. C08 provides durable compare-and-apply outcomes; uncertain access state denies. An exclusive authoritative-instance lock is held for the process lifetime; second instances fail closed. Advance the durable session boot generation before protected readiness after restart.

Revocation first closes affected admission/release, durably records invalidation, quiesces/discards application-side pending output and acknowledges only after enforcement. Lost acknowledgments reconcile the same operation under current authority. Persistence/enforcement failure retains denial and reports uncertainty, never success.

Authorize every bounded release at the irreversible application-to-controlled-TLS-transport handoff, in the same coordination order as invalidation. The handoff must be nonblocking; a full buffer defers output for later reauthorization or ends delivery under finite limits. No stale framework worker may send after the barrier. Already handed-off bytes may arrive after acknowledgment and cannot be recalled. Exact adapter buffering boundaries must be demonstrated, not inferred from client receipt times.

Already admitted coherent work can finish/save privately. Device/session invalidation cannot manufacture runtime termination, release an unresolved conversation busy gate or trigger duplicate inference. Current permission is required for any subsequent status/result/reconciliation. Source/history facts remain unchanged.

Select server-private runtime binding plus caller authentication: either runtime-native authentication or OS-authenticated, caller-restricted local transport. Loopback alone is insufficient against other local accounts. The actual runtime-specific mechanism remains blocked on evidence; a proxy that leaves a reachable unauthenticated backend is not sufficient. Runtime runs under a separate restricted principal with no private egress or ambient source/secret access; actual containment/supervision must be verified before private invocation.

## Consequences

This gives the later backend/API work a concrete concurrency protocol while preserving C02/C03/C05/C08 ownership. It imposes verifiable storage, exclusive-instance and transport-adapter requirements without selecting a database, framework or synchronization API. Revocation latency/capacity must be tested under load. Runtime compatibility with restricted execution and GPU access may eliminate otherwise fast candidates; no runtime is chosen here.

## Affected documents

The [evaluation sections 9–10 and 12–15](../evaluations/v0-access-security-mechanisms.md) supply the sequence, exposure/decision matrices and tests. This resolves protocol portions of SD-04/08 and refines [architecture](../04-architecture.md), [logical CB-07](../05-data-model.md) and [security SG-05/06/09](../07-security.md). ADRs 0001–0007 remain in force; no live concurrency or security result is claimed.
