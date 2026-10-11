"""RuntimePort — the Anonymous-owned boundary to any model runtime (ADR-0003, C07; LD-04 §6.3).

The request is a *constructed view* of conversation history (INV-015): role/content pairs only,
with no database ids, credentials or runtime-specific objects. Adapters translate to and from
their runtime; vendor types never cross this boundary.

Contract summary (each point is a testable adapter obligation):

* ``prepare`` identifies the live instance and performs no execution.
* ``start`` is a *bounded handoff*: it returns by its deadline with ``ACCEPTED``, ``NOT_STARTED``
  or ``UNKNOWN``, and initiates no further transmission after it returns. After an accepted
  ``stop(attempt)`` a later ``start(attempt)`` returns ``NOT_STARTED``.
* ``await_result`` waits for the result of an attempt on the bound instance and reports which
  instance actually delivered it.
* ``stop`` and ``probe`` are callable while ``start``/``await_result`` are blocked, are bounded,
  address the *persisted* binding only and verify its instance identity before acting. A stop
  acknowledgment is never evidence; only a ``CONFIRMED_ENDED(basis)`` probe is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import EvidenceBasis
from anonymous.domain.models import MessageRole
from anonymous.domain.provenance import ComponentIdentity


@dataclass(frozen=True, slots=True)
class ContextMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: tuple[ContextMessage, ...]


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Descriptive identity of a synchronous in-process model and its runtime (labels only)."""

    model_id: str
    runtime_id: str


@dataclass(frozen=True, slots=True)
class ModelOutput:
    content: str
    identity: ModelIdentity  # what actually produced the output


class ModelExecutionError(Exception):
    """A failure reported by a synchronous in-process model.

    ``code`` is a stable machine identifier. ``public_message`` must be safe to persist and show:
    adapters must not put prompt/response text, credentials or paths into it.
    """

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.public_message = public_message


class SynchronousModel(Protocol):
    """A model that runs entirely inside this process, as a blocking call (0A's ``ModelPort``).

    ``InProcessRuntime`` adapts it to ``RuntimePort``. It is not a model of any external runtime.
    """

    @property
    def identity(self) -> ModelIdentity: ...

    def generate(self, request: ModelRequest) -> ModelOutput: ...


class Knowledge(StrEnum):
    NEVER_REACHED = "never_reached"
    ENDED = "ended"  # the *bound* instance reported a terminal outcome for this attempt
    POSSIBLY_ACTIVE = "possibly_active"  # anything else, including unattributable reports


class StartAck(StrEnum):
    ACCEPTED = "accepted"  # the bound instance acknowledged the attempt
    NOT_STARTED = "not_started"  # nothing was sent and nothing will be
    UNKNOWN = "unknown"  # may have been sent


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    adapter_id: str
    adapter_version: str
    binding_formats: frozenset[str]
    max_input_chars: int | None = None  # None = no declared limit; never silent truncation


@dataclass(frozen=True, slots=True)
class PreparedBinding:
    binding: ExecutionBinding
    model_artifact: ComponentIdentity
    runtime_build: ComponentIdentity
    adapter: ComponentIdentity


@dataclass(frozen=True, slots=True)
class PrepareFailed:
    code: str
    public_message: str


@dataclass(frozen=True, slots=True)
class Completed:
    content: str
    instance_ref: str  # the instance that actually delivered (verified by the adapter)
    model_label: str
    complete: bool = True  # False: truncated / output limit


@dataclass(frozen=True, slots=True)
class Failed:
    code: str
    public_message: str
    knowledge: Knowledge
    instance_ref: str | None = None  # the instance that reported it, if attributable


class StopAck(StrEnum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    UNREACHABLE = "unreachable"
    UNSUPPORTED = "unsupported"
    INSTANCE_MISMATCH = "instance_mismatch"
    TIMEOUT = "timeout"


class ProbeKind(StrEnum):
    CONFIRMED_ENDED = "confirmed_ended"
    STILL_ACTIVE = "still_active"
    UNKNOWN = "unknown"
    INSTANCE_MISMATCH = "instance_mismatch"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    kind: ProbeKind
    basis: EvidenceBasis | None = None
    reason: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if (self.kind is ProbeKind.CONFIRMED_ENDED) != (self.basis is not None):
            raise ValueError("only CONFIRMED_ENDED carries a basis")


class RuntimePort(Protocol):
    def describe(self) -> AdapterDescriptor: ...

    def prepare(self, attempt_id: str) -> PreparedBinding | PrepareFailed: ...

    def start(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        request: ModelRequest,
        handoff_deadline_seconds: float,
    ) -> StartAck: ...

    def await_result(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> Completed | Failed: ...

    def stop(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> StopAck: ...

    def probe(
        self, attempt_id: str, binding: ExecutionBinding, deadline_seconds: float
    ) -> ProbeResult: ...


class ControlRouter(Protocol):
    """Routes control to the handler for a *persisted* binding (never to "the current instance").

    ``owner_boot_id`` is the boot recorded on the run at dispatch; it lets the router tell a
    binding owned by an earlier process from one owned by this process.
    """

    def stop(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        owner_boot_id: str | None,
        deadline_seconds: float,
    ) -> StopAck: ...

    def probe(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        owner_boot_id: str | None,
        deadline_seconds: float,
    ) -> ProbeResult: ...
