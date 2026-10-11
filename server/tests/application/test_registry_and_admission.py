"""Worker registration, shutdown and pending-admission coordination (0B-1 remediation 1 and 2).

Finding 1 (worker tracking): a thread used to be registered *before* ``Thread.start()``, and any
concurrent ``spawn``/``alive`` dropped it because ``is_alive()`` was still false, so a shutdown
could conclude "quiescent" and release the instance guard while the worker was about to run.

Finding 2 (pending admission): an admission could commit before its worker was marked live, and a
concurrent reconcile took the accepted ``pending`` run for an abandoned one.

Every interleaving here is forced with barriers on the real ``Thread.start`` or on named
checkpoints; a competing operation is proven to have *reached* its gate (``AdmissionGate.waiting``,
``spawn_registered``/``orphan_scan_*`` checkpoints) before the test proceeds. Nothing relies on a
sleep to establish that something happened.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.instance_guard import InstanceGuard
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.supervisor import SpawnFailed, SpawnRefused, ThreadRegistry
from anonymous.composition import Application, build_application
from anonymous.config import Settings
from anonymous.domain.errors import GenerationBlocked, OwnershipError
from anonymous.domain.ids import ConversationId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import RunStatus
from tests.conftest import FAST, Services
from tests.doubles import Fault, FaultyExecutionStore, Scheduler


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Block on a *condition* (never on a fixed delay). The tiny sleep only yields the CPU."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.001)
    return condition()


def in_thread(call: Callable[[], object]) -> tuple[threading.Thread, list[object]]:
    box: list[object] = []

    def run() -> None:
        try:
            box.append(call())
        except BaseException as error:  # delivered to the test, never swallowed
            box.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def reached_runtime(runtime: ScriptedRuntime) -> list[str]:
    """Every call that could have started work. ``prepare`` only reserves an identity."""
    return [c.operation for c in runtime.calls if c.operation != "prepare"]


class StartBarrier:
    """Holds ``Thread.start`` of matching threads *before* the real start (the unstarted window)."""

    def __init__(self, original: Callable[..., Any], prefix: str, limit: int = 1) -> None:
        self._original = original
        self._prefix = prefix
        self._remaining = limit
        self._lock = threading.Lock()
        self.reached = threading.Event()
        self.release = threading.Event()
        self.fail_with: BaseException | None = None

    def __call__(self, thread: threading.Thread) -> None:
        if thread.name.startswith(self._prefix):
            with self._lock:
                gated = self._remaining > 0
                if gated:
                    self._remaining -= 1
            if gated:
                self.reached.set()
                assert self.release.wait(10), "Thread.start was never released"
                if self.fail_with is not None:
                    raise self.fail_with
        self._original(thread)


@pytest.fixture
def start_barrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., StartBarrier]]:
    original = threading.Thread.start
    created: list[StartBarrier] = []

    def install(prefix: str = "anonymous-run-", limit: int = 1) -> StartBarrier:
        barrier = StartBarrier(original, prefix, limit)
        monkeypatch.setattr(threading.Thread, "start", lambda self: barrier(self))
        created.append(barrier)
        return barrier

    yield install
    for barrier in created:
        barrier.release.set()  # never leave a thread parked


# -- the registry in isolation ------------------------------------------------------------------


def test_a_registered_but_unstarted_thread_is_outstanding_whatever_else_spawns_or_polls() -> None:
    reached = threading.Event()
    go = threading.Event()

    def checkpoint(point: str) -> None:
        if point == "spawn_registered:slow":
            reached.set()
            assert go.wait(10)

    registry = ThreadRegistry(checkpoint)
    ran = threading.Event()
    slow, _ = in_thread(lambda: registry.spawn("slow", ran.set))
    assert reached.wait(5)  # registered and counted; Thread.start() has not been called

    # The original defect: a concurrent spawn or poll dropped every thread with is_alive() False.
    other_ran = threading.Event()
    registry.spawn("other", other_ran.set)
    assert other_ran.wait(5)
    assert registry.outstanding() == ["slow"]
    assert registry.alive() == ["slow"]

    registry.begin_shutdown()
    assert registry.join_all(0.05) is False  # not quiescent: "not alive yet" is not "ended"
    with pytest.raises(SpawnRefused):
        registry.spawn("late", lambda: None)

    go.set()
    slow.join(5)
    assert registry.join_all(5) is True
    assert ran.is_set() and registry.outstanding() == []


def test_shutdown_accounts_for_every_reservation_under_concurrent_spawning() -> None:
    registry = ThreadRegistry()
    accepted: list[int] = []
    completed: list[int] = []
    guard = threading.Lock()
    stop = threading.Event()

    def spawner(base: int) -> None:
        index = 0
        while not stop.is_set():
            index += 1
            token = base * 100000 + index

            def task(token: int = token) -> None:
                with guard:
                    completed.append(token)

            try:
                registry.spawn(f"t{token}", task)
            except SpawnRefused:
                return
            with guard:
                accepted.append(token)

    spawners = [threading.Thread(target=spawner, args=(b,)) for b in range(6)]
    for thread in spawners:
        thread.start()
    assert wait_until(lambda: len(accepted) > 200)
    registry.begin_shutdown()
    assert registry.join_all(10) is True
    stop.set()
    for thread in spawners:
        thread.join(5)
    # Quiescence was declared only after every thread that was ever admitted had finished its work.
    assert sorted(set(accepted)) == sorted(set(completed))
    assert registry.outstanding() == []


def test_a_child_of_a_running_unit_may_spawn_during_shutdown_but_nothing_else_may() -> None:
    registry = ThreadRegistry()
    reservation = registry.reserve("parent")
    entered, finish = threading.Event(), threading.Event()
    child_ran = threading.Event()
    children: list[threading.Thread] = []

    def parent() -> None:
        entered.set()
        assert finish.wait(10)
        children.append(reservation.spawn_child("child", child_ran.set))  # shutdown has begun

    reservation.start(parent)
    assert entered.wait(5)
    registry.begin_shutdown()
    with pytest.raises(SpawnRefused):
        registry.reserve("stranger")
    finish.set()
    assert registry.join_all(5) is True
    assert child_ran.is_set()
    with pytest.raises(SpawnRefused):  # the parent has ended: it can no longer spawn
        reservation.spawn_child("orphan", lambda: None)


def test_a_failed_start_releases_only_after_non_start_is_established(
    start_barrier: Callable[..., StartBarrier],
) -> None:
    registry = ThreadRegistry()
    barrier = start_barrier("doomed")
    barrier.fail_with = RuntimeError("can't start new thread")
    reservation = registry.reserve("doomed")
    thread, box = in_thread(lambda: reservation.start(lambda: None))
    assert barrier.reached.wait(5)
    registry.begin_shutdown()
    assert registry.join_all(0.05) is False  # still counted while start is in progress
    barrier.release.set()
    thread.join(5)
    assert isinstance(box[0], SpawnFailed)
    assert registry.outstanding() == ["doomed"]  # the caller still owns the reservation
    reservation.release()
    assert registry.join_all(1) is True


def test_a_start_that_does_not_prove_non_start_is_never_treated_as_terminated(
    start_barrier: Callable[..., StartBarrier],
) -> None:
    registry = ThreadRegistry()
    barrier = start_barrier("unsure")

    class Interrupted(BaseException):
        pass

    barrier.fail_with = Interrupted()
    reservation = registry.reserve("unsure")
    thread, box = in_thread(lambda: reservation.start(lambda: None))
    assert barrier.reached.wait(5)
    registry.begin_shutdown()
    barrier.release.set()
    thread.join(5)
    assert isinstance(box[0], Interrupted)
    assert registry.join_all(0.1) is False  # conservative: ownership must not be released
    assert registry.outstanding() == ["unsure"]


# -- finding 1 at the application level: registration -> pause -> shutdown -> start -------------


@pytest.fixture
def app(tmp_path: Path) -> Iterator[tuple[Application, ScriptedRuntime, Path]]:
    path = tmp_path / "data" / "registry.sqlite3"
    runtime = ScriptedRuntime()
    application = build_application(
        Settings(db_path=path), runtime=runtime, execution_settings=FAST
    )
    yield application, runtime, path
    application.shutdown(0.5)


def submit_async(
    application: Application, cid: ConversationId
) -> tuple[threading.Thread, list[object]]:
    return in_thread(
        lambda: application.execution.begin_submit(
            owner=application.owner,
            conversation_id=cid,
            submission_id=SubmissionId(new_uuid()),
            content="q",
        )
    )


def test_shutdown_during_the_unstarted_window_keeps_the_guard_until_the_worker_has_run(
    app: tuple[Application, ScriptedRuntime, Path], start_barrier: Callable[..., StartBarrier]
) -> None:
    application, runtime, path = app
    cid = application.conversations.create_conversation(application.owner).id
    barrier = start_barrier()
    submitter, box = submit_async(application, cid)
    assert barrier.reached.wait(5)  # admission committed, worker reserved, Thread.start() parked
    run_id = application.store.list_pending_runs()[0].id

    # A concurrent spawn/poll must not forget the reserved worker (the original defect) ...
    assert application.execution.threads.outstanding() != []
    # ... so a shutdown now is incomplete, and ownership stays with this process.
    assert application.shutdown(timeout_seconds=0.1) is False
    assert application.guard.held
    with pytest.raises(OwnershipError):
        InstanceGuard(path).acquire()  # no second owner can appear

    barrier.release.set()  # the worker starts *after* shutdown began
    submitter.join(5)
    handle = box[0]
    assert not isinstance(handle, BaseException)
    outcome = handle.wait(5)  # type: ignore[attr-defined]
    # A worker that begins after shutdown started settles its own never-dispatched run (B1) and
    # never reaches the runtime.
    assert outcome.run.id == run_id and outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "interrupted_before_dispatch"
    assert reached_runtime(runtime) == []
    assert application.shutdown(timeout_seconds=5) is True
    assert not application.guard.held
    successor = InstanceGuard(path)
    successor.acquire()  # free only now
    successor.release()


def test_a_concurrent_spawn_cannot_make_shutdown_forget_the_unstarted_worker(
    app: tuple[Application, ScriptedRuntime, Path], start_barrier: Callable[..., StartBarrier]
) -> None:
    application, runtime, _ = app
    first = application.conversations.create_conversation(application.owner).id
    second = application.conversations.create_conversation(application.owner).id
    barrier = start_barrier(limit=1)  # only the first worker is parked; the second starts normally
    parked, parked_box = submit_async(application, first)
    assert barrier.reached.wait(5)

    runtime.await_gate.arm()
    other, other_box = submit_async(application, second)  # a second spawn: the old code's filter
    other.join(5)
    assert runtime.await_gate.wait_entered()  # it is really running

    names = application.execution.threads.outstanding()
    # both workers (the parked one and the running one) and the running one's watchdog
    assert len([n for n in names if n.startswith("anonymous-run-")]) == 2
    assert len([n for n in names if n.startswith("anonymous-watchdog-")]) == 1
    assert application.shutdown(timeout_seconds=0.2) is False
    assert application.guard.held

    barrier.release.set()
    runtime.await_gate.release()
    parked.join(5)
    assert wait_until(lambda: application.execution.threads.outstanding() == [])
    assert application.shutdown(timeout_seconds=5) is True
    assert not application.guard.held
    assert not isinstance(parked_box[0], BaseException)
    assert not isinstance(other_box[0], BaseException)


def test_a_worker_thread_the_os_refuses_to_start_settles_the_run_and_releases_cleanly(
    app: tuple[Application, ScriptedRuntime, Path], start_barrier: Callable[..., StartBarrier]
) -> None:
    application, runtime, _ = app
    cid = application.conversations.create_conversation(application.owner).id
    barrier = start_barrier()
    barrier.fail_with = RuntimeError("can't start new thread")
    barrier.release.set()
    outcome = application.execution.begin_submit(
        owner=application.owner,
        conversation_id=cid,
        submission_id=SubmissionId(new_uuid()),
        content="q",
    ).wait(5)
    # Non-start is established: the run never dispatched, the conversation is not stuck, and the
    # reservation and live mark were released only after the run was settled.
    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.failure_code == "interrupted_before_dispatch"
    assert outcome.run.handoff is None and reached_runtime(runtime) == []
    assert application.execution.threads.outstanding() == []
    assert not application.execution.controls.has_live_worker(outcome.run.id)
    assert application.shutdown(timeout_seconds=1) is True


def test_a_start_that_cannot_be_confirmed_keeps_ownership(
    app: tuple[Application, ScriptedRuntime, Path], start_barrier: Callable[..., StartBarrier]
) -> None:
    application, _, _ = app
    cid = application.conversations.create_conversation(application.owner).id

    class Interrupted(BaseException):
        pass

    barrier = start_barrier()
    barrier.fail_with = Interrupted()
    barrier.release.set()
    with pytest.raises(Interrupted):
        application.execution.begin_submit(
            owner=application.owner,
            conversation_id=cid,
            submission_id=SubmissionId(new_uuid()),
            content="q",
        )
    assert application.shutdown(timeout_seconds=0.1) is False  # never claims quiescence
    assert application.guard.held


def test_nothing_new_is_accepted_once_shutdown_has_begun(
    app: tuple[Application, ScriptedRuntime, Path],
) -> None:
    application, runtime, _ = app
    cid = application.conversations.create_conversation(application.owner).id
    assert application.shutdown(timeout_seconds=1) is True
    with pytest.raises(GenerationBlocked):
        application.execution.begin_submit(
            owner=application.owner,
            conversation_id=cid,
            submission_id=SubmissionId(new_uuid()),
            content="q",
        )
    with pytest.raises(GenerationBlocked):
        application.execution.reconcile()
    assert reached_runtime(runtime) == []


# -- finding 2: pending admission versus orphan detection -----------------------------------------


def make(
    store: SqliteStore, owner: UserId
) -> tuple[Services, FaultyExecutionStore, ScriptedRuntime, Scheduler, ConversationId]:
    runtime = ScriptedRuntime()
    scheduler = Scheduler()
    faulty = FaultyExecutionStore(store)
    services = Services(faulty, runtime, checkpoint=scheduler)
    return (
        services,
        faulty,
        runtime,
        scheduler,
        services.conversations.create_conversation(owner).id,
    )


def reconcile_during_admission(
    services: Services, scheduler: Scheduler, observed: dict[str, Any]
) -> Callable[[], None]:
    """A hook that runs *between the admission commit and the live mark* and starts a reconcile."""
    scanned = threading.Event()
    waiting = threading.Event()
    scheduler.hooks["orphan_scan_waiting"] = lambda run_id: waiting.set()
    scheduler.hooks["orphan_scan_done"] = lambda run_id: scanned.set()

    def hook() -> None:
        thread, box = in_thread(services.coordinator.reconcile)
        observed["thread"], observed["box"] = thread, box
        assert waiting.wait(5)  # the competing reconcile has reached the orphan-scan gate
        gate = services.coordinator.controls.admission_gate
        # Either it is parked on the gate (correct) or it has already scanned (the defect).
        wait_until(lambda: gate.waiting() == 1 or scanned.is_set())
        observed["blocked"] = gate.waiting() == 1 and not scanned.is_set()

    return hook


def test_a_reconcile_cannot_settle_a_pending_run_whose_worker_is_not_yet_registered(
    store: SqliteStore, owner: UserId
) -> None:
    services, faulty, runtime, scheduler, cid = make(store, owner)
    observed: dict[str, Any] = {}
    faulty.script(
        "admit_submission",
        Fault("after", hook=reconcile_during_admission(services, scheduler, observed)),
    )
    outcome = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    observed["thread"].join(5)
    report = observed["box"][0]
    assert observed["blocked"], "the reconcile was not held at the admission gate"
    # The accepted admission survived: it dispatched once and succeeded; reconcile settled nothing.
    assert outcome.run.status is RunStatus.SUCCEEDED and outcome.assistant_message is not None
    assert report.pending_settled == 0
    assert len(runtime.calls_of("start")) == 1
    history = store.get_history(owner, cid)
    assert [m.role.value for m in history.messages] == ["user", "assistant"]
    assert len(history.runs) == 1


def test_the_same_rule_protects_an_explicit_retry(store: SqliteStore, owner: UserId) -> None:
    services, faulty, runtime, scheduler, cid = make(store, owner)
    runtime.reply = ""  # the first attempt ends in a known failure (empty output): retry is allowed
    first = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
    )
    assert first.run.status is RunStatus.FAILED
    runtime.reply = "second try"
    observed: dict[str, Any] = {}
    faulty.script(
        "admit_retry",
        Fault("after", hook=reconcile_during_admission(services, scheduler, observed)),
    )
    retried = services.coordinator.retry(
        owner=owner,
        conversation_id=cid,
        retry_id=new_uuid(),
        message_id=first.user_message.id,
    )
    observed["thread"].join(5)
    assert observed["blocked"], "the reconcile was not held at the admission gate"
    assert observed["box"][0].pending_settled == 0
    assert retried.run.status is RunStatus.SUCCEEDED
    history = store.get_history(owner, cid)
    assert [m.role.value for m in history.messages] == ["user", "assistant"]  # no new user message
    assert [r.status for r in history.runs] == [RunStatus.FAILED, RunStatus.SUCCEEDED]
    assert len(runtime.calls_of("start")) == 2  # one invocation per run, none duplicated


def test_a_genuinely_abandoned_pending_run_is_still_recovered(
    store: SqliteStore, owner: UserId
) -> None:
    services, _, runtime, _, cid = make(store, owner)
    # Committed by a process that died before it could start a worker: nothing marks it live.
    from tests.persistence.test_store_behavior import admit

    abandoned = admit(store, owner, cid, "left behind").run
    assert services.coordinator.controls.has_live_worker(abandoned.id) is False
    report = services.coordinator.reconcile()
    assert report.pending_settled == 1
    run = store.get_run(abandoned.id)
    assert run.status is RunStatus.FAILED and run.failure_code == "interrupted_before_dispatch"
    assert reached_runtime(runtime) == []
    # and the conversation accepts new work again, exactly once
    again = services.coordinator.submit(
        owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="next"
    )
    assert again.run.status is RunStatus.SUCCEEDED and len(runtime.calls_of("start")) == 1


def test_startup_recovery_uses_the_same_orphan_rule(store: SqliteStore, owner: UserId) -> None:
    from tests.persistence.test_store_behavior import admit

    cid = store.create_conversation(owner, None).id
    admit(store, owner, cid, "left behind")
    services = Services(store, ScriptedRuntime(), boot_id="boot-after-crash")
    report = services.coordinator.startup()
    assert report.pending_settled == 1


def test_shutdown_during_the_admission_window_waits_and_the_run_is_never_dispatched(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime()
    scheduler = Scheduler()
    faulty = FaultyExecutionStore(store)
    services = Services(faulty, runtime, checkpoint=scheduler)
    cid = services.conversations.create_conversation(owner).id
    window = threading.Event()
    proceed = threading.Event()

    def hook() -> None:
        window.set()
        assert proceed.wait(10)

    faulty.script("admit_submission", Fault("after", hook=hook))
    submitter, box = in_thread(
        lambda: services.coordinator.begin_submit(
            owner=owner, conversation_id=cid, submission_id=SubmissionId(new_uuid()), content="q"
        )
    )
    assert window.wait(5)  # committed, not yet marked live, not yet started
    stopper, stopped = in_thread(lambda: services.coordinator.shutdown(5))
    assert wait_until(lambda: not services.coordinator.threads.accepting)
    assert services.coordinator.threads.outstanding() == ["admission"]  # shutdown must wait for it
    proceed.set()
    submitter.join(5)
    stopper.join(5)
    assert stopped == [True]
    assert not isinstance(box[0], BaseException)
    run = store.get_history(owner, cid).runs[0]
    assert run.status is RunStatus.FAILED and run.failure_code == "interrupted_before_dispatch"
    assert (
        reached_runtime(runtime) == []
    )  # shutdown won the race: nothing was ever sent to the runtime


def test_many_submitters_and_reconcilers_never_duplicate_or_lose_a_run(
    store: SqliteStore, owner: UserId
) -> None:
    runtime = ScriptedRuntime()
    services = Services(store, runtime)
    conversations = [services.conversations.create_conversation(owner).id for _ in range(8)]
    stop = threading.Event()
    errors: list[BaseException] = []

    def reconciler() -> None:
        while not stop.is_set():
            try:
                services.coordinator.reconcile()
            except GenerationBlocked:
                return
            except BaseException as error:
                errors.append(error)
                return

    reconcilers = [threading.Thread(target=reconciler) for _ in range(3)]
    for thread in reconcilers:
        thread.start()
    results: list[Any] = []

    def submitter(cid: ConversationId) -> None:
        for _ in range(5):
            results.append(
                services.coordinator.submit(
                    owner=owner,
                    conversation_id=cid,
                    submission_id=SubmissionId(new_uuid()),
                    content="q",
                )
            )

    submitters = [threading.Thread(target=submitter, args=(c,)) for c in conversations]
    for thread in submitters:
        thread.start()
    for thread in submitters:
        thread.join(60)
        assert not thread.is_alive(), "deadlock between admission, reconcile and the registry"
    stop.set()
    for thread in reconcilers:
        thread.join(10)
    assert errors == []
    assert len(results) == 40
    assert all(r.run.status is RunStatus.SUCCEEDED for r in results)  # no live admission settled
    assert len(runtime.calls_of("start")) == 40  # exactly one invocation per run
    for cid in conversations:
        history = store.get_history(owner, cid)
        assert len(history.messages) == 10 and len(history.runs) == 5
    assert services.coordinator.shutdown(5) is True
