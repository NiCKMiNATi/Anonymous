#!/bin/bash
# Stop the pinned runtime of the Anonymous v0.1 development prototype, in the safe order.
#
#   tools/owner/stop.sh
#
# Order: first the application, then the runtime. The application has no identity record, so this
# wrapper never signals it: you end it with Ctrl-C in its terminal, and only when no reply is being
# generated (tools/owner/status.sh shows an unsettled run). This script then refuses to touch the
# runtime while anything still listens on the application port, because it cannot establish that no
# reply is in flight. The runtime itself is ended only by the launcher's identity-verified stop:
# the kernel (pid, start time) identity is checked immediately before one SIGTERM, a mismatch
# signals nothing, nothing is escalated, and the launch files are removed only once the process is
# confirmed gone. Stopping the runtime settles nothing in Anonymous.

set -u -o pipefail
. "$(dirname "$0")/lib.sh"

[ $# -eq 0 ] || {
  echo "Usage: tools/owner/stop.sh" >&2
  exit 2
}

require_macos
setup_paths
load_config lenient
require_python

# -- 1. the application must already be stopped --------------------------------------------------

case $(port_state "$APP_PORT") in
  free) ;;
  busy)
    note "REFUSED: something is listening on the application port $APP_PORT ($(port_listener_desc "$APP_PORT" | tr '\n' ' '))."
    note "Not stopping the runtime: it cannot be shown that no reply is being generated, and stopping"
    note "the runtime under a reply would quarantine the dataset. Manual procedure:"
    note "  1. tools/owner/status.sh  - confirm no run is unsettled (no reply being generated)."
    note "  2. Press Ctrl-C in the terminal running start.sh."
    note "  3. Run tools/owner/stop.sh again."
    exit 3
    ;;
  *) die 3 "the application port $APP_PORT could not be inspected, so an idle application cannot be shown." ;;
esac

# -- 2. the runtime -------------------------------------------------------------------------------

if [ -e "$INTENT" ] || [ -L "$INTENT" ]; then
  note "REFUSED: an interrupted launch left a recovery file, so a runtime may exist without a record."
  note "Nothing was signalled. Follow the runbook, section 'Diagnosing'. Details from the launcher:"
  ctl status 2>&1 | head -n 20 >&2 || true
  exit 5
fi

if [ ! -e "$RECORD" ] && [ ! -L "$RECORD" ]; then
  say "No launch record: no runtime is recorded as running. Nothing to stop."
else
  rc=0
  out=$(ctl stop --remove-files 2>&1) || rc=$?
  result=$(printf '%s' "$out" | jget result)
  case $rc in
    0) say "Runtime stop: ${result:-ok} (signalled: $(printf '%s' "$out" | jget signalled)); launch files removed." ;;
    3)
      note "REFUSED: the recorded pid now belongs to a different process. Nothing was signalled and nothing was removed."
      note "See the runbook, section 'Diagnosing' (identity mismatch)."
      exit 3
      ;;
    4)
      note "The runtime was sent SIGTERM but is still running. It is not escalated. Wait, run this script again, and"
      note "if it persists follow the runbook, section 'Diagnosing'. The launch files were kept."
      exit 4
      ;;
    *)
      note "Stop did not complete (exit $rc: ${result}$(refusal_code "$out")). The launch files were kept. See the runbook, section 'Diagnosing'."
      exit "$rc"
      ;;
  esac
fi

# -- 3. confirm the shutdown ------------------------------------------------------------------------

clean=1
if [ "$(port_state "$LLAMA_PORT")" != free ]; then
  note "! port $LLAMA_PORT still has a listener (or could not be inspected): $(port_listener_desc "$LLAMA_PORT" | tr '\n' ' ')"
  clean=0
fi
if [ -e "$RECORD" ] || [ -L "$RECORD" ]; then
  note "! the launch record still exists."
  clean=0
fi
leftover=0
if [ -d "$RUNTIME_DIR" ]; then
  for file in "$RUNTIME_DIR"/key-*; do
    [ -e "$file" ] || continue
    leftover=$((leftover + 1))
  done
fi
if [ "$leftover" -ne 0 ]; then
  note "! $leftover key file(s) remain in the runtime directory (from an earlier interrupted launch?)."
  clean=0
fi
if [ "$clean" -eq 1 ]; then
  say "Clean shutdown confirmed: no listener on $LLAMA_PORT or $APP_PORT, no launch record, no key file."
  exit 0
fi
note "Shutdown is not confirmed clean. See the runbook, section 'Diagnosing'."
exit 1
