"""Supervisor infrastructure: settings, scheduling probes, per-run gate, worker registry.

The **handoff gate** (LD-04 §4.3) is an application-owned, in-process, per-run mutual exclusion.
The invoker holds it from before T3b until after the start acknowledgment is recorded; every
in-process closer must hold it to commit a closure. It is never held during generation, probes,
stops or publication, and never while a database transaction is open across an external call.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from anonymous.domain.ids import RunId


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    slot_id: str = "local-runtime-0"  # composition configuration, never an adapter claim
    deadline_seconds: float = 120.0  # await_result bound; the watchdog closes the attempt after it
    handoff_deadline_seconds: float = 5.0  # bound for ``start``
    control_deadline_seconds: float = 5.0  # bound for each stop/probe
    slot_wait_seconds: float = 30.0  # a pending run waits this long for the slot
    slot_poll_seconds: float = 0.02
    closure_gate_wait_seconds: float = 10.0  # >= handoff deadline + slack
    probe_attempts: int = 3
    probe_interval_seconds: float = 0.05
    republish_attempts: int = 3
    shutdown_join_seconds: float = 10.0
    reconcile_min_interval_seconds: float = 0.0


Checkpoint = Callable[[str, str], None]  # (point name, run id): test seam for controlled scheduling


def no_checkpoint(name: str, run_id: str) -> None:
    return None


@dataclass(slots=True)
class RunControl:
    """In-process control state of one run: handoff gate, settle lock, closure intent."""

    run_id: RunId
    handoff_gate: threading.Lock = field(default_factory=threading.Lock)
    settle_lock: threading.RLock = field(default_factory=threading.RLock)
    closure_intent: threading.Event = field(default_factory=threading.Event)


class ControlRegistry:
    """Owns the per-run control objects so they survive replacement of a supervisor thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: dict[RunId, RunControl] = {}
        self._live_workers: set[RunId] = set()

    def control_for(self, run_id: RunId) -> RunControl:
        with self._lock:
            control = self._controls.get(run_id)
            if control is None:
                control = RunControl(run_id)
                self._controls[run_id] = control
            return control

    def mark_worker_live(self, run_id: RunId) -> None:
        with self._lock:
            self._live_workers.add(run_id)

    def mark_worker_done(self, run_id: RunId) -> None:
        with self._lock:
            self._live_workers.discard(run_id)

    def has_live_worker(self, run_id: RunId) -> bool:
        with self._lock:
            return run_id in self._live_workers

    def live_runs(self) -> list[RunId]:
        with self._lock:
            return list(self._live_workers)

    def drop(self, run_id: RunId) -> None:
        with self._lock:
            self._controls.pop(run_id, None)


class ThreadRegistry:
    """Every supervised thread (workers and watchdogs). Shutdown never releases ownership while
    any of them is alive."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self.accepting = True

    def spawn(self, name: str, target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(target=target, name=name, daemon=False)
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()
        return thread

    def alive(self) -> list[threading.Thread]:
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            return list(self._threads)

    def join_all(self, timeout_seconds: float) -> bool:
        """True if every supervised thread has terminated within the bound."""
        import time

        deadline = time.monotonic() + timeout_seconds
        for thread in self.alive():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)
        return not self.alive()
