"""Dev-only launcher and identity-safe cleanup for the external llama.cpp runtime (ADR-0015).

``anonymous-llama-dev launch | status | stop``. This tool starts the pinned runtime as an
independent process (its own session, no-fork sandbox, loopback only, per-launch API key) and
records what it started. It never touches SQLite: stopping or cleaning a runtime is an operator
action on the world and settles nothing (design §6.5). A run that was quarantined stays quarantined.

Process handling rules:

* a process is identified only by its kernel (pid, start time) from the launch record, verified live
  immediately before it is signalled; a mismatch refuses and signals nothing;
* one process, SIGTERM only; never a process group, never "whatever listens on the port", never
  SIGKILL (a runtime that ignores SIGTERM is reported, not escalated);
* output never contains paths, keys or content.

Failure handling:

* an inconclusive inspection (``IdentityUnavailable``) is never treated as "the process is gone":
  nothing is deleted and no previous record is replaced;
* before spawning, the record path is validated (absolute, canonical, no symlink) and a durable
  *launch intent* file is written next to the record; it is removed only once the record is
  durable, so an interrupted launch (even a killed launcher) leaves discoverable recovery state and
  further launches are refused until an operator resolves it;
* after spawning, any failure is contained through the ``Popen`` handle (the pid cannot be reused
  while this tool holds the unreaped child, so that is identity-safe); if the child cannot be shown
  to be gone, the key, intent and record are retained and the pid and start identity are reported
  for manual, verified recovery. No target is ever guessed.

Residual: between the final identity check and ``kill(2)`` a pid could in principle be reused. The
window is short but not bounded (scheduling or suspension can lengthen it); it is the same residual
as the E3 pilot's.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anonymous.adapters.model.llama_launch_record import (
    LOOPBACK_ADDRESS,
    MIN_PORT,
    ArtifactIdentity,
    LaunchRecord,
    LaunchRecordError,
    read_record,
    write_record,
)
from anonymous.adapters.model.process_identity import (
    IdentityInspector,
    IdentityUnavailable,
    ProcessIdentity,
    default_inspector,
)

DEFAULT_PORT = 18080
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# The E2-B/E3 launch profile: no outbound network except localhost, no fork.
SANDBOX_PROFILE = (
    "(version 1)(allow default)(deny network-outbound)"
    '(allow network-outbound (remote ip "localhost:*"))'
    "(deny process-fork)"
)
_KEPT_ENV = ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "__CF_USER_TEXT_ENCODING")
_HEX64 = frozenset("0123456789abcdef")


class CtlError(Exception):
    """An expected refusal. ``code`` is a fixed identifier; the message contains no values."""

    def __init__(
        self, code: str, exit_code: int = 2, *, recovery: dict[str, Any] | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code
        self.recovery = recovery


# -- helpers -------------------------------------------------------------------------------------


def build_command(
    *, runtime_bin: Path, model: Path, key_file: Path, port: int, sandbox: bool = True
) -> list[str]:
    """The pinned launch profile (E2-B/E3 record). Sampling and context are fixed, not tunable."""
    command = [
        str(runtime_bin),
        "-m",
        str(model),
        "--host",
        LOOPBACK_ADDRESS,
        "--port",
        str(port),
        "-c",
        "2048",
        "-np",
        "1",
        "-ngl",
        "all",
        "-t",
        "6",
        "-b",
        "512",
        "-ub",
        "128",
        "-fit",
        "off",
        "--perf",
        "--no-webui",
        "--offline",
        "--api-key-file",
        str(key_file),
        "--no-cache-prompt",
        "--cache-ram",
        "0",
        "--no-context-shift",
        "-to",
        "120",
        "--log-timestamps",
        "--chat-template-kwargs",
        '{"enable_thinking":false}',
    ]
    return [SANDBOX_EXEC, "-p", SANDBOX_PROFILE, *command] if sandbox else command


def child_environment(record_dir: Path) -> dict[str, str]:
    env = {k: os.environ[k] for k in _KEPT_ENV if k in os.environ}
    env["PATH"] = "/usr/bin:/bin"
    env["LLAMA_CACHE"] = str(record_dir / "llama-cache")
    env["HF_HUB_OFFLINE"] = "1"
    return env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pin(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.lower()
    if len(value) != 64 or not set(value) <= _HEX64:
        raise CtlError("pin_invalid")
    return value


def _artifact(label: str, pin: str | None, computed: str | None) -> ArtifactIdentity:
    if computed is not None:
        if pin is not None and pin != computed:
            raise CtlError("artifact_digest_mismatch")
        return ArtifactIdentity(label, computed, "verified")  # hashed by this launcher
    if pin is not None:
        return ArtifactIdentity(label, pin, "asserted")  # a pin is a claim, not a check
    return ArtifactIdentity(label, None, "unspecified")


def _ensure_private_dir(directory: Path) -> None:
    if directory.is_symlink():
        raise CtlError("record_dir_symlink")
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
        os.chmod(directory, 0o700)
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise CtlError("record_dir_not_private")


def _live(inspector: IdentityInspector, record: LaunchRecord) -> bool:
    found = inspector.identity_of(record.pid)
    return found is not None and found.start == record.start


def _listener_ok(inspector: IdentityInspector, record: LaunchRecord) -> bool:
    want = (record.pid, f"{record.host}:{record.port}")
    return inspector.listeners(record.port) == (want,)


def _signal_verified(
    inspector: IdentityInspector,
    identity: ProcessIdentity,
    sig: int,
    send: Callable[[int, int], None],
) -> bool:
    """Signal exactly one process, only if its identity is verified live right now."""
    found = inspector.identity_of(identity.pid)
    if found is None or found != identity:
        return False
    send(identity.pid, sig)
    return True


# -- paths and intent ------------------------------------------------------------------------------

INTENT_SUFFIX = ".intent"


def intent_path(record_path: Path) -> Path:
    return record_path.with_name(record_path.name + INTENT_SUFFIX)


def validated_record_path(record_path: Path) -> Path:
    """An absolute, canonical path with no ``..`` and no symlink in it or its parents, so the key
    file derived beside it is a valid absolute path too."""
    raw = Path(record_path)
    if not raw.is_absolute():
        raise CtlError("record_path_not_absolute")
    if ".." in raw.parts or not raw.name:
        raise CtlError("record_path_unsafe")
    for candidate in (raw, *raw.parents):
        if candidate.is_symlink():
            raise CtlError("record_path_unsafe")
    if Path(os.path.realpath(raw)) != raw:
        raise CtlError("record_path_unsafe")
    return raw


def _create_intent(path: Path) -> int:
    """Create the intent file exclusively. ``FileExistsError`` means another launcher owns it."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)


