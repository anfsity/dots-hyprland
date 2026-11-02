#!/usr/bin/env bash
# Manual scrolling screenshot. Ctrl+C finishes a standalone session.
# Quickshell controls the session with finish/cancel commands on stdin.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
VENV_PATH="${ILLOGICAL_IMPULSE_VIRTUAL_ENV:-$STATE_HOME/quickshell/.venv}"
if [[ -x "$VENV_PATH/bin/python" ]]; then
    exec "$VENV_PATH/bin/python" -u "$SCRIPT_DIR/longshot_capture.py" "$@"
else
    exec python3 -u "$SCRIPT_DIR/longshot_capture.py" "$@"
fi
