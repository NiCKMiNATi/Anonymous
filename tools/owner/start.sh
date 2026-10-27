#!/bin/bash
# Start the Anonymous v0.1 development prototype: pinned local Qwen runtime + the application.
#
#   tools/owner/start.sh [--dataset NAME] [--allow-battery] [--allow-blocked]
#
# DEVELOPMENT ONLY: macOS, loopback only, no authentication, synthetic data only.
#
# Order: verify prerequisites -> (reuse a verified runtime, or launch the pinned runtime through the
# existing launcher with both digests hashed against the pins) -> verify identity and readiness ->
# run the application in the FOREGROUND. Ctrl-C ends the application only; the runtime stays up so
# the application can be restarted. End the runtime with tools/owner/stop.sh. If anything fails
# after this invocation launched the runtime, that runtime is stopped again (identity-verified).
# The wrapper never downloads or installs anything, never creates, resets or deletes a dataset, and
# never signals a process except through the launcher's identity-verified stop.

set -u -o pipefail
. "$(dirname "$0")/lib.sh"

usage() {
  cat <<'EOF'
Usage: tools/owner/start.sh [--dataset NAME] [--allow-battery] [--allow-blocked]

  --dataset NAME   dataset to open; it lives as NAME-dev.sqlite3 in the owner data directory.
                   A name that does not exist yet starts a NEW empty dataset (default: anonymous).
  --allow-battery  start although the Mac is not on AC power (a sleep during a reply can
                   quarantine the dataset).
  --allow-blocked  open a dataset that is blocked, for reading its history only (new messages are
                   refused by the application).
EOF
}

DATASET=anonymous
ALLOW_BATTERY=0
ALLOW_BLOCKED=0
while [ $# -gt 0 ]; do
  case $1 in
    --dataset)
      [ $# -ge 2 ] || {
        usage >&2
        exit 2
      }
      DATASET=$2
      shift 2
      ;;
    --allow-battery)
      ALLOW_BATTERY=1
      shift
      ;;
    --allow-blocked)
      ALLOW_BLOCKED=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

ROLLBACK=0 # 1 only while this invocation owns a runtime it launched

rollback_runtime() {
  [ "$ROLLBACK" -eq 1 ] || return 0
  ROLLBACK=0
  note "Stopping the runtime this invocation launched (identity-verified stop)..."
  local out rc=0
  out=$(ctl stop --remove-files 2>&1) || rc=$?
  if [ "$rc" -eq 0 ]; then
    note "The runtime is stopped and its launch files are removed."
  else
    note "The runtime could not be confirmed stopped (exit $rc, $(printf '%s' "$out" | jget result)$(refusal_code "$out")). Run tools/owner/stop.sh, then see the runbook, section 'Diagnosing'."
  fi
}
trap rollback_runtime EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# -- 1. prerequisites (nothing is started or changed) ----------------------------------------------

require_macos
setup_paths
load_config strict
load_pins
require_python

case $DATASET in
  '' | .* | *[!A-Za-z0-9._-]* | *..*) die 2 "dataset names use letters, digits, '.', '_' and '-', must not start with '.' and must not contain '..'." ;;
esac
[ "${#DATASET}" -le 64 ] || die 2 "dataset names are at most 64 characters."

[ -f "$RUNTIME_BIN" ] && [ ! -L "$RUNTIME_BIN" ] && [ -x "$RUNTIME_BIN" ] ||
  die 2 "RUNTIME_BIN is not an executable regular file (set it in the owner configuration)."
[ -f "$MODEL_PATH" ] && [ ! -L "$MODEL_PATH" ] ||
  die 2 "MODEL_PATH is not a regular file (set it in the owner configuration; models are never downloaded for you)."
[ -f "$REPO_ROOT/client/dist/index.html" ] ||
  die 2 "the browser client is not built. Run 'npm run build' in client/ yourself."

if ! on_ac_power; then
  if [ "$ALLOW_BATTERY" -eq 1 ]; then
    note "WARNING: not on AC power (--allow-battery). A sleep during a reply can quarantine the dataset."
  else
    die 2 "the Mac is not on AC power. Connect it, or pass --allow-battery."
  fi
fi

DB=$DATA_DIR/$DATASET-dev.sqlite3
"$PY" -I -c '
import sys
from pathlib import Path
from anonymous.config import RuntimeConfigurationError, require_dev_dataset
try:
    require_dev_dataset(Path(sys.argv[1]))
