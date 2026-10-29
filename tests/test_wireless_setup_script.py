from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_wireless.sh"


def _fake_tools(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "commands.log"

    tools = {
        "ip": r'''#!/bin/sh
printf 'ip %s\n' "$*" >> "$COMMAND_LOG"
exit 0
''',
        "nmcli": r'''#!/bin/sh
printf 'nmcli %s\n' "$*" >> "$COMMAND_LOG"
exit 0
''',
        "iw": r'''#!/bin/sh
printf 'iw %s\n' "$*" >> "$COMMAND_LOG"
if [ "$*" = "dev wlan1 info" ]; then
    printf 'Interface wlan1\n'
    printf '    type %s\n' "${FAKE_IW_MODE:-monitor}"
fi
exit 0
''',
        "airodump-ng": r'''#!/bin/sh
printf 'airodump-ng %s\n' "$*" >> "$COMMAND_LOG"
exit 0
''',
        "timeout": r'''#!/bin/sh
# Simulate timeout(1): the test airodump command succeeds, then timeout fires.
shift
"$@"
status=$?
if [ "$status" -eq 0 ]; then
    exit 124
fi
exit "$status"
''',
        "sudo": r'''#!/bin/sh
exec "$@"
''',
    }
    for name, body in tools.items():
        executable = bindir / name
        executable.write_text(body, encoding="utf-8")
        executable.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["COMMAND_LOG"] = str(log)
    return log, env


def test_setup_wireless_script_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_setup_wireless_only_configures_wlan1_and_confirms_monitor_mode(tmp_path):
    log, env = _fake_tools(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Monitor mode confirmed on wlan1." in result.stdout
    assert "Setup complete." in result.stdout
    commands = log.read_text(encoding="utf-8")
    assert "ip link show dev wlan1" in commands
    assert "iw dev wlan1 set type monitor" in commands
    assert "airodump-ng wlan1" in commands
    assert "wlan0" not in commands


def test_setup_wireless_fails_and_rolls_back_when_monitor_mode_is_not_confirmed(tmp_path):
    log, env = _fake_tools(tmp_path)
    env["FAKE_IW_MODE"] = "managed"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "did not enter monitor mode" in result.stderr
    assert "Setup complete." not in result.stdout
    commands = log.read_text(encoding="utf-8")
    assert "iw dev wlan1 set type managed" in commands
    assert "ip link set dev wlan1 up" in commands
    assert "wlan0" not in commands
