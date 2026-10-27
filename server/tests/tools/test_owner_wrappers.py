"""The owner wrappers (tools/owner): start, status and stop for the v0.1 development prototype.

Synthetic only. The real wrapper scripts run unchanged from a copy of ``tools/owner`` inside a fake
repository root, with a stand-in runtime (a tiny loopback HTTP server started by the real launcher
under the real sandbox profile), a stand-in application (a shell shim that records its argument
list and exits), a stand-in ``pmset`` and a disposable owner directory. No llama.cpp binary, model,
network beyond ephemeral loopback listeners, inference, dependency installation or preserved smoke
database is involved. Anything that needs the real runtime is left to the acceptance smoke.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from anonymous.adapters.model import llama_ctl
from anonymous.adapters.model.llama_launch_record import (
    ArtifactIdentity,
    LaunchRecord,
    write_record,
)
from anonymous.adapters.model.process_identity import DarwinInspector

pytestmark = [
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS wrappers and process identity"),
    pytest.mark.process,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ("lib.sh", "start.sh", "status.sh", "stop.sh")

RUNTIME_STUB = textwrap.dedent(
    """\
    #!{python}
    import sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    here = Path(__file__).resolve().parent
    argv = sys.argv
    host = argv[argv.index("--host") + 1]
    port = int(argv[argv.index("--port") + 1])


    class Handler(BaseHTTPRequestHandler):
        def _note(self):
            with open(here / "requests.log", "a", encoding="utf-8") as log:
                log.write(self.command + " " + self.path + "\\n")

        def do_GET(self):
            self._note()
            ready = self.path == "/health" and not (here / "unready").exists()
            self.send_response(200 if ready else 503)
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            self._note()
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass


    HTTPServer((host, port), Handler).serve_forever()
    """
)

APP_SHIM = textwrap.dedent(
    """\
    #!/bin/bash
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "-m" ] && [ "$arg" = "anonymous" ]; then
        printf '%s\\n' "$@" > "$FAKE_APP_LOG"
        env | grep '^ANONYMOUS_' | sort > "$FAKE_APP_ENV_LOG" || true
        exit "${{FAKE_APP_EXIT:-0}}"
      fi
      prev=$arg
    done
    exec {python} "$@"
    """
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def occupied(port: int) -> Iterator[None]:
    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", port))
    held.listen(1)
    try:
        yield
    finally:
        held.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, tuple[str, int, int, str | None]]:
    """Every entry under ``root`` with type, size, mtime and (for files) content digest."""
    found: dict[str, tuple[str, int, int, str | None]] = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        kind = "dir" if path.is_dir() else "file"
        digest = sha256(path) if kind == "file" and not path.is_symlink() else None
        found[str(path.relative_to(root))] = (kind, info.st_size, info.st_mtime_ns, digest)
    return found


@dataclass
class Owner:
    root: Path  # fake repository root holding a copy of tools/owner
    home: Path  # the disposable owner directory (it does not exist until start creates it)
    work: Path
    llama_port: int
    app_port: int
    env: dict[str, str]

    @property
    def record(self) -> Path:
        return self.home / "runtime" / "launch.json"

    @property
    def app_log(self) -> Path:
        return self.work / "app-args.txt"

    @property
    def app_env_log(self) -> Path:
        return self.work / "app-env.txt"

    @property
    def stub_requests(self) -> Path:
        return self.work / "bin" / "requests.log"

    @property
    def data(self) -> Path:
        return self.home / "data"

    def run(
        self,
        script: str,
        *args: str,
        extra: dict[str, str] | None = None,
        timeout: float = 90,
    ) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(extra or {})}
        return subprocess.run(
            [str(self.root / "tools" / "owner" / script), *args],
            env=env,
            cwd=self.work,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def runtime_state(self) -> dict[str, object]:
        return llama_ctl.status(self.record)

    def key_text(self) -> str:
        keys = list((self.home / "runtime").glob("key-*"))
        assert len(keys) == 1
        return keys[0].read_text()

    def write_config(self, **overrides: str) -> None:
        values = {
            "RUNTIME_BIN": str(self.work / "bin" / "llama-server"),
            "MODEL_PATH": str(self.work / "model.gguf"),
            "LLAMA_PORT": str(self.llama_port),
            "APP_PORT": str(self.app_port),
        }
        values.update(overrides)
        text = "".join(f"{k}={v}\n" for k, v in values.items() if v != "")
        Path(self.env["ANONYMOUS_OWNER_CONFIG"]).write_text(text)

    def write_pins(self, **overrides: str) -> None:
        values = {
            "RUNTIME_LABEL": "stub-runtime-1",
            "RUNTIME_SHA256": sha256(self.work / "bin" / "llama-server"),
            "MODEL_LABEL": "stub-model-1",
            "MODEL_SHA256": sha256(self.work / "model.gguf"),
        }
        values.update(overrides)
        Path(self.env["ANONYMOUS_OWNER_PINS_FILE"]).write_text(
            "".join(f"{k}={v}\n" for k, v in values.items())
        )

    def app_args(self) -> list[str]:
        return self.app_log.read_text().splitlines()


@pytest.fixture
def owner(tmp_path: Path) -> Iterator[Owner]:
    root = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT / "tools" / "owner",
        root / "tools" / "owner",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (root / "client" / "dist").mkdir(parents=True)
    (root / "client" / "dist" / "index.html").write_text("<html></html>")
    work = tmp_path / "work"
    (work / "bin").mkdir(parents=True)
    runtime = work / "bin" / "llama-server"
    runtime.write_text(RUNTIME_STUB.format(python=sys.executable))
    runtime.chmod(0o755)
    (work / "model.gguf").write_bytes(b"synthetic model bytes")
    shim = work / "bin" / "python-shim"
    shim.write_text(APP_SHIM.format(python=sys.executable))
    shim.chmod(0o755)
    for name, line in (("pmset-ac", "AC Power"), ("pmset-battery", "Battery Power")):
        script = work / "bin" / name
        script.write_text(f"#!/bin/bash\necho \"Now drawing from '{line}'\"\n")
        script.chmod(0o755)
    home = tmp_path / "home"
    (work / "cfg").mkdir()
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(work),
        "LANG": "en_US.UTF-8",
        "ANONYMOUS_OWNER_HOME": str(home),
        "ANONYMOUS_OWNER_CONFIG": str(work / "cfg" / "owner.env"),
        "ANONYMOUS_OWNER_PINS_FILE": str(work / "cfg" / "pins.env"),
        "ANONYMOUS_OWNER_PYTHON": str(shim),
        "ANONYMOUS_OWNER_PMSET": str(work / "bin" / "pmset-ac"),
        "ANONYMOUS_OWNER_READY_SECONDS": "5",
        "FAKE_APP_LOG": str(work / "app-args.txt"),
        "FAKE_APP_ENV_LOG": str(work / "app-env.txt"),
        "FAKE_APP_EXIT": "0",
    }
    instance = Owner(root, home, work, free_port(), free_port(), env)
    instance.write_pins()
    instance.write_config()
    yield instance
    if os.path.lexists(instance.record):  # only a runtime this test's wrappers launched
        with contextlib.suppress(Exception):
            llama_ctl.stop(instance.record, remove_files=True)


# -- shell hygiene -------------------------------------------------------------------------------


def test_the_scripts_parse_and_the_entry_points_are_executable() -> None:
    for name in SCRIPTS:
        path = REPO_ROOT / "tools" / "owner" / name
        assert subprocess.run(["/bin/bash", "-n", str(path)], check=False).returncode == 0, name
        if name != "lib.sh":
            assert os.access(path, os.X_OK), name


def test_no_machine_specific_path_or_secret_is_committed() -> None:
    folder = REPO_ROOT / "tools" / "owner"
    text = "".join(p.read_text() for p in sorted(folder.iterdir()) if p.is_file())
    assert "/Users/" not in text and "/private/" not in text and "Desktop" not in text


# -- prerequisite failures -------------------------------------------------------------------------


def test_a_missing_owner_configuration_is_refused_without_side_effects(owner: Owner) -> None:
    Path(owner.env["ANONYMOUS_OWNER_CONFIG"]).unlink()
    result = owner.run("start.sh")
    assert result.returncode == 2 and "owner configuration not found" in result.stderr
    assert not owner.home.exists() and not listening(owner.llama_port)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("runtime_missing", "RUNTIME_BIN is not an executable regular file"),
        ("runtime_not_executable", "RUNTIME_BIN is not an executable regular file"),
        ("model_missing", "MODEL_PATH is not a regular file"),
        ("runtime_relative", "RUNTIME_BIN must be an absolute path"),
        ("no_client", "client is not built"),
        ("no_python", "virtual environment is missing"),
        ("bad_port", "LLAMA_PORT must be a number"),
        ("same_port", "must differ"),
        ("short_pin", "not a lowercase 64-character SHA-256"),
        ("bad_label", "label in the pins file"),
        ("unknown_key", "unknown key"),
    ],
)
def test_unusable_prerequisites_are_refused_before_anything_starts(
    owner: Owner, case: str, message: str
) -> None:
    if case == "runtime_missing":
        (owner.work / "bin" / "llama-server").unlink()
    elif case == "runtime_not_executable":
        (owner.work / "bin" / "llama-server").chmod(0o644)
    elif case == "model_missing":
        (owner.work / "model.gguf").unlink()
    elif case == "runtime_relative":
        owner.write_config(RUNTIME_BIN="bin/llama-server")
    elif case == "no_client":
        shutil.rmtree(owner.root / "client")
    elif case == "no_python":
        owner.env["ANONYMOUS_OWNER_PYTHON"] = str(owner.work / "nowhere" / "python")
    elif case == "bad_port":
        owner.write_config(LLAMA_PORT="80")
    elif case == "same_port":
        owner.write_config(APP_PORT=str(owner.llama_port))
    elif case == "short_pin":
        owner.write_pins(MODEL_SHA256="abc123")
    elif case == "bad_label":
        owner.write_pins(MODEL_LABEL="has space")
    else:
        owner.write_config(SURPRISE="1")
    result = owner.run("start.sh")
    assert result.returncode == 2, result.stderr
    assert message in result.stderr
    assert not owner.record.exists() and not listening(owner.llama_port)
    assert not owner.app_log.exists()


def test_the_battery_is_refused_unless_explicitly_allowed(owner: Owner) -> None:
    owner.env["ANONYMOUS_OWNER_PMSET"] = str(owner.work / "bin" / "pmset-battery")
    refused = owner.run("start.sh")
    assert refused.returncode == 2 and "not on AC power" in refused.stderr
    assert not owner.record.exists() and not owner.app_log.exists()
    allowed = owner.run("start.sh", "--allow-battery")
    assert allowed.returncode == 0, allowed.stderr
    assert "WARNING: not on AC power" in allowed.stderr and owner.app_log.exists()


@pytest.mark.parametrize("name", ["../escape", "has space", ".hidden", "a..b", "x" * 65, ""])
def test_unsafe_dataset_names_are_refused(owner: Owner, name: str) -> None:
    result = owner.run("start.sh", "--dataset", name)
    assert result.returncode == 2 and "dataset names" in result.stderr
    assert not owner.home.exists() and not owner.app_log.exists()


def test_usage_errors_exit_2(owner: Owner) -> None:
    assert owner.run("start.sh", "--bogus").returncode == 2
    assert owner.run("start.sh", "--dataset").returncode == 2
    assert owner.run("status.sh", "extra").returncode == 2
    assert owner.run("stop.sh", "extra").returncode == 2
    assert owner.run("start.sh", "--help").returncode == 0


# -- pins ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["MODEL_SHA256", "RUNTIME_SHA256"])
def test_a_wrong_pin_refuses_the_launch_and_leaves_nothing(owner: Owner, which: str) -> None:
    owner.write_pins(**{which: "0" * 64})
    result = owner.run("start.sh")
    assert result.returncode == 2 and "artifact_digest_mismatch" in result.stderr
    assert "does not match the pinned SHA-256" in result.stderr
    assert not owner.record.exists() and not list((owner.home / "runtime").glob("key-*"))
    assert not listening(owner.llama_port) and not owner.app_log.exists()


# -- occupied ports ----------------------------------------------------------------------------


def test_an_occupied_application_port_refuses_before_launching(owner: Owner) -> None:
    with occupied(owner.app_port):
        result = owner.run("start.sh")
        assert result.returncode == 3 and f"port {owner.app_port} is occupied" in result.stderr
        assert listening(owner.app_port)  # the occupant was neither signalled nor disturbed
    assert not owner.record.exists() and not listening(owner.llama_port)


def test_an_occupied_runtime_port_refuses_without_launching(owner: Owner) -> None:
    with occupied(owner.llama_port):
        result = owner.run("start.sh")
        assert result.returncode == 3 and f"port {owner.llama_port} is occupied" in result.stderr
    assert not owner.record.exists() and not owner.app_log.exists()


# -- normal start, command construction, isolation of the environment --------------------------


def test_start_launches_verifies_and_runs_the_application_with_the_supported_arguments(
    owner: Owner,
) -> None:
    result = owner.run("start.sh", extra={"ANONYMOUS_LLAMA_MAX_TOKENS": "64"})
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "identity verified" in out and "Runtime: ready." in out
    assert f"http://127.0.0.1:{owner.app_port}/" in out and "Dataset: anonymous" in out
    assert "Dataset 'anonymous': new" in out
    assert owner.app_args() == [
        "-I",
        "-m",
        "anonymous",
        "--runtime",
        "llama-dev",
        "--llama-launch-record",
        str(owner.record),
        "--db-path",
        str(owner.data / "anonymous-dev.sqlite3"),
        "--host",
        "127.0.0.1",
        "--port",
        str(owner.app_port),
        "--client-dist",
        str(owner.root / "client" / "dist"),
    ]
    # A stray application setting is not passed on (and the owner is told).
    assert "ANONYMOUS_LLAMA_MAX_TOKENS" not in owner.app_env_log.read_text()
    assert "ignoring ANONYMOUS_LLAMA_MAX_TOKENS" in result.stderr
    # The wrapper created the data directory privately and no dataset file.
    assert oct(owner.data.stat().st_mode & 0o777) == "0o700"
    assert list(owner.data.iterdir()) == []
    # The launcher hashed both artifacts against the pins; the runtime outlives the application.
    state = owner.runtime_state()
    assert state["process_identity_matches"] is True
    assert state["sole_listener_is_recorded_process"] is True
    assert state["model"] == {"label": "stub-model-1", "digest_verification": "verified"}
    assert state["runtime"] == {"label": "stub-runtime-1", "digest_verification": "verified"}
    # Nothing secret or machine-specific is printed.
    both = result.stdout + result.stderr
    assert owner.key_text() not in both and str(owner.home) not in both
    assert "key-" not in both and str(owner.work) not in both
    # Only the readiness GET reached the runtime: no completion request.
    assert set(owner.stub_requests.read_text().splitlines()) == {"GET /health"}

    stopped = owner.run("stop.sh")
    assert stopped.returncode == 0, stopped.stderr
    assert "Clean shutdown confirmed" in stopped.stdout
    assert not owner.record.exists() and not listening(owner.llama_port)
    assert not list((owner.home / "runtime").glob("key-*"))


def test_an_application_failure_rolls_back_the_runtime_this_invocation_launched(
    owner: Owner,
) -> None:
    result = owner.run("start.sh", extra={"FAKE_APP_EXIT": "1"})
    assert result.returncode == 1 and "Anonymous exited with status 1" in result.stderr
    assert "launch files are removed" in result.stderr
    assert not owner.record.exists() and not list((owner.home / "runtime").glob("key-*"))
    assert not listening(owner.llama_port)


def test_a_runtime_that_never_becomes_ready_is_rolled_back(owner: Owner) -> None:
    (owner.work / "bin" / "unready").write_text("1")
    result = owner.run("start.sh", extra={"ANONYMOUS_OWNER_READY_SECONDS": "2"})
    assert result.returncode == 1 and "did not report ready within 2 seconds" in result.stderr
    assert not owner.record.exists() and not listening(owner.llama_port)
    assert not owner.app_log.exists()


def test_a_verified_running_runtime_is_reused_and_survives_an_application_failure(
    owner: Owner,
) -> None:
    assert owner.run("start.sh").returncode == 0
    before = owner.runtime_state()
    second = owner.run("start.sh", extra={"FAKE_APP_EXIT": "1"})
    assert second.returncode == 1 and "reusing the already running" in second.stdout
    assert "Stopping the runtime" not in second.stderr  # not launched here, so never rolled back
    assert owner.runtime_state() == before and listening(owner.llama_port)


def test_a_runtime_that_does_not_match_the_current_pins_is_not_reused(owner: Owner) -> None:
    assert owner.run("start.sh").returncode == 0
    owner.write_pins(MODEL_LABEL="another-label-1")
    result = owner.run("start.sh")
    assert result.returncode == 3 and "not launched and hash-verified" in result.stderr
    assert listening(owner.llama_port)  # left running for the owner to stop deliberately


# -- stale or foreign launch state -------------------------------------------------------------


def test_a_stale_record_of_an_exited_runtime_is_cleaned_and_replaced(owner: Owner) -> None:
    assert owner.run("start.sh").returncode == 0
    old_nonce = owner.record.read_text()
    llama_ctl.stop(owner.record)  # the runtime ends; the record and key stay behind (stale)
    assert owner.record.exists() and not listening(owner.llama_port)
    status = owner.run("status.sh")
    assert status.returncode == 1 and "launch record is stale" in status.stdout
    result = owner.run("start.sh")
    assert result.returncode == 0, result.stderr
    assert "Removed the stale launch files" in result.stdout
    assert owner.record.read_text() != old_nonce
    assert len(list((owner.home / "runtime").glob("key-*"))) == 1


def foreign_record(owner: Owner, victim_pid: int) -> None:
    """A launch record whose pid is a live process with a different start time (pid reuse)."""
    live = DarwinInspector().identity_of(victim_pid)
    assert live is not None
    runtime_dir = owner.home / "runtime"
    runtime_dir.mkdir(parents=True, mode=0o700)
    key = runtime_dir / ("key-" + "1" * 32)
    key.write_text("k" * 32)
    key.chmod(0o600)
    write_record(
        owner.record,
        LaunchRecord(
            nonce="1" * 32,
            pid=victim_pid,
            start=(live.start[0] - 1000, live.start[1]),
            host="127.0.0.1",
            port=owner.llama_port,
            key_file=key,
            model=ArtifactIdentity("m", None, "unspecified"),
            runtime=ArtifactIdentity("r", None, "unspecified"),
            created_utc=1.0,
        ),
    )


def test_a_record_naming_a_different_process_signals_nothing_anywhere(owner: Owner) -> None:
    victim = subprocess.Popen(["/bin/sleep", "60"])
    try:
        foreign_record(owner, victim.pid)
        before = owner.record.read_bytes()
        for script, expected in (("start.sh", 3), ("stop.sh", 3), ("status.sh", 1)):
            result = owner.run(script)
            assert result.returncode == expected, (script, result.stdout, result.stderr)
            assert victim.poll() is None  # never signalled
            assert owner.record.read_bytes() == before  # never removed or replaced
        assert not owner.app_log.exists() and not listening(owner.llama_port)
    finally:
        victim.kill()
        victim.wait()


def test_a_retained_launch_intent_blocks_start_and_stop(owner: Owner) -> None:
    runtime_dir = owner.home / "runtime"
    runtime_dir.mkdir(parents=True, mode=0o700)
    intent = runtime_dir / "launch.json.intent"
    intent.write_text(json.dumps({"v": 1, "nonce": "a" * 32, "key_file": "x", "port": 19999}))
    for script in ("start.sh", "stop.sh"):
        result = owner.run(script)
        assert result.returncode == 5, (script, result.stderr)
        assert "recovery file" in result.stderr
    assert owner.run("status.sh").returncode == 1
    assert intent.exists() and not owner.app_log.exists()


# -- stop ------------------------------------------------------------------------------------------


def test_stop_refuses_while_the_application_port_is_in_use(owner: Owner) -> None:
    assert owner.run("start.sh").returncode == 0
    with occupied(owner.app_port):
        result = owner.run("stop.sh")
        assert result.returncode == 3, result.stderr
        assert "cannot be shown that no reply is being generated" in result.stderr
        assert "Ctrl-C" in result.stderr
    state = owner.runtime_state()
    assert state["process_identity_matches"] is True and listening(owner.llama_port)


def test_stop_with_nothing_recorded_is_a_safe_noop(owner: Owner) -> None:
    result = owner.run("stop.sh")
    assert result.returncode == 0 and "Nothing to stop" in result.stdout
    assert not owner.home.exists()


def test_stop_does_not_touch_an_unrecorded_listener_on_the_runtime_port(owner: Owner) -> None:
    with occupied(owner.llama_port):
        result = owner.run("stop.sh")
        assert result.returncode == 1 and "still has a listener" in result.stderr
        assert listening(owner.llama_port)


# -- status ----------------------------------------------------------------------------------------


def test_status_with_nothing_running_creates_and_changes_nothing(owner: Owner) -> None:
    result = owner.run("status.sh")
    assert result.returncode == 0 and "nothing running" in result.stdout
    assert not owner.home.exists() and not owner.app_log.exists()


def test_status_of_a_running_runtime_has_no_side_effects_and_no_secrets(owner: Owner) -> None:
    assert owner.run("start.sh").returncode == 0
    key = owner.key_text()
    state_before = snapshot(owner.home)
    requests_before = owner.stub_requests.read_text()
    first = owner.run("status.sh")
    second = owner.run("status.sh")
    assert first.returncode == 0 and second.returncode == 0, first.stdout
    assert (
        "identity matches: true" in first.stdout
        and "readiness (GET /health): ready" in first.stdout
    )
    assert "sole listener is the recorded process: true" in first.stdout
    assert "verified" in first.stdout and "Application (127.0.0.1" in first.stdout
    assert snapshot(owner.home) == state_before  # no file written, removed or touched
    new_requests = owner.stub_requests.read_text()[len(requests_before) :].splitlines()
    assert new_requests and set(new_requests) == {"GET /health"}  # health GETs only
    for text in (first.stdout, first.stderr, second.stdout):
        assert key not in text and str(owner.home) not in text and str(owner.work) not in text


# -- datasets ----------------------------------------------------------------------------------


def make_dataset(path: Path, statuses: list[str]) -> None:
    """A minimal synthetic stand-in carrying only what the read-only probe reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE model_runs (id INTEGER PRIMARY KEY, status TEXT, record_epoch TEXT)"
    )
    connection.executemany(
        "INSERT INTO model_runs (status, record_epoch) VALUES (?, '0b')", [(s,) for s in statuses]
    )
    connection.commit()
    connection.close()


