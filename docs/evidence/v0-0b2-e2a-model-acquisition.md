# Slice 0B-2 E2-A: model acquisition and hash verification

**Status:** E2-A complete 2026-10-14. Acquisition and verification only: the model was **not** loaded, opened by any runtime, or used for inference. E2-B/E3 not started.
**Plan:** [ExecPlan 0B-2](../../.agent/plans/2026-10-12-slice-0b2-runtime-evidence.md). **Script:** [tools/evidence/runtime/e2a_acquire.py](../../tools/evidence/runtime/e2a_acquire.py) (SHA-256 `d42b7243…934d`). **Ledger:** [v0-0b2-e2a/transfer-ledger.json](v0-0b2-e2a/transfer-ledger.json) (`9f197ce9…5ea619` at time of writing).

## 1. Result

| Item | Value |
|---|---|
| Artifact path | `~/Library/Application Support/AnonymousRuntimeBench/20261006-v01/models/Qwen3-4B-Q4_K_M.gguf` (mode 0444) |
| Source | `Qwen/Qwen3-4B-GGUF` at revision `bc640142c66e1fdd12af0bd68f40445458f3869b`, `Qwen3-4B-Q4_K_M.gguf` (Apache-2.0) |
| Size | **2,497,280,256 B** = manifest `expected_bytes` |
| SHA-256 | **`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`** = manifest `expected_sha256` = publisher LFS SHA-256 |
| Verified by | streaming hash during download, then an independent `shasum -a 256` re-hash of the final file; `GGUF` magic bytes present (not a validity claim about the whole file) |
| Outcome | `VERIFIED`, promoted to the final name only after both checks passed |

## 2. Transfer usage

- Method: one fresh full `GET` (HTTP 200), no `Range`, no token or credential, `Accept-Encoding: identity`. `huggingface.co` answered 302 to `us.aws.cdn.hf.co`; both hosts are in the allow-list (`huggingface.co`, `*.hf.co`). The first hop reported `x-repo-commit` = the pinned revision, `x-linked-size` 2,497,280,256 and `x-linked-etag` = the expected SHA-256. `Content-Length` matched the manifest size.
- Bytes transferred (response body): **2,497,280,256 B = 2.326 GiB** in 116.96 s (about 21 MB/s). One attempt, no retries, no errors.
- Cap: **3 GiB = 3,221,225,472 B, cumulative**, persisted in the ledger and enforced per read. **Used 77.5 %; remaining 723,945,216 B (690 MiB).** TLS/HTTP header overhead is not counted (not measured; small against the 690 MiB margin).
- **Interpretation to confirm:** the cap was counted from E2-A onward (the owner's cap supersedes the earlier unrecovered 12 GB record prospectively). The unknown-origin partial (1,786,773,504 B, written 2026-10-06) was not counted because its transfer is unrecorded. If the owner counts it, the cumulative total would be 4,284,053,760 B (3.99 GiB), over the 3 GiB cap; that reading would make this download itself non-compliant, so it is flagged rather than assumed.

## 3. Partial file

`Qwen3-4B-Q4_K_M.gguf.partial` is **untouched**: size 1,786,773,504 B and mtime (ns) identical before and after the run (recorded by the script), and its SHA-256 `328707193716194c…2549c9` equals the fingerprint recorded in the [E2 preflight](v0-0b2-e2-preflight-runtime-topology.md) §4. Not used, resumed, cloned or deleted; its disposition remains the owner's. It is a different file from the verified artifact (different hashes).

## 4. Scope and gaps

- No model load, no `llama-server` start, no inference, no change to accepted 0B-1 behavior; nothing pushed.
- The download ran on battery (100 %, host kept awake with `caffeinate -i`). AC power and the 60-second idle/memory gate remain **prerequisites for E2-B's load**, not for acquisition, and have not been re-measured here.
- SHA-256 proves integrity against the publisher value, not safety: the first load runs llama.cpp's GGUF parser on externally sourced bytes (preflight §6 guidance stands).
- The ledger records the hosts reached and public response headers only; no private data or secrets.

## 5. E2-B readiness

Acquisition prerequisite met. Remaining E2-B gates (all unchanged from the preflight): AC power plus idle/memory gate immediately before load; the no-fork sandbox profile for the single-model start (`-m`, `-np 1`, `--no-webui`, `--host 127.0.0.1`, no router, allow-listed environment); the E1 record/classify protocol; and an explicit owner authorization to begin E2-B.
