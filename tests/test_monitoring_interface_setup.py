from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
async def test_start_refuses_new_capture_while_managed_mode_restore_is_pending():
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    monitor._managed_mode_restore_pending = True

    with pytest.raises(RuntimeError, match="call stop\\(\\) to retry"):
        await monitor.start()

    assert monitor._running is False
    assert monitor._loop_task is None


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



def test_persistent_scan_counters_apply_only_new_deltas():
    class FakePersistence:
        def __init__(self):
            self.bssids = {}
            self.stations = {}

        def update_bssid(self, *, bssid, essid, packets, beacons, channel, encryption):
            record = self.bssids.setdefault(bssid, {"packets": 0, "beacons": 0})
            record["packets"] += packets
            record["beacons"] += beacons

        def update_station(self, *, sta_mac, associated_bssid, packets, essids):
            record = self.stations.setdefault(sta_mac, {"packets": 0})
            record["packets"] += packets

    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    store = FakePersistence()
    monitor.persistent_network = store

    first_aps = [{
        "bssid": "00:11:22:33:44:55",
        "essid": "Test-AP",
        "iv": "50",
        "beacons": "100",
        "channel": "6",
        "privacy": "WPA2",
    }]
    first_stations = [{
        "station_mac": "AA:BB:CC:DD:EE:FF",
        "packets": "10",
        "bssid": "00:11:22:33:44:55",
        "probed_essids": "",
    }]
    second_aps = [{**first_aps[0], "iv": "67", "beacons": "125"}]
    second_stations = [{**first_stations[0], "packets": "13"}]

    monitor._persist_scan_counters(first_aps, first_stations)
    monitor._persist_scan_counters(second_aps, second_stations)

    assert store.bssids["00:11:22:33:44:55"] == {"packets": 67, "beacons": 125}
    assert store.stations["AA:BB:CC:DD:EE:FF"]["packets"] == 13


def test_persistent_scan_counter_handles_capture_counter_reset():
    class FakePersistence:
        def __init__(self):
            self.bssids = []

        def update_bssid(self, **record):
            self.bssids.append(record)

        def update_station(self, **_record):
            pass

    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    store = FakePersistence()
    monitor.persistent_network = store
    ap = {"bssid": "00:11:22:33:44:55", "iv": "90", "beacons": "200"}
    monitor._persist_scan_counters([ap], [])
    monitor._persist_scan_counters([{**ap, "iv": "4", "beacons": "7"}], [])

    assert store.bssids[0]["packets"] == 90
    assert store.bssids[0]["beacons"] == 200
    assert store.bssids[1]["packets"] == 4
    assert store.bssids[1]["beacons"] == 7



@pytest.mark.asyncio
async def test_cancelled_monitor_mode_setup_restores_managed_interface(monkeypatch):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    setup_started = asyncio.Event()
    restored = False
    launched = False

    async def blocked_setup():
        setup_started.set()
        await asyncio.Event().wait()

    async def restore_managed_mode():
        nonlocal restored
        restored = True

    async def launch_airodump():
        nonlocal launched
        launched = True

    monkeypatch.setattr(monitor, "_set_monitor_mode", blocked_setup)
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_launch_airodump", launch_airodump)

    start_task = asyncio.create_task(monitor.start())
    await setup_started.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert monitor._running is False
    assert restored is True
    assert launched is False


@pytest.mark.asyncio
async def test_cancelled_airodump_spawn_reaps_child_and_cleans_private_directory(
    tmp_path, monkeypatch
):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    monkeypatch.setattr(
        monitoring_module.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        monitoring_module.shutil,
        "which",
        lambda command: "/usr/bin/airodump-ng" if command == "airodump-ng" else None,
    )
    monkeypatch.setattr(monitoring_module, "PCAP_STORAGE_DIR", tmp_path / "archive")

    spawn_started = asyncio.Event()
    allow_spawn = asyncio.Event()
    restored = False

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            self.waited = True
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = FakeProcess()

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        spawn_started.set()
        await allow_spawn.wait()
        return process

    async def set_monitor_mode():
        return None

    async def restore_managed_mode():
        nonlocal restored
        restored = True

    monkeypatch.setattr(
        monitoring_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(monitor, "_set_monitor_mode", set_monitor_mode)
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", lambda: None)

    start_task = asyncio.create_task(monitor.start())
    await spawn_started.wait()
    start_task.cancel()
    allow_spawn.set()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert process.terminated is True
    assert process.waited is True
    assert monitor._process is None
    assert monitor._capture_tmp_dir is None
    assert not list(tmp_path.glob(f"kaiagotchi_{os.getpid()}_*"))
    assert monitor._running is False
    assert restored is True



@pytest.mark.asyncio
async def test_cancelled_during_startup_summary_stops_running_capture(monkeypatch):
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})
    summary_started = asyncio.Event()
    restored = False
    stop_summaries = []

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            self.waited = True
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = -9

    process = FakeProcess()

    async def set_monitor_mode():
        return None

    async def launch_airodump():
        monitor._process = process

    async def scan_loop():
        await asyncio.Event().wait()

    async def restore_managed_mode():
        nonlocal restored
        restored = True

    async def emit_summary(message):
        if message == "Monitoring initialized.":
            summary_started.set()
            await asyncio.Event().wait()
        else:
            stop_summaries.append(message)

    monkeypatch.setattr(monitor, "_set_monitor_mode", set_monitor_mode)
    monkeypatch.setattr(monitor, "_launch_airodump", launch_airodump)
    monkeypatch.setattr(monitor, "_scan_loop", scan_loop)
    monkeypatch.setattr(monitor, "_restore_managed_mode", restore_managed_mode)
    monkeypatch.setattr(monitor, "_archive_pcap_sync", lambda: None)
    monkeypatch.setattr(monitor, "_cleanup_capture_temp_dir", lambda: None)
    monkeypatch.setattr(monitor, "_emit_capture_summary", emit_summary)

    start_task = asyncio.create_task(monitor.start())
    await summary_started.wait()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    assert process.terminated is True
    assert process.waited is True
    assert monitor._process is None
    assert monitor._running is False
    assert monitor._loop_task is None
    assert restored is True
    assert stop_summaries == ["Monitoring stopped."]



