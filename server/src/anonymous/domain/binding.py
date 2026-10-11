"""The durable description of the runtime instance an attempt was dispatched to (LD-04 §6.2).

Opaque to the domain: it is stored, compared for equality and passed back to the control path.
It never contains paths, secrets or content.
"""

from __future__ import annotations

from dataclasses import dataclass

from anonymous.domain.evidence import EvidenceBasis, LifetimeScope


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    format: str  # namespaced, versioned payload layout; selects the control handler
    adapter_id: str
    adapter_version: str
    instance_ref: str  # one runtime-instance lifetime; never reused
    lifetime_scope: LifetimeScope
    declared_bases: frozenset[EvidenceBasis]
    late_delivery_excluded: bool
    model_label: str  # descriptive; recorded as model_id
    runtime_label: str  # descriptive; recorded as runtime_id
    control_ref: str | None = None
