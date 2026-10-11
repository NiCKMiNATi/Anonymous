"""Pure rules: admissible termination evidence, provenance identity, configuration digests."""

from __future__ import annotations

import itertools

import pytest

from anonymous.application.configuration import baseline_manifest
from anonymous.domain.configuration import (
    ContextConstruction,
    EffectiveConfiguration,
    manifest_matches_digest,
)
from anonymous.domain.evidence import (
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    RecordEpoch,
    admissible_bases,
)
from anonymous.domain.provenance import (
    Comparison,
    ComponentIdentity,
    ExecutionProvenance,
    Verification,
    compare_component,
    environments_equivalent,
)

B = EvidenceBasis


def allowed(handoff: Handoff | None, outcome: HandoffOutcome | None, late: bool = False):  # type: ignore[no-untyped-def]
    return admissible_bases(
        epoch=RecordEpoch.CURRENT, handoff=handoff, outcome=outcome, late_delivery_excluded=late
    )


def test_never_invoked_states_admit_only_non_invocation() -> None:
    assert allowed(Handoff.NONE, None) == {B.NEVER_DISPATCHED}
    assert allowed(Handoff.STARTED, HandoffOutcome.NOT_CALLED) == {B.NEVER_DISPATCHED}
    assert allowed(Handoff.STARTED, HandoffOutcome.NOT_STARTED) == {B.ADAPTER_NEVER_REACHED}


def test_accepted_handoff_admits_termination_evidence_but_not_non_invocation() -> None:
    result = allowed(Handoff.STARTED, HandoffOutcome.ACCEPTED)
    assert result == {
        B.RUNTIME_REPORTED_TERMINAL,
        B.PROCESS_EXIT_VERIFIED,
        B.EXECUTION_TERMINATED_VERIFIED,
    }
    assert B.NEVER_DISPATCHED not in result and B.ADAPTER_NEVER_REACHED not in result


@pytest.mark.parametrize("outcome", [None, HandoffOutcome.UNKNOWN])
def test_uncertain_handoff_is_never_claimed_uninvoked_and_b5_needs_late_delivery_exclusion(
    outcome: HandoffOutcome | None,
) -> None:
    without = allowed(Handoff.STARTED, outcome, late=False)
    assert without == {B.RUNTIME_REPORTED_TERMINAL, B.PROCESS_EXIT_VERIFIED}
    assert B.EXECUTION_TERMINATED_VERIFIED in allowed(Handoff.STARTED, outcome, late=True)
    assert B.NEVER_DISPATCHED not in allowed(Handoff.STARTED, outcome, late=True)


def test_binding_less_legacy_runs_have_no_admissible_basis() -> None:
    for handoff, outcome, late in itertools.product(
        [None, *Handoff], [None, *HandoffOutcome], [False, True]
    ):
        assert (
            admissible_bases(
                epoch=RecordEpoch.LEGACY_0A,
                handoff=handoff,
                outcome=outcome,
                late_delivery_excluded=late,
            )
            == frozenset()
        )


def test_there_is_no_isolation_or_operator_basis() -> None:
    assert {b.value for b in EvidenceBasis} == {
        "never_dispatched",
        "adapter_never_reached",
        "runtime_reported_terminal",
        "process_exit_verified",
        "execution_terminated_verified",
    }


# -- provenance identity -------------------------------------------------------------------------

D1, D2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64


def verified(label: str, digest: str) -> ComponentIdentity:
    return ComponentIdentity(label, digest, Verification.VERIFIED)


def asserted(label: str, digest: str) -> ComponentIdentity:
    return ComponentIdentity(label, digest, Verification.ASSERTED)


def test_comparison_is_three_valued_and_labels_prove_nothing() -> None:
    assert (
        compare_component(verified("a", D1), verified("zzz", D1)) is Comparison.IDENTICAL_VERIFIED
    )
    assert compare_component(asserted("a", D1), verified("a", D1)) is Comparison.CLAIMED_IDENTICAL
    assert compare_component(verified("a", D1), verified("a", D2)) is Comparison.DIFFERENT
    same = ComponentIdentity.label_only("model-7b")
    assert (
        compare_component(same, ComponentIdentity.label_only("model-7b"))
        is Comparison.NOT_COMPARABLE
    )
    assert compare_component(same, verified("model-7b", D1)) is Comparison.NOT_COMPARABLE
    assert compare_component(None, None) is Comparison.NOT_COMPARABLE  # two unrecorded values
    assert (
        compare_component(ComponentIdentity.none(), ComponentIdentity.none())
        is Comparison.IDENTICAL_VERIFIED
    )


def test_identity_without_a_digest_cannot_claim_verification() -> None:
    with pytest.raises(ValueError):
        ComponentIdentity("x", None, Verification.VERIFIED)
    with pytest.raises(ValueError):
        ComponentIdentity("x", D1, Verification.UNSPECIFIED)


def provenance(model: ComponentIdentity) -> ExecutionProvenance:
    return ExecutionProvenance(
        application_build=verified("app", D1),
        adapter=verified("adapter", D1),
        model_artifact=model,
        runtime_build=verified("rt", D1),
        context_configuration=verified("ctx", D1),
        behavior_configuration=ComponentIdentity.none(),
    )


def test_environments_are_equivalent_only_if_every_component_is_verified_identical() -> None:
    a = provenance(verified("m", D1))
    assert environments_equivalent(a, provenance(verified("other label", D1)))
    assert not environments_equivalent(a, provenance(asserted("m", D1)))
    assert not environments_equivalent(a, provenance(ComponentIdentity.label_only("m")))
    assert not environments_equivalent(
        provenance(ComponentIdentity.label_only("m")), provenance(ComponentIdentity.label_only("m"))
    )
    assert not environments_equivalent(a, None)


def test_provenance_round_trips_with_verification_states() -> None:
    value = provenance(asserted("m", D1))
    assert ExecutionProvenance.from_json(value.to_json()) == value


# -- configuration manifests ---------------------------------------------------------------------


def test_manifest_digest_is_content_addressed_and_verified_on_read() -> None:
    manifest = baseline_manifest()
    assert manifest.digest.startswith("sha256:")
    assert manifest_matches_digest(manifest.canonical(), manifest.digest)
    other = EffectiveConfiguration(ContextConstruction("whole-history", 2))
    assert other.digest != manifest.digest
    assert not manifest_matches_digest(other.canonical(), manifest.digest)  # tampered content
    assert not manifest_matches_digest("not json", manifest.digest)
    assert EffectiveConfiguration.from_canonical(manifest.canonical()).digest == manifest.digest


def test_baseline_manifest_pins_the_slice_0a_reference() -> None:
    reference = dict(baseline_manifest().baseline_reference)
    assert reference["commit"] == "01e9f46559cfca4c30777b940a8ca7d5f8af25d8"
    assert baseline_manifest().system_instructions is None and baseline_manifest().behavior is None
