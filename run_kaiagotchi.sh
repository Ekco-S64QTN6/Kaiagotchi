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

# Select exactly one interface. A graphical desktop gets the standalone HUD;
# --no-window/--tui selects curses; --headless disables both interfaces.
MODE="desktop"
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --no-window) MODE="tui" ;;
        --headless) MODE="headless" ;;
        --tui|--no-web) MODE="tui"; ARGS+=("$arg") ;;
        --no-tui) MODE="web"; ARGS+=("$arg") ;;
        *) ARGS+=("$arg") ;;
    esac
done
if [ "${EUID:-$(id -u)}" -ne 0 ] && [ "$MODE" = "desktop" ] \
        && { [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; }; then
    exec "$SCRIPT_DIR/kaiagotchi-hud" "${ARGS[@]+"${ARGS[@]}"}"
fi

# Without a GUI, prefer curses on an interactive terminal; otherwise headless.
if [ "$MODE" = "desktop" ]; then
    if [ -t 1 ]; then MODE="tui"; else MODE="headless"; fi
fi
if [ "$MODE" = "tui" ] && [[ ! " ${ARGS[*]} " =~ " --tui " ]]; then
    ARGS+=(--tui)
elif [ "$MODE" = "headless" ]; then
    ARGS+=(--no-web --no-tui)
fi
set -- "${ARGS[@]+"${ARGS[@]}"}"
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
