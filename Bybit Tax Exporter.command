#!/bin/zsh
# Run Bybit Tax Exporter on macOS by double-clicking this file
# This script activates the project's virtual environment if present,
# falls back to system python3 otherwise, and launches the app.

set -euo pipefail

# Resolve repository root (folder containing this .command file)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer local venv if available
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "Error: Python 3 not found. Please install Python 3 or create a virtual environment in .venv." >&2
  echo "Press return to close this window."; read -r
  exit 1
fi

# Launch the application
"$PY" "$SCRIPT_DIR/src/main.py" || {
  status=$?
  echo "\nThe app exited with status $status."
  echo "Press return to close this window."; read -r
  exit $status
}

exit 0
