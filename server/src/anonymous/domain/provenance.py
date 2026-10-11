"""Execution provenance: label versus verifiable identity (ADR-0014, LD-04 §12).

A *label* is descriptive. An *identity* is a digest or immutable reference. Each component also
records how far its identity was verified. Labels, unspecified values and unrecorded values are
never evidence that two execution environments were equivalent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Verification(StrEnum):
    VERIFIED = "verified"  # computed or checked against the actual artifact
    ASSERTED = "asserted"  # supplied by a component, not checked
    UNSPECIFIED = "unspecified"  # capture attempted; no value available


class Comparison(StrEnum):
    IDENTICAL_VERIFIED = "identical_verified"
    CLAIMED_IDENTICAL = "claimed_identical"
    DIFFERENT = "different"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    label: str  # human-readable, descriptive only
    digest: str | None = None  # e.g. "sha256:<hex>"; None when no identity exists
    verification: Verification = Verification.UNSPECIFIED
    explicit_none: bool = False  # a recorded "no such component" (e.g. no behavior profile)

    def __post_init__(self) -> None:
        if (
            self.digest is None
            and self.verification is not Verification.UNSPECIFIED
            and not self.explicit_none
        ):
            raise ValueError("a verified or asserted identity needs a digest")
        if self.digest is not None and self.verification is Verification.UNSPECIFIED:
            raise ValueError("an unspecified identity cannot carry a digest")

    @classmethod
    def none(cls, label: str = "none") -> ComponentIdentity:
        return cls(label=label, digest=None, verification=Verification.VERIFIED, explicit_none=True)

    @classmethod
    def label_only(cls, label: str) -> ComponentIdentity:
        return cls(label=label)


COMPONENTS = (
    "application_build",
    "adapter",
    "model_artifact",
    "runtime_build",
    "context_configuration",
    "behavior_configuration",
)


@dataclass(frozen=True, slots=True)
class ExecutionProvenance:
    application_build: ComponentIdentity
    adapter: ComponentIdentity
    model_artifact: ComponentIdentity
    runtime_build: ComponentIdentity
    context_configuration: ComponentIdentity
    behavior_configuration: ComponentIdentity

    def to_json(self) -> str:
        body: dict[str, Any] = {}
        for name in COMPONENTS:
            c: ComponentIdentity = getattr(self, name)
            body[name] = {
                "label": c.label,
                "digest": c.digest,
                "verification": c.verification.value,
                "explicit_none": c.explicit_none,
            }
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> ExecutionProvenance:
        raw = json.loads(text)
        parts = {
            name: ComponentIdentity(
                label=raw[name]["label"],
                digest=raw[name]["digest"],
                verification=Verification(raw[name]["verification"]),
                explicit_none=bool(raw[name]["explicit_none"]),
            )
            for name in COMPONENTS
        }
        return cls(**parts)


def compare_component(a: ComponentIdentity | None, b: ComponentIdentity | None) -> Comparison:
    """Three-valued comparison. ``None`` means *unrecorded* (predates capture)."""
    if a is None or b is None:
        return Comparison.NOT_COMPARABLE
    if a.explicit_none and b.explicit_none:
        return Comparison.IDENTICAL_VERIFIED
    if a.digest is None or b.digest is None:
        return Comparison.NOT_COMPARABLE  # labels, however equal, prove nothing
    if a.digest.split(":", 1)[0] != b.digest.split(":", 1)[0]:
        return Comparison.NOT_COMPARABLE  # different digest algorithms
    if a.digest != b.digest:
        return Comparison.DIFFERENT
    if a.verification is Verification.VERIFIED and b.verification is Verification.VERIFIED:
        return Comparison.IDENTICAL_VERIFIED
    return Comparison.CLAIMED_IDENTICAL


def environments_equivalent(a: ExecutionProvenance | None, b: ExecutionProvenance | None) -> bool:
    """Equivalent only if every component is identical *and* verified. No behavioral equivalence
    of model output is implied (NFR-08 class 3)."""
    if a is None or b is None:
        return False
    return all(
        compare_component(getattr(a, name), getattr(b, name)) is Comparison.IDENTICAL_VERIFIED
        for name in COMPONENTS
    )
