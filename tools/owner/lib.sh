# shellcheck shell=bash
# Shared helpers for the Anonymous owner wrappers (start.sh, status.sh, stop.sh). Sourced only.
#
# v0.1 DEVELOPMENT PROTOTYPE, macOS only: loopback only, no authentication, synthetic data only.
# The wrappers add no supervisor. The runtime lifecycle is the existing identity-verified launcher
# (llama_ctl); the application stays a foreground process. Nothing here prints message content,
# keys or launch-record contents, and nothing signals a process except llama_ctl's stop, which
# verifies the kernel (pid, start time) identity first. Written for the system bash 3.2.
#
# Exit codes used by the wrappers: 0 ok; 1 failure; 2 prerequisite or usage refusal;
# 3 refused because of an occupied port or a process-identity mismatch; 5 unresolved state that
# needs the manual procedure in the runbook.

if [ -z "${BASH_VERSION:-}" ]; then
  echo "REFUSED: run these wrappers with bash." >&2
  return 2 2>/dev/null || exit 2
fi

OWNER_TOOLS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$OWNER_TOOLS_DIR/../.." && pwd -P)

DEFAULT_LLAMA_PORT=18080
DEFAULT_APP_PORT=8000
LOOPBACK=127.0.0.1
# Application settings the wrappers pin on the command line; a stray value in the environment
# must not change them silently.
APP_ENV_NAMES="ANONYMOUS_DB_PATH ANONYMOUS_HOST ANONYMOUS_PORT ANONYMOUS_CLIENT_DIST
ANONYMOUS_FAKE_DELAY_SECONDS ANONYMOUS_RUNTIME ANONYMOUS_LLAMA_LAUNCH_RECORD
ANONYMOUS_LLAMA_MAX_TOKENS ANONYMOUS_LLAMA_MAX_INPUT_CHARS"

say() { printf '%s\n' "$*"; }
note() { printf '%s\n' "$*" >&2; }
die() {
  local code=$1
  shift
  printf 'REFUSED: %s\n' "$*" >&2
  exit "$code"
}

require_macos() {
  [ "$(uname -s)" = Darwin ] || die 2 "macOS only (the identity checks use libproc and lsof)."
}

# -- paths and configuration ---------------------------------------------------------------------

