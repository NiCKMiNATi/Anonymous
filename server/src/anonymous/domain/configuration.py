"""Effective context/behavior configuration: immutable, content-addressed (ADR-0014).

A manifest's identity is the sha256 of its canonical serialization. V0 configurations are
application-shipped assets; nothing here is a persona, Memory or profile editor.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DIGEST_PREFIX = "sha256:"
CANONICAL_FORM = "cfg1"


class BindingOrigin(StrEnum):
    INITIAL = "initial"
    ADOPTION = "adoption"
    LEGACY_BASELINE = "legacy_baseline"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest_of(value: Any) -> str:
    return DIGEST_PREFIX + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextConstruction:
    id: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "version": self.version}


@dataclass(frozen=True, slots=True)
class EffectiveConfiguration:
    """Manifest of the effective configuration. ``behavior`` is always an explicit ``None`` in V0.

    ``baseline_reference`` records the Slice 0A reference (commit and golden fixture digest) for
    the legacy baseline; it participates in the digest so the claim cannot change silently.
    """

    context: ContextConstruction
    system_instructions: str | None = None
    behavior: str | None = None
    baseline_reference: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": CANONICAL_FORM,
            "context_construction": self.context.to_dict(),
            "system_instructions": self.system_instructions,
            "behavior_configuration": self.behavior,
            "baseline_reference": dict(self.baseline_reference),
        }

    def canonical(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return digest_of(self.to_dict())

    @property
    def context_digest(self) -> str:
        return digest_of(
            {
                "form": CANONICAL_FORM,
                "context_construction": self.context.to_dict(),
                "system_instructions": self.system_instructions,
            }
        )

    @classmethod
    def from_canonical(cls, text: str) -> EffectiveConfiguration:
        raw = json.loads(text)
        ctx = raw["context_construction"]
        return cls(
            context=ContextConstruction(ctx["id"], int(ctx["version"])),
            system_instructions=raw["system_instructions"],
            behavior=raw["behavior_configuration"],
            baseline_reference=tuple(sorted(raw["baseline_reference"].items())),
        )


def manifest_matches_digest(canonical: str, digest: str) -> bool:
    """A stored manifest is trusted only if its digest recomputes."""
    try:
        return EffectiveConfiguration.from_canonical(canonical).digest == digest
    except (KeyError, ValueError, TypeError):
        return False
