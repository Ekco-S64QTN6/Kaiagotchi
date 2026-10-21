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


@pytest.mark.asyncio
async def test_timed_out_command_is_killed_and_reaped():
    import asyncio

    class HangingProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self._killed = asyncio.Event()

        async def communicate(self):
            await self._killed.wait()
            self.returncode = -9
            return b"", b"killed"

        def kill(self):
            self.killed = True
            self._killed.set()

        async def wait(self):
            if self.returncode is None:
                await self._killed.wait()
                self.returncode = -9
            return self.returncode

    manager = InterfaceActionManager({"main": {"iface": "wlan1"}})
    proc = HangingProcess()
    with pytest.raises(TimeoutError):
        await manager._communicate_with_timeout(proc, timeout=0.01, command="fake-tool")

    assert proc.killed is True
    assert proc.returncode == -9


@pytest.mark.asyncio
async def test_run_checked_uses_bounded_subprocess_communication(monkeypatch):
    import asyncio

    class HangingProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self._killed = asyncio.Event()

        async def communicate(self):
            await self._killed.wait()
            self.returncode = -9
            return b"", b"killed"

        def kill(self):
            self.killed = True
            self._killed.set()

        async def wait(self):
            if self.returncode is None:
                await self._killed.wait()
                self.returncode = -9
            return self.returncode

    manager = InterfaceActionManager({"main": {"iface": "wlan1"}})
    proc = HangingProcess()
    original_helper = manager._communicate_with_timeout

    async def short_timeout(process, *, timeout, command):
        return await original_helper(process, timeout=0.01, command=command)

    async def fake_create(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(manager, "_communicate_with_timeout", short_timeout)
    monkeypatch.setattr(action_manager_module.asyncio, "create_subprocess_exec", fake_create)

    with pytest.raises(TimeoutError):
        await manager._run_checked("fake-tool")

    assert proc.killed is True
    assert proc.returncode == -9
