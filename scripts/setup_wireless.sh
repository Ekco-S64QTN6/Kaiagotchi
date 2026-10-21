#!/usr/bin/env bash
# Configure only the dedicated Kaiagotchi capture dongle.
set -euo pipefail

INTERFACE="wlan1"
SUDO=()
CHANGED=0

if [[ "$EUID" -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Error: run as root or install sudo." >&2
        exit 1
    fi
    SUDO=(sudo)
fi

for required in ip iw timeout airodump-ng; do
    if ! command -v "$required" >/dev/null 2>&1; then
        echo "Error: required command '$required' was not found." >&2
        exit 1
    fi
done

if ! "${SUDO[@]}" ip link show dev "$INTERFACE" >/dev/null 2>&1; then
    echo "Error: capture interface '$INTERFACE' not found." >&2
    echo "Available interfaces:" >&2
    "${SUDO[@]}" ip -brief link >&2 || true
    exit 1
fi

restore_on_failure() {
    local status="$1"
    if [[ "$CHANGED" -eq 1 ]]; then
        echo "Setup failed; attempting to restore $INTERFACE to managed mode." >&2
        "${SUDO[@]}" ip link set dev "$INTERFACE" down >/dev/null 2>&1 || true
        "${SUDO[@]}" iw dev "$INTERFACE" set type managed >/dev/null 2>&1 || true
        "${SUDO[@]}" ip link set dev "$INTERFACE" up >/dev/null 2>&1 || true
        if command -v nmcli >/dev/null 2>&1; then
            "${SUDO[@]}" nmcli device set "$INTERFACE" managed yes >/dev/null 2>&1 || true
        fi
    fi
    exit "$status"
}

run_required() {
    if "$@"; then
        return 0
    else
        local status="$?"
        echo "Error: command failed: $*" >&2
        restore_on_failure "$status"
    fi
}

echo "Setting up Kaiagotchi capture interface: $INTERFACE"
echo "The primary internet interface (normally wlan0) will not be changed."

# NetworkManager is optional, but if present it must successfully release the
# capture dongle before the interface mode is changed.
CHANGED=1
if command -v nmcli >/dev/null 2>&1; then
    run_required "${SUDO[@]}" nmcli device set "$INTERFACE" managed no
else
    echo "Warning: nmcli not found; skipping NetworkManager unmanaged setting." >&2
fi

run_required "${SUDO[@]}" ip link set dev "$INTERFACE" down
run_required "${SUDO[@]}" iw dev "$INTERFACE" set type monitor
run_required "${SUDO[@]}" ip link set dev "$INTERFACE" up

if ! interface_info=$("${SUDO[@]}" iw dev "$INTERFACE" info); then
    echo "Error: could not read wireless interface state after setup." >&2
    restore_on_failure 1
fi
if ! grep -Eq '^[[:space:]]*type[[:space:]]+monitor([[:space:]]|$)' <<<"$interface_info"; then
    echo "Error: $INTERFACE did not enter monitor mode; actual state:" >&2
    printf '%s\n' "$interface_info" >&2
    restore_on_failure 1
fi

echo "Monitor mode confirmed on $INTERFACE."
echo "Testing airodump-ng for up to 3 seconds..."
# Exit status 124 means the short airodump probe was stopped by timeout.
# Other failures trigger rollback rather than a false success message.
if timeout 3s "${SUDO[@]}" airodump-ng "$INTERFACE" >/dev/null 2>&1; then
    echo "airodump-ng exited before the probe timeout."
else
    status="$?"
    if [[ "$status" -ne 124 ]]; then
        echo "Error: airodump-ng probe failed (exit $status)." >&2
        restore_on_failure "$status"
    fi
fi

CHANGED=0
echo "Setup complete. $INTERFACE is in monitor mode and ready for Kaiagotchi."