@pytest.mark.asyncio
async def test_update_state_keeps_unknown_channel_unset():
    state = {}
    view = SimpleNamespace(
        state={"channel": None},
        async_update=AsyncMock(),
        display=None,
    )
    monitor = MonitoringAgent(
        interface="wlan1",
        view=view,
        config={},
        system_state=state,
    )

    await monitor._update_state([], [])

    assert "network" not in state
    view.async_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_monitor_mode_refuses_the_default_route_interface(monkeypatch):
    """A re-enumerated onboard NIC landing on the capture name must not be put
    into monitor mode and drop the machine's internet (9 Nov: wlan1)."""
    async def fake_create_subprocess_exec(*cmd, **_kwargs):
        if cmd[:4] == ("ip", "-o", "route", "show"):
            return FakeProcess(stdout=b"default via 192.168.1.254 dev wlan1 proto dhcp metric 600\n")
        return FakeProcess()

    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _c: None)
    monkeypatch.setattr(monitoring_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monitor = MonitoringAgent(interface="wlan1", config={}, system_state={})

    with pytest.raises(RuntimeError, match="refusing monitor mode"):
        await monitor._set_monitor_mode()


@pytest.mark.asyncio
async def test_default_route_on_another_interface_does_not_block_the_dongle(monkeypatch):
    calls = []

    async def fake_create_subprocess_exec(*cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:4] == ("ip", "-o", "route", "show"):
            return FakeProcess(stdout=b"default via 192.168.1.254 dev wlan1 proto dhcp metric 600\n")
        if cmd == ("iw", "dev", "wlan3", "info"):
            return FakeProcess(stdout=b"Interface wlan3\n\ttype monitor\n")
        return FakeProcess()

    monkeypatch.setattr(monitoring_module.shutil, "which", lambda _c: None)
    monkeypatch.setattr(monitoring_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monitor = MonitoringAgent(interface="wlan3", config={}, system_state={})

    await monitor._set_monitor_mode()

    assert ("iw", "dev", "wlan3", "set", "type", "monitor") in calls
    assert all("wlan1" not in call for call in calls if call[:4] != ("ip", "-o", "route", "show"))

def test_capture_interface_uses_main_capture_iface_and_ignores_main_iface():
    monitor = MonitoringAgent(
        config={"main": {"iface": "wlan0", "capture_iface": "wlan3"}},
        system_state={},
    )
    assert monitor.interface == "wlan3"


def test_capture_interface_environment_overrides_config(monkeypatch):
    monkeypatch.setenv("KAIAGOTCHI_INTERFACE", "wlan2")
    monitor = MonitoringAgent(
        config={"main": {"iface": "wlan0", "capture_iface": "wlan3"}},
        system_state={},
    )
    assert monitor.interface == "wlan2"


def test_explicit_capture_interface_argument_has_highest_precedence(monkeypatch):
    monkeypatch.setenv("KAIAGOTCHI_INTERFACE", "wlan2")
    monitor = MonitoringAgent(
        interface="wlan4",
        config={"main": {"iface": "wlan0", "capture_iface": "wlan3"}},
        system_state={},
    )
    assert monitor.interface == "wlan4"


def test_capture_interface_defaults_when_capture_iface_is_missing():
    monitor = MonitoringAgent(config={"main": {"iface": "wlan0"}}, system_state={})
    assert monitor.interface == "wlan1"


def test_legacy_flat_capture_interface_remains_supported():
    monitor = MonitoringAgent(config={"interface": "wlan2"}, system_state={})
    assert monitor.interface == "wlan2"