except RuntimeConfigurationError as error:
    print(f"REFUSED: {error}.", file=sys.stderr)
    sys.exit(1)
' "$DB" || exit 2

state_line=$(dataset_state "$DB")
state=${state_line%% *}
case $state in
  absent) say "Dataset '$DATASET': new (the application creates it empty)." ;;
  open) say "Dataset '$DATASET': existing, open (${state_line#* })." ;;
  unsettled) note "WARNING: dataset '$DATASET' has a run that is still unsettled (${state_line#* }). The application reconciles it at start; that can block the dataset." ;;
  blocked)
    if [ "$ALLOW_BLOCKED" -eq 1 ]; then
      note "WARNING: dataset '$DATASET' is BLOCKED; history is readable but new messages are refused."
    else
      die 2 "dataset '$DATASET' is BLOCKED (an earlier run could not be shown to have ended). Its history stays readable and it is never modified. Keep it, and start a new dataset: tools/owner/start.sh --dataset <new-name>. (--allow-blocked opens it for reading.)"
    fi
    ;;
  busy) die 2 "dataset '$DATASET' is locked by another process." ;;
  *) die 2 "dataset '$DATASET' cannot be read; it was not opened." ;;
esac

for name in $APP_ENV_NAMES; do
  if [ -n "${!name:-}" ]; then
    note "Note: ignoring $name from the environment; the wrapper passes the supported settings explicitly."
  fi
done

[ "$(port_state "$APP_PORT")" = free ] ||
  die 3 "port $APP_PORT is occupied or could not be inspected (another Anonymous or another program?). Nothing was signalled."

# -- 2. the runtime: reuse a verified one, or launch the pinned one ------------------------------

[ ! -e "$INTENT" ] && [ ! -L "$INTENT" ] ||
  die 5 "an interrupted earlier launch left a recovery file. Follow the runbook, section 'Diagnosing'. Nothing was started."

REUSE=0
if [ -e "$RECORD" ] || [ -L "$RECORD" ]; then
  rc=0
  out=$(ctl status 2>&1) || rc=$?
  [ "$rc" -eq 0 ] || die 5 "the launch record is unreadable or unsafe ($(refusal_code "$out")). See the runbook, section 'Diagnosing'."
  matches=$(printf '%s' "$out" | jget process_identity_matches)
  sole=$(printf '%s' "$out" | jget sole_listener_is_recorded_process)
  if [ "$matches" = true ]; then
    [ "$sole" = true ] ||
      die 3 "a recorded runtime is alive but is not the sole listener on its port. Run tools/owner/stop.sh and investigate (runbook: 'Diagnosing')."
    record_ok=0
    "$PY" -I -c '
import sys
from pathlib import Path
from anonymous.adapters.model.llama_launch_record import LaunchRecordError, read_record
try:
    r = read_record(Path(sys.argv[1]))
except LaunchRecordError:
    sys.exit(1)
same = (
    r.model.sha256 == sys.argv[2] and r.model.verification == "verified" and r.model.label == sys.argv[3]
    and r.runtime.sha256 == sys.argv[4] and r.runtime.verification == "verified"
    and r.runtime.label == sys.argv[5]
)
sys.exit(0 if same else 1)
' "$RECORD" "$MODEL_SHA256" "$MODEL_LABEL" "$RUNTIME_SHA256" "$RUNTIME_LABEL" || record_ok=1
    [ "$record_ok" -eq 0 ] ||
      die 3 "the running runtime was not launched and hash-verified against the current pins. Stop it with tools/owner/stop.sh and start again."
    REUSE=1
    say "Runtime: reusing the already running, identity-verified runtime."
  else
    # The recorded process is gone (or its pid now belongs to something else). The launcher's stop
    # removes the stale files only when the process is confirmed absent; otherwise it refuses.
    rc=0
    out=$(ctl stop --remove-files 2>&1) || rc=$?
    [ "$rc" -eq 0 ] ||
      die 3 "a stale launch record could not be cleaned safely ($(refusal_code "$out")$(printf '%s' "$out" | jget result)). Nothing was signalled. See the runbook, section 'Diagnosing'."
    say "Removed the stale launch files of a runtime that is no longer running."
  fi
fi

