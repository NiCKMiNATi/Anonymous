"""Supervisor infrastructure: settings, scheduling probes, per-run gate, worker registry.

Synchronization rules (remediation of the 0B-1 review; lock order is total, outermost first):

  1. ``AdmissionGate`` (process-wide)   — admission commit + "run is live" mark are atomic with
                                           respect to orphan detection of ``pending`` runs.
  2. per-run handoff gate / settle lock — as before (worker.py, settling.py).
  3. store transactions (SQLite)         — short, never nested in 4 or 5.
  4. ``ControlRegistry`` lock            — leaf.
  5. ``ThreadRegistry`` condition        — leaf.

A leaf lock is never held while taking any other lock, calling the store or runtime, or running a
checkpoint. The admission gate is never held across a thread start, a runtime call or a wait.

The **handoff gate** (LD-04 §4.3) is an application-owned, in-process, per-run mutual exclusion.
The invoker holds it from before T3b until after the start acknowledgment is recorded; every
in-process closer must hold it to commit a closure. It is never held during generation, probes,
stops or publication, and never while a database transaction is open across an external call.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

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


class AdmissionGate:
    """A plain mutual-exclusion lock that also reports how many threads are waiting for it, so a
    test can prove a competing operation has *reached* the gate rather than guess with a delay."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count_lock = threading.Lock()
        self._waiting = 0

    def waiting(self) -> int:
        with self._count_lock:
            return self._waiting

    def __enter__(self) -> None:
        with self._count_lock:
            self._waiting += 1
        try:
            self._lock.acquire()
        finally:
            with self._count_lock:
                self._waiting -= 1

    def __exit__(self, *exc: object) -> None:
        self._lock.release()


