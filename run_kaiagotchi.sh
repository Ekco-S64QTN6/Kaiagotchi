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

    # Do not preserve the caller's PATH or arbitrary Python environment into
    # a privileged process. The app resolves system tools (ip, iw, nmcli,
    # airodump-ng) by name, so keeping a user-writable PATH could shadow them.
    # Preserve only the explicit app selectors that are intended to cross sudo.
    APP_ENV=()
    if [ -n "${KAIAGOTCHI_INTERFACE:-}" ]; then
        APP_ENV+=("KAIAGOTCHI_INTERFACE=$KAIAGOTCHI_INTERFACE")
    fi
    if [ -n "${KAIA_CONFIG:-}" ]; then
        APP_ENV+=("KAIA_CONFIG=$KAIA_CONFIG")
    fi

    exec sudo env "${APP_ENV[@]}" "$PYTHON_EXEC" -m kaiagotchi.cli --debug "$@"
else
    exec "$PYTHON_EXEC" -m kaiagotchi.cli --debug "$@"
fi
