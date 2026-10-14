#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION. E2-A: acquire ONE official model artifact and verify it. No load.

Fetches the pinned artifact from the approved manifest with a fresh full download (no Range, no
reuse of any existing partial file), streams it to a new file, hashes while writing, and enforces
a CUMULATIVE transfer cap persisted in a ledger so that retries cannot exceed it. The artifact is
promoted to its final name only if its size and SHA-256 equal the manifest values; otherwise it is
renamed to a `.e2a-rejected` quarantine name and nothing is promoted.

Safety: HTTPS only; hosts limited to huggingface.co and *.hf.co (checked on every redirect hop);
no token or credential is read or sent; the existing `.partial` file is never opened for writing
(its size/mtime are recorded before and after); the model is never opened by any runtime.

Run: python3 -B e2a_acquire.py --manifest model-candidate.json --models-dir DIR --ledger FILE.json
"""

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CAP_BYTES = 3 * 1024 ** 3  # cumulative network transfer cap (body bytes), owner-approved 3 GiB
ALLOWED = ("huggingface.co", ".hf.co")
CHUNK = 1024 * 1024


def host_ok(url):
    u = urllib.parse.urlparse(url)
    h = (u.hostname or "").lower()
    return u.scheme == "https" and (h == ALLOWED[0] or h.endswith(ALLOWED[1]))


class Guard(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.hops = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_ok(newurl):
            raise urllib.error.URLError("redirect to non-allowed host refused")
        self.hops.append({"status": code, "host": urllib.parse.urlparse(req.full_url).hostname,
                          "to_host": urllib.parse.urlparse(newurl).hostname,
                          "x-repo-commit": headers.get("x-repo-commit"),
                          "x-linked-size": headers.get("x-linked-size"),
                          "x-linked-etag": headers.get("x-linked-etag")})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def stat_of(p):
    s = os.stat(p)
    return {"size": s.st_size, "mtime_ns": s.st_mtime_ns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--models-dir", required=True)
    ap.add_argument("--ledger", required=True)
    a = ap.parse_args()

    m = json.load(open(a.manifest))
    name, want_size, want_sha = m["filename"], m["expected_bytes"], m["expected_sha256"]
    url = "https://huggingface.co/%s/resolve/%s/%s" % (m["repository"], m["revision"], name)
    final = os.path.join(a.models_dir, name)
    partial = final + ".partial"
    tmp = final + ".e2a-download"
    rejected = final + ".e2a-rejected"

    ledger = json.load(open(a.ledger)) if os.path.exists(a.ledger) else {
        "cap_bytes": CAP_BYTES, "cumulative_bytes": 0, "attempts": []}
    used = ledger["cumulative_bytes"]
    if os.path.exists(final):
        sys.exit("refusing: final artifact already exists")
    for p in (tmp, rejected):
        if os.path.exists(p):
            sys.exit("refusing: leftover %s exists; inspect before another attempt" % os.path.basename(p))
    if used >= CAP_BYTES:
        sys.exit("refusing: cumulative cap already reached")

    partial_before = stat_of(partial) if os.path.exists(partial) else None
    att = {"url": url, "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "range_requested": False, "token_sent": False, "partial_before": partial_before}
    guard = Guard()
    opener = urllib.request.build_opener(guard, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "anonymous-e2a/1"})

    got, h, outcome = 0, hashlib.sha256(), "ERROR"
    t0 = time.monotonic()
    try:
        with opener.open(req, timeout=60) as r:
            att["http_status"] = r.status
            att["final_host"] = urllib.parse.urlparse(r.geturl()).hostname
            att["hops"] = guard.hops
            att["content_length"] = r.headers.get("Content-Length")
            att["etag"] = r.headers.get("ETag")
            if r.status != 200:
                raise RuntimeError("unexpected status %s" % r.status)
            if att["content_length"] != str(want_size):
                raise RuntimeError("content-length != expected")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                while True:
                    left = min(CAP_BYTES - used - got, want_size - got + 1)
                    if left <= 0:
                        raise RuntimeError("cap or expected size exceeded; aborting")
                    b = r.read(min(CHUNK, left))
                    if not b:
                        break
                    got += len(b)
                    f.write(b)
                    h.update(b)
                f.flush()
                os.fsync(f.fileno())
        outcome = "DOWNLOADED"
    except BaseException as e:  # record everything, including interrupts
        att["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    att["bytes_transferred"] = got
    att["elapsed_s"] = round(time.monotonic() - t0, 2)
    att["sha256_of_received"] = h.hexdigest()

    if outcome == "DOWNLOADED":
        ok = got == want_size and h.hexdigest() == want_sha
        att["size_match"] = got == want_size
        att["sha256_match"] = h.hexdigest() == want_sha
        if ok:
            os.rename(tmp, final)
            os.chmod(final, 0o444)
            outcome = "VERIFIED"
        else:
            os.rename(tmp, rejected)
            outcome = "REJECTED"
    att["outcome"] = outcome
    att["partial_after"] = stat_of(partial) if os.path.exists(partial) else None
    att["partial_untouched"] = att["partial_before"] == att["partial_after"]
    ledger["cumulative_bytes"] = used + got
    ledger["attempts"].append(att)
    ledger["cap_remaining_bytes"] = CAP_BYTES - ledger["cumulative_bytes"]
    with open(a.ledger, "w") as f:
        json.dump(ledger, f, indent=2)
        f.write("\n")
    print(json.dumps({k: att.get(k) for k in ("outcome", "bytes_transferred", "elapsed_s", "error",
                                              "size_match", "sha256_match", "partial_untouched")}))
    sys.exit(0 if outcome == "VERIFIED" else 1)


if __name__ == "__main__":
    main()
