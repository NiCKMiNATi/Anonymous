# ADR-0012: V0 local primary storage and controlled authority transfer

**Status:** Accepted bounded V0 operational decision; physical persistence and enforcement mechanisms remain open.  
**Date:** 2026-10-04.

## Context

Anonymous owns canonical state on one authoritative server. ADR-0011 requires lifetime-held exclusive application authority, but a local lock cannot exclude an independently copied dataset running on another host. V0 guarantees normal/abrupt process restart with intact storage, not backup restore, distributed failover or disaster recovery. Deployment needs an explicit answer about network-mounted primary storage and activating copied state without choosing a database.

## Alternatives

- Permit arbitrary local, network-mounted or cloud-synchronized primary paths. This introduces unverified locking, durability, disconnect, replication and privacy behavior unrelated to the minimal one-host requirement.
- Treat copied dataset identity or a local process lock as global exclusivity. Independent copies cannot communicate an exclusion decision solely through separate local state; this would create a false guarantee.
- Introduce distributed coordination/fencing or automatic failover. It adds infrastructure and availability dependencies outside current V0 requirements.
- Restrict primary state to protected server-local storage and require explicit controlled authority transfer before any copied/restored state is activated. This fits the bounded deployment and makes the residual operational assumption explicit.

## Decision

V0 production authoritative primary storage must reside on an eligible protected server-local filesystem. Network-mounted SMB/NFS/NAS primary storage and cloud-synchronized or redirected primary folders are unsupported in V0. This does not choose a database, filesystem product, volume, directory layout or drive letter. Later reconsideration requires evidence and an explicit decision.

The authoritative application establishes exclusive ownership of the intended dataset before writes, boot-generation changes, recovery dispositions or protected admission. The future persistence/OS mechanism must account for aliases, simultaneous startup, process lifetime, crashes and loss of trustworthy ownership. An ambiguous/stale marker or missing state cannot be discarded to admit another writer. Failure closes affected protected operation and is observable without exposing private identifiers.

Copies/restores do not automatically become authoritative, and V0 has no automatic failover. Before a separately scoped migration/restore can activate a replacement, trusted operation must establish that the original writer is stopped and prevented from resuming. If its status is unknown, the replacement remains inactive. Restore also needs separately designed anti-rollback handling for device/recovery authority and runtime/publication uncertainty; a fresh session boot generation alone does not solve these.

Maintain a protected operational record of the active deployment, separate from public documentation. Do not encode the host/path in domain identity. Relocation preserves source history, provenance, order and commit instants and must never interpret inaccessible storage as an empty new dataset.

## Consequences

The initial deployment has a smaller, testable persistence/failure surface without new distributed infrastructure. Network primary storage, parallel clones and unattended failover are not supported conveniences. Exact locking/durability and authority-transfer procedures remain future design/evidence work.

A local lock can prevent competing access to the same underlying local dataset only when its implementation is proven; it cannot enforce global exclusion across independent offline copies. The no-parallel-activation operating rule relies on trusted administration, consistent with the existing host-administrator threat boundary. No protection against a malicious privileged operator cloning an entire host is claimed.

This decision does not add a backup/export feature or promise recovery from lost/damaged storage. Existing independent key custody is necessary but cannot reconstruct absent source history. Unavailable/full/locked storage fails safely without fallback stores or source pruning.

## Affected documents

- [Access Environment & Security Operations Baseline](../evidence/v0-access-environment-baseline.md), sections 7–8 and the evidence matrix.
- [Environment ExecPlan](../../.agent/plans/2026-10-04-v0-access-environment-baseline.md).

[ADR-0011](0011-v0-access-coordinator-and-delivery.md), [Architecture](../04-architecture.md), [Logical Model](../05-data-model.md) and the [mechanism evaluation](../evaluations/v0-access-security-mechanisms.md) retain their existing semantics. This narrows the supported V0 deployment envelope without changing canonical ownership, selecting persistence technology, configuring storage or implementing a lock.
