#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT PART OF THE ANONYMOUS SERVER.

E3 pilot OWNER: the process that is intentionally SIGKILLed. It launches the runtime exactly as the
E2-B harness does (same flags, profile, environment, stdin at /dev/null: it inherits Instance.argv and
Instance.env unchanged), persists INTENT -> SPAWNED -> BOUND, reports on stdout, and then idles. It
performs NO record write, request or polling while idle (a SIGKILL during a write would leave a
temporary file that blocks new runs). It holds no API key: the Driver created the key file and the
Owner only passes its path to the runtime. A SHUTDOWN command (or stdin EOF = Driver gone) runs the
normal E2-B shutdown, which is the pre-kill abort path.

Spec: one JSON file path on argv (no secrets in it).
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e1_lib as L  # noqa: E402
import e2b_harness as H  # noqa: E402
import e2b_lib as E  # noqa: E402
import e3_lib as T  # noqa: E402


class OwnerInstance(H.Instance):
    """E2-B Instance whose key file is prepared by the Driver. Everything except ``launch`` is the
    E2-B code unchanged (readiness, binding, shutdown, containment, exit conjunction)."""

    def __init__(self, *a, driver_identity=None, **kw):
        super().__init__(*a, **kw)
        self.key = None  # the Owner never holds a valid key
        self.driver_identity = driver_identity

    def _check_key_file(self):
        st = os.stat(self.key_file)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
            raise RuntimeError("key file is not a private regular file prepared by the driver")

    def launch(self, hashes):
        """E2-B ``Instance.launch`` with one difference: the key file already exists (created by the
        Driver, mode 0600) and is only verified, never written."""
        try:
            os.makedirs(self.cache, mode=0o700, exist_ok=True)
            self._check_key_file()
            target, full = self.argv()
            me = L.identity(os.getpid())
            self.rec = self.records.create({
                "v": 1, "run_id": self.run_id, "state": "INTENT", "tag": self.tag, "port": self.cfg.port,
                "argv_target": target, "argv_full": full, "argv_digest": E.sha256_bytes(E.canon(full)),
                "profile_sha256": E.sha256_bytes(self.cfg.profile.encode()), "binary_sha256": hashes.get("binary"),
                "model_sha256": hashes.get("model"), "boottime": E.HostProbes().boottime(),
                "harness": {"pid": os.getpid(), "start": me["start"] if me else None}, "created_utc": time.time(),
                "scope": T.SCOPE, "owner": {"pid": os.getpid(), "start": me["start"] if me else None},
                "driver": self.driver_identity, "history": [{"state": "INTENT", "utc": time.time()}]})
            log = open(os.path.join(self.run_dir, "server.log"), "wb")
            sigs = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, sigs)
            try:
                if self._abort_requested(sigs):
                    self._abandon("stop or interrupt requested before spawn")
                    raise H.StopRun("PRE_SPAWN_ABORT", "stop or interrupt requested before spawn")
                try:
                    self.proc = subprocess.Popen(full, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                                 env=self.env(), start_new_session=True,
                                                 preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, []))
                except OSError as exc:
                    self._spawn_failed(exc)
                    raise H.StopRun("SPAWN", f"spawn raised {type(exc).__name__}")
                ident = L.identity(self.proc.pid)
                if ident is None:
                    raise RuntimeError("kernel reported no identity for the new process")
                self.root = {"pid": self.proc.pid, "start": ident["start"], "pgid": ident["pgid"]}
                self.records.advance(self.rec, "SPAWNED", pid=self.proc.pid, start=ident["start"], pgid=ident["pgid"],
                                     sid=os.getsid(self.proc.pid), binding_verified=False, descendants=[])
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
                log.close()
            self.watch = L.ExitWatch(self.proc.pid)
        except H.StopRun:
            raise
        except BaseException as exc:
            what = type(exc).__name__
            if self.proc is not None:
                self.contain(f"launch bookkeeping failed after spawn: {what}")
            elif self.rec is not None:
                self._abandon(f"launch failed before spawn: {what}")
            raise H.StopRun("LAUNCH", f"launch failed: {what}")


def _refresh_before_final(self, out, policy_quarantine):
    """Re-read the record first: the Driver may have flagged owner review while the Owner was busy."""
    try:
        self.records._refresh(self.rec)
    except Exception as exc:
        out.setdefault("errors", []).append("refresh: " + type(exc).__name__)
    return H.Instance._finalize(self, out, policy_quarantine)


