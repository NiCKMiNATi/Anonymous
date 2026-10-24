"""The dev launcher and cleanup tool: identity-verified, never touching SQLite (ADR-0015).

Real processes are used only for harmless stand-ins this test starts itself (a socket-holding
script and ``sleep``); no llama.cpp binary, model or network beyond an ephemeral loopback listener.
"""

from __future__ import annotations

import ast
import ctypes
import errno
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from anonymous.adapters.model import llama_ctl
from anonymous.adapters.model.llama_ctl import CtlError, build_command, launch, status, stop
from anonymous.adapters.model.llama_launch_record import (
    ArtifactIdentity,
    LaunchRecord,
    read_record,
    write_record,
)
from anonymous.adapters.model.process_identity import (
    DarwinInspector,
    IdentityUnavailable,
    ProcessIdentity,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS process identity only")

STUB = textwrap.dedent(
    """\
    #!{python}
    import socket, sys, time
    argv = sys.argv
    port = int(argv[argv.index("--port") + 1])
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    time.sleep(120)
    """
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def children() -> Iterator[list[int]]:
    pids: list[int] = []
    yield pids
    for pid in pids:  # only children this test started; an already-reaped pid is never signalled
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue
        if done == 0:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


class Spawner:
    """Records the processes ``launch`` starts; ``check`` runs just before each spawn."""

    def __init__(self, check: Callable[[], None] | None = None) -> None:
        self.processes: list[subprocess.Popen[bytes]] = []
        self.check = check

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if self.check is not None:
            self.check()
        process = subprocess.Popen(*args, **kwargs)
        self.processes.append(process)
        return process


@pytest.fixture
def popens() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for process in started:  # only processes this test started, still held as unreaped children
        if process.poll() is None:
            process.kill()
            process.wait()


class Faulty:
    """The real inspector with injected inspection failures."""

    def __init__(self) -> None:
        self._real = DarwinInspector()
        self.calls = 0
        self.ok_calls: int | None = None  # identity_of works this many times, then fails
        self.exc: BaseException = IdentityUnavailable("injected")
        self.fail_listeners = False
        self.wait_for: Path | None = None  # hold the first failure until this file exists

    def identity_of(self, pid: int) -> ProcessIdentity | None:
        self.calls += 1
        if self.ok_calls is not None and self.calls > self.ok_calls:
            if self.wait_for is not None:
                deadline = time.monotonic() + 10
                while not self.wait_for.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
            raise self.exc
        return self._real.identity_of(pid)

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        if self.fail_listeners:
            raise IdentityUnavailable("injected")
        return self._real.listeners(port)


STUBBORN = textwrap.dedent(
    """\
    #!{python}
    import pathlib, signal, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(sys.argv[0] + ".ready").write_text("ready")
    time.sleep(120)
    """
)


def plain_args(tmp_path: Path, binary: Path, model: Path, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        record_path=tmp_path / "rec" / "launch.json",
        runtime_bin=binary,
        model=model,
        port=free_port(),
        model_label="m",
        runtime_label="r",
        sandbox=False,
        ready_timeout_seconds=20.0,
        contain_wait_seconds=0.5,
    )
    base.update(kw)
    return base


def files_in(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


@pytest.fixture
def stub(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "fake-llama-server"
    binary.write_text(STUB.format(python=sys.executable))
    binary.chmod(0o755)
    model = tmp_path / "fake-model.gguf"
    model.write_bytes(b"synthetic model bytes")
    return binary, model


def do_launch(tmp_path: Path, stub: tuple[Path, Path], children: list[int], **kw):  # type: ignore[no-untyped-def]
    binary, model = stub
    port = free_port()
    record = launch(
        record_path=tmp_path / "rec" / "launch.json",
        runtime_bin=binary,
        model=model,
        port=port,
        model_label="Qwen3-4B-Q4_K_M",
        runtime_label="llama.cpp-b11440",
        sandbox=False,
        ready_timeout_seconds=20.0,
        **kw,
    )
    children.append(record.pid)
    return record, tmp_path / "rec" / "launch.json"


# -- launch / status / stop on a real stand-in process ---------------------------------------------


def test_launch_records_the_kernel_identity_independent_private_files(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    record, path = do_launch(tmp_path, stub, children)
    live = DarwinInspector().identity_of(record.pid)
    assert live == ProcessIdentity(record.pid, record.start)
    assert record.host == "127.0.0.1" and read_record(path) == record
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(record.key_file.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    assert os.getsid(record.pid) == record.pid  # its own session: independent of this tool
    report = status(path)
    assert report["process_identity_matches"] and report["sole_listener_is_recorded_process"]
    dumped = json.dumps(report)
    assert str(tmp_path) not in dumped and record.key_file.read_text() not in dumped


def test_stop_signals_only_the_verified_process_and_can_remove_the_files(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    record, path = do_launch(tmp_path, stub, children)
    sent: list[tuple[int, int]] = []

    def send(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        os.kill(pid, sig)

    report = stop(path, remove_files=True, wait_seconds=10.0, send=send)
    os.waitpid(record.pid, 0)
    assert sent == [(record.pid, signal.SIGTERM)]
    assert report["result"] in ("terminated", "already_gone") and report["signalled"]
    assert not path.exists() and not record.key_file.exists()


def test_stop_refuses_an_identity_mismatch_and_signals_nothing(
    tmp_path: Path, children: list[int]
) -> None:
    victim = subprocess.Popen(["/bin/sleep", "60"])
    children.append(victim.pid)
    live = DarwinInspector().identity_of(victim.pid)
    assert live is not None
    key = tmp_path / "rec" / "key"
    key.parent.mkdir(mode=0o700)
    key.write_text("k" * 32)
    key.chmod(0o600)
    record = LaunchRecord(
        nonce="1" * 32,
        pid=victim.pid,
        start=(live.start[0] - 1000, live.start[1]),  # same pid, different process lifetime
        host="127.0.0.1",
        port=19999,
        key_file=key,
        model=ArtifactIdentity("m", None, "unspecified"),
        runtime=ArtifactIdentity("r", None, "unspecified"),
        created_utc=1.0,
    )
    path = tmp_path / "rec" / "launch.json"
    write_record(path, record)
    sent: list[tuple[int, int]] = []
    with pytest.raises(CtlError) as caught:
        stop(path, send=lambda pid, sig: sent.append((pid, sig)))
    assert caught.value.code == "identity_mismatch" and caught.value.exit_code == 3
    assert sent == [] and victim.poll() is None  # untouched and still running
    assert path.exists()


def test_stop_of_a_process_that_is_gone_signals_nothing(tmp_path: Path) -> None:
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    key = tmp_path / "rec" / "key"
    key.parent.mkdir(mode=0o700)
    key.write_text("k" * 32)
    key.chmod(0o600)
    path = tmp_path / "rec" / "launch.json"
    write_record(
        path,
        LaunchRecord(
            nonce="2" * 32,
            pid=dead.pid,
            start=(1, 1),
            host="127.0.0.1",
            port=19998,
            key_file=key,
            model=ArtifactIdentity("m", None, "unspecified"),
            runtime=ArtifactIdentity("r", None, "unspecified"),
            created_utc=1.0,
        ),
    )
    sent: list[tuple[int, int]] = []
    report = stop(path, send=lambda pid, sig: sent.append((pid, sig)), remove_files=True)
    assert report["result"] == "already_gone" and not report["signalled"] and sent == []
    assert not path.exists()


def test_a_second_launch_over_a_live_runtime_is_refused(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    do_launch(tmp_path, stub, children)
    with pytest.raises(CtlError) as caught:
        do_launch(tmp_path, stub, children)
    assert caught.value.code == "already_running"


def test_a_port_in_use_is_refused(tmp_path: Path, stub: tuple[Path, Path]) -> None:
    binary, model = stub
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = int(held.getsockname()[1])
        with pytest.raises(CtlError) as caught:
            launch(
                record_path=tmp_path / "rec" / "launch.json",
                runtime_bin=binary,
                model=model,
                port=port,
                model_label="m",
                runtime_label="r",
                sandbox=False,
            )
    assert caught.value.code == "port_in_use"


# -- artifact identity: a pin is a claim, hashing is a check ---------------------------------------


def test_a_pin_without_hashing_is_only_asserted_and_hashing_verifies(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    _, model = stub
    digest = llama_ctl.sha256_file(model)
    record, _ = do_launch(tmp_path, stub, children, model_sha256=digest)
    assert record.model == ArtifactIdentity("Qwen3-4B-Q4_K_M", digest, "asserted")
    assert record.runtime == ArtifactIdentity("llama.cpp-b11440", None, "unspecified")
    sub = tmp_path / "second"
    sub.mkdir()
    second = launch(
        record_path=sub / "rec" / "launch.json",
        runtime_bin=stub[0],
        model=model,
        port=free_port(),
        model_label="m",
        runtime_label="r",
        model_sha256=digest,
        hash_artifacts=True,
        sandbox=False,
        ready_timeout_seconds=20.0,
    )
    children.append(second.pid)
    assert second.model == ArtifactIdentity("m", digest, "verified")
    assert second.runtime.verification == "verified"


def test_a_wrong_pin_is_refused_when_hashing(tmp_path: Path, stub: tuple[Path, Path]) -> None:
    binary, model = stub
    with pytest.raises(CtlError) as caught:
        launch(
            record_path=tmp_path / "rec" / "launch.json",
            runtime_bin=binary,
            model=model,
            port=free_port(),
            model_label="m",
            runtime_label="r",
            model_sha256="0" * 64,
            hash_artifacts=True,
            sandbox=False,
        )
    assert caught.value.code == "artifact_digest_mismatch"
    assert not (tmp_path / "rec" / "launch.json").exists()


@pytest.mark.parametrize("bad", ["abc", "G" * 64, "a" * 63])
def test_malformed_pins_are_refused(tmp_path: Path, stub: tuple[Path, Path], bad: str) -> None:
    binary, model = stub
    with pytest.raises(CtlError) as caught:
        launch(
            record_path=tmp_path / "rec" / "launch.json",
            runtime_bin=binary,
            model=model,
            port=free_port(),
            model_label="m",
            runtime_label="r",
            model_sha256=bad,
            sandbox=False,
        )
    assert caught.value.code == "pin_invalid"


def test_relative_or_missing_artifacts_are_refused(tmp_path: Path, stub: tuple[Path, Path]) -> None:
    binary, model = stub
    with pytest.raises(CtlError) as caught:
        launch(
            record_path=tmp_path / "r" / "l.json",
            runtime_bin=Path("llama-server"),
            model=model,
            port=free_port(),
            model_label="m",
            runtime_label="r",
            sandbox=False,
        )
    assert caught.value.code == "runtime_missing"
    with pytest.raises(CtlError) as caught:
        launch(
            record_path=tmp_path / "r" / "l.json",
            runtime_bin=binary,
            model=tmp_path / "none.gguf",
            port=free_port(),
            model_label="m",
            runtime_label="r",
            sandbox=False,
        )
    assert caught.value.code == "model_missing"


# -- the pinned launch profile --------------------------------------------------------------------


def test_the_launch_command_is_the_pinned_loopback_sandboxed_profile() -> None:
    command = build_command(
        runtime_bin=Path("/x/llama-server"),
        model=Path("/x/m.gguf"),
        key_file=Path("/x/key"),
        port=18080,
    )
    assert command[:2] == [llama_ctl.SANDBOX_EXEC, "-p"]
    profile = command[2]
    assert "(deny network-outbound)" in profile and "(deny process-fork)" in profile
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "18080"
    assert command[command.index("--api-key-file") + 1] == "/x/key"
    for flag in ("--no-cache-prompt", "--offline", "--no-context-shift", "--no-webui"):
        assert flag in command
    assert command[command.index("-np") + 1] == "1"
    assert "0.0.0.0" not in command and "--api-key" not in command  # the key is never an argument


def test_the_child_environment_is_an_allow_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("LLAMA_ARG_HOST", "0.0.0.0")
    env = llama_ctl.child_environment(tmp_path)
    assert env["PATH"] == "/usr/bin:/bin" and env["HF_HUB_OFFLINE"] == "1"
    assert "ANTHROPIC_API_KEY" not in env and "LLAMA_ARG_HOST" not in env


# -- structural: process hygiene and no persistence access -------------------------------------


def _tree() -> ast.AST:
    return ast.parse(Path(llama_ctl.__file__).read_text(encoding="utf-8"))


def test_the_tool_never_signals_groups_or_escalates() -> None:
    attributes = {n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(_tree()) if isinstance(n, ast.Name)}
    assert not attributes & {"killpg", "SIGKILL", "SIGINT", "SIGHUP", "kill_process"}
    assert not names & {"killpg", "SIGKILL"}
    strings = {
        n.value
        for n in ast.walk(_tree())
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert not {"pkill", "killall", "kill -9"} & strings


def test_the_tool_cannot_reach_sqlite_or_settlement() -> None:
    imported: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("sqlite3", "anonymous.application", "anonymous.domain", "anonymous.composition")
    assert not [m for m in imported if m.startswith(forbidden) or "persistence" in m]


def test_a_started_process_that_never_listens_is_contained_through_its_handle(
    tmp_path: Path, children: list[int]
) -> None:
    binary = tmp_path / "silent"
    binary.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    binary.chmod(0o755)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    spawner = Spawner()
    started = time.monotonic()
    with pytest.raises(CtlError) as caught:
        launch(
            record_path=tmp_path / "rec" / "launch.json",
            runtime_bin=binary,
            model=model,
            port=free_port(),
            model_label="m",
            runtime_label="r",
            sandbox=False,
            ready_timeout_seconds=1.5,
            spawn=spawner,
        )
    assert caught.value.code == "not_ready_in_time" and time.monotonic() - started < 15
    assert spawner.processes[0].poll() is not None  # terminated through the Popen handle
    assert not (tmp_path / "rec" / "launch.json").exists()
    assert not [p for p in (tmp_path / "rec").iterdir() if p.name.startswith("key-")]


# -- F1: the spawn-to-record interval -------------------------------------------------------


@pytest.mark.parametrize("kind", ["relative", "parent_ref", "symlink_parent"])
def test_an_unsafe_record_path_is_refused_before_anything_is_spawned(
    tmp_path: Path, stub: tuple[Path, Path], kind: str
) -> None:
    binary, model = stub

    def never() -> None:
        raise AssertionError("spawned with an unsafe record path")

    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    path = {
        "relative": Path("rel") / "launch.json",
        "parent_ref": tmp_path / "x" / ".." / "launch.json",
        "symlink_parent": tmp_path / "link" / "launch.json",
    }[kind]
    before = files_in(tmp_path) + files_in(real)
    with pytest.raises(CtlError):
        launch(**plain_args(tmp_path, binary, model, record_path=path, spawn=Spawner(never)))
    assert files_in(tmp_path) + files_in(real) == before  # nothing was created


def test_a_durable_intent_exists_before_the_spawn_and_is_gone_once_the_record_is_durable(
    tmp_path: Path, stub: tuple[Path, Path], popens: list[subprocess.Popen[bytes]]
) -> None:
    binary, model = stub
    rec = tmp_path / "rec"
    seen: dict[str, object] = {}

    def check() -> None:
        intent = rec / "launch.json.intent"
        seen["intent_mode"] = oct(intent.stat().st_mode & 0o777)
        seen["intent"] = json.loads(intent.read_text())
        seen["key_exists"] = any(p.name.startswith("key-") for p in rec.iterdir())

    spawner = Spawner(check)
    record = launch(**plain_args(tmp_path, binary, model, spawn=spawner))
    popens.extend(spawner.processes)
    assert seen["intent_mode"] == "0o600" and seen["key_exists"] is True
    intent = seen["intent"]
    assert isinstance(intent, dict) and intent["nonce"] == record.nonce
    assert not (rec / "launch.json.intent").exists() and (rec / "launch.json").exists()


def test_a_failed_spawn_removes_everything_it_created(
    tmp_path: Path, stub: tuple[Path, Path]
) -> None:
    binary, model = stub

    def failing(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        raise OSError("synthetic spawn failure")

    with pytest.raises(CtlError) as caught:
        launch(**plain_args(tmp_path, binary, model, spawn=failing))
    assert caught.value.code == "spawn_failed"
    leftovers = [n for n in files_in(tmp_path / "rec") if n != "llama-cache"]
    assert leftovers == []


@pytest.mark.parametrize("fault", ["identity_unavailable", "interrupt", "record_write"])
def test_a_failure_between_spawn_and_record_is_contained_and_cleaned(
    tmp_path: Path,
    stub: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    popens: list[subprocess.Popen[bytes]],
    fault: str,
) -> None:
    binary, model = stub
    spawner = Spawner()
    inspector = Faulty()
    expected: type[BaseException] = IdentityUnavailable
    if fault == "identity_unavailable":
        inspector.ok_calls = 0
    elif fault == "interrupt":
        inspector.ok_calls, inspector.exc, expected = 0, KeyboardInterrupt(), KeyboardInterrupt
    else:

        def broken(path: Path, record: LaunchRecord) -> None:
            raise OSError("synthetic write failure")

        monkeypatch.setattr(llama_ctl, "write_record", broken)
        expected = CtlError
    with pytest.raises(expected) as caught:
        launch(**plain_args(tmp_path, binary, model, inspector=inspector, spawn=spawner))
    popens.extend(spawner.processes)
    if fault == "record_write":
        assert isinstance(caught.value, CtlError) and caught.value.code == "record_not_persisted"
    assert spawner.processes[0].poll() is not None  # the child is gone: no unrecorded survivor
    leftovers = [n for n in files_in(tmp_path / "rec") if n != "llama-cache"]
    assert leftovers == []  # no key, intent, log-less record: all removed because it is gone


def test_a_survivor_that_cannot_be_recorded_leaves_recovery_state_and_blocks_a_new_launch(
    tmp_path: Path, children: list[int], popens: list[subprocess.Popen[bytes]]
) -> None:
    binary = tmp_path / "stubborn"
    binary.write_text(STUBBORN.format(python=sys.executable))
    binary.chmod(0o755)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    spawner = Spawner()
    inspector = Faulty()
    inspector.ok_calls = 0
    inspector.wait_for = Path(str(binary) + ".ready")  # SIGTERM is ignored only once this exists
    with pytest.raises(CtlError) as caught:
        launch(**plain_args(tmp_path, binary, model, inspector=inspector, spawn=spawner))
    popens.extend(spawner.processes)
    survivor = spawner.processes[0]
    assert caught.value.code == "runtime_may_survive_unrecorded"
    assert caught.value.recovery is not None and caught.value.recovery["pid"] == survivor.pid
    assert survivor.poll() is None  # it really survived SIGTERM
    names = files_in(tmp_path / "rec")
    assert "launch.json.intent" in names and any(n.startswith("key-") for n in names)
    assert "launch.json" not in names
    # Fail closed: nothing further is launched, signalled, guessed or deleted by the tool.
    sent: list[tuple[int, int]] = []
    with pytest.raises(CtlError) as again:
        launch(**plain_args(tmp_path, binary, model, spawn=Spawner()))
    assert again.value.code == "unresolved_launch_intent"
    calls: list[Callable[[], object]] = [
        lambda: status(tmp_path / "rec" / "launch.json"),
        lambda: stop(tmp_path / "rec" / "launch.json", send=lambda p, s: sent.append((p, s))),
    ]
    for call in calls:
        with pytest.raises(CtlError) as refused:
            call()
        assert refused.value.code == "launch_intent_without_record"
    assert sent == [] and survivor.poll() is None
    assert files_in(tmp_path / "rec") == names


class InterruptedSpawner(Spawner):
    """``Popen`` interrupted after the fork: the child exists but no handle is ever returned."""

    def __init__(self, *, start_child: bool) -> None:
        super().__init__()
        self.start_child = start_child

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        if self.start_child:
            self.processes.append(subprocess.Popen(*args, **kwargs))
        raise KeyboardInterrupt


@pytest.mark.parametrize("start_child", [True, False])
def test_an_interrupt_during_popen_keeps_the_recovery_evidence_instead_of_guessing(
    tmp_path: Path,
    stub: tuple[Path, Path],
    popens: list[subprocess.Popen[bytes]],
    start_child: bool,
) -> None:
    binary, model = stub
    spawner = InterruptedSpawner(start_child=start_child)
    with pytest.raises(CtlError) as caught:
        launch(**plain_args(tmp_path, binary, model, spawn=spawner))
    popens.extend(spawner.processes)  # the test, not the tool, cleans up the stand-in child
    assert caught.value.code == "spawn_status_unknown"
    recovery = caught.value.recovery
    assert recovery is not None and recovery["pid"] is None  # no handle: no pid is claimed
    names = files_in(tmp_path / "rec")
    assert "launch.json.intent" in names and "launch.json" not in names
    assert f"key-{recovery['nonce']}" in names and f"runtime-{recovery['nonce']}.log" in names
    # The nonce in the retained intent is what identifies a surviving child by its command line.
    intent = json.loads((tmp_path / "rec" / "launch.json.intent").read_text())
    assert intent["nonce"] == recovery["nonce"] and intent["port"] == recovery["port"]
    # Fail closed: a further launch is refused and nothing is deleted or signalled.
    with pytest.raises(CtlError) as again:
        launch(**plain_args(tmp_path, binary, model, spawn=Spawner()))
    assert again.value.code == "unresolved_launch_intent"
    assert files_in(tmp_path / "rec") == names


class RacingInspector:
    """Another launcher claims the intent after this launcher's pre-checks and before its create."""

    def __init__(self, intent: Path) -> None:
        self._real = DarwinInspector()
        self.intent = intent

    def identity_of(self, pid: int) -> ProcessIdentity | None:
        return self._real.identity_of(pid)

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        if not self.intent.exists():
            self.intent.write_text('{"winner": true}')
            self.intent.chmod(0o600)
        return self._real.listeners(port)


def test_a_launcher_that_loses_the_intent_race_never_deletes_the_winners_intent(
    tmp_path: Path, stub: tuple[Path, Path]
) -> None:
    binary, model = stub
    rec = tmp_path / "rec"
    intent = rec / "launch.json.intent"
    inspector = RacingInspector(intent)
    spawner = Spawner()
    with pytest.raises(CtlError) as caught:
        launch(**plain_args(tmp_path, binary, model, inspector=inspector, spawn=spawner))
    assert caught.value.code == "unresolved_launch_intent"
    assert spawner.processes == []  # nothing was spawned by the loser
    assert intent.read_text() == '{"winner": true}'  # the winner's evidence is intact
    assert [n for n in files_in(rec) if n != "llama-cache"] == ["launch.json.intent"]


def test_a_retained_intent_tells_the_operator_the_nonce_and_port_but_no_paths(
    tmp_path: Path,
    stub: tuple[Path, Path],
    popens: list[subprocess.Popen[bytes]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    binary, model = stub
    spawner = InterruptedSpawner(start_child=False)
    with pytest.raises(CtlError) as caught:
        launch(**plain_args(tmp_path, binary, model, spawn=spawner))
    popens.extend(spawner.processes)
    nonce = caught.value.recovery["nonce"] if caught.value.recovery else ""
    for command in (
        ["status"],
        ["stop", "--remove-files"],
        [
            "launch",
            "--runtime-bin",
            str(binary),
            "--model",
            str(model),
            "--model-label",
            "m",
            "--runtime-label",
            "r",
        ],
    ):
        code = llama_ctl.main(["--record", str(tmp_path / "rec" / "launch.json"), *command])
        err = capsys.readouterr().err
        assert code == 5 and nonce in err and str(tmp_path) not in err
        assert "launch_intent_without_record" in err or "unresolved_launch_intent" in err
    assert (tmp_path / "rec" / "launch.json.intent").exists()  # nothing was removed


def test_cli_errors_name_codes_and_never_absolute_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    binary, model = tmp_path / "bin", tmp_path / "model"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    model.write_bytes(b"x")
    common = [
        "launch",
        "--runtime-bin",
        str(binary),
        "--model",
        str(model),
        "--model-label",
        "m",
        "--runtime-label",
        "r",
    ]
    # a record under a regular file: an expected filesystem failure
    code = llama_ctl.main(["--record", str(blocker / "sub" / "launch.json"), *common])
    err = capsys.readouterr().err
    assert code == 2 and str(tmp_path) not in err and "refused" in err
    code = llama_ctl.main(["--record", "relative/launch.json", *common])
    err = capsys.readouterr().err
    assert (
        code == 2
        and "record_path_not_absolute" in err
        and "relative" not in err.replace("record_path_not_absolute", "")
    )


# -- F2: an inconclusive inspection is not absence -------------------------------------------


class FakeLib:
    def __init__(self, result: int, errno_value: int) -> None:
        self.result, self.errno_value = result, errno_value

    def proc_pidinfo(self, *args: object) -> int:
        ctypes.set_errno(self.errno_value)
        return self.result


def test_only_a_positive_no_such_process_is_absence() -> None:
    inspector = DarwinInspector()
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    assert inspector.identity_of(dead.pid) is None  # the kernel says ESRCH
    for result, errno_value in ((0, errno.ESRCH), (-1, errno.ESRCH)):
        inspector._lib = FakeLib(result, errno_value)  # type: ignore[assignment]
        assert inspector.identity_of(4242) is None
    for result, errno_value in ((-1, errno.EPERM), (0, 0), (0, errno.EPERM), (8, 0), (-1, 0)):
        inspector._lib = FakeLib(result, errno_value)  # type: ignore[assignment]
        with pytest.raises(IdentityUnavailable):
            inspector.identity_of(4242)


def test_stop_with_an_inconclusive_inspection_deletes_nothing_and_signals_nothing(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    record, path = do_launch(tmp_path, stub, children)
    inspector = Faulty()
    inspector.ok_calls = 0
    sent: list[tuple[int, int]] = []
    with pytest.raises(IdentityUnavailable):
        stop(
            path,
            inspector=inspector,
            remove_files=True,
            send=lambda pid, sig: sent.append((pid, sig)),
        )
    assert sent == [] and path.exists() and record.key_file.exists()
    assert DarwinInspector().identity_of(record.pid) is not None  # still running


def test_status_reports_an_inconclusive_inspection_instead_of_inventing_a_state(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    _, path = do_launch(tmp_path, stub, children)
    inspector = Faulty()
    inspector.ok_calls = 0
    with pytest.raises(IdentityUnavailable):
        status(path, inspector)


def test_a_previous_record_is_never_replaced_on_uncertain_process_state(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    record, path = do_launch(tmp_path, stub, children)
    before = path.read_bytes()
    inspector = Faulty()
    inspector.ok_calls = 0
    spawner = Spawner()
    with pytest.raises(IdentityUnavailable):
        launch(**plain_args(tmp_path, *stub, inspector=inspector, spawn=spawner))
    assert spawner.processes == [] and path.read_bytes() == before and record.key_file.exists()


def test_an_inspection_failure_after_sigterm_keeps_the_files_even_when_asked_to_remove(
    tmp_path: Path, stub: tuple[Path, Path], children: list[int]
) -> None:
    record, path = do_launch(tmp_path, stub, children)
    inspector = Faulty()
    inspector.ok_calls = 2  # the initial check and the check just before the signal succeed
    report = stop(path, inspector=inspector, remove_files=True, wait_seconds=5.0)
    os.waitpid(record.pid, 0)
    assert report["signalled"] and report["result"] == "inconclusive_after_sigterm"
    assert report["exit_code"] == 5 and "files_removed" not in report
    assert path.exists() and record.key_file.exists()


def test_main_reports_an_inconclusive_inspection_by_code_only(
    tmp_path: Path,
    stub: tuple[Path, Path],
    children: list[int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, path = do_launch(tmp_path, stub, children)
    inspector = Faulty()
    inspector.ok_calls = 0
    monkeypatch.setattr(llama_ctl, "default_inspector", lambda: inspector)
    assert llama_ctl.main(["--record", str(path), "stop", "--remove-files"]) == 2
    err = capsys.readouterr().err
    assert "identity_unavailable" in err and str(tmp_path) not in err
    assert path.exists()


def test_a_readiness_inspection_failure_is_contained_through_the_handle_not_guessed(
    tmp_path: Path, stub: tuple[Path, Path], popens: list[subprocess.Popen[bytes]]
) -> None:
    spawner = Spawner()
    inspector = Faulty()
    inspector.ok_calls = 1  # identity acquired, then every later inspection fails
    with pytest.raises(CtlError) as caught:
        launch(
            **plain_args(
                tmp_path, *stub, inspector=inspector, spawn=spawner, ready_timeout_seconds=1.0
            )
        )
    popens.extend(spawner.processes)
    assert caught.value.code == "not_ready_in_time"
    assert spawner.processes[0].poll() is not None
