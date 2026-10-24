"""Termination evidence and handoff vocabulary (LD-04 §1.3, §4).

Pure rules, no I/O. The SQLite adapter enforces the same table in a trigger; a test enumerates
every combination to keep the two in agreement.

Only positive evidence that execution *and any delayed invocation* cannot continue releases a
run. Timeouts, labels, stop acknowledgments, restarts, snapshots and human statements never do.
"""

from __future__ import annotations

from enum import StrEnum


class EvidenceBasis(StrEnum):
    NEVER_DISPATCHED = "never_dispatched"  # B1
    ADAPTER_NEVER_REACHED = "adapter_never_reached"  # B2
    RUNTIME_REPORTED_TERMINAL = "runtime_reported_terminal"  # B3
    PROCESS_EXIT_VERIFIED = "process_exit_verified"  # B4
    EXECUTION_TERMINATED_VERIFIED = "execution_terminated_verified"  # B5


class RecordEpoch(StrEnum):
    LEGACY_0A = "legacy_0a"  # existed when the 0B schema was applied
    CURRENT = "0b"


class Handoff(StrEnum):
    NONE = "NONE"  # authorized (T3) but start has never been, and can never be, called while open
    STARTED = "STARTED"  # T3b committed: start may have been called


class HandoffOutcome(StrEnum):
    NOT_CALLED = "NOT_CALLED"
    NOT_STARTED = "NOT_STARTED"
    ACCEPTED = "ACCEPTED"
    UNKNOWN = "UNKNOWN"


class ClosureReason(StrEnum):
    DEADLINE = "deadline"
    SHUTDOWN = "shutdown"
    PUBLICATION_UNCONFIRMED = "publication_unconfirmed"
    CONNECTION_LOST = "connection_lost"
    RUNTIME_FAILURE = "runtime_failure"
    INSTANCE_MISMATCH = "instance_mismatch"
    SUPERVISOR_FAULT = "supervisor_fault"
    ORPHAN_RECONCILE = "orphan_reconcile"


class CompletionObserved(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class LifetimeScope(StrEnum):
    OWNING_PROCESS = "owning_process"  # the runtime exists only inside the owning process
    EXTERNAL = "external"


class RunKind(StrEnum):
    INITIAL = "initial"
    RETRY = "retry"


# Bases that assert something about the runtime's own execution (B3-B5). B1 and B2 are facts of
# Anonymous's own durable handoff record.
RUNTIME_ASSERTING_BASES = frozenset(
    {
        EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
        EvidenceBasis.PROCESS_EXIT_VERIFIED,
        EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
    }
)


def basis_permitted_for_binding(
    basis: EvidenceBasis, *, scope: LifetimeScope, declared: frozenset[EvidenceBasis]
) -> bool:
    """An ``EXTERNAL`` binding may rely on a runtime-asserting basis only if its adapter declared
    it (ADR-0015). Owning-process bindings are unchanged (design §4.8); B1/B2 need no declaration.
    Pure; enforced both by the settler and inside the store's settlement transaction."""
    return not (
        scope is LifetimeScope.EXTERNAL
        and basis in RUNTIME_ASSERTING_BASES
        and basis not in declared
    )


def admissible_bases(
    *,
    epoch: RecordEpoch,
    handoff: Handoff | None,
    outcome: HandoffOutcome | None,
    late_delivery_excluded: bool,
) -> frozenset[EvidenceBasis]:
    """Bases that may settle an ``in_flight`` or ``indeterminate`` run, given the durable
    handoff state. Empty means: no settlement is possible (quarantine persists)."""
    if epoch is RecordEpoch.LEGACY_0A or handoff is None:
        return frozenset()  # binding-less runs have no admissible basis in 0B-1
    if handoff is Handoff.NONE:
        return frozenset({EvidenceBasis.NEVER_DISPATCHED})
    if outcome is HandoffOutcome.NOT_CALLED:
        return frozenset({EvidenceBasis.NEVER_DISPATCHED})
    if outcome is HandoffOutcome.NOT_STARTED:
        return frozenset({EvidenceBasis.ADAPTER_NEVER_REACHED})
    bases = {
        EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
        EvidenceBasis.PROCESS_EXIT_VERIFIED,
    }
    if outcome is HandoffOutcome.ACCEPTED or late_delivery_excluded:
        bases.add(EvidenceBasis.EXECUTION_TERMINATED_VERIFIED)
    return frozenset(bases)
