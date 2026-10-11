"""Control routing (LD-04 §6): stop/probe reach the *persisted* binding only, bounded.

* No operation resolves "the currently active instance". A replacement instance is never probed
  or stopped on behalf of an old attempt; the handler itself verifies the binding's instance.
* Every call is bounded here as well as in the adapter: a call that does not return in time is
  ``UNKNOWN``/``TIMEOUT`` — never evidence.
* A basis an adapter did not declare for the binding is discarded (an adapter does not invent one).
* The single positive evidence the router produces itself is **B4 for ``owning_process``
  bindings owned by an earlier boot**, and only while this process holds the exclusive instance
  guard: the earlier owner process, and every worker thread in it, no longer exists (design §4.8).
  A label, a missing process in a snapshot, or an adapter's declaration is never used.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence

from anonymous.application.ports.model import (
    ProbeKind,
    ProbeResult,
    RuntimePort,
    StopAck,
)
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.evidence import EvidenceBasis, LifetimeScope

logger = logging.getLogger("anonymous.control")

_GRACE_SECONDS = 0.25


def _bounded[T](call: Callable[[], T], timeout_seconds: float, on_timeout: T, on_error: T) -> T:
    """Run ``call`` in a helper thread and give up waiting after ``timeout_seconds``.

    The helper thread is a daemon: a hung adapter never prevents the router from answering, and
    its eventual return is ignored.
    """
    box: list[T] = []

    def target() -> None:
        try:
            box.append(call())
        except Exception as error:
            logger.error("control call raised type=%s", type(error).__name__)
            box.append(on_error)

    thread = threading.Thread(target=target, name="anonymous-control", daemon=True)
    thread.start()
    thread.join(timeout_seconds + _GRACE_SECONDS)
    return box[0] if box else on_timeout


class BindingControlRouter:
    def __init__(
        self,
        adapters: Sequence[RuntimePort],
        *,
        current_boot_id: str,
        guard_held: Callable[[], bool],
    ) -> None:
        self._adapters = list(adapters)
        self._boot = current_boot_id
        self._guard_held = guard_held

    def _handler(self, binding: ExecutionBinding) -> RuntimePort | None:
        for adapter in self._adapters:
            descriptor = adapter.describe()
            if descriptor.adapter_id == binding.adapter_id and binding.format in (
                descriptor.binding_formats
            ):
                return adapter
        return None

    def _owner_is_gone(self, binding: ExecutionBinding, owner_boot_id: str | None) -> bool:
        return (
            binding.lifetime_scope is LifetimeScope.OWNING_PROCESS
            and owner_boot_id is not None
            and owner_boot_id != self._boot
            and self._guard_held()
        )

    def stop(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        owner_boot_id: str | None,
        deadline_seconds: float,
    ) -> StopAck:
        if self._owner_is_gone(binding, owner_boot_id):
            return StopAck.UNREACHABLE  # nothing to stop: the owning process no longer exists
        handler = self._handler(binding)
        if handler is None:
            return StopAck.UNSUPPORTED
        return _bounded(
            lambda: handler.stop(attempt_id, binding, deadline_seconds),
            deadline_seconds,
            StopAck.TIMEOUT,
            StopAck.UNREACHABLE,
        )

    def probe(
        self,
        attempt_id: str,
        binding: ExecutionBinding,
        owner_boot_id: str | None,
        deadline_seconds: float,
    ) -> ProbeResult:
        if self._owner_is_gone(binding, owner_boot_id):
            return ProbeResult(ProbeKind.CONFIRMED_ENDED, EvidenceBasis.PROCESS_EXIT_VERIFIED)
        handler = self._handler(binding)
        if handler is None:
            return ProbeResult(ProbeKind.UNSUPPORTED, reason="no handler for the persisted binding")
        result = _bounded(
            lambda: handler.probe(attempt_id, binding, deadline_seconds),
            deadline_seconds,
            ProbeResult(ProbeKind.UNKNOWN, reason="control call timed out"),
            ProbeResult(ProbeKind.UNKNOWN, reason="control call failed"),
        )
        if result.kind is ProbeKind.CONFIRMED_ENDED and result.basis not in binding.declared_bases:
            return ProbeResult(ProbeKind.UNKNOWN, reason="basis not declared for this binding")
        return result
