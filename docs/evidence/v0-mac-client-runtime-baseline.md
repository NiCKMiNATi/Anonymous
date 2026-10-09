# V0 Mac Client & Alternate Runtime Baseline v0.1

**Status:** Evidence and feasibility design, 2026-10-04. No runtime selected; no benchmark executed.  
**Scope:** The currently available Mac, explicitly designated by the user as the intended Mac client. Windows remains the initial authoritative V0 server and persistent-data owner.  
**Review ownership:** Operations, Frontend, Security, Runtime, Architect and QA; separate author review passes, not independent approvals.

## 1. Authority and evidence boundaries

This baseline follows the [project definition](../00-project-definition.md), [domain model](../01-domain-model.md), [requirements](../02-requirements.md), [V0 scope](../03-v0-scope.md), [architecture](../04-architecture.md), [logical model](../05-data-model.md), [security baseline](../07-security.md), [mechanism evaluation](../evaluations/v0-access-security-mechanisms.md), [environment baseline](v0-access-environment-baseline.md) and accepted [ADRs](../adr/). The [ExecPlan](../../.agent/plans/2026-10-04-v0-mac-client-runtime-baseline.md) records this task. The [runtime feasibility plan](runtime-feasibility-plan.md) retains the mandatory Windows experiment; Mac results cannot substitute for it.

The execution-host gate returned `Darwin` before repository edits. All machine observations below are bounded read-only observations on 2026-10-04. Public documentation describes capabilities, not a successful deployment on this Mac. Predictions and future tests are explicitly separated. Dynamic disk, memory, battery and process values are snapshots, not reserved capacity or continuous monitoring.

No software, dependencies or models were installed/downloaded; no services were started; no settings, trust stores, DNS, firewall, FileVault, Safari preferences or power configuration were changed. No application code, frameworks, physical data models or APIs were created. No Windows/iPhone inspection, network scan, stress test or certificate installation occurred. Only sanitized capability/state is retained; no account identity, device serial, UUID, MAC/IP address, SSID, credentials or recovery material belongs in the evidence package.

## A. Verified Mac hardware

| Fact | VERIFIED observation | Method / interpretation |
| --- | --- | --- |
| Device class | MacBookPro18,3; Apple M1 Pro | Selected hardware fields from `system_profiler` and `sysctl`; model identifier is a product class, not a unique device identifier. |
| CPU | 8 physical and 8 logical cores; 6 performance and 2 efficiency cores | Hardware/performance-level counters. |
| GPU | Apple M1 Pro, 14 cores | Selected display metadata. OS advertises Metal support with `spdisplays_metal4`; this is not proof of a runtime backend or every Metal feature. |
| Architecture | Apple Silicon / ARM64 capability | `hw.optional.arm64=1`; future runtime binary architecture must also be checked, avoiding an unnoticed emulated build. |
| Unified memory | 17,179,869,184 bytes = **16 GiB** | Shared CPU/GPU memory; there is no additional independent 16 GiB VRAM pool. |
| Internal physical SSD | 500,277,792,768 bytes, about **500.28 GB / 465.92 GiB** | Filtered `diskutil` physical disk fields: internal and solid-state. |
| APFS container | 494,384,795,648 bytes, about **494.38 GB / 460.43 GiB** | Container capacity differs from whole-device capacity. |
| Available container storage | 400,628,920,320 bytes, about **400.63 GB / 373.11 GiB** | Shared APFS space at observation; do not add system/data volume free-space figures together. |
| Filesystem/protection | APFS; FileVault On | Filtered volume metadata and `fdesetup status`. This does not establish backup/recovery-key custody. |
| External physical disks | None enumerated | `diskutil list -plist external physical`; not an exhaustive statement about network/cloud mounts. |
| Virtualization capability | `kern.hv_support=1` | Hardware/OS capability only; no hypervisor deployment proved. Native ARM64/Metal is the proposed inference test path. |
| Power snapshot | AC attached; battery 90%, not charging | Power-state observation; not a battery endurance result. |

The M1 Pro and 16 GiB facts agree with the repository inventory. A reported “512 GB” storage class and the observed physical/container capacities use different capacity boundaries; retain both descriptions without silently rewriting the project definition. There is no newly established chip/memory discrepancy.

## B. macOS, operations and memory state

| Fact | VERIFIED observation | Limit / consequence |
| --- | --- | --- |
| macOS | **27.0.1, build 26A434** | `sw_vers`; observed values, not a claim of latest patch or supported release channel. |
| Timezone | **JST, UTC+09:00** | Current abbreviation/offset; no inference of a unique named timezone from that alone. FR-15 persisted instants remain timezone-independent. |
| FileVault | On | Protects data at rest under its operating conditions; does not prevent an unlocked authorized process reading accessible content. |
| Application firewall | **Disabled, State 0** | Read-only `socketfilterfw` status. Other packet filters/reachability were not assessed. Do not equate this with a safe runtime listener. |
| Administrative capability | Current execution account is in the administrator group | Boolean membership only. Effective management restrictions and approval for later changes remain unverified. |
| Update metadata | Automatic download enabled; last successful metadata date 2026-10-04 04:48:27 UTC; result code 2 | Selected existing Software Update preference keys only. Code 2 is not interpreted as success/failure or “fully updated”; pending updates and release channel were not queried. Missing preference keys do not mean disabled. |
| Idle sleep | Battery and AC profiles each report `sleep 1` | One-minute configured idle sleep; assertions, lid state and workload can affect actual behavior. No suspend/resume test occurred. |
| Other power settings | Display sleep 2 minutes battery / 10 minutes AC; hibernatemode 3; standby and powernap enabled; low-power mode off | `pmset -g custom`. An AC connection does not by itself ensure uninterrupted service. |
| Swap snapshot | Total 5,120 MiB; used **3,957.94 MiB**; encrypted | `sysctl vm.swapusage`; already-used swap is not proof of current thrashing, a leak or insufficient runtime capacity. Future tests need baseline deltas. |
| Memory snapshot | `memory_pressure -Q` reported system-wide free percentage 66%; `vm_stat` page size 16,384 bytes | Not a claim that 66% of installed RAM is freely assignable to model weights. Pressure, compression, paging and other applications must be measured together. |

