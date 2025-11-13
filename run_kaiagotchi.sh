#!/bin/bash
# Launch Kaiagotchi with full root permissions and debug logging

set -e
cd /home/ekco/github/Kaiagotchi || exit 1

# Activate venv if not already
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Always run as root because Kaiagotchi needs CAP_NET_ADMIN
if [ "$EUID" -ne 0 ]; then
    echo "🔐 Re-launching as root..."
    exec sudo -E env "PATH=$PATH" python3 -m kaiagotchi.cli --debug "$@"
else
    python3 -m kaiagotchi.cli --debug "$@"
fi
