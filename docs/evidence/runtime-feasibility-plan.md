# Anonymous — V0 Local Model Runtime Feasibility Plan

**Status:** Proposed experiment procedure; not executed. No runtime or model selected.  
**Date:** 2026-10-03.  
**Execution host:** Actual Windows desktop; optional separate MacBook comparison.  
**Results:** Not collected. Every result and performance target remains pending.

## 1. Purpose, authority, and limits

Determine whether a local runtime/model configuration can support V0 on the existing equipment, and produce evidence for later decisions. Read the [Project Definition](../00-project-definition.md), [Domain Model](../01-domain-model.md), [Requirements](../02-requirements.md), [V0 Scope](../03-v0-scope.md), and [Architecture](../04-architecture.md). In particular, V0 §§4–5 and Architecture §12 require measured capacity before implementation acceptance. The [ExecPlan](../../.agent/plans/2026-10-03-runtime-feasibility-plan.md) records preparation of this document.

Reported equipment, to be verified rather than assumed:

| Host | Reported equipment | Experiment role |
| --- | --- | --- |
| Windows desktop | Ryzen 7 5700X; RTX 3070, 8 GB dedicated VRAM; 32 GB RAM; 1 TB NVMe | Mandatory initial inference/server host and desktop client. |
| MacBook Pro (2021) | M1 Pro; 16 GB unified memory; 512 GB SSD | Optional feasibility comparison. Success here does not substitute for the Windows gate or select Mac hosting. |
| iPhone | iPhone 17 Pro Max (2025), 256 GB | V0 client; no inference benchmark required here. |

Installed capacity is not available capacity. Model file size is not peak inference memory. The Windows GPU also serves the display; Mac GPU and CPU share the same memory pool.

This task creates documentation only. Commands below are instructions for a subsequent operator-run experiment, not commands executed during preparation. They install no Anonymous dependency, create no application, and define no Anonymous API. Temporary scripts copied from this document belong in an external benchmark folder. Runtime HTTP paths below are experimental vendor interfaces only. Do not initialize `client/`, `server/`, a database, or an application framework to run this plan.

All trial counts, context steps, output caps, timeouts, and synthetic load sizes below are experiment controls, not V0 performance promises. There is no existing evidence justifying a final choice of Ollama, llama.cpp, or any model. Later selection requires measured results, an explicit finite acceptance envelope, and an ADR if adopted architecturally.

## 2. Mandatory evidence versus optional work

“Mandatory” means evidence needed from this feasibility exercise before recommending a Windows configuration. It does not mean this exercise passes the referenced release scenarios. Failed or blocked candidates remain legitimate evidence; absence of a viable candidate is a reported blocker.

| ID | Mandatory Windows evidence | Trace and limits |
| --- | --- | --- |
| RF-01 | Verified OS, CPU/RAM, GPU/driver, storage/free space, power profile, runtime build, model artifact hashes, license and effective settings. Compatibility/load outcome for each screened candidate. | NFR-06; V0-AC-12; Q-19/Q-23. Hardware facts alone are insufficient. |
| RF-02 | At least two model-size bands and a quantization comparison, or explicit acquisition/compatibility blockers. Load time, streamed first-output latency, actual generation tokens/sec, input/output counts, and wall time. | FR-02, FR-12; V0-AC-01/12. Do not treat a faster model as adequate without the chat smoke checks. |
| RF-03 | Machine RAM/commit/paging and dedicated/shared GPU memory behavior at baseline, load, prefill, generation, and after unload; repeated-run stability. | NFR-06, REC-03/04; V0-AC-06/12. Record telemetry gaps. |
| RF-04 | Context sweep, actual input accounting, output reserve, short-history chat/role checks, near-limit and over-limit behavior; evidence of whether truncation/context shifting is detectable or preventable. | FR-08, DATA-03, REC-04; V0-AC-08; C06/C07. Model recall alone cannot prove input preservation. |
| RF-05 | Runtime-only and controlled coexistence runs; visible desktop responsiveness and resource headroom. | NFR-05/06; V0-AC-03/12. Synthetic reserve is not a measured server footprint. Actual server integration remains mandatory later. |
| RF-06 | Serial inference, a controlled overlapping-request probe, request interruption, requester death, runtime death/restart, and observable quiescence before another attempt. | V0-D04/D06; REC-03; V0-AC-02/06/07; C05/C07/C10. Runtime queuing is not Anonymous busy refusal. |
| RF-07 | Fully local execution with external connectivity disabled after acquisition; explicit endpoint binding and no automatic cloud path. | NFR-01, PRIV-01/04/05, SEC-06/08; V0-AC-09/12/14. This is not a complete application security assessment. |
| RF-08 | CPU-only diagnostic on a small candidate; partial-offload trial on a retained candidate if supported. If spill occurs in any proposed configuration, characterize it under repetition/coexistence. | NFR-06; C07. CPU fallback is not automatically a required supported V0 mode. Record unsupported modes rather than silently assuming them. |

Useful optional measurements: Mac inference; a third runtime; additional model families; 12–14B stress candidates; contexts above 16K; finer thread/batch/KV-cache/Flash-Attention tuning; sustained power/energy/noise/temperature studies; true disk-cold loads after reboot; simultaneous generations for different conversations; long overnight soak; broader task-quality evaluation. These cannot excuse missing mandatory evidence. A configuration proposed for use must receive mandatory coverage even if it originated in an optional trial.

FR-15 remains unchanged: a message's commit time is not a runtime `created_at`, a request-start time, or a benchmark stopwatch reading. This experiment has no persistent Anonymous conversation history and cannot verify FR-15's UI or commit semantics.

## 3. Candidate matrix and acquisition