A filtered, current-user-visible TCP-listener inventory found wildcard-bound socket records, but no matching Ollama/llama/MLX/Tailscale process family. No ports, addresses or unrelated process names are retained. This is a limited observation, not a reachability/security audit. Later runtime launch must verify its own bind scope and caller protection.

APFS internal storage is a plausible local benchmark/development location. That does not select a Mac production data directory or prove the chosen persistence technology's durability semantics. Sleep, thermal behavior, existing swap and the disabled application firewall are concrete operational gates for any sustained local service.

## C. Safari and V0 client readiness

**VERIFIED:** Installed Safari **27.0.1**, build **22625.1.29.11.28**, from application metadata. Running instance, profile settings, extensions, sync and managed policies were not inspected. Safari maintenance follows macOS updates; the version observation does not establish update currency. [Apple Safari update guidance](https://support.apple.com/en-us/102665).

The accepted client is a normal first-party Safari browser client, same-origin HTTPS, with server-authoritative User/Device/Session identities. The approved browser-device credential and opaque session remain distinct. Eight-hour absolute and thirty-minute idle session limits are server rules, with no silent refresh; cookie persistence cannot extend them. See [ADR-0009](../adr/0009-v0-browser-device-and-session-credentials.md).

| Concern | Design / documented behavior | Required evidence on this Mac |
| --- | --- | --- |
| Secure and HttpOnly | Secure restricts cookie transport to secure transport subject to platform rules; HttpOnly blocks script access, not automatic authenticated requests. | REQUIRES_BROWSER_TEST: deployed HTTPS fixture accepts cookies, script cannot read them, plain HTTP cannot carry the credential. |
| SameSite=Strict | Cross-site requests must not gain the ordinary authenticated-cookie path. It complements origin/CSRF validation. | REQUIRES_BROWSER_TEST: direct navigation, reload and legitimate same-origin requests work; cross-site navigation/request cases follow the selected contract. |
| HTTPS / secure context | Trusted HTTPS at the canonical name is required; do not rely on a localhost exception for the remote Mac. | REQUIRES_BROWSER_TEST: valid chain/hostname and `window.isSecureContext`; no warning bypass. |
| Persistence / clearing | A persistent device cookie is conditional on browser retention. Clearing it loses browser-device proof; it does not delete canonical history or silently restore approval. | REQUIRES_BROWSER_TEST: relaunch, explicit site-data clearing in a disposable profile, expired/revoked credentials and re-enrollment. |
| Normal / private browsing | Private mode has ephemeral storage behavior; it is outside the persistent-device support profile. | REQUIRES_BROWSER_TEST: verify supported normal profile and clearly bounded private-mode behavior; do not promise private-mode continuity. |
| Cache / history / sync | PRIVATE conversation text can remain in rendered pages, local browser artifacts, history titles or synced metadata. | REQUIRES_BROWSER_TEST: sensitive responses are not served from an unintended cache after logout/revocation; review back navigation, page titles, service-worker/storage behavior, extensions and sync. No offline history copy is authorized. |
| Background tab / Mac sleep | Background execution can be throttled; network streams need not survive sleep. | REQUIRES_BROWSER_TEST: background, lock, sleep/wake and reconnect against persisted server state, without duplicate send or automatic retry. |
| Private CA | Safari must validate the configured chain and canonical hostname through applicable macOS trust. | REQUIRES_BROWSER_TEST plus deployment test in D. |

Cookie semantics are documented in [Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie), secure-context rules in [Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts), private storage in [WebKit tracking prevention](https://webkit.org/tracking-prevention/), and background throttling in [Page Visibility](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API). None of these citations substitutes for Safari acceptance. Do not interpret tracking-prevention limits as a blanket expiry rule for every HttpOnly first-party cookie.

## D. Private CA readiness

| Finding | Classification | Later action / evidence |
| --- | --- | --- |
| macOS exposes certificate trust policies in Keychain Access; Safari uses applicable system trust evaluation for HTTPS. | VERIFIED_PLATFORM_BEHAVIOR | [Apple trust-policy documentation](https://support.apple.com/guide/keychain-access/change-the-trust-settings-of-a-certificate-kyca11871/mac). No store was modified or certificate inventory exported. |
| The canonical server DNS name must match the certificate's SAN; a trusted root does not excuse a name mismatch or invalid chain. | VERIFIED_PLATFORM_BEHAVIOR | [Apple certificate requirements](https://support.apple.com/en-us/103769). Recheck current policy when issuing; this older baseline is not a selected lifetime/cryptographic profile. |
| Appropriate trust-store scope and authenticated administrative approval must be established for deployment. | REQUIRES_DEPLOYMENT_TEST | Admin-group membership is observed, but management restrictions, login versus system scope and exact authorization prompts are untested. Install only an authenticated public root in a later task; never copy the CA private key to clients. |
| Actual Anonymous HTTPS chain, name, validity, purpose and profile trust | REQUIRES_DEPLOYMENT_TEST | Select canonical origin under existing design, verify root fingerprint through an independent authenticated channel, then test successful connection and wrong-name/untrusted/expired rejection. No certificate-warning bypass. |
| Compromised CA replacement | REQUIRES_DEPLOYMENT_TEST | Follow existing custody/recovery design: isolate compromise, issue replacement under a new protected CA, distribute verified public trust, remove old trust on every supported client and test rejection of the old chain. Offline/unupdated clients remain a gate, not presumed recovered. |

Private root trust broadens what that Mac trusts; scope and custody need explicit deployment records. Tailscale enrollment is not CA installation, and private-network encryption is not a replacement for the approved HTTPS layer. Existing owner CA/key-custody questions remain unanswered.

## E. Tailscale readiness

**Observed status: NOT_FOUND_IN_INSPECTED_LOCATIONS; no running instance identified.** Checks covered PATH, standard system/user application locations, selected Homebrew installation locations and matching process families. This supports an installation prerequisite unless the owner identifies an existing nonstandard installation; it is not a claim that every private directory was searched. No app was launched and no VPN/account/tailnet configuration was accessed.

| Capability | VERIFIED_FROM_OFFICIAL_DOCS | MUST_VERIFY_ON_THIS_MAC / IMPLEMENTATION_CONFIGURATION |
| --- | --- | --- |
| Mac enrollment | Official Mac variants support enrollment; current documented minimum is macOS 12. [Mac install reference](https://tailscale.com/docs/install/mac). | Locate/select variant later; authorize install, VPN/system extension and legitimate tailnet enrollment. Observed macOS exceeds the documented minimum, but installation is untested. |
| Device approval | Pending devices cannot send/receive tailnet traffic when approval is enabled. [Device approval](https://tailscale.com/docs/features/access-control/device-management/device-approval). | Configure tailnet approval and exercise pending/approved/rejected states. This is separate from Anonymous device approval. |
| Grants | Grants express access policy; overlapping permissions must be evaluated together. [Grants reference](https://tailscale.com/docs/reference/syntax/grants). | Restrict designated client-to-server HTTPS; test denied paths and avoid runtime/storage/admin exposure. No actual tailnet policy reviewed. |
| Naming | MagicDNS provides device names/FQDNs; rename can change them. [MagicDNS](https://tailscale.com/docs/features/magicdns). | Fix the owner-selected canonical origin, certificate SAN and name lifecycle; test Safari resolution. Do not diagnose solely with tools that bypass macOS system DNS. |
| Roaming / private connectivity | Devices can connect across changing networks. [Connection guidance](https://tailscale.com/docs/how-to/connect-to-devices). | Test owner-approved home/mobile paths and direct/relay cases. Ordinary IP change must not change Anonymous device identity; stream survival is not guaranteed. |
| Revocation | Removing a node disconnects it per the product's documented behavior; uninstall alone does not remove it. [Remove a device](https://tailscale.com/docs/features/access-control/device-management/how-to/remove). | Test removal and expired keys, including established connections; no propagation time was measured. Keep application revocation independent and enforce the accepted delivery barrier. |

Network control-plane/account availability remains a deployment dependency; it is not Anonymous login or authority over conversation data. No public ingress, router port forwarding or cloud inference follows from this choice.

## F. Development and runtime tool inventory

Version reads used existing executables or package/app metadata. No package manager install/update/list operation that could fetch software was used. “Not found” is limited to PATH, standard app locations, selected Homebrew paths and the two inspected Python environments; project virtual environments and arbitrary model directories were not exhaustively searched.

| Tool | Observation / version | Limit |
| --- | --- | --- |
| Git | **2.54.0 (Apple Git-157)**, on PATH | Existing executable version read. |
| Python | Default **3.9.6**; uv-managed **3.12.14** also present | Both versions verified directly; no interpreter downloaded. |
| pip | Default-Python package **21.2.4**; managed-Python package **26.2.1** | `pip3` on PATH, unqualified `pip` not on PATH; versions from installed distribution metadata. |
| uv | **0.12.21**, Homebrew build 2026-09-29, aarch64-apple-darwin | Version read only; no `uv run` environment resolution. |
| Node.js | Not found on PATH / inspected formula locations | Does not exclude an app-bundled or private installation. |
| npm | Not found on PATH | No bootstrap attempted. |
| pnpm | Executable/shim found on PATH; **version unverified** | Not executed because a bootstrap/download path was not ruled out. Presence does not establish a usable Node toolchain. |
| yarn | Not found on PATH | Not installed by this task. |
| Docker / Docker Desktop | CLI/app not found in inspected locations; no matching running process identified | Virtualization capability does not imply Docker readiness. |
| VS Code | App **1.140.0** | `code` CLI not on PATH; app exists independently. |
| Homebrew | **7.0.7** | Version only; no formula installation/update. |
| Ollama | CLI/app/formula not found in inspected locations; no matching process | Default model directory absent. |
| llama.cpp | `llama-cli`, `llama-server`, `llama-bench` not found on PATH or selected formula paths | No backend/build compatibility test. |
| MLX | No installed distribution in either inspected Python | Not proof about every private environment. |
| MLX-LM | No installed distribution in either inspected Python; command not on PATH | No local server available to test. |
| PyTorch | No `torch` distribution in either inspected Python | Neither required nor selected by this task. |
| Tailscale | Not found in inspected CLI/app/formula locations; no running match | Version/enrollment unavailable. |

The default Ollama model directory and default Hugging Face hub cache directory did not exist. This scoped observation is sufficient to withhold a benchmark; it does not assert there are no model files anywhere on the Mac. No exact model, quantization or artifact digest was established.

## G. Relevant local runtime candidates

These are candidates for a future controlled comparison, not selected dependencies. Use native ARM64 builds; an API shaped like another vendor's API does not move context ownership to that vendor or select Anonymous's application API.

| Candidate | Documented platform / format / API | Assessment for this Mac, still requiring evidence |
| --- | --- | --- |
| Ollama | Apple M-series CPU/GPU support; managed local model lifecycle and streaming HTTP interface. Model compatibility/import is architecture/format dependent, including supported GGUF artifacts. [macOS requirements](https://docs.ollama.com/macos), [import reference](https://docs.ollama.com/import), [generate API](https://docs.ollama.com/api/generate). | Likely lower setup effort, but service lifetime, model residency, caching, effective context and resource controls need recording. Managed defaults can obscure a comparison unless pinned. Development candidate; fallback candidate only after performance/security validation. |
| llama.cpp | ARM/Metal support, GGUF models and multiple quantizations; CPU/GPU execution and an HTTP server. [Project](https://github.com/ggml-org/llama.cpp), [server reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). | More explicit control of model path, context, offload and timing; more build/flag responsibility. Useful reference candidate for native Metal and CPU/partial-offload comparison. Exact architecture, quantization and kernel combinations require a pinned-build test. |
| MLX / MLX-LM | MLX uses shared CPU/GPU memory and lazy computation; MLX-LM loads supported model/tokenizer configurations, including MLX quantized artifacts, and exposes generation/server interfaces. [MLX](https://ml-explore.github.io/mlx/build/html/index.html), [MLX-LM](https://github.com/ml-explore/mlx-lm), [server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md). | Apple Silicon-focused development candidate; Python/environment/model conversion increases operational surface. MLX artifacts are not interchangeable GGUF files. Upstream warns its server has only basic security checks and is not recommended for production: any Anonymous use needs the existing private-runtime boundary, not a directly exposed endpoint. |

All three compete with macOS, Safari and development tools for the same physical memory. Weight quantization, KV-cache representation, batching, caching and supported context differ; equal “4-bit” labels do not establish equal model quality or resident bytes. Record base-model lineage and artifact-specific hashes; report format differences instead of treating them as a controlled same-file comparison.

Ollama documents local-only configuration, loopback binding and model-directory control; those options do not independently satisfy authenticated caller isolation or egress enforcement. Docker Desktop on macOS is not the equivalent of its native GPU execution path. [Ollama FAQ](https://docs.ollama.com/faq). MLX-LM describes wiring large-model memory; this plan forbids raising system wired-memory limits to force a fit. [MLX-LM large-model guidance](https://github.com/ml-explore/mlx-lm#large-models).

For all candidates: promising for isolated development experiments; **REQUIRES_BENCHMARK** for useful capacity; **RUNTIME_EVIDENCE_REQUIRED** for private operational use. A future network inference node additionally needs an architecture decision, authenticated protected transport, explicit private-data eligibility and host isolation. No candidate is finalized.

## H. Theoretical model envelope

The following is arithmetic and experiment prioritization, **not measured performance**. A dense model's idealized weight lower bound is `parameters × nominal bits / 8`; real quantization metadata, unquantized tensors, buffers, activations and KV cache increase it. Mixture-of-experts active parameter counts must not be mistaken for total resident weights.

| Model class | Approximate ideal 4-bit weights only | Classification / first proposed screen |
| --- | --- | --- |
| 3B–4B | 1.40–1.86 GiB | THEORETICALLY_PLAUSIBLE; REQUIRES_BENCHMARK. First 2K total-context screen, then 4K/8K if stable. |
| 7B–8B | 3.26–3.73 GiB | THEORETICALLY_PLAUSIBLE; REQUIRES_BENCHMARK. Second 2K screen after the smaller class passes; test headroom with browser/tools present. |
| 12B–14B | 5.59–6.52 GiB | THEORETICALLY_PLAUSIBLE only with favorable architecture/quantization/context; REQUIRES_BENCHMARK. Conditional short-context trial after measured headroom, not a default V0 candidate. |
| 20B+ or high-bit larger models | 20B alone is at least 9.31 GiB at ideal 4-bit | LIKELY_OUTSIDE_COMFORTABLE_V0_ENVELOPE with normal applications and context. Deferred absent a specific justified artifact and safe memory budget; not a claim that every such model is impossible. |

For initial planning reserve **at least 6 GiB** of the 16 GiB for OS, Safari, editor, normal background work and possible development-server needs. This is a conservative planning allocation, not a measured combined footprint or guaranteed available 10 GiB model budget. Actual pressure can require a larger reserve or stopping entirely. Remaining capacity must cover weights **plus** runtime working memory and KV cache. Do not count compressed/swap-backed memory as fast model headroom.

Start with a pinned 4-bit artifact; optional 5/6/8-bit comparisons follow a safe baseline and have higher weight costs. KV memory depends on architecture, layers, cache precision and tokens; calculate from actual metadata and confirm by measurement. Advertised model maximum context is not practical context on this machine. No latency or tokens/second estimate is asserted.

## I. Existing benchmark opportunity: not available

| Required prerequisite | Result |
| --- | --- |
| Exact installed supported runtime/version/backend | Not established; relevant runtimes not found in inspected locations/environments. |
| Exact local model identity/revision | Not established. |
| Quantization and artifact integrity | Not established. |
| Confirmed execution without install/download | Cannot establish without the above. |
| Non-destructive synthetic workload | Specified below, but not executed. |
| Bounded safe execution | Specified below, but no runtime/model qualified to launch. |

**No benchmark ran.** Runtime, model, quantization, context, load latency, TTFT, generation speed and stability results are **NOT MEASURED**. Hardware/OS inventory commands are not inference benchmarks. Do not infer a failed model test from missing prerequisites.

## J. Future reproducible benchmark procedure

### J1. Authorization, evidence package and preflight

This is a procedure for a **later explicitly authorized experiment**, not permission to install or execute it now. First authorize acquisition of named pinned runtime builds and named model revisions/quantizations, permitted disk budget, local non-synced evidence folder and maximum session length. Model license/source and any tokenizer custom code require review; do not enable remote-code trust automatically. Never pass real Anonymous conversations to the experiment.

For every candidate record: runtime/version/build commit and binary architecture; model/base revision, total parameters, exact quantization, tokenizer/chat-template revision and hash; every model shard's SHA-256 and byte size; runtime launch arguments; actual backend/offloaded layers, CPU threads, batch/microbatch, KV type, context configuration, seed/sampling/output limit, cache policy and one-in-flight setting. Record OS/build, power state, background-app profile and baseline memory/swap/disk. Preserve native units and `unavailable` fields, never zero-fill missing measurements.

Use an external local folder with `manifest`, `fixtures`, `telemetry`, `trials` and `summary` subfolders. Retain exact synthetic UTF-8 fixture/request bytes and hashes. Each attempt gets a unique directory and terminal status, including failures. No application files need changing. Archive only sanitized logs; strip local personal paths before sharing.

Before loading: inspect current Memory Pressure in Activity Monitor; sample idle state for 60 seconds. Use AC power, normal ventilation and a stable foreground/background profile; save unrelated work. Record power settings without changing them. Keep the experiment attended and the Mac awake through ordinary interaction; if sleep interrupts it, label that trial interrupted and repeat only after explicit operator review. Do not use power assertions, change sleep, purge caches, disable swap or raise wired-memory limits to conceal limits.

Start with one 3B–4B quantized model, one generation globally, 2,048 total context and at most 256 output tokens. Allow at most 120 seconds per request and five minutes for initial startup/readiness. These are experiment bounds, not acceptance latency targets. A person must enforce the wall-clock deadline independently of a socket timeout; abort the owned request/runtime if it is still working, confirm exit/unload and record the incomplete outcome. No automatic retry.

Stop on any red Memory Pressure, yellow lasting 10 seconds, swap growth over 512 MiB above that phase's baseline persisting 10 seconds, visible loss of responsiveness, a thermal warning, unexpected egress/download, wrong bind scope or loss of AC power. These conservative experiment guardrails are proposed controls, not product performance requirements. Do not intentionally exhaust memory. Cool down/recheck baseline after a stop; do not proceed to a larger configuration.

### J2. Runtime setup and measurement path

Capture existing pinned `--version`/`--help` output first. Commands below are **future templates**, not commands run in this task. Replace local artifact placeholders; no remote repository shorthand, implicit model pull or wildcard listener. If a flag differs in the pinned version, record the equivalent from that version's help before running. Unsupported controls are a comparison limitation, not permission to use unrecorded defaults.

| Runtime | Proposed local experiment setup | Exact collection path |
| --- | --- | --- |
| Ollama | Native foreground `ollama serve` with process-local `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, and an explicitly authorized local model directory. Only a previously acquired, verified local model is eligible. | Submit streaming `/api/chat` with `model`, exact fixture `messages`, `stream:true`, `keep_alive:"5m"`, and `options:{"num_ctx":2048,"num_predict":256,"temperature":0,"seed":42}`. Change context only for declared trials. Capture final prompt/evaluation counts and durations plus `load_duration`; use `/api/ps`/local logs to verify residency. Verify unload before cold trials using the pinned documented unload operation. |
| llama.cpp | Native `llama-server -m MODEL.gguf --host 127.0.0.1 --port 8080 --ctx-size 2048 --parallel 1 --n-gpu-layers all --threads 6 --batch-size 512 --ubatch-size 128 --fit off --perf`; confirm actual context/offload in logs. | Use streaming `/v1/chat/completions` with the fixture, `max_tokens:256`, `temperature:0`, `seed:42`. Collect token usage and timing logs. If the chat route lacks decode timing, use a separately labeled native `/completion` run of the exact rendered prompt and retain its `timings`; do not silently combine durations from different runs. |
| MLX-LM | Native isolated installed Python environment; `mlx_lm.server --model LOCAL_MODEL_DIRECTORY --host 127.0.0.1 --port 8080`. Verify pinned help, no model download, effective context/output and cache controls; submit only one request at a time. | Streaming `/v1/chat/completions`, fixture and bounded output as above; use only sampling fields supported by pinned help/source. Record the seed as unavailable if unsupported. Capture server counters if available. For missing decode/load metrics, a separate native `load` / `stream_generate` measurement must record `prompt_tokens`, `generation_tokens`, `generation_tps` and `peak_memory`, and synchronize lazy work at timing boundaries. Mark this separate mode; server TTFT remains independently measured. |

The [Ollama chat API](https://docs.ollama.com/api/chat), [llama.cpp server reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [MLX-LM server reference](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md) and [MLX-LM generation source](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/generate.py) define vendor interfaces only. Pin source revisions at experiment time. MLX-LM does not thereby acquire a llama.cpp-style fixed context allocation; record its actual input/cache limit and distinguish that from the experiment's total-token ceiling. Inability to obtain a required metric leaves the candidate's evidence incomplete.

For request timing, copy the standard-library `bench_request.py` recorder in [runtime feasibility plan §6](runtime-feasibility-plan.md#6-measurement-definitions-and-request-recorder) into the external experiment folder. For example, after prerequisites:

```sh
python3 -B bench_request.py --url http://127.0.0.1:8080/v1/chat/completions --body fixtures/request.json --out trials/short-warm-01
```

For Ollama substitute its explicit loopback chat URL. This recorder makes no retries and records SSE/NDJSON events with monotonic elapsed time. Its built-in 600-second check is not the Mac experiment limit and is not a hard watchdog: **the separate attended 120-second wall limit above is required**, including silent streams. Verify terminal status, usage events and stop reason manually; the last event alone may not contain usage. It does not measure Anonymous persistence.

### J3. Deterministic fixtures and workloads

Create UTF-8 files with LF line endings outside the repository in the later experiment. Use exactly this system message for all fixtures: `This is a synthetic Anonymous benchmark. Use only the supplied facts. Do not call tools.` Use this preceding exchange: user `The synthetic project label is ORCHID.`; assistant `I will use the label ORCHID.`

For medium/pressure prompts, generate numbered lines in ascending order with this exact rule for integer `i` from 1 through N: `Record {i:06d}: unit-{i:06d} has status READY and value {i % 97:02d}.` Join with LF. Final user message is those lines followed by LF and `Report the project label, then the values of the first and last records. Explain in at most 128 words.` This is synthetic current-conversation context, not a memory retrieval or summary pipeline.

Count the **fully templated** input using the pinned tokenizer/template (llama.cpp tokenize/template facilities or the local model tokenizer); retain both text bytes and actual token count. For a runtime without a preflight tokenizer count, use a bounded small calibration request and its actual input count, then obtain a matching local tokenizer before pressure growth. Do not silently truncate to fit. Use identical fixture bytes across runtimes when comparing, acknowledging different templates/tokenizers; additionally record token-matched comparisons separately if needed.

| Workload | Reproducible execution | Evidence / stop |
| --- | --- | --- |
| SHORT CHAT | Replace final message with `What is the project label? Explain why preserving raw conversation history helps continuity, in at most 128 words.` Keep the preceding exchange. Total ceiling 2,048; output cap 256. | Three independently unloaded/process-cold runs, then five warm runs. Retain all timings and actual output counts, even early EOS. |
| MEDIUM ANONYMOUS CONTEXT | Choose largest N whose templated input is at most 1,536 tokens at the 2,048 ceiling; find N with the tokenizer, starting N=1 and increasing until the bound. Save N and exact fixture. | Five warm trials with fresh request context. Include normal Safari and VS Code background profile. Verify ORCHID, first value 01 and last value N mod 97; failures are quality evidence. |
| CONTEXT PRESSURE | Raise total ceiling through 2,048, 4,096, 8,192. At each step choose largest N with input ≤ ceiling−512, leaving 256 output plus 256 reserve. Optional 16,384 only after safe 8K results and separate operator approval. | Three trials per completed step, fresh context. Record actual accepted input, no truncation/sliding, memory and latency curve. Stop at first guardrail/failure/material regression; last completed safe point is the observed bound, not the model's theoretical maximum. |
| REPEATED GENERATION | At the highest safe medium configuration, send the same fixture sequentially for 10 attempts or 15 minutes, whichever comes first; one request at a time, each ≤120 seconds. | Record every run plus memory at baseline, after each completion and 60 seconds after unload. Report trends and completed count; this short sequence cannot prove absence of all leaks or long-term stability. |

For uncached comparisons restart/unload between requests where necessary and verify cached-token counts; repeated warm-cache continuation is a separate labeled condition. Do not compare a cached prefix against an uncached prefix without saying so. Temperature zero and seed 42, where supported, reduce variation but do not guarantee identical output across backends.

Material regression for this experiment means median TTFT exceeding twice the prior context step or median decode rate falling below half, as well as the memory/timeout guardrails. Report the curve and stop growing; these exploratory thresholds are not V0 latency commitments. Process-cold means weights unloaded or process restarted; filesystem caches may remain warm. Do not purge caches or reboot to manufacture disk-cold results.

### J4. Required measurements and exact definitions

Run telemetry at one-second intervals from the 60-second idle phase through load, generation and 60 seconds after unload. Use `vm_stat 1` in an attended console, retain page size, and stop it when the experiment ends. Sample `sysctl vm.swapusage` and `ps -o rss=,%cpu= -p RUNTIME_PID` once per second with elapsed/UTC sample times; include known worker PIDs identified locally, but omit names/arguments/personal paths from shared output. Keep PID-to-runtime mapping locally only. Use the same sampling interval for every candidate.

| Measurement | Required collection / interpretation |
| --- | --- |
| Model load | Ollama native `load_duration / 1e9` after verified unload. Other runtimes: capture internal load timing if emitted and separately monotonic launch-to-ready time; MLX native timing must materialize/synchronize lazy work. Label pure load unavailable if only readiness exists. |
| TTFT-visible | Monotonic dispatch to first nonempty answer text in stream. Empty/role events and HTTP first byte do not count. Track reasoning-first separately if present. This is a user-visible proxy, not a claim about internal first-token scheduling. |
| Generation tokens/sec | Native generated token count divided by native decode duration: Ollama `eval_count/(eval_duration/1e9)`; llama.cpp `predicted_n/(predicted_ms/1000)`; MLX native `generation_tps` with pinned definition. Never count chunks/words as tokens. |
| Total generation time | Retain native decode duration, dispatch-to-terminal wall time and first-visible-text-to-terminal wall time as separate fields; no conflation with model load or persistence. |
| Context / prefill | Configured ceiling, actual templated input and cached input tokens, actual output tokens, prefill time, termination/truncation flags, template/cache settings. A silently truncated trial fails the intended context test. |
| Unified memory / pressure | Observe Activity Monitor Memory Pressure continuously; record maximum color and duration, compressed/wired memory and whole-system Memory Used at phase boundaries/observed peaks. Retain one-second VM samples and sampled runtime RSS peaks. No addition of GPU allocation to RSS as if disjoint pools. |
| Swap | Baseline, maximum absolute used swap, delta, post-unload value; page-in/out deltas from VM samples. Existing used swap is not attributed to the runtime. |
| CPU | One-second process/worker `%cpu` and machine CPU view where available; report normalization convention, since process CPU can exceed 100% across cores. |
| GPU / Metal | Backend logs must confirm acceleration. Use Activity Monitor Window > GPU History during phases, transcribing aggregate utilization/shape and time if numeric export is unavailable; mark precise per-process utilization unavailable. Do not invent a VRAM number. |
| Thermal / power | Record AC/battery/low-power state before/after; operator heat/fan/slowdown observations are qualitative. Record thermal warnings if emitted. Numeric watts/temperature/throttling counters are optional only with already available authorized instrumentation. |
| Stability / failure | Per-attempt success, EOS/limit, malformed output, timeout, crash, memory guardrail or observed allocation/OOM error; verify runtime exits/unloads before retry. Preserve all failures. Do not label every crash OOM without evidence. |

[Apple's memory-pressure guidance](https://support.apple.com/guide/activity-monitor/view-memory-usage-actmntr1004/mac) explains why free RAM alone is insufficient. [GPU History](https://support.apple.com/guide/activity-monitor/view-gpu-activity-actm9329b315/mac) provides an observable GPU view. Screenshots must be cropped to aggregate charts with no account/app-content disclosure. Report sampling limits: sub-second spikes can be missed; memory pressure is not a single byte-valued maximum.

Summarize cold/warm and cache modes separately, with count, median, minimum/maximum, all failures and individual trial rows. Five runs are insufficient for a meaningful high-percentile latency promise; do not advertise a p95 from this sample. Record output correctness as well as speed. A missing required metric or stopped context level stays incomplete, not “passed.”

### J5. Coexistence, concurrency and optional evidence

Mandatory evidence **for a Mac runtime suitability claim** includes compatibility, exact artifacts, all four bounded workloads, actual context preservation, load/TTFT/decode/wall timing, memory/swap/CPU, observable GPU/power state, and repeat/failure records. Record optional instrumentation as unavailable when absent. Mac runtime evidence is itself optional to the Windows-first V0 release; supported Mac **client** acceptance is mandatory.

Repeat the safe 2K/medium condition first with a minimal background profile and then with Safari and VS Code in their normal documented profile. If Anonymous is not implemented, label server coexistence **NOT TESTED**; browser/editor coexistence is not a substitute. A later isolated synthetic Anonymous development instance must repeat the same fixture while list/open/history operations run, with canonical production data excluded. Measure application memory and response latency as well as model metrics. An artificial reserved-memory experiment is optional and must be labeled a sensitivity test, not the server's real footprint.

One active generation per conversation is enforced by Anonymous, not proved by runtime throughput. Later integration must race two requests to one conversation: one is admitted, the other is refused as busy without a new append or hidden queue; uncertain work remains blocked until reconciled. Reconnect/revocation must not trigger a second inference. This baseline's global one-request limit is only an experiment control. Cross-conversation concurrency is an optional separate capacity test after a safe sequential baseline; no global concurrency promise follows.

Useful optional measurements: quantization quality comparison, higher contexts after headroom evidence, CPU-only/partial offload, battery endurance, longer thermal soak, exact GPU counters, cold filesystem-cache behavior and cross-conversation load. For CPU-only llama.cpp use verified CPU mode (`--device none`, zero GPU layers and disabled operation/KV offload where needed by pinned help), confirming logs; partial offload uses a fixed recorded layer count. Start only with the small short fixture and the same 120-second limit. CPU/Metal share memory on this Mac, so partial offload is not an additional RAM pool. Do not force unsupported CPU paths in other candidates or infer Mac results from CUDA settings.

Before selecting any production runtime, agree workload-specific acceptable latency/quality/headroom with the owner and obtain the mandatory Windows evidence plus runtime security evidence. This Mac screen alone cannot close those gates.

## K. Role comparison

| Role | Architecture and data ownership | Security / performance / operations |
| --- | --- | --- |
| 1 — Mac client only | Compatible with accepted V0. Windows owns canonical data; Mac renders/requests through C01. No local model needed. | Hardware/browser inventory supports proceeding to configuration/implementation tests. Needs Tailscale, verified CA and actual client acceptance. Sleep reconnect is expected to reconcile with Windows, not recreate history. |
| 2 — Local development server + model | Plausible isolated development environment using synthetic data and explicitly separate development authority. Does not become the production server or a live replica. | Requires runtime/model acquisition, benchmarks and a later implementation task. Sixteen GiB, existing swap and sleep make coexistence evidence important. Do not copy/activate production storage, reuse production keys or claim Windows DPAPI custody works on macOS. |
| 3 — Alternate/fallback inference host, Windows still canonical | Future hypothesis, **DEFERRED**. Existing C07 is server-local; remotely calling a Mac is a topology/security change requiring explicit later architecture work. Moving compute never moves canonical ownership. | Requires measured Mac capacity, protected authenticated runtime transport, strict allowed context, egress/filesystem isolation, sleep/outage handling and serialized admission/delivery. No silent failover or automatic retry of uncertain work; no permission to expose a raw runtime through Tailscale. Highest operational complexity. |

Replacement at the C05/C07 model execution boundary remains required; it does not require shipping two live integrations or distributing inference. [ADR-0003](../adr/0003-context-and-model-execution-boundary.md), [ADR-0011](../adr/0011-v0-access-coordinator-and-delivery.md) and [ADR-0012](../adr/0012-v0-local-storage-and-authority-transfer.md) remain unchanged. No ADR is needed for these machine facts or unaccepted hypotheses.

## L. Model storage, cache and retention

About 400.63 GB free is sufficient in principle for runtime software, several small quantized candidates and bounded synthetic evidence; it is not unlimited capacity or measured installation size. Preflight sum actual artifact sizes, duplicate format conversions, temporary acquisition space, caches and trial logs. A proposed first acquisition budget is 30 GiB total with at least 50 GiB remaining free; authorize exact artifacts first, check space after each acquisition and reduce the set rather than consuming the reserve. These are experiment controls, not storage policy or a selected model count.

The model and evidence folder must be explicitly local and non-synced; an APFS volume alone does not prove a folder is outside cloud backup/sync. Do not select Mac authoritative storage. FileVault does not isolate accessible files from another process in an unlocked session.

Runtime logs, prompt caches, server request logs, crash reports, shell arguments, model manifests and tokenizer caches may retain private material or identifying paths. This experiment uses only synthetic prompts. Later Runtime Security work must inspect actual defaults and retention, verify authenticated caller restrictions and denial of ambient filesystem/egress, separate identities, bound logs/cache permissions, and define cleanup without touching source history. Model weights can be reacquired subject to license/source; saved assistant messages are authoritative history and are not regenerated as a substitute. No cache was deleted during this task.

## M. Mac client acceptance readiness

ENVIRONMENT_READY means only the listed local prerequisite is present. Multiple remaining labels can apply to one scenario; none below claims a passed live test.

| Scenario | Status | Required future observation |
| --- | --- | --- |
| Local browser/hardware | ENVIRONMENT_READY | Safari installed, ARM64 Mac/16 GiB/FileVault observed; supported normal-profile details still require review. |
| HTTPS connection | REQUIRES_CONFIGURATION; REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Actual Windows service, canonical name, valid HTTPS and no warning bypass. |
| Private-CA trust | REQUIRES_CONFIGURATION; REQUIRES_LIVE_TEST | Correct authenticated root, effective trust scope and rejection tests from D. |
| Tailscale connectivity | REQUIRES_CONFIGURATION; REQUIRES_LIVE_TEST | Install prerequisite, enrollment/approval, restricted policy and private origin reachability. |
| Authentication | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Passphrase/session flow, invalid/expired credentials, absolute/idle expiry and no silent refresh. |
| Device enrollment | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Distinct user/device/session, explicit approval, cleared credential and revoked-device cases. |
| List/open conversation | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Same authorized canonical history after relaunch/reconnect; no independent browser authority. |
| Send message | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | User commit confirmed before inference; second busy send refused without append. |
| Receive response | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Distinguish provisional stream from final saved response/run/provenance; failures observable. |
| FR-15 timestamps | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Every saved user/assistant message continuously shows time near actions without hover. Selected/local formatting changes presentation only; full date/time can be secondary. Identity, server order and absolute commit time remain distinct, including equal/non-monotonic instants. |
| Reconnect/background/sleep | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Recover saved state, reconcile uncertain outcomes, no duplicate generation or invented “saved” confirmation. |
| Network roaming | REQUIRES_CONFIGURATION; REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Change authorized physical network without reidentifying the device; revalidate session/connection normally. |
| Revocation | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Barrier cuts authorized delivery before acknowledgement; admitted computation may finish/save privately, but no new bytes released to revoked access. Already released bytes cannot be recalled. |
| Server unavailable | REQUIRES_IMPLEMENTATION; REQUIRES_LIVE_TEST | Honest unavailable/uncertain state; no automatic Mac authority promotion, cloud fallback or silent resend. |

These checks trace to V0-AC-01–07, V0-AC-10–11 and V0-AC-14–15 as applicable; the scope's complete acceptance set remains authoritative. Client work can proceed under a new implementation task without a Mac model, but deployment cannot be declared ready from this inventory.

## N. Decision and dependency matrix

| Question / finding | Classification | What it blocks |
| --- | --- | --- |
| Intended Mac, M1 Pro/8 CPU/14 GPU, 16 GiB, APFS capacity, installed OS/Safari | VERIFIED | Nothing yet; facts need rechecking if environment changes. |
| Windows canonical authority; browser client; private HTTPS/Tailscale; identity/order/commit-time separation | DESIGN_DECIDED | No new choice; all future work must preserve these constraints. |
| FileVault On / application firewall Off / short idle sleep / existing swap | VERIFIED | Not a client implementation blocker; unresolved service-exposure and uptime evidence blocks local-runtime deployment claims. |
| Tailscale installation in the inspected environment | REQUIRES_INSTALLATION | Mac remote-access deployment, not writing client logic. Reclassify if a usable existing installation is later identified. |
| Tailnet policy, CA trust, canonical name, management constraints and owner custody | REQUIRES_CONFIGURATION | Deployment and live acceptance, not generic client implementation. Existing unanswered owner choices remain open. |
| Safari cookie retention, clearing, cache, background and reconnect behavior | REQUIRES_BROWSER_TEST | Client acceptance/deployment. Fixtures can be implemented before results exist. |
| Runtime + exact local model acquisition | REQUIRES_INSTALLATION | Mac runtime experiment/selection; nothing for client-only role. |
| 3B–8B headroom, conditional 12B–14B, practical context and load/TTFT/rate | REQUIRES_BENCHMARK | Mac runtime suitability/selection and any claimed development coexistence. |
| Runtime caller auth, isolation, egress, logs/caches and failure handling | RUNTIME_EVIDENCE_REQUIRED | Private runtime deployment and final selection; loopback alone is insufficient. |
| Required client behavior and integration acceptance | REQUIRES_BROWSER_TEST | Release/deployment; requires a separate implementation task and running server first. |
| Node/npm toolchain or usable pnpm version | DEFERRED | Nothing yet; framework/toolchain not chosen. Any later stack must establish its own prerequisites. |
| Mac network inference node / automatic failover / production server migration | DEFERRED | Nothing in selected V0 client work; future topology needs explicit scope/ADR/security work. |
| Larger models, extended context, thermal soak, battery and concurrent conversations | DEFERRED | Nothing yet; optional after bounded baseline evidence. |
| Windows runtime/hardware and actual Windows+Mac acceptance | RUNTIME_EVIDENCE_REQUIRED | Initial-server runtime selection and V0 deployment; Mac measurements cannot close it. |

## 2. Review passes and validation

| Author review | Finding / disposition |
| --- | --- |
| Operations | Storage is promising but snapshot-based; APFS free space is shared. Short configured sleep, existing swap and untested thermal behavior prevent uptime/capacity promises. |
| Security | FileVault observed; firewall disabled. CA/Tailscale not configured, Safari retention untested. Synthetic-only benchmarks and future runtime caller/egress/cache isolation remain explicit. No private payload or key collection. |
| Frontend | Installed Safari supports proceeding with the selected design's test fixtures; persistence/Strict cookies, background recovery and always-visible FR-15 still need live acceptance. No client authority introduced. |
| Runtime | No qualified runtime/model pair; no measurements fabricated. Exact artifacts, token counts, cold/warm/cache distinction, monotonic timing and bounded failure recording required before selection. MLX server security warning retained. |
| Architect | Windows authority, single-server local-runtime boundary and replaceability preserved. Isolated Mac development is distinct from production; remote inference remains a deferred architecture change. No new ADR warranted. |
| QA | Observations, official platform claims, theoretical arithmetic and future tests are labeled separately. Scoped negative inventory avoids asserting global absence; missing metric is not a zero or pass. |

Documentation validation passed: 32 relative links across the three task files, all A–N sections, required status labels, requested inventory/workload/metric coverage, balanced code fences and sensitive-path/UUID screening. Manual reviews checked scenario coverage, observation provenance, benchmark limits and consistency with accepted ADRs/V0 semantics; unit calculations corrected two GiB roundings. Source hashes confirm prior fully read authoritative documents remained unchanged before drafting. The before/after manifest confirms only this baseline, the ExecPlan and newly verified Mac entries/follow-up notes in the environment baseline changed, with no deleted files. No application tests apply to this documentation-only task; no live client/security/inference acceptance is claimed.

The next bounded evidence task should collect the still-missing Windows environment facts on the actual intended server, using the existing read-only checklist. Prerequisites: that machine is available and the owner identifies eligible storage/admin context. An optional Mac benchmark task instead needs explicit acquisition/experiment authorization, exact runtime/model revisions, a local non-synced folder and the bounds in J; it cannot select the initial Windows runtime by itself.
