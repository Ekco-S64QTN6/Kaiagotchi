"""
Tests for the Kaiagotchi Cyber-Deck web server and telemetry serialization.
"""
from types import SimpleNamespace

import pytest

from kaiagotchi.config.manager import load_config as load_legacy_config
from kaiagotchi.ui.web.server import WebServer, _generate_mock_snapshot


def test_mock_snapshot_structure():
    """Mock telemetry carries every field the dashboard reads."""
    snap = _generate_mock_snapshot()
    for key in ("timestamp", "uptime", "status", "mood", "mode", "aps", "stations", "chatter",
                "current_channel", "current_rssi", "packet_breakdown", "packet_rate", "total_packets",
                "pwnd_count"):
        assert key in snap, key
    assert "face" not in snap
    assert len(snap["aps"]) > 0


def test_mock_chatter_is_passive():
    """Sample chatter stays in passive-observation language."""
    text = " ".join(e["text"].lower() for e in _generate_mock_snapshot()["chatter"])
    for word in ("deauth", "attack", "inject"):
        assert word not in text


def test_web_server_initialization():
    cfg = {"web": {"host": "127.0.0.1", "port": 8888, "update_hz": 15.0}}
    server = WebServer(cfg)
    assert server._host == "127.0.0.1"
    assert server._port == 8888
    assert server._hz == 15.0




def test_legacy_config_loader_defaults_web_to_loopback(tmp_path):
    config = load_legacy_config(str(tmp_path / "missing.toml"))
    assert config["ui"]["web"]["host"] == "127.0.0.1"

def test_web_server_defaults_to_loopback():
    """The unauthenticated telemetry UI is local-only unless opted into LAN."""
    server = WebServer()
    assert server._host == "127.0.0.1"


def test_serialize_snapshot():
    """View snapshot (airodump-style string fields) converts to the wire format."""
    server = WebServer()
    raw = {
        "uptime": "01:23:45",
        "status": "Target locked",
        "agent_mood": "happy",
        "channel": "6",
        "pwnd_count": 3,
        "aps_list": [
            {"bssid": "AA:BB:CC:DD:EE:FF", "essid": "TestNet", "channel": " 6", "power": " -42",
             "privacy": "WPA2", "beacons": "150"},
            {"bssid": "11:11:11:11:11:11", "essid": "Far", "channel": "11", "power": "-30", "privacy": "WPA2"},
            {"bssid": "22:22:22:22:22:22", "essid": "", "channel": "6", "power": "-1", "privacy": "OPN"},
        ],
        "stations_list": [
            {"station_mac": "11:22:33:44:55:66", "bssid": "AA:BB:CC:DD:EE:FF", "power": "-50", "packets": "320"},
            {"station_mac": "66:55:44:33:22:11", "bssid": "(not associated)", "power": "-70", "packets": "4"},
        ],
        "chatter_log": ["[12:00:00] Initialized"],
    }
    out = server._serialize_snapshot(raw)
    assert out["uptime"] == "01:23:45"
    assert out["mood"] == "happy"
    assert out["current_channel"] == 6
    assert out["pwnd_count"] == 3
    assert "face" not in out

    assert out["aps"][0]["ssid"] == "TestNet"
    assert out["aps"][0]["pwr"] == -42
    assert out["aps"][0]["ch"] == 6
    assert out["aps"][2]["pwr"] is None          # airodump -1 = not reported
    assert out["aps"][2]["ssid"] == "<Hidden>"
    # RSSI is the strongest AP on the *current* channel, not the strongest overall.
    assert out["current_rssi"] == -42

    assert out["stations"][0]["mac"] == "11:22:33:44:55:66"
    assert out["stations"][0]["status"] == "CONNECTED"
    assert out["stations"][1]["status"] == "PROBING"

    assert out["chatter"][0] == {"time": "12:00:00", "type": "info", "text": "Initialized"}


def test_serialize_does_not_invent_metrics():
    """Metrics the engine does not measure are null, never placeholder numbers."""
    out = WebServer()._serialize_snapshot({"aps_list": []})
    assert out["packet_breakdown"] is None
    assert out["packet_rate"] is None
    assert out["total_packets"] is None
    assert out["current_rssi"] is None
    assert out["current_channel"] is None


def test_empty_live_state_does_not_fabricate_network_activity():
    server = WebServer(state_provider=lambda: {})
    snapshot = server._get_latest_snapshot()

    assert snapshot["aps"] == []
    assert snapshot["stations"] == []
    assert snapshot["aps_count"] == 0
    assert snapshot["pwnd_count"] == 0
    assert snapshot["packet_rate"] is None


def test_live_provider_failure_returns_empty_snapshot_not_mock_data():
    def broken_provider():
        raise RuntimeError("simulated provider failure")

    server = WebServer(state_provider=broken_provider)
    snapshot = server._get_latest_snapshot()

    assert snapshot["aps"] == []
    assert snapshot["stations"] == []
    assert snapshot["aps_count"] == 0


def test_mock_telemetry_is_used_only_without_a_live_provider():
    snapshot = WebServer()._get_latest_snapshot()
    assert snapshot["aps"]
    assert snapshot["stations"]


def test_web_server_stop_signals_worker_without_scheduling_duplicate_cleanup(monkeypatch):
    import kaiagotchi.ui.web.server as server_module

    server = WebServer()
    server._started = True
    server._loop = SimpleNamespace(is_running=lambda: True)

    class FakeThread:
        def __init__(self):
            self.alive = True
            self.joined = False

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.joined = True
            self.alive = False

    thread = FakeThread()
    server._thread = thread
    monkeypatch.setattr(
        server_module.asyncio,
        "run_coroutine_threadsafe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cleanup must be owned by _serve")),
    )

    server.stop()

    assert server._stop_event.is_set()
    assert thread.joined
    assert not server._started


@pytest.mark.asyncio
async def test_web_server_cleans_runner_when_site_start_fails(monkeypatch):
    import kaiagotchi.ui.web.server as server_module

    class FakeRunner:
        def __init__(self, _app):
            self.cleaned = False
            self.setup_called = False

        async def setup(self):
            self.setup_called = True

        async def cleanup(self):
            self.cleaned = True

    class FakeSite:
        def __init__(self, _runner, _host, _port):
            pass

        async def start(self):
            raise OSError("simulated bind failure")

    monkeypatch.setattr(server_module.web, "AppRunner", FakeRunner)
    monkeypatch.setattr(server_module.web, "TCPSite", FakeSite)
    server = WebServer({"web": {"host": "127.0.0.1", "port": 0}})

    with pytest.raises(OSError, match="simulated bind failure"):
        await server._serve()

    assert server._runner.setup_called
    assert server._runner.cleaned
