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