if [ "$REUSE" -eq 0 ]; then
  [ "$(port_state "$LLAMA_PORT")" = free ] ||
    die 3 "port $LLAMA_PORT is occupied or could not be inspected. Nothing was started or signalled."
  (umask 077 && mkdir -p "$RUNTIME_DIR") || die 2 "the runtime directory could not be created."
  say "Launching the pinned runtime. Both artifacts are hashed against the pins first (this reads about 2.5 GB)..."
  rc=0
  out=$(ctl launch --runtime-bin "$RUNTIME_BIN" --model "$MODEL_PATH" --port "$LLAMA_PORT" \
    --model-label "$MODEL_LABEL" --runtime-label "$RUNTIME_LABEL" \
    --model-sha256 "$MODEL_SHA256" --runtime-sha256 "$RUNTIME_SHA256" --hash 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    code=$(refusal_code "$out")
    note "Launch refused: ${code:-unknown} (exit $rc)."
    case $code in
      artifact_digest_mismatch) note "The model file or the runtime binary does not match the pinned SHA-256. Nothing was started." ;;
      port_in_use | already_running) note "Nothing was started or signalled." ;;
      *survive* | unresolved_launch_intent | spawn_status_unknown)
        note "A runtime may be running without a record. Do not launch again. Details for the manual procedure (runbook, 'Diagnosing'):"
        note "$out"
        ;;
      *) note "The launcher removed everything it had created. See the runbook, section 'Diagnosing'." ;;
    esac
    exit "$rc"
  fi
  ROLLBACK=1
fi

# -- 3. verify identity and readiness ---------------------------------------------------------------

rc=0
out=$(ctl status 2>&1) || rc=$?
[ "$rc" -eq 0 ] || die 1 "the runtime's launch record could not be read back ($(refusal_code "$out"))."
[ "$(printf '%s' "$out" | jget process_identity_matches)" = true ] &&
  [ "$(printf '%s' "$out" | jget sole_listener_is_recorded_process)" = true ] &&
  [ "$(printf '%s' "$out" | jget model.digest_verification)" = verified ] &&
  [ "$(printf '%s' "$out" | jget runtime.digest_verification)" = verified ] ||
  die 1 "the runtime's identity could not be verified after launch."
say "Runtime: identity verified (process identity, sole listener on 127.0.0.1:$LLAMA_PORT, model and runtime digests verified against the pins)."

ready=0
i=0
# ANONYMOUS_OWNER_READY_SECONDS exists for the wrapper tests; the default is the real wait.
READY_SECONDS=${ANONYMOUS_OWNER_READY_SECONDS:-60}
case $READY_SECONDS in '' | *[!0-9]*) READY_SECONDS=60 ;; esac
while [ "$i" -lt "$READY_SECONDS" ]; do
  if [ "$(http_code "http://$LOOPBACK:$LLAMA_PORT/health")" = 200 ]; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 1
done
[ "$ready" -eq 1 ] || die 1 "the runtime did not report ready within $READY_SECONDS seconds."
say "Runtime: ready."

# -- 4. the application, in the foreground -----------------------------------------------------------

(umask 077 && mkdir -p "$DATA_DIR") || die 2 "the data directory could not be created."

UNSET_ARGS=''
for name in $APP_ENV_NAMES; do UNSET_ARGS="$UNSET_ARGS -u $name"; done
CAFFEINATE=''
[ -x /usr/bin/caffeinate ] && CAFFEINATE='/usr/bin/caffeinate -i'

say ""
say "Open http://$LOOPBACK:$APP_PORT/ in your browser. Dataset: $DATASET. Synthetic data only; no authentication."
say "When no reply is being generated, press Ctrl-C here to stop Anonymous (the runtime stays up; tools/owner/stop.sh ends it)."
say ""

trap ':' INT # Ctrl-C reaches the application; this wrapper then reports and exits
app_rc=0
# shellcheck disable=SC2086
env $UNSET_ARGS $CAFFEINATE "$PY" -I -m anonymous \
  --runtime llama-dev --llama-launch-record "$RECORD" --db-path "$DB" \
  --host "$LOOPBACK" --port "$APP_PORT" --client-dist "$REPO_ROOT/client/dist" || app_rc=$?
trap 'exit 130' INT

case $app_rc in
  0 | 130 | 143)
    ROLLBACK=0
    say ""
    say "Anonymous has stopped. The runtime is still running; run tools/owner/stop.sh to end it, or start.sh again to reuse it."
    exit 0
    ;;
  *)
    note "Anonymous exited with status $app_rc."
    exit 1 # the EXIT trap stops a runtime this invocation launched
    ;;
esac