def _write_intent(fd: int, *, nonce: str, key_file: Path, port: int) -> None:
    """Durable launch intent, written (and synced) before anything is spawned."""
    body = json.dumps(
        {
            "v": 1,
            "nonce": nonce,
            "key_file": str(key_file),
            "port": port,
            "created_utc": time.time(),
        }
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _contain(
    process: subprocess.Popen[bytes],
    *,
    wait_seconds: float,
    files: tuple[Path, ...],
) -> bool:
    """Stop our own just-spawned child through its handle and, only if it is gone, delete ``files``.

    The pid cannot be reused while this tool holds the unreaped child, so signalling through the
    handle is identity-safe. Returns ``True`` iff the child is gone; otherwise nothing is
    deleted."""
    gone = process.poll() is not None
    if not gone:
        with contextlib.suppress(OSError):
            process.terminate()
        try:
            process.wait(timeout=wait_seconds)
            gone = True
        except subprocess.TimeoutExpired:
            gone = False
    if gone:
        for path in files:
            path.unlink(missing_ok=True)
    return gone


# -- launch --------------------------------------------------------------------------------------


def launch(
    *,
    record_path: Path,
    runtime_bin: Path,
    model: Path,
    port: int = DEFAULT_PORT,
    model_label: str,
    runtime_label: str,
    model_sha256: str | None = None,
    runtime_sha256: str | None = None,
    hash_artifacts: bool = False,
    inspector: IdentityInspector | None = None,
    sandbox: bool = True,
    ready_timeout_seconds: float = 60.0,
    contain_wait_seconds: float = 5.0,
    spawn: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> LaunchRecord:
    inspector = inspector or default_inspector()
    record_path = validated_record_path(record_path)
    if not (MIN_PORT <= port <= 65535):
        raise CtlError("port_invalid")
    for path, code in ((runtime_bin, "runtime_missing"), (model, "model_missing")):
        if not (path.is_absolute() and path.is_file() and not path.is_symlink()):
            raise CtlError(code)
    if not os.access(runtime_bin, os.X_OK):
        raise CtlError("runtime_not_executable")
    model_pin, runtime_pin = _pin(model_sha256), _pin(runtime_sha256)
    model_hash = sha256_file(model) if hash_artifacts else None
    runtime_hash = sha256_file(runtime_bin) if hash_artifacts else None
    model_id = _artifact(model_label, model_pin, model_hash)
    runtime_id = _artifact(runtime_label, runtime_pin, runtime_hash)

    _ensure_private_dir(record_path.parent)
    intent = intent_path(record_path)
    if os.path.lexists(intent):
        # An earlier launch was interrupted and may have left a runtime nobody recorded.
        raise CtlError("unresolved_launch_intent", 5, recovery=_intent_recovery(record_path))
    if os.path.lexists(record_path):
        try:
            previous = read_record(record_path)
        except LaunchRecordError as error:
            raise CtlError("existing_record_unreadable") from error
        # An inconclusive inspection raises IdentityUnavailable: the record is never replaced on
        # uncertain process state. Only a confirmed absence or a different process lifetime
        # (the recorded pid was reused) makes the old record stale.
        if _live(inspector, previous):
            raise CtlError("already_running")
    if inspector.listeners(port):
        raise CtlError("port_in_use")

    nonce = uuid.uuid4().hex
    record_dir = record_path.parent
    key_file = record_dir / f"key-{nonce}"
    log_file = record_dir / f"runtime-{nonce}.log"  # the runtime's own log: local only
    # Artifact ownership: only files this launcher created are ever deleted by it. The intent is the
    # one contested artifact (another launcher may hold it), so it is claimed only after our own
    # exclusive create succeeds; the nonce-named key and log are unique to this launch.
    owned: list[Path] = [key_file, log_file]
    log_fd = -1
    spawn_called = False
    spawned: subprocess.Popen[bytes] | None = None
    record_written = False
    identity: ProcessIdentity | None = None
    try:
        try:
            intent_fd = _create_intent(intent)
        except FileExistsError as error:
            # Lost the race to another launcher: its intent is not ours and is left untouched.
            raise CtlError(
                "unresolved_launch_intent", 5, recovery=_intent_recovery(record_path)
            ) from error
        owned.append(intent)
        _write_intent(intent_fd, nonce=nonce, key_file=key_file, port=port)
        (record_dir / "llama-cache").mkdir(mode=0o700, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(32))
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        command = build_command(
            runtime_bin=runtime_bin, model=model, key_file=key_file, port=port, sandbox=sandbox
        )
        spawn_called = True
        spawned = spawn(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            env=child_environment(record_dir),
            start_new_session=True,  # independent of this tool and of Anonymous
            close_fds=True,
        )
    except BaseException as error:
        if spawn_called and spawned is None and not isinstance(error, OSError):
            # The spawn was entered but no handle came back (for example an interrupt during
            # Popen): a child may exist. Do not guess: keep the intent, key and log as recovery
            # evidence and report how to find it. (An OSError from Popen means exec failed and
            # Popen reaped its own child: nothing was started.)
            raise CtlError(
                "spawn_status_unknown", 1, recovery=_recovery(None, None, nonce, port)
            ) from error
        # Nothing was started: remove only what this launcher created.
        for leftover in owned:
            leftover.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise CtlError("spawn_failed", 1) from error
        raise
    finally:
        if log_fd >= 0:
            os.close(log_fd)

    # -- the spawn-to-record interval: contained through the Popen handle -----------------------
    assert spawned is not None  # the spawn either returned a handle or raised
    process = spawned
    try:
        identity = inspector.identity_of(process.pid)  # IdentityUnavailable: contained below
        if identity is None:
            raise CtlError("exited_immediately", 1)
        record = LaunchRecord(
            nonce=nonce,
            pid=identity.pid,
            start=identity.start,
            host=LOOPBACK_ADDRESS,
            port=port,
            key_file=key_file,
            model=model_id,
            runtime=runtime_id,
            created_utc=time.time(),
        )
        write_record(record_path, record)
        record_written = True
        intent.unlink(missing_ok=True)  # the record is durable; the intent has served its purpose
    except BaseException as error:
        files = (key_file, intent, log_file, *((record_path,) if record_written else ()))
        if not _contain(process, wait_seconds=contain_wait_seconds, files=files):
            raise CtlError(
                "runtime_may_survive_unrecorded",
                1,
                recovery=_recovery(process.pid, identity, nonce, port),
            ) from error
        if isinstance(error, OSError):
            raise CtlError("record_not_persisted", 1) from error
        raise

    deadline = time.monotonic() + ready_timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            for path in (key_file, record_path):
                path.unlink(missing_ok=True)
            raise CtlError("exited_during_startup", 1)
        try:
            if _live(inspector, record) and _listener_ok(inspector, record):
                return record
        except IdentityUnavailable:
            pass  # inconclusive: not ready yet; the deadline below contains it through the handle
        time.sleep(0.2)
    if _contain(process, wait_seconds=contain_wait_seconds, files=(key_file, record_path)):
        raise CtlError("not_ready_in_time", 1)
    raise CtlError(
        "not_ready_and_may_survive", 1, recovery=_recovery(process.pid, identity, nonce, port)
    )


def _recovery(
    pid: int | None, identity: ProcessIdentity | None, nonce: str, port: int
) -> dict[str, Any]:
    """What an operator needs to find and verify an unrecorded survivor by hand. No secrets.

    The nonce appears in the runtime's own command line (``--api-key-file …/key-<nonce>``), so it
    identifies the process uniquely even when no pid is known."""
    return {
        "pid": pid,
        "start": list(identity.start) if identity is not None else None,
        "nonce": nonce,
        "key_file_name": f"key-{nonce}",
        "port": port,
        "procedure": "find the process whose command line contains the key file name, verify it is"
        " unique and the one listening on the port, terminate that one process, then delete the"
        " retained .intent, key and log files (see the implementation record)",
    }


# -- status and stop -----------------------------------------------------------------------------


def _intent_recovery(record_path: Path) -> dict[str, Any] | None:
    """The retained intent's nonce and port (never its paths), so an operator can look for the
    process whose command line carries that nonce. ``None`` if the intent cannot be read."""
    try:
        with open(intent_path(record_path), "rb") as handle:
            raw = json.loads(handle.read(4096))
        nonce, port = raw["nonce"], raw["port"]
        if not (isinstance(nonce, str) and len(nonce) == 32 and set(nonce) <= _HEX64):
            return None
        if not (isinstance(port, int) and not isinstance(port, bool)):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return _recovery(None, None, nonce, port)


def _require_record(record_path: Path) -> LaunchRecord:
    if not os.path.lexists(record_path) and os.path.lexists(intent_path(record_path)):
        raise CtlError("launch_intent_without_record", 5, recovery=_intent_recovery(record_path))
    return read_record(record_path)


def status(record_path: Path, inspector: IdentityInspector | None = None) -> dict[str, Any]:
    inspector = inspector or default_inspector()
    record = _require_record(validated_record_path(record_path))
    live = _live(inspector, record)
    return {
        "instance_ref": record.instance_ref,
        "pid": record.pid,
        "address": f"{record.host}:{record.port}",
        "process_identity_matches": live,
        "sole_listener_is_recorded_process": _listener_ok(inspector, record) if live else False,
        "model": {"label": record.model.label, "digest_verification": record.model.verification},
        "runtime": {
            "label": record.runtime.label,
            "digest_verification": record.runtime.verification,
        },
    }


def stop(
    record_path: Path,
    *,
    inspector: IdentityInspector | None = None,
    wait_seconds: float = 15.0,
    remove_files: bool = False,
    send: Callable[[int, int], None] = os.kill,
) -> dict[str, Any]:
    """SIGTERM the recorded runtime iff its identity matches. Never settles anything.

    Files are removed only after the process is *confirmed* absent: an inspection that fails at
    any point leaves the key and record in place."""
    inspector = inspector or default_inspector()
    record_path = validated_record_path(record_path)
    record = _require_record(record_path)
    found = inspector.identity_of(record.pid)  # IdentityUnavailable: refuse, files untouched
    report: dict[str, Any] = {"instance_ref": record.instance_ref, "signalled": False}
    if found is None:
        report["result"] = "already_gone"
    elif found.start != record.start:
        # The pid is now a different process: refuse, signal nothing.
        raise CtlError("identity_mismatch", 3)
    else:
        if not _signal_verified(inspector, found, signal.SIGTERM, send):
            raise CtlError("identity_mismatch", 3)
        report["signalled"] = True
        deadline = time.monotonic() + wait_seconds
        try:
            while inspector.identity_of(record.pid) is not None and time.monotonic() < deadline:
                time.sleep(0.1)
            gone = inspector.identity_of(record.pid) is None
        except IdentityUnavailable:
            report["result"] = "inconclusive_after_sigterm"
            report["exit_code"] = 5  # cannot show it is gone: keep everything
            return report
        report["result"] = "terminated" if gone else "still_running_after_sigterm"
        if not gone:
            report["exit_code"] = 4  # no escalation: the operator decides
            return report
    if remove_files:
        record.key_file.unlink(missing_ok=True)
        record_path.unlink(missing_ok=True)
        report["files_removed"] = True
    return report


# -- command line --------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anonymous-llama-dev",
        description="Dev-only launcher/cleanup for the external llama.cpp runtime (ADR-0015)."
        " Synthetic data only. Stopping a runtime settles nothing in Anonymous.",
    )
    parser.add_argument("--record", type=Path, required=True, help="launch record file")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("launch", help="start the pinned runtime as an independent process")
    up.add_argument("--runtime-bin", type=Path, required=True)
    up.add_argument("--model", type=Path, required=True)
    up.add_argument("--port", type=int, default=DEFAULT_PORT)
    up.add_argument("--model-label", required=True, help="descriptive label, not a path")
    up.add_argument("--runtime-label", required=True, help="descriptive label, not a path")
    up.add_argument("--model-sha256", help="pinned digest (a claim unless --hash is given)")
    up.add_argument("--runtime-sha256", help="pinned digest (a claim unless --hash is given)")
    up.add_argument("--hash", action="store_true", help="hash both artifacts now and verify pins")
    sub.add_parser("status", help="show the recorded runtime and whether its identity matches")
    down = sub.add_parser("stop", help="SIGTERM the recorded runtime if its identity matches")
    down.add_argument("--wait-seconds", type=float, default=15.0)
    down.add_argument("--remove-files", action="store_true", help="delete key and record once gone")
    args = parser.parse_args(argv)
    try:
        if args.command == "launch":
            record = launch(
                record_path=args.record,
                runtime_bin=args.runtime_bin,
                model=args.model,
                port=args.port,
                model_label=args.model_label,
                runtime_label=args.runtime_label,
                model_sha256=args.model_sha256,
                runtime_sha256=args.runtime_sha256,
                hash_artifacts=args.hash,
            )
            print(json.dumps({"launched": record.instance_ref, "pid": record.pid}))
            return 0
        if args.command == "status":
            print(json.dumps(status(args.record), indent=1))
            return 0
        report = stop(args.record, wait_seconds=args.wait_seconds, remove_files=args.remove_files)
        print(json.dumps(report))
        return int(report.get("exit_code", 0))
    except CtlError as error:
        refusal: dict[str, Any] = {"refused": error.code}
        if error.recovery is not None:
            refusal["recovery"] = error.recovery
        print(json.dumps(refusal), file=sys.stderr)
        return error.exit_code
    except LaunchRecordError as error:
        print(json.dumps({"refused": error.code}), file=sys.stderr)
        return 2
    except IdentityUnavailable:
        print(json.dumps({"refused": "identity_unavailable"}), file=sys.stderr)
        return 2
    except OSError:
        # Expected filesystem failures are reported by code only: no path ever reaches the output.
        print(json.dumps({"refused": "filesystem_error"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