def test_an_existing_open_dataset_is_opened_and_preserved_byte_for_byte(owner: Owner) -> None:
    dataset = owner.data / "keep-dev.sqlite3"
    make_dataset(dataset, ["succeeded", "succeeded", "failed"])
    before = dataset.read_bytes()
    result = owner.run("start.sh", "--dataset", "keep")
    assert result.returncode == 0, result.stderr
    assert "Dataset 'keep': existing, open (runs=3 indeterminate=0 unsettled=0)" in result.stdout
    assert dataset.read_bytes() == before
    assert owner.app_args()[owner.app_args().index("--db-path") + 1] == str(dataset)
    assert sorted(p.name for p in owner.data.iterdir()) == ["keep-dev.sqlite3"]  # no journal etc.


def test_a_blocked_dataset_is_refused_untouched_and_a_new_name_is_the_way_out(
    owner: Owner,
) -> None:
    blocked = owner.data / "stuck-dev.sqlite3"
    make_dataset(blocked, ["succeeded", "indeterminate"])
    before = blocked.read_bytes()
    refused = owner.run("start.sh", "--dataset", "stuck")
    assert refused.returncode == 2 and "is BLOCKED" in refused.stderr
    assert "--dataset <new-name>" in refused.stderr
    assert not owner.record.exists() and not owner.app_log.exists()  # no runtime was launched
    assert blocked.read_bytes() == before
    fresh = owner.run("start.sh", "--dataset", "stuck-2")
    assert fresh.returncode == 0 and "Dataset 'stuck-2': new" in fresh.stdout
    assert blocked.read_bytes() == before and not (owner.data / "stuck-2-dev.sqlite3").exists()
    reading = owner.run("start.sh", "--dataset", "stuck", "--allow-blocked")
    assert reading.returncode == 0 and "is BLOCKED; history is readable" in reading.stderr
    assert blocked.read_bytes() == before
    listing = owner.run("status.sh")
    assert "stuck: blocked runs=2 indeterminate=1 unsettled=0" in listing.stdout


