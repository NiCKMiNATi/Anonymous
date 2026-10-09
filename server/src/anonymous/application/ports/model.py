"""ModelPort — the Anonymous-owned boundary to any model runtime (ADR-0003, C07).

The request is a *constructed view* of conversation history (INV-015): role/content pairs only,
with no database ids, credentials or runtime-specific objects. Adapters translate to and from
their runtime; vendor types never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from anonymous.domain.models import MessageRole


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Stable historical identity of the model and the runtime that serves it (kept distinct)."""

    model_id: str
    runtime_id: str


@dataclass(frozen=True, slots=True)
class ContextMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: tuple[ContextMessage, ...]


@dataclass(frozen=True, slots=True)
class ModelOutput:
    content: str
    identity: ModelIdentity  # what actually produced the output; checked against the dispatch


class ModelExecutionError(Exception):
    """A runtime failure reported by an adapter.

    ``code`` is a stable machine identifier. ``public_message`` must be safe to persist and show:
    adapters must not put prompt/response text, credentials or paths into it.
    """

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = public_message


class ModelPort(Protocol):
    @property
    def identity(self) -> ModelIdentity:
        """Identity recorded on the run *before* invocation."""
        ...

    def generate(self, request: ModelRequest) -> ModelOutput:
        """Execute one generation. Raise ``ModelExecutionError`` for known failures."""
        ...