Screen two independently packaged runtime candidates: **native Windows Ollama** and **native Windows llama.cpp with its CUDA backend**. They are hypotheses, not commitments; shared backend lineage also means this is not evidence of two independent inference engines. Start with native execution to avoid adding WSL/container overhead; any later WSL/container result is a separately labeled configuration. Ollama documents Windows and GPU prerequisites; verify the pinned release against the actual OS/driver before running. [Ollama Windows](https://docs.ollama.com/windows), [hardware support](https://docs.ollama.com/gpu).

Use the following bounded initial model ladder. Qwen2.5 Instruct GGUF artifacts are concrete reproducible starting examples, not a claim that this family is newest or best. Check the publisher's model card, license, architecture, supported context, and quantization for each exact artifact. A different family is allowed under a new candidate ID with the same evidence requirements. [3B publisher card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF), [7B publisher card](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF), [14B publisher card](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF).

| Candidate | Initial quantization | Purpose and promotion rule |
| --- | --- | --- |
| M-S: approximately 3B dense instruct | Q4_K_M | Small baseline on both runtimes; CPU diagnostic. If it fails to load, investigate compatibility before interpreting capacity. |
| M-M: approximately 7–8B dense instruct | Q4_K_M | Medium capacity/quality comparison. No assumption that it fits entirely in 8 GB VRAM at every context. |
| M-Q: same weights/revision/size as M-S or M-M | Q5_K_M, or Q8_0 if Q5 is unavailable | Controlled quantization comparison. Record unavailable artifacts, not an imaginary equivalent. |
| M-L: approximately 12–14B dense instruct | Q4_K_M | Optional upper-bound/partial-offload probe after smaller candidates are stable. Do not run merely to force exhaustion. |

Screen all available initial pairs at 2K context. Carry viable pairs into the context sweep. Full cold/warm, stability, coexistence, and lifecycle evidence is mandatory for each pair proposed for selection, not for a pair already rejected with recorded evidence. Keep at least one identical-artifact cross-runtime comparison where supported; otherwise report the comparison as confounded. Do not sweep the entire Cartesian product of every runtime/model/setting.

Perform acquisition while online, before measurement:

1. Use an operator-owned local account and a benchmark directory outside the repository and cloud-synced folders. In PowerShell: `$BenchRoot = Join-Path $env:LOCALAPPDATA 'AnonymousRuntimeBench'`; `New-Item -ItemType Directory -Force $BenchRoot`; `Set-Location $BenchRoot`. Create `tools`, `models`, `fixtures`, and a fresh dated `runs` directory. Keep commands/scripts under this root. Do not collect real conversations or credentials.
2. Download a chosen release from the official [Ollama releases](https://github.com/ollama/ollama/releases) and [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases). Record exact tag, source URL, archive filename, checksum, and acquisition date. For llama.cpp use the Windows x64 CUDA build and its matching runtime DLL bundle if the release requires it; keep all DLLs beside the executable. Do not mix releases. Prefer portable archives for isolation. If no compatible binary exists, record the blocker; a source-build experiment needs a separately recorded compiler/build recipe from the [upstream build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).
3. For each model, open the publisher repository's Files and versions page, choose an immutable commit revision, then download the exact quantized GGUF file(s) from that revision. Record every filename, revision and SHA-256. For split GGUFs obtain all shards. llama.cpp can load the first shard; if another runtime needs a single file, use the pinned release's `llama-gguf-split --merge FIRST-SHARD OUTPUT.gguf`, retain source and merged hashes, and use the same merged file in both runtimes. This is repackaging, not re-quantization. Do not silently substitute a registry tag.
4. Save model card, license, tokenizer/chat-template metadata and maximum advertised context with the candidate manifest. Hash artifacts using `Get-FileHash -Algorithm SHA256 PATH`. A moving `latest`/`main` reference alone is insufficient to reproduce a trial. Record any conversion recipe and source hashes.
5. Have a standalone Python 3 interpreter for the standard-library measurement snippets below; record its exact version with `py -3 --version`. This is external measurement tooling, not a selected Anonymous language/dependency. No pip package is needed. If absent, provision it separately before the session; do not change repository dependencies.
6. Inspect `--version` and `--help` for the pinned binaries, retaining output. Current upstream documentation informed these instructions on 2026-10-03; the actual binary's help and observed behavior govern that trial. Unsupported flags/options are compatibility findings, not permission to omit a control silently. Freeze binary/model versions for a comparison round.

Minimum `manifest.json` information: experiment ID/date; operator pseudonym; host alias; OS/build; CPU/cores; installed/free RAM; GPU/driver and dedicated/shared baseline; free disk/model location; power mode; runtime release/build/backend; archive/model hashes; model family/parameter count/quantization/license; tokenizer/template; requested/effective context; GPU layers/offload; threads/batch settings; KV type/Flash Attention; parallel slots; sampling/output cap; cache/load condition; fixture hashes; background workload; command line; instrumentation versions. Redact usernames, serial numbers, machine/network names, and private paths in material shared outside the host. Do not dump the entire environment.

## 4. Windows inventory, isolation, and telemetry

Open a fresh PowerShell console. Save inventory to a new session directory; do not overwrite prior evidence. Run locally, not through a remote connection that will be lost in the offline test.

```powershell
$BenchRoot = Join-Path $env:LOCALAPPDATA 'AnonymousRuntimeBench'
$Session = Join-Path $BenchRoot ('runs\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $Session | Out-Null
Set-Location $BenchRoot
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption,Version,BuildNumber,TotalVisibleMemorySize,FreePhysicalMemory |
  ConvertTo-Json | Set-Content "$Session\os.json"
Get-CimInstance Win32_Processor |
  Select-Object Name,NumberOfCores,NumberOfLogicalProcessors |
  ConvertTo-Json | Set-Content "$Session\cpu.json"
Get-CimInstance Win32_ComputerSystem |
  Select-Object TotalPhysicalMemory | ConvertTo-Json | Set-Content "$Session\ram.json"
Get-Volume | Select-Object DriveLetter,FileSystem,Size,SizeRemaining |
  Export-Csv "$Session\volumes.csv" -NoTypeInformation
powercfg /getactivescheme | Set-Content "$Session\power.txt"
$PSVersionTable | Out-String | Set-Content "$Session\powershell.txt"
py -3 --version 2>&1 | Set-Content "$Session\python.txt"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,memory.free --format=csv |
  Set-Content "$Session\gpu.csv"
```

CIM provides local inventory and counters; OS memory properties use documented units, including KiB for `FreePhysicalMemory`. Do not record it as bytes. [Microsoft CIM](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance), [OS properties](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem).

Quit unrelated model runtimes and avoid downloads, updates, video playback, or changing power modes during a comparison. Record the normal desktop apps that remain. Keep antivirus enabled and record its presence; do not weaken host security to improve scores. Allow five minutes of idle settling, then capture 60 seconds of idle telemetry. The settling time is a repeatability control, not a performance target.

In a second console, set `$Session` to the exact directory above and paste this sampler. It aims for one-second intervals; CIM overhead adds time, so retain actual UTC sample times. Start before runtime launch and stop with Ctrl+C after at least 60 seconds following unload. Record gaps as gaps, not zeros.

```powershell
while ($true) {
  $sampleTime = [DateTimeOffset]::UtcNow.ToString('o')
  $mem = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
  $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
  [pscustomobject]@{
    utc=$sampleTime; available_bytes=$mem.AvailableBytes
    committed_bytes=$mem.CommittedBytes; commit_limit=$mem.CommitLimit
    pages_input_sec=$mem.PagesInputPersec; pages_output_sec=$mem.PagesOutputPersec
    cpu_percent=$cpu.PercentProcessorTime
  } | Export-Csv "$Session\system.csv" -NoTypeInformation -Append
  Get-Process | Where-Object {
    $_.ProcessName -match '^(ollama|llama-server|python|python3)'
  } | ForEach-Object {
    [pscustomobject]@{
      utc=$sampleTime; pid=$_.Id; process=$_.ProcessName
      working_set_bytes=$_.WorkingSet64; private_bytes=$_.PrivateMemorySize64
      cpu_seconds=$_.CPU
    }
  } | Export-Csv "$Session\processes.csv" -NoTypeInformation -Append
  Start-Sleep -Seconds 1
}
```

Check the process filter against Task Manager once: include any differently named runner/child and record its PID, without dumping private command lines. Collect both whole-machine deltas and each runtime process. Summed working sets can double-count shared pages; they are not total unique RAM. Page reads can include ordinary mapped-file loading: sustained paging together with declining available RAM, higher commit, and latency degradation is stronger pressure evidence than an isolated counter spike.

In a third console:

```powershell
nvidia-smi --query-gpu=timestamp,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw --format=csv -l 1 -f "$Session\gpu-series.csv"
```

Record unsupported fields as unavailable and rerun with supported fields listed by `nvidia-smi --help-query-gpu`. WDDM may not expose reliable per-process GPU memory; use total device usage plus Task Manager's GPU dedicated/shared memory views. [NVIDIA SMI reference](https://docs.nvidia.com/deploy/nvidia-smi/index.html).

For a shared-memory time series on English Windows, use a fourth console:

```powershell
Get-Counter -Counter '\GPU Process Memory(*)\Dedicated Usage','\GPU Process Memory(*)\Shared Usage' -SampleInterval 1 -Continuous |
  ForEach-Object { $_.CounterSamples | Select-Object Timestamp,Path,CookedValue } |
  Export-Csv "$Session\gpu-process-memory.csv" -NoTypeInformation
```

Use `Get-Counter -ListSet *GPU*` to find the installed/localized names if needed. If unavailable, capture Task Manager GPU and Memory screenshots at idle, loaded, during largest prefill, during generation, and after unload; label this a sampled observation with no guaranteed peak. Do not call missing shared-memory data zero. [Microsoft counter documentation](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.diagnostics/get-counter).

Save an `events.csv` with `utc,trial_id,event` marking load, request start/end, failure, unload, and workload changes. Use `[DateTimeOffset]::UtcNow.ToString('o')` for event correlation; use a monotonic stopwatch for durations. Sampling gives observed peaks and may miss brief spikes.

During every trial, stop escalation if available RAM remains below 2 GiB for 10 seconds, system commit exceeds 90% of its limit for 10 seconds, the desktop becomes unresponsive, or the driver/runtime reports OOM/reset. These are conservative experiment stop conditions, not V0 acceptance thresholds. Retain the aborted result. Do not disable the pagefile, change GPU clocks, or kill unrelated user processes. First stop the identified request/runtime; preserve logs before retrying at a lower load.

## 5. Runtime setup and effective configuration

Run one candidate runtime at a time. Ports 11434 and 18080 below must be unused by unrelated services. Verify with `Get-NetTCPConnection -State Listen -LocalPort 11434,18080 -ErrorAction SilentlyContinue`. Use only loopback, never `0.0.0.0`, tunnels, LAN exposure, or public forwarding. Record the listener's owning PID after launch. This synthetic loopback experiment is not a protected Anonymous client deployment.

### 5.1 Ollama candidate

Quit the tray application to avoid testing a previously configured service. In a dedicated PowerShell console, use session-scoped variables and the pinned executable path:

```powershell
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $BenchRoot 'models\ollama-cache'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_CONTEXT_LENGTH = '2048'
$OllamaExe = Join-Path $BenchRoot 'tools\ollama\ollama.exe'
& $OllamaExe --version
$LaunchDir = Join-Path $Session ('ollama-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory $LaunchDir -ErrorAction Stop | Out-Null
& $OllamaExe serve 1> "$LaunchDir\stdout.log" 2> "$LaunchDir\stderr.log"
```

Set `$BenchRoot` and `$Session` in this console first. Confirm local-only mode in logs. Record effective Flash Attention/KV settings rather than trusting changing defaults. Keep them unchanged through baseline comparisons. Ollama's context, residency, cloud-disable and parallel controls are documented in its [FAQ](https://docs.ollama.com/faq).

In the request console, also set `OLLAMA_HOST` and `$OllamaExe`. Import the chosen local GGUF: create a UTF-8 file named `Modelfile` containing `FROM "ABSOLUTE/PATH/TO/MODEL.gguf"`, substituting the actual path (forward slashes avoid ambiguity). Then:

```powershell
$Candidate = 'anonymous-bench-ms-q4'
& $OllamaExe create $Candidate -f .\Modelfile
& $OllamaExe show $Candidate --modelfile | Set-Content "$Session\ollama-modelfile.txt"
& $OllamaExe list | Set-Content "$Session\ollama-models.txt"
```

Record imported metadata and template. If import fails, preserve the error and classify the artifact/runtime combination as unsupported; do not hide a fallback to other weights. [Ollama import procedure](https://docs.ollama.com/import).

For residency checks run `ollama ps` using this executable and host before/after each cold trial; save results. For CPU-only diagnostics, stop the dedicated server and relaunch it with session variable `$env:CUDA_VISIBLE_DEVICES = '-1'`, verifying CPU placement in logs and `ps`. Remove the variable and restart before GPU trials. If the pinned release does not honor this, classify the mode as unverified and use the explicit llama.cpp CPU probe; do not infer CPU use from a slow result. For partial offload, use observed automatic placement if exposed, recording the actual split; controlled layer sweeps below belong to llama.cpp. [Ollama GPU controls](https://docs.ollama.com/gpu).

### 5.2 llama.cpp candidate

Use the pinned `llama-server.exe`, not a model-routing/download mode. In the runtime console:

```powershell
$LlamaExe = Join-Path $BenchRoot 'tools\llama\llama-server.exe'
$ModelFile = Read-Host 'Absolute local GGUF path'
$Context = 2048
$GpuLayers = 99
& $LlamaExe --version
& $LlamaExe --help | Set-Content "$Session\llama-help.txt"
$LaunchDir = Join-Path $Session ('llama-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory $LaunchDir -ErrorAction Stop | Out-Null
& $LlamaExe -m $ModelFile --host 127.0.0.1 --port 18080 -c $Context -np 1 -ngl $GpuLayers -t 8 --fit off --no-context-shift --cache-ram 0 --perf 1> "$LaunchDir\stdout.log" 2> "$LaunchDir\stderr.log"
```

Eight threads is an initial control based on the reported eight-core CPU, not a tuned optimum. `99` requests up to that many layers; logs must establish actual placement. Set `-ngl 0` for a CPU diagnostic and an intermediate layer count for partial offload. Record actual offloaded layers, buffers, effective context, cache settings and backend. If the pinned help lacks a flag, select its documented equivalent and record the exact difference; never silently allow auto-fit to shrink context. Health readiness is `GET http://127.0.0.1:18080/health`. [llama.cpp server controls and endpoints](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Change one setting at a time and restart for each context/offload configuration. Run `--list-devices` if supported; retain device/backend evidence. Distinguish partial model-weight offload from Windows shared-memory spill. For an unambiguous CPU baseline use the pinned CPU-only build if a GPU build still allocates work to a GPU.

## 6. Measurement definitions and request recorder

| Measurement | Definition and collection |
| --- | --- |
| Load time | Ollama: final `load_duration / 1e9` on the first request after verified unload. llama.cpp: retain internal load timing if exposed, plus launch-to-healthy elapsed time measured with `time.perf_counter()`. Label startup/readiness, warmup, and weight-load durations separately; readiness is not a pure weight-load timer. |
| TTFT-visible | Client monotonic elapsed time from immediately before HTTP dispatch to first nonempty generated text event. This is an observable streaming proxy for first token, potentially affected by buffering. HTTP headers/first byte, empty events, and role metadata do not count. Record first reasoning output separately if a candidate emits it; visible answer may arrive later. |
| Generation rate | Ollama: `eval_count / (eval_duration / 1e9)`; llama.cpp: `timings.predicted_n / (timings.predicted_ms / 1000)`. Retain raw counters/units. Counts are generated tokens, not words, characters, or stream chunks. |
| Prefill | Retain input/cached token counts and evaluation duration; compare uncached prefill separately from cached continuation. |
| End-to-end latency | Dispatch to observed terminal success/error/EOF. Includes queue/load/prefill/decode/transport; does not include Anonymous persistence. |
| Memory/headroom | Sampled machine/process/device peaks, minimum available RAM, maximum commit, paging, dedicated/shared GPU use; compare idle, loaded, request and post-unload phases. Record absolute values and idle deltas. |
| Stability | Failure/timeout/OOM counts, output/completion validity, latency distribution and memory trend over repeated trials. Retain every attempt, including failures. |

Ollama timing fields use nanoseconds; they are distinct from wall-clock timestamps. [Generate API](https://docs.ollama.com/api/generate). The llama.cpp final response exposes timing/counter and truncation information; retain the pinned response format rather than assuming it matches another build. [Server response reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Save the following as `bench_request.py` in the external benchmark directory. It posts a supplied UTF-8 JSON request, records NDJSON or SSE events, and never retries. It uses the Python standard library, handles error/absent terminal outcomes, and avoids proxies for loopback. Only synthetic request bodies are allowed. Each run gets a new directory; failed records are not overwritten.

```python
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

p = argparse.ArgumentParser()
p.add_argument('--url', required=True)
p.add_argument('--body', required=True)
p.add_argument('--out', required=True)
a = p.parse_args()
u = urllib.parse.urlparse(a.url)
if u.scheme != 'http' or u.hostname != '127.0.0.1':
    p.error('Only explicit HTTP IPv4 loopback is allowed')
root = pathlib.Path(a.out)
root.mkdir(parents=True, exist_ok=False)
body = pathlib.Path(a.body).read_bytes()
json.loads(body.decode('utf-8-sig'))
body = body.decode('utf-8-sig').encode('utf-8')
(root / 'request.json').write_bytes(body)
print('request recorder PID', os.getpid(), flush=True)
(root / 'pid.txt').write_text(str(os.getpid()))
summary = {'pid': os.getpid(), 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'request_sha256': hashlib.sha256(body).hexdigest(), 'url': a.url,
           'status': 'incomplete', 'first_text_s': None, 'first_thinking_s': None}
req = urllib.request.Request(a.url, body, {'Content-Type': 'application/json'})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
start = time.perf_counter()
terminal = False
final = None
try:
    with opener.open(req, timeout=60) as response, (root / 'events.jsonl').open('w', encoding='utf-8') as log:
        summary['http_status'] = response.status
        for raw in response:
            elapsed = time.perf_counter() - start
            if elapsed > 600:
                raise TimeoutError('600-second trial observation limit')
            line = raw.decode('utf-8').strip()
            if not line or line.startswith(':') or line.startswith('event:'):
                continue
            if line.startswith('data:'):
                line = line[5:].strip()
            if line == '[DONE]':
                break
            event = json.loads(line)
            log.write(json.dumps({'elapsed_s': elapsed, 'event': event}) + '\n')
            log.flush()
            if event.get('error'):
                raise RuntimeError(str(event['error']))
            message = event.get('message') or {}
            choices = event.get('choices') or []
            delta = choices[0].get('delta', {}) if choices else {}
            text = event.get('response') or event.get('content') or message.get('content') or delta.get('content')
            thinking = event.get('thinking') or message.get('thinking') or delta.get('reasoning_content')
            if isinstance(text, str) and text and summary['first_text_s'] is None:
                summary['first_text_s'] = elapsed
            if isinstance(thinking, str) and thinking and summary['first_thinking_s'] is None:
                summary['first_thinking_s'] = elapsed
            if event.get('done') is True or event.get('stop') is True or any(c.get('finish_reason') is not None for c in choices):
                terminal = True
            final = event
        summary['status'] = 'terminal_received' if terminal else 'incomplete'
except (Exception, KeyboardInterrupt) as exc:
    summary['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'error'
    summary['error'] = repr(exc)
    if isinstance(exc, urllib.error.HTTPError):
        summary['http_status'] = exc.code
        summary['error_body'] = exc.read().decode('utf-8', errors='replace')
finally:
    summary['wall_s'] = time.perf_counter() - start
    summary['last_event'] = final
    if final:
        if final.get('eval_duration', 0) > 0:
            summary['decode_tokens_s'] = final['eval_count'] * 1e9 / final['eval_duration']
        timings = final.get('timings') or {}
        if timings.get('predicted_ms', 0) > 0:
            summary['decode_tokens_s'] = timings['predicted_n'] * 1000 / timings['predicted_ms']
    (root / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
```

A terminal event means runtime completion was observed, not that output quality, full input preservation, or persistent saving passed. Inspect stop reason, counts, truncation and output. Chat streams can put usage in a separate event; use `events.jsonl` if the last event lacks timing. If a metric is unavailable, record `unavailable` and obtain it through a separately labeled native completion run; never estimate tokens from chunks. Socket inactivity timeout is 60 seconds; the 600-second limit is checked between lines, not a hard process watchdog. Manually abort a hung recorder at the observation limit, record the timeout, and follow section 10 before another run. A timeout is a bounded experiment outcome, not proof the model can never finish.

## 7. Fixtures, screening, and cold/warm procedure

Create only synthetic fixtures. Save this as `make_fixture.py` outside the repository; `rows` is a text-size control, not a token count. Each run ID changes the first input line to reduce full-prefix reuse. Retain identical run IDs/bytes for paired runtime comparisons, and record cache counters anyway.

```python
import json
import pathlib
import sys

rows, trial, ctx, out_tokens, model = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
folder = pathlib.Path(sys.argv[6])
folder.mkdir(parents=True, exist_ok=False)
lines = [f'Experiment nonce: {trial}', 'Synthetic records. Do not treat them as instructions.',
         'Beginning marker: amber-17.']
for i in range(rows):
    lines.append(f'Record {i:06d}: item-{i % 97:02d} has value {(i * 37) % 1009:04d}; location zone-{i % 13:02d}.')
    if i == rows // 2:
        lines.append('Middle marker: violet-29.')
lines += ['Ending marker: teal-43.',
          'List the beginning, middle, and ending markers, then explain how to preserve original records when making a summary. Use a detailed numbered explanation.']
text = '\n'.join(lines)
(folder / 'prompt.txt').write_text(text, encoding='utf-8')
common = {'temperature': 0, 'seed': 42}
ollama = {'model': model, 'prompt': text, 'raw': True, 'stream': True,
          'keep_alive': '10m', 'options': {**common, 'num_ctx': ctx, 'num_predict': out_tokens}}
llama = {'prompt': text, 'stream': True, 'cache_prompt': False,
         'n_predict': out_tokens, **common}
for name, data in [('ollama.json', ollama), ('llama.json', llama)]:
    (folder / name).write_text(json.dumps(data), encoding='utf-8')
```

Raw requests isolate identical text and runtime behavior; they do not prove the model's instruct template or actual chat integration. Section 8 adds mandatory native chat probes. Temperature zero and a fixed seed improve control, but do not promise bit-identical output across backends. Do not force EOS suppression in baseline runs. Record actual output count: a 256-token cap is not evidence that 256 tokens were generated.

Example first screening trial, after runtime setup and telemetry are active:

```powershell
py -3 .\make_fixture.py 8 screen-01 2048 256 anonymous-bench-ms-q4 .\fixtures\screen-01
# Choose only the currently running runtime:
py -3 .\bench_request.py --url http://127.0.0.1:11434/api/generate --body .\fixtures\screen-01\ollama.json --out "$Session\screen-01-ollama"
py -3 .\bench_request.py --url http://127.0.0.1:18080/completion --body .\fixtures\screen-01\llama.json --out "$Session\screen-01-llama"
```

Execute one successful short screening request per initial candidate pair. Record any missing DLL, unsupported architecture, startup error, rejected setting, OOM, silent fallback or empty output. Retain logs and actual placement. Do not compare throughput from failure or different output lengths as if matched.

For each pair promoted after screening:

1. **Runtime-cold, disk-cache-unspecified:** Three trials at each proposed operating context. For Ollama, run `& $OllamaExe stop $Candidate`, wait until `ps` shows it absent, and confirm memory settles before requesting. For llama.cpp stop the dedicated process, verify it exits, then relaunch with the same settings. Record cold load plus first request. Unload/process restart does not clear the OS file cache.
2. **Startup timing:** For llama.cpp, measure launch-to-HTTP-200 readiness with a monotonic timer and retain startup logs. An exact Python launcher is below. Internal model load timing, if emitted, is a separate measurement. Do not label all readiness time as model loading.
3. **Resident warm:** After an excluded warmup, run five sequential requests with different first-line nonces, unchanged size/sampling/output cap. Confirm weights remain resident. llama.cpp uses `cache_prompt:false`; for Ollama inspect available cache counts/logs. If prefix reuse cannot be ruled out, label the measurement `cache_unknown` rather than uncached.
4. **Repeated prefix:** Optionally send the identical body five times as a separate `cache_reuse` condition. Never mix these samples with cold/fresh-prefix medians.
5. **Stability:** On every proposed operating configuration, run 20 sequential warm trials, then three unload/reload cycles. Retain per-trial timings/memory, first-versus-last-five medians, failures and post-unload observations. No automatic retry. If interrupted, keep completed attempts and resume with new IDs; report the incomplete round.
6. Rotate candidate order between rounds and record the order. Run the paired comparison under the same workload/power/telemetry settings. Report median, minimum, maximum and all raw samples for small groups; do not advertise a robust p95 from five samples. Rates and sizes across different tokenizers are not directly equivalent measures of task quality.

Save `start_llama.py` next to the recorder; it leaves the runtime running and records only its own child PID. Use new output directory and the same argument list as section 5:

```python
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

root = pathlib.Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
start = time.perf_counter()
with (root / 'stdout.log').open('w') as out, (root / 'stderr.log').open('w') as err:
    proc = subprocess.Popen(sys.argv[2:], stdout=out, stderr=err)
    result = {'pid': proc.pid, 'status': 'not_ready'}
    (root / 'pid.txt').write_text(str(proc.pid))
    while time.perf_counter() - start < 600 and proc.poll() is None:
        try:
            with opener.open('http://127.0.0.1:18080/health', timeout=2) as response:
                if response.status == 200:
                    result['status'] = 'ready'
                    break
        except Exception:
            pass
        time.sleep(0.1)
    result['launch_to_observation_s'] = time.perf_counter() - start
    result['exit_code'] = proc.poll()
    (root / 'startup.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
```

Before this launcher, verify port 18080 is free; otherwise it could observe the wrong process. Example:

```powershell
py -3 .\start_llama.py "$Session\load-01" $LlamaExe -m $ModelFile --host 127.0.0.1 --port 18080 -c 2048 -np 1 -ngl 99 -t 8 --fit off --no-context-shift --cache-ram 0 --perf
```

If not ready, inspect the recorded PID/logs and stop only that benchmark process; the launcher does not kill it automatically. Optional disk-cold trials require a recorded reboot and first load with the same startup apps; do not use undocumented cache-purge tricks. These are separate samples, not replacements for the three runtime-cold repeats.

## 8. Practical context, chat compatibility, and offload

For each viable pair sweep configured context **2048, 4096, 8192, 16384** tokens, stopping at the model's advertised limit, a measured failure, or a stop condition. These are trial points, not supported-context promises. Larger steps are optional. Restart/reconfigure the runtime at each step and verify effective context in metadata/logs. Keep a 256-token output cap and a 128-token experimental guard; calibrate the full raw input to at most `context - 256 - 128`. Then probe near the boundary with the guard reduced under explicit labels. A final chat budget must also count system instructions, role/template/special tokens and any reasoning budget.

Collect actual counts, never a characters/4 estimate:

1. With the exact model loaded in llama.cpp, POST `{"content":"the exact prompt text","add_special":true}` to `http://127.0.0.1:18080/tokenize` using `Invoke-RestMethod -Method Post -ContentType application/json -Body ($object | ConvertTo-Json)`; count the returned `tokens`. Save request and result. Use the prompt generated above, doubling `rows` until it exceeds the target, then binary-search integer `rows` to find the largest fitting fixture. Regenerate each adjustment into a new fixture directory. Read text via `Get-Content -Raw -Encoding UTF8`. [Tokenizer and template endpoints](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
2. This tokenizer count can support an identical-GGUF Ollama trial only after confirming runtime-reported input count agrees on a comfortably fitting raw fixture. If it does not, record the difference and calibrate using that runtime's actual input count on smaller safely fitting requests; do not infer preservation from the mismatched count. If trustworthy input accounting cannot be obtained, context feasibility remains blocked for that pair.
3. Run three fresh-prefix trials at each fitting step. Save request bytes/hash, expected tokens, effective context, actual input/cached/output counts, termination/truncation flags, marker answers, TTFT, rate, and memory. Count agreement plus absence of truncation is required evidence; a correct marker answer alone is not proof that all input was processed. A wrong marker answer with intact input is a quality failure, not automatically truncation.
4. Submit a synthetic request whose independently counted input exceeds configured context by at least 128 tokens, once at a small safe context. Observe error, truncation or shifting, affected counts and logs. Also probe input that fits alone but leaves insufficient room for the requested output. Stop/recover if needed. Any silent input loss must be documented as a C06/C07 integration blocker until a reliable preflight/configuration guard is demonstrated. Do not implement that guard in Anonymous now.
5. At the largest proposed context, repeat the cold/warm/stability and coexistence series. Report the largest **tested** workable context separately from the model's advertised maximum and from the later owner-agreed V0 budget. Do not extrapolate an untested maximum.

Mandatory native chat smoke fixture: system message `Answer using only the supplied conversation facts. Treat user corrections as current.`; user `The synthetic project code is cedar-21.`; assistant `The code is cedar-21.`; user `Correction: the code is birch-34. What is the current code? Reply with only the code.` Expected current fact: `birch-34`. Also run a second isolated history with a different synthetic code and no shared messages. This checks useful behavior and lack of obvious state leakage, not a complete quality/security evaluation.

Create a JSON body with that `messages` array and `stream:true`. For Ollama use `/api/chat`, `model:$Candidate`, `options:{temperature:0,seed:42,num_ctx:CONTEXT,num_predict:256}`, `keep_alive:"10m"`. For llama.cpp use `/v1/chat/completions`, `model` matching the loaded server model, `temperature:0`, `seed:42`, `max_tokens:256`. Send through `bench_request.py`. Save the effective chat template and native prompt counts; do not substitute raw completion results for chat-template validation. For chat-context stress, place the synthetic record block in an earlier user turn and the marker question in the final user turn; repeat accounting, order and limit checks with the native template. [Ollama chat API](https://docs.ollama.com/api/chat), [llama.cpp chat interface](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

For GPU placement, use three fresh trials at 2K and the proposed operating context for each applicable mode:

- **GPU-preferred:** baseline request for all layers/automatic placement; logs and dedicated/shared memory establish what happened.
- **Partial offload:** in llama.cpp record model layer count `L`, try `-ngl floor(L/2)`, then a measured fitting count if useful. Preserve explicit context and threads. In Ollama characterize an observed split if one occurs; do not call it equivalent to a controlled layer count. Record host RAM, PCIe-related slowdown if observable, and whether paging occurs.
- **CPU-only:** small candidate with no GPU offload, verified by runtime logs and telemetry. Test eight CPU threads initially. Sixteen-thread or other tuning is optional. If a proposed fallback needs it, extend full mandatory coverage to that fallback; otherwise label it diagnostic only.

Failure at full offload does not prove the model is unusable with partial offload; loading with partial offload does not prove acceptable latency. Weight quantization and KV-cache quantization are different controls. Keep KV type fixed for weight comparisons; any change becomes a separate experiment with renewed context/quality checks.

## 9. Coexistence with the future Anonymous server

The server does not exist. Measure three profiles on each proposed Windows configuration and retain them separately:

| Profile | Exact workload | Interpretation |
| --- | --- | --- |
| P0 | Settled desktop, recorder and telemetry, one runtime only | Isolated baseline including instrumentation overhead. |
| P1 | P0 plus fixed synthetic 2 GiB resident-memory reserve and approximately one logical CPU's busy work; normal recorded desktop/browser remains open | Sensitivity probe for server/client headroom. Neither size nor CPU demand is an estimate of Anonymous. |
| P2 | Later, actual authorized Anonymous build with its storage/context/authentication work and representative client operations | Required integration follow-up before declaring real coexistence. Not executable in this documentation task. |

Save as `reserve.py` outside the repository. It holds two GiB in touched 16 MiB chunks, re-touches pages, and runs one Python worker. Runtime 15 minutes is an experiment cap. Start only with enough available RAM to respect section 4 stop conditions. Its printed PID is for cleanup.

```python
import os
import time

print('synthetic reserve PID', os.getpid(), flush=True)
blocks = []
for _ in range(128):
    block = bytearray(16 * 1024 * 1024)
    for offset in range(0, len(block), 4096):
        block[offset] = 1
    blocks.append(block)
print('reserve ready; verify actual resident memory in telemetry', flush=True)
end = time.perf_counter() + 900
value = 1
try:
    while time.perf_counter() < end:
        for block in blocks:
            for offset in range(0, len(block), 4096):
                block[offset] ^= 1
        for _ in range(100000):
            value = (value * 1664525 + 1013904223) & 0xffffffff
except KeyboardInterrupt:
    pass
```

Run `py -3 .\reserve.py` in a separate console. Confirm actual working set/private bytes and CPU use before trials; OS paging may reduce residency, so requested reservation is not proof of physical residency. Run the same five warm fixtures as P0, followed by a 20-trial stability series at the proposed context; restart the reserve under a new workload-segment ID if its time cap expires. Repeat one cold load under P1. During each run, type and scroll a local synthetic text page in the browser and record freezes/stalls with trial/time references. Use no private pages. Capture remaining RAM/VRAM, paging and rate/TTFT changes relative to P0. End the reserve with Ctrl+C and confirm memory recovery.

If this profile is too heavy or too light to distinguish behavior, record that outcome; optional 1/4 GiB or different CPU profiles may explore sensitivity under new labels. Do not silently redefine P1 or turn two GiB into a production memory requirement. P2 later must measure real persistence/context work, protected reads during generation, UI responsiveness, and memory peaks with the same metrics and fixtures. No database write-loop or invented server framework is needed now.

## 10. Serial admission, failure, and local-only probes

Perform on each configuration proposed for selection, using synthetic data and isolated recorded PIDs. Keep telemetry running. Give each probe a fresh trial ID and retain startup/request logs. Do not erase model files or touch a real conversation store.

1. **Serial path:** Twenty sequential requests must be attributable and leave the runtime reusable. Configure one runtime slot and one loaded model for this experiment. A single global slot is a benchmark control, not a decision about scheduling between conversations.
2. **Overlap characterization:** Use a sufficiently long prompt/output to keep request A active; start request B from a second recorder console while A is visibly generating. Save both timings and runtime slot/process activity. Classify B as queued, rejected, parallel, or unknown. Runtime queueing alone cannot meet V0-D04: Anonymous C05 must refuse a second send to the same busy conversation before dispatch or append. Runtime requests have no authoritative Anonymous conversation identity. Later integration must test two clients sending to the same conversation, plus eligible retry; leave V0-AC-07 pending here.
3. **Requester disconnect:** After first output, press Ctrl+C in the recorder. Observe whether inference continues, cancels, releases its slot, or stays uncertain. Save runtime logs and 60 seconds of post-disconnect telemetry. Record time to confirmed quiescence; if not confirmed, mark unresolved and do not start overlapping replacement work.
4. **Requester death:** Repeat by terminating only the recorder process through Task Manager (use `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId,ParentProcessId` to identify the recorded benchmark process; verify before stopping). There may be no final summary, so retain request/events and a manual interruption record. This approximates loss of an upstream process, not an Anonymous crash-recovery test. Establish what a restarted supervisor could observe through runtime status/logs/process control. Low GPU use alone does not prove the request ended.
5. **Runtime death and recovery:** During a separate request, stop only the isolated runtime PID/process tree. For a known benchmark tree, Windows `taskkill /PID RECORDED_PID /T /F` provides the abrupt-stop probe; substitute the verified PID. Confirm client error/incomplete outcome, collect exit status/logs, restart with the same settings, and explicitly send a new request. Do not treat its output as recovery of the killed response. Repeat normal stop/restart separately.
6. **Orphan-resolution evidence:** If a killed requester leaves work active, record the supported way to observe completion, cancel that request, or terminate the isolated runtime tree and prove it has exited before another request. Track worker descendants and confirm no automatic respawn. Runtime-wide stopping may be operationally disruptive and is only experimental evidence, not an accepted production recovery mechanism. If bounded termination/reconciliation cannot be demonstrated, C05/C07/C10 lifecycle feasibility remains blocked even if throughput is good.
7. **Unavailable runtime:** With the runtime stopped, send one request; retain connection failure and confirm the recorder performs no retry/fallback. Recover explicitly. Synthetic oversize-context and capacity failures from section 8 also belong in the failure inventory.
8. **Offline local operation:** After all required artifacts are present, use the Windows network UI locally to disconnect Wi-Fi and unplug Ethernet (and any other external route), retaining loopback. Record start/end times and disconnected state without publishing network identifiers. Restart the candidate offline, then run three chat/short-context requests and one unload/reload. Confirm local execution, no account requirement, and no missing-model download/cloud fallback. Restore the prior connection afterward. Record loopback listeners with `Get-NetTCPConnection -State Listen -LocalPort 11434,18080 -ErrorAction SilentlyContinue`. No public bind is permitted. Offline success proves no required external connection for these fixtures, not absence of all future telemetry when online; later security review still applies.

Preserve request/output association using trial IDs, hashes and logs, never timestamps alone. The evidence must describe observable boundaries that a future adapter/supervisor could use; application persistence, duplicate reconciliation, revocation and recovery remain untested until implemented.

## 11. Optional M1 Pro MacBook procedure

Keep Mac results separate. They do not make Mac inference or distributed execution part of V0. Use native Apple Silicon builds with a documented Metal backend; do not compare an emulated x86 build or Docker GPU behavior as equivalent. Pin the same model artifacts and fixture hashes where supported. Record macOS build, runtime/Metal support, unified-memory totals, AC power/battery mode, available disk and background apps. Apple's memory-pressure view reflects more than just free memory. [Activity Monitor memory guidance](https://support.apple.com/guide/activity-monitor/view-memory-usage-actmntr1004/mac).

Run in a local non-synced external folder:

```sh
sw_vers > mac-os.txt
uname -m > mac-architecture.txt
sysctl hw.memsize hw.physicalcpu hw.logicalcpu > mac-hardware.txt
system_profiler SPHardwareDataType SPDisplaysDataType > mac-hardware-private.txt
df -h . > mac-disk.txt
pmset -g custom > mac-power.txt
shasum -a 256 /absolute/path/to/model.gguf > model.sha256
vm_stat 1 > vm-series.txt
```

`system_profiler` can contain serial/host identifiers: redact before sharing. Run `vm_stat` in its own console, stop with Ctrl+C, and retain its reported page size when converting counts. In another console, every second record `date -u '+%Y-%m-%dT%H:%M:%SZ'`, `sysctl vm.swapusage`, and `ps -o pid,rss,%cpu,comm -p RUNTIME_PID`; RSS is KiB and a process sample is not unique total GPU+CPU memory. Include worker PIDs. Capture Activity Monitor Memory Pressure, compressed memory and swap at the same five phase boundaries used on Windows. Do not add a supposed VRAM total to unified RAM.

Use the same standard-library scripts with `python3`, same trial counts, context/output controls and stop conditions adapted to unified memory; stop on sustained red pressure or severe swapping/unresponsiveness. For llama.cpp use the native executable and the section 5 arguments, recording actual Metal offload. For Ollama run the native standalone executable with session environment `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1`, with a dedicated model directory. Quit any existing app before launch. Use pinned help rather than assuming CUDA controls affect Metal. CPU-only runs use an explicitly CPU-configured llama.cpp build/mode and verify logs.

Do a small/medium 2K screen before a full optional matrix. The Windows 2 GiB reserve is a sensitivity comparison, not a claim about a 16 GB Mac server. Do not infer Windows performance or purchase needs from Mac results.

## 12. Evidence package, decision rubric, and remaining gates

Keep raw artifacts locally outside the repository: manifests, exact scripts/commands, help/version outputs, model/fixture hashes, runtime startup logs, request/event/final records, telemetry CSVs, phase screenshots, and a manual failure ledger. Later publish only sanitized summaries and synthetic fixtures under a separately authorized evidence task; do not commit model binaries, credentials, private paths or user data.

For matched throughput comparisons, flag trials that end early or produce very few tokens; do not compare their startup-dominated rates to long decodes without qualification. Longer fixed-cap fixtures are optional follow-ups, with actual EOS behavior retained.

One result row per attempt, including failed attempts:

```text
trial_id,host_alias,runtime_build,backend,model_revision,artifact_sha256,
quantization,context_requested,context_effective,input_tokens,input_cached_tokens,
output_cap,output_tokens,offload_requested,offload_observed,threads,kv_type,
cache_condition,load_condition,workload_profile,load_metric_kind,load_seconds,
startup_ready_seconds,ttft_visible_seconds,first_thinking_seconds,decode_tokens_sec,
wall_seconds,ram_available_min_bytes,ram_commit_peak_bytes,runtime_private_peak_bytes,
gpu_dedicated_peak_bytes,gpu_shared_peak_bytes,paging_observation,
http_status,stop_reason,truncation,status,error_class,evidence_paths
```

Use `not_measured`, `unsupported`, `unknown`, or `not_applicable` with explanations; never put zero for missing data. Add units and collection method to every manual measurement. Report prompt and decode timing separately; load, TTFT, and runtime total can overlap and should not be summed blindly. Preserve actual output lengths and separate thinking/non-thinking modes. Summaries should identify the trial set and exclusions, not silently discard outliers or failures.

Decision record template (leave results pending until run):

| Question | Evidence to enter | Current state |
| --- | --- | --- |
| Which runtime/model/quant combinations loaded and executed on Windows? | RF-01/02 rows plus failures and hashes | Not measured |
| Which context/offload profiles fit with useful headroom? | RF-03/04/08 and effective counts/settings | Not measured |
| What are cold/warm load, TTFT and generation distributions? | Raw trials, median/min/max, cache distinctions | Not measured |
| Does behavior remain stable under repetition and P1? | RF-03/05 trends, errors, paging and responsiveness | Not measured |
| Can ongoing work be bounded/observed after upstream or runtime failure? | RF-06 lifecycle evidence and unresolved adapter obligations | Not measured |
| Does execution work offline without a mandatory paid service? | RF-07, artifact/license/prerequisite inventory | Not measured |
| What performance/quality envelope does the owner accept? | Explicit context/output workload, maximum cold/warm wait, minimum useful rate, memory reserve and task-quality expectations, agreed after reviewing results | Not agreed |
| Is a final runtime/model selected? | Separate decision/ADR after evidence review | No |

Classify each candidate as **blocked** (compatibility, missing evidence, or unresolved lifecycle/input-integrity issue), **unsuitable for a tested profile**, or **feasible within a measured profile pending product acceptance**. Do not claim universal hardware compatibility. If none works, report the specific failures and consider another local candidate or an explicit scope revision; do not silently require a hardware purchase or cloud inference.

A later recommendation must cite exact successful and failed trial IDs, explain quality/latency/memory/maintenance tradeoffs, identify a supported context/output envelope, and state remaining risk. Final approval requires explicit measured acceptance targets; no model-size rule or vendor reputation can substitute for evidence. A second production integration is not required by V0-AC-11; these comparative experiments do not implement its replaceability fixture.

Still required after this experiment: actual C05 admission/reconciliation and C10 restart recovery with persistent history; C06 input construction/omission behavior; real P2 server coexistence; protected Windows/Mac/iPhone client acceptance; security/credential/transport design; FR-15 timestamp persistence/display; data model and API design. No runtime benchmark passes these by itself.

## 13. Documentation validation and execution handoff

Before executing, the operator must confirm pinned binaries accept the recorded commands, telemetry is nonempty with correct units, the streamer observes actual content before completion, effective context/offload are visible, and only intended loopback ports are used. Record any correction under a new procedure revision before collecting comparable samples. Current command blocks are unexecuted on the target hardware; static review is not a compatibility result.

Preparation checks on 2026-10-03 passed for local links, requirement/scenario references, the eight evidence groups, Markdown fences/whitespace, and Python syntax in all four embedded programs. PowerShell was unavailable in the preparation environment; Windows commands received manual review only. No runtime requests or hardware benchmarks ran. Existing requirements, scope, architecture, domain model, ADRs, and application areas were left unchanged.

The mandatory run sequence is: acquire/pin → verify inventory → idle telemetry → screen candidates → calibrate fixtures → context/offload sweep → cold/warm/stability → P1 coexistence → lifecycle/offline probes → sanitized evidence review → agree finite acceptance envelope → consider a separate selection decision. Optional Mac/tuning work follows without delaying a reported Windows blocker.

## ChatGPT handoff summary

- **Completed:** A documentation-only V0 runtime feasibility procedure covering the Windows desktop, with optional M1 Pro measurements; mandatory/optional evidence, pinned candidates, collection commands, synthetic workloads, timing/memory/context/offload checks, coexistence, lifecycle and reporting rules.
- **Not performed:** Runtime installation, model downloads, hardware inspection, benchmark execution, Anonymous implementation, or runtime/model selection. No benchmark results exist from this task.
- **Candidates, not decisions:** Native Ollama and llama.cpp; small/medium quantized instruct models with a controlled quantization comparison. Larger models and Mac hosting remain optional experiments.
- **Important boundary:** Runtime serialization is not Anonymous per-conversation admission; synthetic resource reservation is not proof of real server coexistence; runtime timestamps are not FR-15 commit times.
- **Next task:** Execute the mandatory Windows procedure on the actual equipment, retain all raw evidence locally, and return a sanitized comparison with blockers and proposed acceptance targets. Use those results to decide whether further candidate trials or a selection ADR are justified. Detailed security/data/API work and actual application integration gates remain open.