def test_an_unreadable_dataset_file_is_not_opened_or_changed(owner: Owner) -> None:
    junk = owner.data / "junk-dev.sqlite3"
    junk.parent.mkdir(parents=True)
    junk.write_bytes(b"this is not a database")
    result = owner.run("start.sh", "--dataset", "junk")
    assert result.returncode == 2 and "cannot be read" in result.stderr
    assert junk.read_bytes() == b"this is not a database" and not owner.record.exists()


def test_the_dataset_probe_module_loads_and_checks_its_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # never write into the repository

    spec = importlib.util.spec_from_file_location(
        "dataset_state", REPO_ROOT / "tools" / "owner" / "dataset_state.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.probe)
    assert module.main(["dataset_state.py"]) == 2


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "open runs=0 indeterminate=0 unsettled=0"),
        (["succeeded", "failed"], "open runs=2 indeterminate=0 unsettled=0"),
        (["succeeded", "in_flight"], "unsettled runs=2 indeterminate=0 unsettled=1"),
        (["pending"], "unsettled runs=1 indeterminate=0 unsettled=1"),
        (["in_flight", "indeterminate"], "blocked runs=2 indeterminate=1 unsettled=1"),
    ],
)
def test_probe_states(tmp_path: Path, statuses: list[str], expected: str) -> None:
    dataset = tmp_path / "d-dev.sqlite3"
    make_dataset(dataset, statuses)
    before = snapshot(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(REPO_ROOT / "tools" / "owner" / "dataset_state.py"),
            str(dataset),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == expected and result.returncode == 0
    assert snapshot(tmp_path) == before


def test_probe_absent_busy_and_unreadable(tmp_path: Path) -> None:
    script = str(REPO_ROOT / "tools" / "owner" / "dataset_state.py")

    def probe(path: Path) -> str:
        return subprocess.run(
            [sys.executable, "-I", script, str(path)], capture_output=True, text=True, check=False
        ).stdout.strip()

    assert probe(tmp_path / "missing-dev.sqlite3") == "absent"
    assert list(tmp_path.iterdir()) == []  # a read-only probe never creates the file
    junk = tmp_path / "junk-dev.sqlite3"
    junk.write_bytes(b"not sqlite")
    assert probe(junk) == "unreadable"
    locked = tmp_path / "locked-dev.sqlite3"
    make_dataset(locked, ["succeeded"])
    connection = sqlite3.connect(locked, isolation_level=None)
    connection.execute("BEGIN EXCLUSIVE")
    try:
        assert probe(locked) == "busy"
    finally:
        connection.execute("ROLLBACK")
        connection.close()
    assert probe(tmp_path) == "unreadable"  # a directory is not a dataset


# -- the real application, foreground lifecycle and Ctrl-C ----------------------------------------


def test_the_real_application_starts_on_the_supported_arguments_and_ctrl_c_ends_only_it(
    owner: Owner,
) -> None:
    """The real entry point against the stand-in runtime: health GETs only, no inference."""
    import signal
    import time
    import urllib.request

    owner.env["ANONYMOUS_OWNER_PYTHON"] = sys.executable  # the real server environment
    process = subprocess.Popen(
        [str(owner.root / "tools" / "owner" / "start.sh"), "--dataset", "real"],
        env=owner.env,
        cwd=owner.work,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # its own process group, as a terminal's foreground group would be
    )
    try:
        health: dict[str, object] = {}
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and process.poll() is None:
            try:
                url = f"http://127.0.0.1:{owner.app_port}/api/v1/health"
                with urllib.request.urlopen(url, timeout=2) as response:
                    health = json.loads(response.read())
                break
            except OSError:
                time.sleep(0.3)
        assert health.get("status") == "ok", process.poll()
        assert health["generation"] == {
            "state": "open",
            "reason": None,
            "legacy_unresolved_runs": 0,
            "quarantined_runs": 0,
        }
        status = owner.run("status.sh")
        assert status.returncode == 0, status.stdout
        assert "health: ok" in status.stdout and "generation: open" in status.stdout
        assert "real: open runs=0" in status.stdout
        # Ctrl-C reaches the foreground group: the application ends and the wrapper exits 0.
        os.killpg(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=40)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)  # test-owned group only
            process.wait()
    assert process.returncode == 0, stderr
    assert "Anonymous has stopped. The runtime is still running" in stdout
    assert owner.runtime_state()["process_identity_matches"] is True and listening(owner.llama_port)
    assert not listening(owner.app_port) and (owner.data / "real-dev.sqlite3").is_file()
    assert set(owner.stub_requests.read_text().splitlines()) == {"GET /health"}  # no inference
    stopped = owner.run("stop.sh")
    assert stopped.returncode == 0 and "Clean shutdown confirmed" in stopped.stdout
