"""Kernel process identity and listener facts for the dev-only external runtime (ADR-0015).

A pid alone is not an identity: the pair (pid, start time) is issued by the kernel at process
creation, so a reused pid has a different start. Everything here is read-only observation;
signalling belongs to the cleanup tool, which uses these facts immediately before it signals.

macOS only (libproc, ``lsof``). On any other platform, or when a fact cannot be established, the
inspector raises :class:`IdentityUnavailable` and callers fail closed.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol

_PROC_PIDTBSDINFO = 3
_SZOMB = 5
_LSOF = "/usr/sbin/lsof"
_LSOF_TIMEOUT_SECONDS = 3.0


class IdentityUnavailable(Exception):
    """A process or listener fact could not be established (fail closed).

    This is NOT absence. ``identity_of`` returns ``None`` only when the kernel positively says the
    process does not exist; an inconclusive inspection raises this instead, and no caller may
    treat it as "gone" (for example to delete recovery metadata or replace a record)."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start: tuple[int, int]  # kernel start time (seconds, microseconds)


class IdentityInspector(Protocol):
    def identity_of(self, pid: int) -> ProcessIdentity | None:
        """The live identity of ``pid``. ``None`` means the kernel positively reports no such
        process (an exited, unreaped one counts as gone). Raises :class:`IdentityUnavailable`
        when the inspection itself is inconclusive."""
        ...

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        """TCP LISTEN sockets on ``port`` as ``(pid, "host:port")`` pairs."""
        ...


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class DarwinInspector:
    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise IdentityUnavailable("process identity inspection requires macOS")
        name = ctypes.util.find_library("proc")
        if name is None or ctypes.sizeof(_ProcBsdInfo) != 136:
            raise IdentityUnavailable("libproc is not usable")
        lib = ctypes.CDLL(name, use_errno=True)
        lib.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._lib = lib

    def identity_of(self, pid: int) -> ProcessIdentity | None:
        if pid <= 0:
            return None
        info = _ProcBsdInfo()
        ctypes.set_errno(0)
        n = self._lib.proc_pidinfo(
            int(pid), _PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info)
        )
        if n != ctypes.sizeof(info):
            # Only ESRCH is a positive "no such process". Anything else (EPERM, a short or failed
            # result with no errno, ...) is an inspection failure, not absence.
            if n <= 0 and ctypes.get_errno() == errno.ESRCH:
                return None
            raise IdentityUnavailable("process inspection was inconclusive")
        if info.pbi_status == _SZOMB:
            return None  # exited, not yet reaped
        return ProcessIdentity(
            int(info.pbi_pid), (int(info.pbi_start_tvsec), int(info.pbi_start_tvusec))
        )

    def listeners(self, port: int) -> tuple[tuple[int, str], ...]:
        try:
            result = subprocess.run(
                [_LSOF, "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fpn"],
                capture_output=True,
                text=True,
                timeout=_LSOF_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise IdentityUnavailable("listener inventory unavailable") from error
        if result.returncode not in (0, 1):  # 1 = nothing found
            raise IdentityUnavailable("listener inventory failed")
        found: list[tuple[int, str]] = []
        pid: int | None = None
        for line in result.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None:
                found.append((pid, line[1:]))
        return tuple(found)


def default_inspector() -> IdentityInspector:
    return DarwinInspector()
