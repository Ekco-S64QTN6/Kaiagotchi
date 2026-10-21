"""
Tests for the Kaiagotchi Cyber-Deck web server and telemetry serialization.
"""
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
