from __future__ import annotations

import pytest

import kaiagotchi.agent.monitoring_agent as monitoring_module
from kaiagotchi.agent.monitoring_agent import MonitoringAgent


class FakeProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_monitor_mode_setup_checks_commands_and_verifies_wlan1(monkeypatch):
    calls = []
    monkeypatch.setattr(
        monitoring_module.shutil,
        "which",
        lambda command: "/usr/bin/nmcli" if command == "nmcli" else None,
    )

    async def fake_create_subprocess_exec(*cmd, **_kwargs):
        calls.append(cmd)
        if cmd == ("iw", "dev", "wlan1", "info"):
            return FakeProcess(stdout=b"Interface wlan1\n\ttype monitor\n")
        return FakeProcess()

    monkeypatch.setattr(monitoring_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})

    await monitor._set_monitor_mode()

    assert ("iw", "dev", "wlan1", "set", "type", "monitor") in calls
    assert ("iw", "dev", "wlan1", "info") in calls
    assert all("wlan0" not in call for call in calls)
    assert ("nmcli", "device", "set", "wlan1", "managed", "no") in calls


@pytest.mark.asyncio
async def test_monitor_mode_setup_raises_when_iw_fails(monkeypatch):
    async def fake_create_subprocess_exec(*cmd, **_kwargs):
        if cmd == ("iw", "dev", "wlan1", "set", "type", "monitor"):
            return FakeProcess(returncode=1, stderr=b"driver refused monitor mode")
        return FakeProcess()

    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _command: None)
    monkeypatch.setattr(monitoring_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})

    with pytest.raises(RuntimeError, match="failed with exit code 1"):
        await monitor._set_monitor_mode()


@pytest.mark.asyncio
async def test_monitoring_aborts_startup_if_monitor_mode_setup_fails(monkeypatch):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    restored = False
    launched = False

    async def fail_setup():
        raise RuntimeError("simulated setup failure")

    async def restore_managed_mode():
        nonlocal restored
        restored = True

    async def launch_airodump():
        nonlocal launched
        launched = True

    monkeypatch.setattr(monitor, "_set_monitor_mode", fail_setup)
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_launch_airodump", launch_airodump)

    with pytest.raises(RuntimeError, match="Could not configure capture interface wlan1"):
        await monitor.start()

    assert monitor._running is False
    assert restored is True
    assert launched is False

@pytest.mark.asyncio
async def test_monitoring_restores_interface_when_airodump_launch_fails(monkeypatch):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    restored = False

    async def set_monitor_mode():
        return None

    async def restore_managed_mode():
        nonlocal restored
        restored = True

    async def fail_launch():
        raise RuntimeError("simulated airodump launch failure")

    monkeypatch.setattr(monitor, "_set_monitor_mode", set_monitor_mode)
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_launch_airodump", fail_launch)

    with pytest.raises(RuntimeError, match="simulated airodump launch failure"):
        await monitor.start()

    assert monitor._running is False
    assert restored is True
    assert monitor._loop_task is None

