"""Helpers that drive the store's conditional writes directly (below the coordinator)."""

from __future__ import annotations

from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import baseline_manifest
from anonymous.application.ports.persistence import DispatchRecord, Transition, WriteResult
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import EvidenceBasis, HandoffOutcome, LifetimeScope
from anonymous.domain.ids import RunId
from anonymous.domain.models import ModelRun
from anonymous.domain.provenance import ComponentIdentity, ExecutionProvenance, Verification

DEFAULT_DIGEST = baseline_manifest().digest
BOOT = "boot-test"


def binding(
    *,
    instance: str = "instance-1",
    scope: LifetimeScope = LifetimeScope.OWNING_PROCESS,
    late_excluded: bool = True,
    model: str = "m",
    runtime: str = "r",
) -> ExecutionBinding:
    return ExecutionBinding(
        format="scripted/1" if scope is LifetimeScope.OWNING_PROCESS else "scripted-external/1",
        adapter_id="scripted-runtime",
        adapter_version="1",
        instance_ref=instance,
        lifetime_scope=scope,
        declared_bases=frozenset(
            {
                EvidenceBasis.RUNTIME_REPORTED_TERMINAL,
                EvidenceBasis.PROCESS_EXIT_VERIFIED,
                EvidenceBasis.EXECUTION_TERMINATED_VERIFIED,
            }
        ),
        late_delivery_excluded=late_excluded,
        model_label=model,
        runtime_label=runtime,
    )


def provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        application_build=ComponentIdentity.label_only("test-build"),
        adapter=ComponentIdentity.label_only("test-adapter"),
        model_artifact=ComponentIdentity.label_only("m"),
        runtime_build=ComponentIdentity.label_only("r"),
        context_configuration=ComponentIdentity(
            label="whole-history@1", digest="sha256:" + "0" * 64, verification=Verification.VERIFIED
        ),
        behavior_configuration=ComponentIdentity.none(),
    )


def record(
    *,
    slot: str = "slot-1",
    boot: str = BOOT,
    digest: str = DEFAULT_DIGEST,
    **binding_kwargs: object,
) -> DispatchRecord:
    return DispatchRecord(
        binding=binding(**binding_kwargs),  # type: ignore[arg-type]
        provenance=provenance(),
        configuration_digest=digest,
        slot_id=slot,
        boot_id=boot,
    )


def authorize(store: SqliteStore, run_id: RunId, **kwargs: object) -> ModelRun:
    transition = store.authorize_dispatch(run_id, record(**kwargs))  # type: ignore[arg-type]
    assert transition.result is WriteResult.APPLIED, transition.result
    return transition.run


def dispatch(
    store: SqliteStore,
    run_id: RunId,
    *,
    outcome: HandoffOutcome | None = HandoffOutcome.ACCEPTED,
    **kwargs: object,
) -> ModelRun:
    """T3 + T3b (+ T3c): the run is in flight with a started handoff, as ``record_dispatch`` was."""
    boot = str(kwargs.get("boot", BOOT))
    authorize(store, run_id, **kwargs)
    started = store.mark_handoff_started(run_id, boot)
    assert started.result is WriteResult.APPLIED, started.result
    if outcome is not None:
        recorded: Transition = store.record_handoff_outcome(run_id, outcome)
        assert recorded.result is WriteResult.APPLIED
    return store.get_run(run_id)
