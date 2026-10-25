"""Configuration continuity (ADR-0014, LD-04 §11): catalog, golden baseline, binding service.

The shipped configuration ``whole-history@1`` reproduces Slice 0A's context construction. That is
not asserted: at startup the shipped builder replays golden fixtures captured from the *real* 0A
code at commit ``01e9f46`` and must reproduce every recorded view byte-for-byte. Only then are
legacy (pre-0B) conversations bound to it; otherwise they stay readable, unbound, and need an
explicit adoption before generation. Nothing here is a persona, Memory or profile subsystem.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any, Protocol

from anonymous.application.context import BoundedRecentContextBuilder, ContextBuilder, ContextView
from anonymous.application.ports.model import ModelRequest
from anonymous.application.ports.persistence import ExecutionStore, HistorySource
from anonymous.domain.configuration import (
    ContextConstruction,
    EffectiveConfiguration,
    canonical_json,
    manifest_matches_digest,
)
from anonymous.domain.ids import ConversationId, MessageId, RunId, UserId
from anonymous.domain.models import Message, MessageRole

logger = logging.getLogger("anonymous.configuration")

REFERENCE_COMMIT = "01e9f46559cfca4c30777b940a8ca7d5f8af25d8"
GOLDEN_FILE_SHA256 = "afb16c8821f80c5ce4eaf6aee328fb772ee7057e6b62c8d810fdab3e5e2d5bf1"
WHOLE_HISTORY_ID = "whole-history"
BOUNDED_RECENT_ID = "bounded-recent-history"


class ContextBuilderLike(Protocol):
    def build(self, triggering_message: Message) -> ModelRequest: ...

    def build_view(self, triggering_message: Message, limit_chars: int | None) -> ContextView: ...


BuilderFactory = Callable[[HistorySource], ContextBuilderLike]


@dataclass(frozen=True, slots=True)
class ShippedConfiguration:
    manifest: EffectiveConfiguration
    builder_factory: BuilderFactory
    golden_checked: bool = False  # True: must pass the Slice 0A golden replay to be executable


def baseline_manifest() -> EffectiveConfiguration:
    """``whole-history@1`` with its Slice 0A reference. The reference participates in the digest."""
    return EffectiveConfiguration(
        context=ContextConstruction(WHOLE_HISTORY_ID, 1),
        baseline_reference=(("commit", REFERENCE_COMMIT), ("fixture_sha256", GOLDEN_FILE_SHA256)),
    )


def bounded_recent_manifest() -> EffectiveConfiguration:
    """``bounded-recent-history@1`` (ADR-0017): a contiguous recent suffix within the runtime's
    declared character limit. No Slice 0A reference: it is a new configuration, not a baseline."""
    return EffectiveConfiguration(context=ContextConstruction(BOUNDED_RECENT_ID, 1))


def shipped_configurations() -> list[ShippedConfiguration]:
    """``whole-history@1`` stays first and golden-checked (only it may bind legacy conversations);
    the bounded configuration is executable alongside it."""
    return [
        ShippedConfiguration(baseline_manifest(), ContextBuilder, golden_checked=True),
        ShippedConfiguration(bounded_recent_manifest(), BoundedRecentContextBuilder),
    ]


def default_configuration_digest() -> str:
    """The configuration new conversations are bound to (ADR-0017). Existing ones keep theirs."""
    return bounded_recent_manifest().digest


# -- golden replay -------------------------------------------------------------------------------


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_golden_bytes() -> bytes:
    return (
        resources.files("anonymous.application.golden")
        .joinpath("slice0a_context_golden.json")
        .read_bytes()
    )


class _ListSource:
    """An in-memory ``HistorySource`` over one fixture history."""

    def __init__(self, messages: list[Message]) -> None:
        self._messages = messages

    def read_messages_through(
        self, conversation_id: ConversationId, last_message_id: MessageId
    ) -> tuple[Message, ...]:
        cut = next(m.position for m in self._messages if m.id == last_message_id)
        return tuple(m for m in self._messages if m.position <= cut)


def golden_document(raw: bytes | None = None) -> dict[str, Any]:
    """The fixture document with its ``@rule:`` markers expanded. Raises ``ValueError`` if the file
    is not byte-identical to the pinned fixture (the digest is the reference's identity)."""
    data = raw if raw is not None else load_golden_bytes()
    if hashlib.sha256(data).hexdigest() != GOLDEN_FILE_SHA256:
        raise ValueError("golden fixture file digest does not match the pinned digest")
    big = "ab" * 16000

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        if value == "@rule:'ab'*16000":
            return big
        return value

    document: dict[str, Any] = expand(json.loads(data))
    return document


def view_digest(view: list[dict[str, str]]) -> str:
    return _sha(_canon(view))


def golden_replay(factory: BuilderFactory, raw: bytes | None = None) -> list[str]:
    """Replay fixtures FX-01..FX-06 through ``factory``; return the list of mismatches (empty =
    the builder reproduces Slice 0A). FX-07 (two interleaved conversations) is covered by the test
    suite through the real store and coordinator."""
    try:
        doc = golden_document(raw)
    except ValueError as error:
        return [str(error)]
    problems: list[str] = []
    for fixture in doc["fixtures"]:
        if "history_after" not in fixture:
            continue  # FX-07: exercised by the test suite
        messages = [
            Message(
                id=MessageId(f"{fixture['id']}-m{h['position']}"),
                conversation_id=ConversationId(fixture["id"]),
                position=h["position"],
                role=MessageRole(h["role"]),
                content=h["content"],
                committed_at=datetime(2026, 1, 1, tzinfo=UTC),
                produced_by_run_id=RunId("golden") if h["role"] == "assistant" else None,
            )
            for h in fixture["history_after"]
        ]
        builder = factory(_ListSource(messages))
        recorded = fixture["rebuilt_views_over_final_history"] + [
            {**d} for d in fixture["dispatched_views"]
        ]
        for entry in recorded:
            trigger = next(m for m in messages if m.position == entry["trigger_position"])
            view = [
                {"role": m.role.value, "content": m.content}
                for m in builder.build(trigger).messages
            ]
            if _canon(view) != _canon(entry["view"]) or view_digest(view) != entry["view_sha256"]:
                problems.append(f"{fixture['id']}@{entry['trigger_position']}")
    return problems


# -- catalog and service -------------------------------------------------------------------------


class ConfigurationCatalog:
    """The configurations the running build can *execute* (retained ≠ executable)."""

    def __init__(
        self, shipped: list[ShippedConfiguration], default_digest: str | None = None
    ) -> None:
        if not shipped:
            raise ValueError("at least one configuration must be shipped")
        self._by_digest = {s.manifest.digest: s for s in shipped}
        self._disabled: set[str] = set()
        self.default_digest = default_digest or shipped[0].manifest.digest

    @property
    def shipped(self) -> list[ShippedConfiguration]:
        return list(self._by_digest.values())

    def disable(self, digest: str) -> None:
        self._disabled.add(digest)

    def executable_digests(self) -> frozenset[str]:
        return frozenset(d for d in self._by_digest if d not in self._disabled)

    def is_executable(self, digest: str) -> bool:
        return digest in self.executable_digests()

    def manifest(self, digest: str) -> EffectiveConfiguration | None:
        shipped = self._by_digest.get(digest)
        return None if shipped is None else shipped.manifest

    def builder(self, digest: str, source: HistorySource) -> ContextBuilderLike | None:
        if not self.is_executable(digest):
            return None
        return self._by_digest[digest].builder_factory(source)


class ConfigurationService:
    def __init__(self, store: ExecutionStore, catalog: ConfigurationCatalog) -> None:
        self._store = store
        self._catalog = catalog

    def startup(self) -> int:
        """Register manifests, run the golden self-test, bind legacy conversations if (and only
        if) the baseline reproduced Slice 0A. Returns the number of conversations bound."""
        bound = 0
        for shipped in self._catalog.shipped:
            digest = shipped.manifest.digest
            consistent = self._store.register_configuration(digest, shipped.manifest.canonical())
            stored = self._store.get_configuration_manifest(digest)
            if not consistent or stored is None or not manifest_matches_digest(stored, digest):
                self._catalog.disable(digest)
                logger.error("stored configuration failed digest verification")
                continue
            if not shipped.golden_checked:
                continue
            problems = golden_replay(shipped.builder_factory)
            if problems:
                self._catalog.disable(digest)
                logger.error("baseline configuration failed the Slice 0A golden replay")
                continue
            bound += self._store.bind_legacy_conversations(digest, GOLDEN_FILE_SHA256)
        if bound:
            logger.warning("bound %d legacy conversation(s) to the verified baseline", bound)
        return bound

    def adopt(
        self, owner: UserId, conversation_id: ConversationId, adoption_id: str, digest: str
    ) -> Any:
        if not self._catalog.is_executable(digest):
            from anonymous.domain.errors import ConfigurationUnavailable

            raise ConfigurationUnavailable("That configuration cannot be executed by this build.")
        return self._store.adopt_configuration(owner, conversation_id, adoption_id, digest)


__all__ = [
    "BuilderFactory",
    "ConfigurationCatalog",
    "ConfigurationService",
    "ShippedConfiguration",
    "baseline_manifest",
    "bounded_recent_manifest",
    "canonical_json",
    "default_configuration_digest",
    "golden_replay",
    "shipped_configurations",
]
