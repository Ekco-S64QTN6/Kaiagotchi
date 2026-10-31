import asyncio

import pytest

import kaiagotchi.core.system as system_module
from kaiagotchi.core.system import SystemTicker


def stub_system_metrics(monkeypatch):
    monkeypatch.setattr(system_module, "uptime", lambda: 120.5)
    monkeypatch.setattr(system_module, "cpu_load", lambda: 0.75)
    monkeypatch.setattr(
        system_module,
        "mem_usage",
        lambda: {"MemTotal": "100 kB", "MemAvailable": "25 kB"},
    )
    monkeypatch.setattr(system_module, "temperature", lambda: 51.0)
    monkeypatch.setattr(system_module.time, "time", lambda: 1700.0)


def expected_snapshot():
    return {
        "uptime_seconds": 120.5,
        "cpu_load": 0.75,
        "meminfo": {"MemTotal": "100 kB", "MemAvailable": "25 kB"},
        "temperature": 51.0,
        "timestamp": 1700.0,
    }


@pytest.mark.asyncio
async def test_system_ticker_calls_synchronous_on_tick_callback(monkeypatch):
    stub_system_metrics(monkeypatch)
    snapshots = []

    def on_tick(snapshot):
        snapshots.append(snapshot)

    ticker = SystemTicker(on_tick=on_tick)

    await ticker._tick()

    assert snapshots == [expected_snapshot()]
    assert ticker._tick_count == 1
    assert ticker._last_update == 1700.0


@pytest.mark.asyncio
async def test_system_ticker_awaits_asynchronous_on_tick_callback(monkeypatch):
    stub_system_metrics(monkeypatch)
    snapshots = []

    async def on_tick(snapshot):
        await asyncio.sleep(0)
        snapshots.append(snapshot)

    ticker = SystemTicker(on_tick=on_tick)

    await ticker._tick()

    # The callback must have completed before _tick() returns.
    assert snapshots == [expected_snapshot()]
    assert ticker._tick_count == 1
    assert ticker._last_update == 1700.0



@pytest.mark.asyncio
async def test_system_ticker_awaits_awaitable_from_sync_callback(monkeypatch):
    stub_system_metrics(monkeypatch)
    snapshots = []

    async def record_snapshot(snapshot):
        await asyncio.sleep(0)
        snapshots.append(snapshot)

    def on_tick(snapshot):
        return record_snapshot(snapshot)

    ticker = SystemTicker(on_tick=on_tick)

    await ticker._tick()

    assert snapshots == [expected_snapshot()]
    assert ticker._tick_count == 1
    assert ticker._last_update == 1700.0



@pytest.mark.asyncio
async def test_system_ticker_updates_temperature_when_sensor_is_available(monkeypatch):
    from kaiagotchi.data.system_types import SystemState

    monkeypatch.setattr(system_module, "uptime", lambda: None)
    monkeypatch.setattr(system_module, "cpu_load", lambda: None)
    monkeypatch.setattr(system_module, "mem_usage", lambda: {})
    monkeypatch.setattr(system_module, "temperature", lambda: 48.5)
    monkeypatch.setattr(system_module.time, "time", lambda: 1701.0)

    state = SystemState()
    state.metrics.temperature = 42.0
    ticker = SystemTicker(system_state=state)

    await ticker._tick()

    assert state.metrics.temperature == 48.5


@pytest.mark.asyncio
async def test_system_ticker_preserves_last_temperature_when_sensor_unavailable(monkeypatch):
    from kaiagotchi.data.system_types import SystemState

    monkeypatch.setattr(system_module, "uptime", lambda: None)
    monkeypatch.setattr(system_module, "cpu_load", lambda: None)
    monkeypatch.setattr(system_module, "mem_usage", lambda: {})
    monkeypatch.setattr(system_module, "temperature", lambda: None)
    monkeypatch.setattr(system_module.time, "time", lambda: 1702.0)

    state = SystemState()
    state.metrics.temperature = 42.0
    ticker = SystemTicker(system_state=state)

    await ticker._tick()

    assert state.metrics.temperature == 42.0