setup_paths() {
  [ -n "${HOME:-}" ] || die 2 "HOME is not set."
  OWNER_HOME=${ANONYMOUS_OWNER_HOME:-"$HOME/Library/Application Support/AnonymousDev"}
  case $OWNER_HOME in
    /*) ;;
    *) die 2 "ANONYMOUS_OWNER_HOME must be an absolute path." ;;
  esac
  case $OWNER_HOME in
    *..* | *$'\n'*) die 2 "ANONYMOUS_OWNER_HOME must not contain '..' or a newline." ;;
  esac
  CONFIG_FILE=${ANONYMOUS_OWNER_CONFIG:-"$OWNER_HOME/owner.env"}
  PINS_FILE=${ANONYMOUS_OWNER_PINS_FILE:-"$OWNER_TOOLS_DIR/pins.env"}
  RUNTIME_DIR=$OWNER_HOME/runtime
  DATA_DIR=$OWNER_HOME/data
  RECORD=$RUNTIME_DIR/launch.json
  INTENT=$RECORD.intent
  PY=${ANONYMOUS_OWNER_PYTHON:-"$REPO_ROOT/server/.venv/bin/python"}
  PMSET=${ANONYMOUS_OWNER_PMSET:-/usr/bin/pmset}
  LSOF=/usr/sbin/lsof
  CURL=/usr/bin/curl
}

# Reads KEY=VALUE lines into CFG_<KEY>. Only the listed keys are accepted; the file is never
# sourced or evaluated. One pair of surrounding double quotes is removed.
load_kv_file() {
  local file=$1 allowed=$2 line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case $line in '' | '#'*) continue ;; esac
    case $line in *=*) ;; *) die 2 "unparseable line in a configuration file (expected KEY=VALUE)." ;; esac
    key=${line%%=*}
    value=${line#*=}
    case $value in
      \"*\")
        value=${value#\"}
        value=${value%\"}
        ;;
    esac
    case " $allowed " in
      *" $key "*) ;;
      *) die 2 "unknown key '$key' in a configuration file." ;;
    esac
    printf -v "CFG_$key" '%s' "$value"
  done <"$file"
}

valid_port() {
  case $1 in '' | *[!0-9]*) return 1 ;; esac
  [ "$1" -ge 1024 ] && [ "$1" -le 65535 ]
}

# is_owner_only PATH: succeeds only if PATH exists and has no group or other permission bits (read
# from the entry itself, so a symlink is judged by its own mode and fails). Reads metadata only.
is_owner_only() {
  local mode
  mode=$(/usr/bin/stat -f %Lp "$1" 2>/dev/null) || return 1
  case $mode in '' | *[!0-7]*) return 1 ;; esac
  [ $((8#$mode & 8#077)) -eq 0 ]
}

is_abs_path() {
  case $1 in
    /*) ;;
    *) return 1 ;;
  esac
  case $1 in *..* | *$'\n'*) return 1 ;; esac
}

# load_config strict|lenient. Strict (start) needs the owner file with both artifact paths;
# lenient (status, stop) tolerates a missing file and only needs the ports.
load_config() {
  local mode=$1
  CFG_RUNTIME_BIN='' CFG_MODEL_PATH='' CFG_LLAMA_PORT='' CFG_APP_PORT=''
  if [ -f "$CONFIG_FILE" ]; then
    load_kv_file "$CONFIG_FILE" "RUNTIME_BIN MODEL_PATH LLAMA_PORT APP_PORT"
  elif [ "$mode" = strict ]; then
    die 2 "owner configuration not found at '$CONFIG_FILE'. Copy tools/owner/owner.env.example there and edit it (see the runbook)."
  fi
  LLAMA_PORT=${CFG_LLAMA_PORT:-$DEFAULT_LLAMA_PORT}
  APP_PORT=${CFG_APP_PORT:-$DEFAULT_APP_PORT}
  valid_port "$LLAMA_PORT" || die 2 "LLAMA_PORT must be a number from 1024 to 65535."
  valid_port "$APP_PORT" || die 2 "APP_PORT must be a number from 1024 to 65535."
  [ "$LLAMA_PORT" != "$APP_PORT" ] || die 2 "LLAMA_PORT and APP_PORT must differ."
  if [ "$mode" = strict ]; then
    is_abs_path "${CFG_RUNTIME_BIN:-}" || die 2 "RUNTIME_BIN must be an absolute path in the owner configuration."
    is_abs_path "${CFG_MODEL_PATH:-}" || die 2 "MODEL_PATH must be an absolute path in the owner configuration."
    RUNTIME_BIN=$CFG_RUNTIME_BIN
    MODEL_PATH=$CFG_MODEL_PATH
  fi
}

load_pins() {
  [ -f "$PINS_FILE" ] || die 2 "the pins file is missing (tools/owner/pins.env)."
  CFG_RUNTIME_LABEL='' CFG_RUNTIME_SHA256='' CFG_MODEL_LABEL='' CFG_MODEL_SHA256=''
  load_kv_file "$PINS_FILE" "RUNTIME_LABEL RUNTIME_SHA256 MODEL_LABEL MODEL_SHA256"
  RUNTIME_LABEL=$CFG_RUNTIME_LABEL
  RUNTIME_SHA256=$CFG_RUNTIME_SHA256
  MODEL_LABEL=$CFG_MODEL_LABEL
  MODEL_SHA256=$CFG_MODEL_SHA256
  local value
  for value in "$RUNTIME_SHA256" "$MODEL_SHA256"; do
    case $value in
      *[!0-9a-f]*) die 2 "a pin in the pins file is not a lowercase 64-character SHA-256." ;;
    esac
    [ "${#value}" -eq 64 ] || die 2 "a pin in the pins file is not a lowercase 64-character SHA-256."
  done
  for value in "$RUNTIME_LABEL" "$MODEL_LABEL"; do
    case $value in
      '' | *[!A-Za-z0-9._-]*) die 2 "a label in the pins file is empty or has unsupported characters." ;;
    esac
  done
}

require_python() {
  [ -x "$PY" ] || die 2 "the server virtual environment is missing. Run 'uv sync' in server/ yourself (the wrappers never install anything)."
  "$PY" -I -c 'import anonymous.adapters.model.llama_ctl' >/dev/null 2>&1 ||
    die 2 "the server environment cannot import the launcher. Run 'uv sync' in server/ yourself."
}

# -- launcher, ports, health ---------------------------------------------------------------------

# The existing identity-verified launcher. -I keeps the current directory and user site off the
# import path.
ctl() { "$PY" -I -m anonymous.adapters.model.llama_ctl --record "$RECORD" "$@"; }

# jget DOTTED.KEY: reads JSON on stdin, prints the value (booleans as true/false) or nothing.
jget() {
  "$PY" -I -c '
import json, sys
try:
    value = json.loads(sys.stdin.read())
    for part in sys.argv[1].split("."):
        value = value[part]
except (ValueError, KeyError, TypeError):
    sys.exit(0)
print(str(value).lower() if isinstance(value, bool) else value)
' "$1"
}

# port_state PORT -> free | busy | unknown (unknown: the inventory itself failed).
port_state() {
  local rc=0
  [ -x "$LSOF" ] || {
    echo unknown
    return 0
  }
  "$LSOF" -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1 || rc=$?
  case $rc in
    0) echo busy ;;
    1) echo free ;;
    *) echo unknown ;;
  esac
}

# "pid N (command)" for each listener on PORT; names no arguments, paths or content.
port_listener_desc() {
  "$LSOF" -nP -iTCP:"$1" -sTCP:LISTEN -Fpc 2>/dev/null |
    awk '/^p/ { p = substr($0, 2) } /^c/ { print "pid " p " (" substr($0, 2) ")" }'
}

# http_code URL -> the HTTP status code of a GET, or 000. Loopback only; proxies are bypassed.
http_code() {
  local code
  code=$("$CURL" --noproxy '*' -sS -o /dev/null --max-time 3 -w '%{http_code}' "$1" 2>/dev/null) || true
  printf '%s' "${code:-000}"
}

on_ac_power() {
  "$PMSET" -g batt 2>/dev/null | head -n 1 | grep -q "AC Power"
}

# dataset_state PATH -> "STATE key=value ...", read-only (see dataset_state.py).
dataset_state() { "$PY" -I "$OWNER_TOOLS_DIR/dataset_state.py" "$1"; }

# Reports a launcher refusal from captured output without ever echoing anything but fixed codes.
refusal_code() { printf '%s' "$1" | jget refused; }
