from __future__ import annotations

import pytest

import kaiagotchi.network.action_manager as action_manager_module
from kaiagotchi.network.action_manager import InterfaceActionManager


class FakeProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_mode_changes_stay_pinned_to_capture_adapter(monkeypatch):
    calls = []
    manager = InterfaceActionManager({"main": {"iface": "wlan0"}})
    manager.set_monitor_interface("wlan1")

    async def exists(_interface):
        return True

    async def get_info(interface):
        assert interface == "wlan1"
        return {"mode": "monitor"}

    async def fake_create_subprocess_exec(*command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(manager, "_interface_exists", exists)
    monkeypatch.setattr(manager, "get_interface_info", get_info)
    monkeypatch.setattr(action_manager_module.shutil, "which", lambda name: "/usr/bin/nmcli" if name == "nmcli" else None)
    monkeypatch.setattr(action_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await manager.set_monitor_mode("wlan0") is True
    assert ("iw", "dev", "wlan1", "set", "type", "monitor") in calls
    assert ("nmcli", "device", "set", "wlan1", "managed", "no") in calls
    assert all("wlan0" not in command for command in calls)


@pytest.mark.asyncio
async def test_managed_mode_uses_valid_iw_syntax_and_capture_adapter(monkeypatch):
    calls = []
    manager = InterfaceActionManager({"main": {"iface": "wlan0"}})
    manager.set_monitor_interface("wlan1")

    async def exists(_interface):
        return True

    async def get_info(interface):
        assert interface == "wlan1"
        return {"mode": "managed"}

    async def fake_create_subprocess_exec(*command, **_kwargs):
        calls.append(command)
        return FakeProcess()

    monkeypatch.setattr(manager, "_interface_exists", exists)
    monkeypatch.setattr(manager, "get_interface_info", get_info)
    monkeypatch.setattr(action_manager_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(action_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await manager.set_managed_mode("wlan0") is True
    assert ("iw", "dev", "wlan1", "set", "type", "managed") in calls
    assert all("wlan0" not in command for command in calls)
    assert manager._monitor_interface is None


@pytest.mark.asyncio
async def test_mode_change_fails_when_command_returns_nonzero(monkeypatch):
    manager = InterfaceActionManager({"main": {"iface": "wlan0"}})
    manager.set_monitor_interface("wlan1")

    async def exists(_interface):
        return True

    async def fake_create_subprocess_exec(*command, **_kwargs):
        if command == ("iw", "dev", "wlan1", "set", "type", "monitor"):
            return FakeProcess(returncode=1, stderr=b"driver refused monitor mode")
        return FakeProcess()

    monkeypatch.setattr(manager, "_interface_exists", exists)
    monkeypatch.setattr(action_manager_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(action_manager_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    assert await manager.set_monitor_mode("wlan0") is False
    assert manager._monitor_interface == "wlan1"
