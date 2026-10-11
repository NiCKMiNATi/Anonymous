"""Process ownership, shutdown, aliases and crash/restart with REAL processes (LD-04 §4.8, §9).

Nothing here is simulated with sleeps: contention is a second OS process refused by the exclusive
lock; a crash is ``SIGKILL`` delivered by the supervised thread itself at a named checkpoint; a
restart is a fresh ``build_application`` on the same dataset.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from anonymous.adapters.model.scripted import ScriptedRuntime
from anonymous.adapters.persistence.sqlite.instance_guard import DatasetIdentity, InstanceGuard
from anonymous.composition import build_application
from anonymous.config import Settings
from anonymous.domain.errors import OwnershipError
from anonymous.domain.evidence import EvidenceBasis, Handoff, LifetimeScope
from anonymous.domain.ids import ConversationId, SubmissionId, new_uuid
from anonymous.domain.models import RunStatus
from tests.conftest import FAST

pytestmark = pytest.mark.process

CHILD = textwrap.dedent(
    """
    import os, signal, sys
    from pathlib import Path
    from anonymous.adapters.model.scripted import ScriptedRuntime
    from anonymous.composition import build_application
    from anonymous.config import Settings
    from anonymous.domain.evidence import LifetimeScope
    from anonymous.domain.ids import new_uuid

    mode, db, point, scope = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    def checkpoint(name, run_id):
        if name == point:
            os.kill(os.getpid(), signal.SIGKILL)

    runtime = ScriptedRuntime(scope=LifetimeScope(scope))
    try:
        app = build_application(Settings(db_path=Path(db)), runtime=runtime, checkpoint=checkpoint)
    except Exception as error:
        print("REFUSED", type(error).__name__, flush=True)
        sys.exit(3)
    print("STARTED", flush=True)
    if mode == "hold":
        sys.stdin.readline()  # keep ownership until the parent closes stdin
        sys.exit(0)
    cid = app.conversations.create_conversation(app.owner).id
    print("CID", cid, flush=True)
    app.conversations.send_message(app.owner, cid, new_uuid(), "hello")
    print("DONE", flush=True)
    """
)


def spawn(
    mode: str, db: Path, point: str = "-", scope: str = "owning_process"
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", CHILD, mode, str(db), point, scope],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def read_until(proc: subprocess.Popen[str], prefix: str, timeout: float = 20.0) -> str:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith(prefix):
            return line.strip()
    raise AssertionError(f"child never printed {prefix!r}")


# -- canonical dataset identity and aliases ------------------------------------------------------


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    real = tmp_path / "data" / "real.sqlite3"
    real.parent.mkdir()
    return real


def test_every_alias_of_a_dataset_resolves_to_the_same_lock(dataset: Path, tmp_path: Path) -> None:
    from anonymous.adapters.persistence.sqlite.migrations import migrate

    migrate(dataset)
    file_link = tmp_path / "file-link.sqlite3"
    file_link.symlink_to(dataset)
    dir_link = tmp_path / "dir-link"
    dir_link.symlink_to(dataset.parent, target_is_directory=True)
    dotted = dataset.parent / ".." / "data" / "real.sqlite3"
    relative = Path(os.path.relpath(dataset, Path.cwd()))
    locks = {
        DatasetIdentity.validate(p).lock_path
        for p in (dataset, file_link, dir_link / "real.sqlite3", dotted, relative)
    }
    assert len(locks) == 1  # one dataset, one lock, whatever it is called

    first = InstanceGuard(dataset)
    first.acquire()
    try:
        for alias in (file_link, dir_link / "real.sqlite3", dotted, relative):
            with pytest.raises(OwnershipError, match="Another Anonymous server"):
                InstanceGuard(alias).acquire()
    finally:
        first.release()
    InstanceGuard(file_link).acquire()  # free again once released


def test_a_case_variant_alias_cannot_bypass_the_lock_on_a_case_insensitive_filesystem(
    dataset: Path,
) -> None:
    from anonymous.adapters.persistence.sqlite.migrations import migrate

    migrate(dataset)
    variant = dataset.parent / dataset.name.upper()
    if not variant.exists():
        pytest.skip("case-sensitive filesystem: the variant is a different dataset")
    first = InstanceGuard(dataset)
    first.acquire()
    try:
        with pytest.raises(OwnershipError):
            InstanceGuard(variant).acquire()
    finally:
        first.release()


def test_a_hard_linked_dataset_is_refused_because_it_would_bypass_the_lock(
    dataset: Path, tmp_path: Path
) -> None:
    from anonymous.adapters.persistence.sqlite.migrations import migrate

    migrate(dataset)
    alias = tmp_path / "hardlink.sqlite3"
    os.link(dataset, alias)
    for path in (dataset, alias):
        with pytest.raises(OwnershipError, match="hard link"):
            InstanceGuard(path)


@pytest.mark.parametrize("bad", [":memory:", "file:x?mode=memory", ""])
def test_special_names_are_not_acceptable_datasets(bad: str) -> None:
    with pytest.raises(OwnershipError):
        DatasetIdentity.validate(bad)


def test_a_missing_directory_or_a_non_regular_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OwnershipError):
        DatasetIdentity.validate(tmp_path / "nope" / "x.sqlite3")
    with pytest.raises(OwnershipError, match="regular file"):
        DatasetIdentity.validate(tmp_path)


# -- a second real process -----------------------------------------------------------------------


def test_a_second_process_is_refused_through_any_alias_while_the_first_owns_the_dataset(
    dataset: Path, tmp_path: Path
) -> None:
    alias_dir = tmp_path / "alias"
    alias_dir.symlink_to(dataset.parent, target_is_directory=True)
    owner = spawn("hold", dataset)
    try:
        read_until(owner, "STARTED")
        for alias in (alias_dir / dataset.name, dataset.parent / ".." / "data" / dataset.name):
            contender = spawn("hold", alias)
            line = read_until(contender, "REFUSED")
            assert "OwnershipError" in line
            assert contender.wait(10) == 3
    finally:
        assert owner.stdin is not None
        owner.stdin.close()
        assert owner.wait(10) == 0
    again = spawn("hold", dataset)  # ownership was released with the process
    try:
        read_until(again, "STARTED")
    finally:
        assert again.stdin is not None
        again.stdin.close()
        again.wait(10)


# -- hung worker during shutdown -----------------------------------------------------------------


def test_a_hung_worker_keeps_ownership_until_it_ends_and_never_releases_to_finish_shutdown(
    dataset: Path,
) -> None:
    runtime = ScriptedRuntime()
    runtime.ignore_deadline = True
    runtime.await_gate.arm()
    app = build_application(Settings(db_path=dataset), runtime=runtime, execution_settings=FAST)
    cid = app.conversations.create_conversation(app.owner).id
    handle = app.execution.begin_submit(
        owner=app.owner,
        conversation_id=cid,
        submission_id=SubmissionId(new_uuid()),
        content="q",
    )
    assert runtime.await_gate.wait_entered()

    assert app.shutdown(timeout_seconds=0.3) is False  # a worker is still alive: incomplete
    assert app.guard.held  # ownership was NOT released to complete the shutdown
    contender = spawn("hold", dataset)
    try:
        assert "OwnershipError" in read_until(contender, "REFUSED")  # no second owner can appear
        assert contender.wait(10) == 3
    finally:
        pass
    run = app.store.get_run(handle.run_id)
    assert run.status is RunStatus.INDETERMINATE  # closed and quarantined, never guessed at

    runtime.await_gate.release()  # the hung worker finally returns
    handle.wait(5)
    assert app.shutdown(timeout_seconds=5) is True
    assert not app.guard.held
    settled = app.store.get_run(handle.run_id)
    assert settled.status is RunStatus.FAILED
    successor = spawn("hold", dataset)
    try:
        read_until(successor, "STARTED")  # now, and only now, another process may own it
    finally:
        assert successor.stdin is not None
        successor.stdin.close()
        successor.wait(10)


# -- crash and restart ---------------------------------------------------------------------------


def crash_at(dataset: Path, point: str, scope: str = "owning_process") -> ConversationId:
    child = spawn("send", dataset, point, scope)
    cid = read_until(child, "CID").split()[1]
    assert child.wait(20) == -signal.SIGKILL  # a real crash: no cleanup of any kind ran
    return ConversationId(cid)


@pytest.mark.parametrize(
    ("point", "basis", "handoff"),
    [
        ("before_gate", EvidenceBasis.NEVER_DISPATCHED, Handoff.NONE),  # T3 durable, T3b not
        ("after_t3b", EvidenceBasis.PROCESS_EXIT_VERIFIED, Handoff.STARTED),  # start never called
        ("before_await", EvidenceBasis.PROCESS_EXIT_VERIFIED, Handoff.STARTED),
        ("before_publish", EvidenceBasis.PROCESS_EXIT_VERIFIED, Handoff.STARTED),
    ],
)
def test_crash_and_restart_settles_only_on_evidence_and_never_re_invokes(
    dataset: Path, point: str, basis: EvidenceBasis, handoff: Handoff
) -> None:
    cid = crash_at(dataset, point)
    runtime = ScriptedRuntime()  # the restarted process has a different runtime instance
    app = build_application(Settings(db_path=dataset), runtime=runtime, execution_settings=FAST)
    try:
        assert app.startup_report.settled == 1 and app.startup_report.still_unresolved == 0
        run = app.store.get_history(app.owner, cid).runs[0]
        assert run.status is RunStatus.FAILED and run.handoff is handoff
        assert run.termination_basis is basis
        assert run.failure_code in ("interrupted_before_dispatch", "interrupted_server_restart")
        assert runtime.calls_of("start") == []  # reconcile never invokes the model
        history = app.conversations.open_conversation(app.owner, cid)
        assert [m.role.value for m in history.messages] == ["user"]  # user input preserved
        again = app.conversations.send_message(app.owner, cid, new_uuid(), "again")
        assert again.assistant_message is not None  # the conversation and the slot are free
    finally:
        assert app.shutdown()


def test_crash_with_an_external_runtime_leaves_the_slot_quarantined_after_restart(
    dataset: Path,
) -> None:
    cid = crash_at(dataset, "before_await", scope="external")
    for _ in range(2):  # restarting again does not help: a restart is not evidence
        app = build_application(
            Settings(db_path=dataset),
            runtime=ScriptedRuntime(scope=LifetimeScope.EXTERNAL),
            execution_settings=FAST,
        )
        try:
            assert app.startup_report.still_unresolved == 1
            run = app.store.get_history(app.owner, cid).runs[0]
            assert run.status is RunStatus.INDETERMINATE and run.termination_basis is None
            assert app.store.generation_state().quarantined_runs == (run.id,)
            assert app.conversations.open_conversation(app.owner, cid).messages  # readable
        finally:
            assert app.shutdown()
