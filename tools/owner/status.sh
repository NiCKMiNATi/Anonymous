#!/bin/bash
# Report the state of the Anonymous v0.1 development prototype. Read-only.
#
#   tools/owner/status.sh
#
# Shows the runtime (identity, sole listener, readiness), the application (listener, health,
# generation state) and each dataset's run-status counts. It starts nothing, signals nothing,
# writes nothing and never asks the model to generate: the only requests are two loopback GETs of
# health endpoints, and datasets are opened read-only for run-status counts. It prints no message
# content, no key and no file paths.
#
# Exit 0: no anomaly. Exit 1: something needs attention (stale or mismatched launch state, an
# unexpected listener, an unhealthy application, an interrupted launch).

set -u -o pipefail
. "$(dirname "$0")/lib.sh"

[ $# -eq 0 ] || {
  echo "Usage: tools/owner/status.sh" >&2
  exit 2
}

require_macos
setup_paths
load_config lenient
require_python

ANOMALY=0
flag() {
  ANOMALY=1
  say "  ! $*"
}

say "Anonymous v0.1 development prototype (loopback only, no authentication, synthetic data only)"
say ""

# -- runtime ---------------------------------------------------------------------------------------

say "Runtime (127.0.0.1:$LLAMA_PORT)"
runtime_alive=0
if [ -e "$INTENT" ] || [ -L "$INTENT" ]; then
  flag "an interrupted launch left a recovery file; follow the runbook, section 'Diagnosing'. Do not launch again."
fi
if [ -e "$RECORD" ] || [ -L "$RECORD" ]; then
  rc=0
  out=$(ctl status 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    flag "the launch record is unreadable or unsafe (${out:+$(refusal_code "$out")})."
  else
    matches=$(printf '%s' "$out" | jget process_identity_matches)
    sole=$(printf '%s' "$out" | jget sole_listener_is_recorded_process)
    say "  recorded process: pid $(printf '%s' "$out" | jget pid), identity matches: $matches"
    say "  sole listener is the recorded process: $sole"
    say "  model: $(printf '%s' "$out" | jget model.label) ($(printf '%s' "$out" | jget model.digest_verification)); runtime: $(printf '%s' "$out" | jget runtime.label) ($(printf '%s' "$out" | jget runtime.digest_verification))"
    if [ "$matches" = true ] && [ "$sole" = true ]; then
      runtime_alive=1
      code=$(http_code "http://$LOOPBACK:$LLAMA_PORT/health")
      if [ "$code" = 200 ]; then
        say "  readiness (GET /health): ready"
      else
        flag "readiness (GET /health) returned $code"
      fi
    elif [ "$matches" = true ]; then
      flag "the recorded runtime is alive but is not the sole listener on its port."
    else
      flag "the launch record is stale (the recorded process is gone). tools/owner/stop.sh cleans it safely."
    fi
  fi
else
  say "  no launch record: the runtime is not running under the wrappers."
  case $(port_state "$LLAMA_PORT") in
    free) ;;
    busy) flag "port $LLAMA_PORT is occupied by an unrecorded program: $(port_listener_desc "$LLAMA_PORT" | tr '\n' ' ')" ;;
    *) flag "port $LLAMA_PORT could not be inspected." ;;
  esac
fi

# -- application -----------------------------------------------------------------------------------

say ""
say "Application (127.0.0.1:$APP_PORT)"
app_state=$(port_state "$APP_PORT")
case $app_state in
  free) say "  not running." ;;
  unknown) flag "port $APP_PORT could not be inspected." ;;
  busy)
    say "  listener: $(port_listener_desc "$APP_PORT" | tr '\n' ' ')"
    body=$("$CURL" --noproxy '*' -sS --max-time 3 "http://$LOOPBACK:$APP_PORT/api/v1/health" 2>/dev/null) || body=''
    if [ -n "$body" ] && [ "$(printf '%s' "$body" | jget status)" = ok ]; then
      say "  health: ok, schema version $(printf '%s' "$body" | jget schema_version)"
      gen=$(printf '%s' "$body" | jget generation.state)
      say "  generation: ${gen:-unknown}, quarantined runs: $(printf '%s' "$body" | jget generation.quarantined_runs)"
      if [ "$gen" != open ]; then
        flag "generation is $gen: new messages are refused. See the runbook, 'A blocked dataset'."
      fi
    else
      flag "the listener did not answer as a healthy Anonymous application."
    fi
    ;;
esac

# -- datasets (run-status counts only) -------------------------------------------------------------

say ""
say "Datasets"
found=0
if [ -d "$DATA_DIR" ]; then
  for file in "$DATA_DIR"/*-dev.sqlite3; do
    [ -e "$file" ] || continue
    found=1
    name=${file##*/}
    name=${name%-dev.sqlite3}
    line=$(dataset_state "$file")
    say "  $name: $line"
    case ${line%% *} in
      unsettled) if [ "$app_state" != busy ]; then flag "dataset '$name' has an unsettled run and the application is not running (it is reconciled at the next start)."; else say "    (a reply is being generated, or one was left unsettled)"; fi ;;
      blocked) say "    (blocked: history readable, new messages refused; keep it and start a new dataset)" ;;
      busy | unreadable) flag "dataset '$name' could not be read." ;;
    esac
  done
fi
[ "$found" -eq 1 ] || say "  none yet."

say ""
if [ "$ANOMALY" -eq 0 ]; then
  if [ "$runtime_alive" -eq 1 ]; then say "Result: consistent."; else say "Result: consistent (nothing running)."; fi
  exit 0
fi
say "Result: needs attention (see the lines marked !)."
exit 1