OwnerInstance._finalize = _refresh_before_final


def emit(**kw):
    try:
        print(json.dumps(kw, default=str), flush=True)
    except (BrokenPipeError, ValueError, OSError):
        pass  # the Driver is gone; its stdin EOF triggers the shutdown path


def main(spec_path):
    spec = json.load(open(spec_path))
    pins = json.load(open(spec["pins_path"]))
    if E.sha256_bytes(E.canon(pins)) != spec["pins_canonical_sha256"]:
        emit(e="FINAL", ok=False, why="pins differ from the Driver's")
        return 1
    cfg = H.Config(spec["bench"], pins=pins, root=spec["root"], binary=spec["binary"], model=spec["model"],
                   port=spec["port"], readiness_s=spec["readiness_s"], profile=spec["profile"])
    records = T.LockedRecords(spec["root"], lock_timeout_s=spec.get("lock_timeout_s"))
    cancel, cmd = threading.Event(), {}
    # Every SIGKILL of the abort path (shutdown, contain, emergency kill) goes through the signal ledger.
    # Two signals of the inherited E2-B code are not ledgered, by design (protocol section 8): the single
    # SIGTERM of the normal shutdown (E1 safe_kill, identity-verified) and contain()'s kill of an unreaped
    # direct child through its own Popen handle when its identity could not be read.
    ledger = T.SignalLedger(spec["run_dir"], lock_timeout_s=spec.get("lock_timeout_s"))
    inst = OwnerInstance(cfg, records, spec["run_id"], spec["run_dir"], wrap=spec["wrap"], driver_identity=spec.get("driver"),
                         cancel=cancel, kill_fn=ledger.kill_fn("owner", "owner_abort"))

    def read_commands():
        for line in sys.stdin:
            line = line.strip()
            if line.startswith("SHUTDOWN"):
                try:
                    cmd.update(json.loads(line[len("SHUTDOWN"):] or "{}"))
                except ValueError:
                    pass
                break
        else:
            cmd.update(reason="driver_eof")  # stdin closed: the Driver is gone
        cancel.set()

    threading.Thread(target=read_commands, daemon=True).start()
    try:
        inst.launch(spec["hashes"])
    except H.StopRun as stop:
        emit(e="FINAL", ok=False, stop=stop.sid, why=stop.why, record_state=(inst.rec or {}).get("state"))
        return 1
    emit(e="SPAWNED", pid=inst.root["pid"], start=inst.root["start"], pgid=inst.root["pgid"], tag=inst.tag)
    state, val = inst.wait_ready(cancel, cfg.readiness_s)
    verified = False
    if state == "READY" and not cancel.is_set():
        verified = inst.bind()
        emit(e="BOUND", verified=verified, bind_detail=dict(inst.bind_detail))
        announced = False
        # idle: no record write, no request, no polling beyond reaping the runtime if it exits
        while not cancel.wait(0.2):
            if inst.proc.poll() is not None and not announced:
                announced = True
                emit(e="RUNTIME_EXITED", returncode=inst.proc.returncode)
    else:
        emit(e="NOT_BOUND", state=state)
    res = inst.safe_shutdown(immediate=bool(cmd.get("immediate")) or state != "READY",
                             policy_quarantine=cmd.get("policy_quarantine"))
    result = {k: v for k, v in res.items() if k in
              ("verified", "record_written", "reaped", "returncode", "checks", "e1_classify", "policy_quarantine", "errors")}
    # E2-B's term_sent / kill_sent only say that the call was MADE (set whether or not the signal was
    # delivered or the ledger refused it), so they are reported as attempts. Delivery is confirmed only
    # where it is observable: the SIGKILL goes through the ledger; the one inherited SIGTERM does not
    # (the E1 helper's result is discarded by the E2-B code), so its delivery is reported as not observable.
    runtime = inst.root["pid"] if inst.root else None
    delivered_kill = any(e.get("who") == "owner" and e.get("pid") == runtime and e.get("sig") == int(signal.SIGKILL) and e.get("sent")
                         for e in ledger.entries())
    result.update(term_attempted=bool(res.get("term_sent")), term_delivery="not_observable",
                  kill_attempted=bool(res.get("kill_sent")), kill_delivered_by_ledger=delivered_kill,
                  unrecorded_signal_attempts=ledger.unrecorded_total)  # SIGKILL attempts refused for want of the ledger lock (not in the ledger file)
    emit(e="FINAL", ok=bool(res.get("verified")), result=result, command=cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
