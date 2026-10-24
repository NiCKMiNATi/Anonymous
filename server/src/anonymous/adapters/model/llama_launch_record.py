"""The launch record of an independently launched dev llama.cpp runtime (ADR-0015).

The record is written by the dev launcher and read by the adapter and the cleanup tool. It lives
outside the repository and outside SQLite, in a private (0700) directory, as a private (0600) file
owned by the current user. It describes a process Anonymous did not start and does not own.

It holds paths (the key file) and therefore must never be copied into the database, logs, error
messages or committed files; readers surface fixed error codes only.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RECORD_VERSION = 1
LOOPBACK_ADDRESS = "127.0.0.1"
MIN_PORT = 1024
MAX_RECORD_BYTES = 16_384

_NONCE = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LABEL = re.compile(r"[A-Za-z0-9._:+@-]{1,80}")
_VERIFICATIONS = frozenset({"verified", "asserted", "unspecified"})


class LaunchRecordError(Exception):
    """The record or key file is missing, unsafe or malformed. ``code`` is a fixed identifier."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    label: str  # descriptive; never a path
    sha256: str | None
    verification: str  # "verified" (hashed by the launcher) | "asserted" (pin) | "unspecified"

    def __post_init__(self) -> None:
        if not _LABEL.fullmatch(self.label):
            raise LaunchRecordError("record_label_invalid")
        if self.verification not in _VERIFICATIONS:
            raise LaunchRecordError("record_verification_invalid")
        if self.sha256 is None:
            if self.verification != "unspecified":
                raise LaunchRecordError("record_verification_invalid")
        elif not _SHA256.fullmatch(self.sha256) or self.verification == "unspecified":
            raise LaunchRecordError("record_digest_invalid")


@dataclass(frozen=True, slots=True)
class LaunchRecord:
    nonce: str
    pid: int
    start: tuple[int, int]
    host: str
    port: int
    key_file: Path
    model: ArtifactIdentity
    runtime: ArtifactIdentity
    created_utc: float

    @property
    def instance_ref(self) -> str:
        """One runtime-instance lifetime; never reused (a fresh nonce per launch)."""
        return f"llama-{self.nonce}"

    def to_json(self) -> str:
        body: dict[str, Any] = {
            "v": RECORD_VERSION,
            "nonce": self.nonce,
            "pid": self.pid,
            "start": list(self.start),
            "host": self.host,
            "port": self.port,
            "key_file": str(self.key_file),
            "model": _artifact_json(self.model),
            "runtime": _artifact_json(self.runtime),
            "created_utc": self.created_utc,
        }
        return json.dumps(body, sort_keys=True, indent=1)


def _artifact_json(a: ArtifactIdentity) -> dict[str, Any]:
    return {"label": a.label, "sha256": a.sha256, "verification": a.verification}


def _check_private_file(path: Path, code: str, *, max_bytes: int) -> int:
    """A regular, non-symlink file owned by this user with no group/other access."""
    try:
        info = os.lstat(path)
    except OSError as error:
        raise LaunchRecordError(f"{code}_missing") from error
    if not stat.S_ISREG(info.st_mode):
        raise LaunchRecordError(f"{code}_not_regular")
    if info.st_uid != os.geteuid():
        raise LaunchRecordError(f"{code}_not_owned")
    if info.st_mode & 0o077:
        raise LaunchRecordError(f"{code}_not_private")
    if info.st_size > max_bytes:
        raise LaunchRecordError(f"{code}_too_large")
    return info.st_size


def _read_private(path: Path, code: str, max_bytes: int) -> str:
    _check_private_file(path, code, max_bytes=max_bytes)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise LaunchRecordError(f"{code}_unreadable") from error
    with os.fdopen(fd, "rb") as handle:
        return handle.read(max_bytes + 1).decode("utf-8", errors="strict")


def _artifact(raw: object) -> ArtifactIdentity:
    if not isinstance(raw, dict):
        raise LaunchRecordError("record_malformed")
    label, sha, verification = raw.get("label"), raw.get("sha256"), raw.get("verification")
    if not isinstance(label, str) or not isinstance(verification, str):
        raise LaunchRecordError("record_malformed")
    if sha is not None and not isinstance(sha, str):
        raise LaunchRecordError("record_malformed")
    return ArtifactIdentity(label, sha, verification)


def read_record(path: Path) -> LaunchRecord:
    try:
        text = _read_private(Path(path), "record", MAX_RECORD_BYTES)
        raw = json.loads(text)
    except (ValueError, UnicodeDecodeError) as error:
        raise LaunchRecordError("record_malformed") from error
    if not isinstance(raw, dict) or raw.get("v") != RECORD_VERSION:
        raise LaunchRecordError("record_version")
    nonce, pid, start = raw.get("nonce"), raw.get("pid"), raw.get("start")
    host, port, key_file = raw.get("host"), raw.get("port"), raw.get("key_file")
    created = raw.get("created_utc")
    if not (isinstance(nonce, str) and _NONCE.fullmatch(nonce)):
        raise LaunchRecordError("record_nonce_invalid")
    if not (isinstance(pid, int) and not isinstance(pid, bool) and pid > 1):
        raise LaunchRecordError("record_pid_invalid")
    if not (
        isinstance(start, list)
        and len(start) == 2
        and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in start)
    ):
        raise LaunchRecordError("record_start_invalid")
    if host != LOOPBACK_ADDRESS:
        raise LaunchRecordError("record_host_not_loopback")
    if not (isinstance(port, int) and not isinstance(port, bool) and MIN_PORT <= port <= 65535):
        raise LaunchRecordError("record_port_invalid")
    if not (isinstance(key_file, str) and os.path.isabs(key_file)):
        raise LaunchRecordError("record_key_file_invalid")
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        raise LaunchRecordError("record_malformed")
    return LaunchRecord(
        nonce=nonce,
        pid=pid,
        start=(start[0], start[1]),
        host=host,
        port=port,
        key_file=Path(key_file),
        model=_artifact(raw.get("model")),
        runtime=_artifact(raw.get("runtime")),
        created_utc=float(created),
    )


def read_key(record: LaunchRecord) -> str:
    """The per-launch API key, from its private file. Held in memory only."""
    try:
        key = _read_private(record.key_file, "key", 1024).strip()
    except (ValueError, UnicodeDecodeError) as error:
        raise LaunchRecordError("key_malformed") from error
    if len(key) < 16 or not key.isprintable() or any(c.isspace() for c in key):
        raise LaunchRecordError("key_malformed")
    return key


def write_record(path: Path, record: LaunchRecord) -> None:
    """Atomically write the record as a private file (the directory is created 0700)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(record.to_json())
    os.replace(temporary, path)