class ControlRegistry:
    """Owns the per-run control objects so they survive replacement of a supervisor thread.

    ``admission_gate`` closes the window between "the pending run is committed" and "the run is
    marked live": admission holds it across both; orphan detection of pending runs holds it across
    list → liveness check → settle. A committed admission is therefore never observed as
    abandoned, while a pending run with no live mark (and no admission in progress) is.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.admission_gate = AdmissionGate()
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


class SpawnRefused(Exception):
    """No new supervised thread may be reserved (shutdown has begun or finished)."""


class SpawnFailed(Exception):
    """The operating system refused to start the thread: it is established NOT to have started."""


class _State(Enum):
    RESERVED = "reserved"  # counted; the thread has not been started
    STARTING = "starting"  # ``Thread.start`` was called; the target may begin executing at any time
    RUNNING = "running"  # the target is executing
    UNRESOLVED = "unresolved"  # ``start`` failed in a way that does not prove non-start
    ENDED = "ended"  # no longer counted


class Reservation:
    """A counted claim on one supervised unit of work: a thread, or an inline activity.

    A reservation exists from before the work can possibly begin until after it has certainly
    ended; the registry is quiescent only when none is outstanding. "Not alive yet" is never read
    as "terminated". A reservation is released only by (a) the wrapper of the thread it started,
    when the target returns, (b) :meth:`release`, valid only while nothing was started, or (c) a
    failed ``start`` that is established not to have started.
    """

    __slots__ = ("_registry", "_token", "name", "state", "thread")

    def __init__(self, registry: ThreadRegistry, token: int, name: str) -> None:
        self._registry = registry
        self._token = token
        self.name = name
        self.state = _State.RESERVED
        self.thread: threading.Thread | None = None

    def start(self, target: Callable[[], None], name: str | None = None) -> threading.Thread:
        if name is not None:
            self.name = name
        return self._registry._start(self, target)

    def spawn_child(self, name: str, target: Callable[[], None]) -> threading.Thread:
        """A thread owned by this running unit (e.g. a deadline watchdog). Allowed during
        shutdown, because the parent is itself still counted, so quiescence cannot be observed
        between the parent and its child."""
        return self._registry._spawn_child(self, name, target)

    def release(self) -> None:
        """Release a reservation whose thread was never started (an inline activity, a refused
        admission, or a ``start`` that failed with :class:`SpawnFailed`)."""
        self._registry._release_unstarted(self)


class ThreadRegistry:
    """Every supervised thread and inline activity, tracked by explicit reservation.

    One lock (a leaf: never held across a store call, a runtime call, a gate or a checkpoint) and
    one condition. Shutdown (1) forbids new top-level reservations, then (2) waits for every
    outstanding reservation. Nothing here consults ``Thread.is_alive`` to decide that work is
    over: an entry leaves the registry only when its own wrapper says the target returned.
    """

    def __init__(self, checkpoint: Callable[[str], None] | None = None) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._entries: dict[int, Reservation] = {}
        self._next = 0
        self._accepting = True
        self._checkpoint = checkpoint or (lambda point: None)

    # -- reservation ---------------------------------------------------------------------------

    @property
    def accepting(self) -> bool:
        with self._cond:
            return self._accepting

    def reserve(self, name: str) -> Reservation:
        """Count a new unit of work, or refuse it. Everything after this is covered by shutdown."""
        with self._cond:
            if not self._accepting:
                raise SpawnRefused("shutting down")
            return self._reserve_locked(name)

    def _reserve_locked(self, name: str) -> Reservation:
        self._next += 1
        reservation = Reservation(self, self._next, name)
        self._entries[self._next] = reservation
        return reservation

    def spawn(self, name: str, target: Callable[[], None]) -> threading.Thread:
        return self.reserve(name).start(target)

    # -- starting --------------------------------------------------------------------------------

    def _start(self, reservation: Reservation, target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(
            target=self._wrap(reservation, target), name=reservation.name, daemon=False
        )
        with self._cond:
            if reservation.state is not _State.RESERVED:
                raise RuntimeError("reservation already used")
            reservation.state = _State.STARTING
            reservation.thread = thread
        # Registered and counted, but not started: the window the original defect lived in.
        self._checkpoint(f"spawn_registered:{reservation.name}")
        try:
            thread.start()
        except RuntimeError as error:
            # ``Thread.start`` raises ``RuntimeError`` only when the OS could not create the thread
            # (``_start_new_thread`` failed before any code of the new thread could run), so
            # non-start is established. The reservation is NOT dropped here: the caller finishes
            # its own cleanup (which may still write) and then releases it.
            with self._cond:
                if reservation.state is _State.STARTING:
                    reservation.state = _State.RESERVED
                    reservation.thread = None
            raise SpawnFailed(str(error)) from error
        except BaseException:
            # Anything else does not prove the thread did not start (e.g. an interrupt after the
            # OS thread was created): keep the reservation outstanding. If the thread did start,
            # its wrapper ends the reservation when the target returns; if it did not, nothing
            # ever will, shutdown reports "incomplete" and the process must exit.
            with self._cond:
                reservation.state = _State.UNRESOLVED
            raise
        return thread

    def _wrap(self, reservation: Reservation, target: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            with self._cond:
                if reservation.state is _State.STARTING:
                    reservation.state = _State.RUNNING
            try:
                target()
            finally:
                with self._cond:
                    reservation.state = _State.ENDED
                    self._entries.pop(reservation._token, None)
                    self._cond.notify_all()

        return run

    def _spawn_child(
        self, parent: Reservation, name: str, target: Callable[[], None]
    ) -> threading.Thread:
        with self._cond:
            if parent.state not in (_State.STARTING, _State.RUNNING):
                raise SpawnRefused("the parent is not running")
            child = self._reserve_locked(name)
        return child.start(target)

    def _release_unstarted(self, reservation: Reservation) -> None:
        with self._cond:
            if reservation.state is not _State.RESERVED:
                raise RuntimeError("only a reservation that never started may be released")
            reservation.state = _State.ENDED
            self._entries.pop(reservation._token, None)
            self._cond.notify_all()

    # -- shutdown --------------------------------------------------------------------------------

    def begin_shutdown(self) -> None:
        with self._cond:
            self._accepting = False

    def outstanding(self) -> list[str]:
        """Names of every reservation that may still execute. Empty ⇒ quiescent."""
        with self._cond:
            return [r.name for r in self._entries.values()]

    def alive(self) -> list[str]:
        return self.outstanding()

    def join_all(self, timeout_seconds: float) -> bool:
        """True iff every reservation (started or not) has ended within the bound. Only
        meaningful after :meth:`begin_shutdown`; a reservation made earlier is waited for."""
        deadline = time.monotonic() + timeout_seconds
        with self._cond:
            while self._entries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True
