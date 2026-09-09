#!/usr/bin/env bash
# Unified entry point for launching Godot against this project.
#
#   ./godot.sh                      Open the project in the Godot editor
#   ./godot.sh --headless --path .  Any other invocation; arguments pass through
#
# The engine binary is resolved by tools/godot_runtime.py, so this script and the
# Python experiment runners always agree on which executable is used.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "godot.sh: '$PYTHON_BIN' not found on PATH. Set PYTHON_BIN to a Python 3 interpreter." >&2
  exit 1
fi

if ! GODOT_EXE="$("$PYTHON_BIN" "$REPO_ROOT/tools/godot_runtime.py" --godot-exe "${GODOT_EXE:-auto}" --print-exe)"; then
  echo "godot.sh: could not resolve a Godot executable (see the error above)." >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  exec "$GODOT_EXE" --editor --path "$REPO_ROOT"
fi

exec "$GODOT_EXE" "$@"
