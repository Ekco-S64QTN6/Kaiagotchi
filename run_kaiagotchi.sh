#!/bin/bash
# Launch Kaiagotchi with the privileges it needs (CAP_NET_ADMIN) and debug logging.
set -euo pipefail

# Resolve the repository root from this script's location (portable, no hardcoded paths).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer the project virtualenv if present.
PYTHON_EXEC="python3"
if [ -x "venv/bin/python3" ]; then
    PYTHON_EXEC="$SCRIPT_DIR/venv/bin/python3"
fi

# Kaiagotchi needs elevated privileges to manage the wireless interface.
if [ "$EUID" -ne 0 ]; then
    echo "🔐 Re-launching as root..."
    exec sudo -E env "PATH=$PATH" "$PYTHON_EXEC" -m kaiagotchi.cli --debug "$@"
else
    exec "$PYTHON_EXEC" -m kaiagotchi.cli --debug "$@"
fi
