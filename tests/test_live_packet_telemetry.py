"""The monitoring agent turns cumulative frame tallies into per-second rates,
and the web server fills the RSSI history from the strongest signal available.
"""
from __future__ import annotations

import pytest

from kaiagotchi.agent.monitoring_agent import MonitoringAgent

scapy_dot11 = pytest.importorskip("scapy.layers.dot11")
from scapy.layers.dot11 import Dot11, Dot11Beacon, RadioTap  # noqa: E402
from scapy.utils import wrpcap  # noqa: E402

AP = "aa:bb:cc:dd:ee:ff"


def _beacons(n: int):
    return [RadioTap(present="dBm_AntSignal", dBm_AntSignal=-42)
            / Dot11(type=0, subtype=8, addr2=AP, addr3=AP) / Dot11Beacon() for _ in range(n)]


def test_strongest_ap_power_picks_the_closest_to_zero():
    agent = MonitoringAgent(config={}, system_state={})
    aps = [{"power": "-70"}, {"power": "-40"}, {"power": "bad"}, {"power": "0"}, {"power": "-55"}]
    assert agent._strongest_ap_power(aps) == -40
    assert agent._strongest_ap_power([{"power": "0"}, {"power": ""}]) is None


@pytest.mark.asyncio
async def test_packet_rates_come_from_the_delta_between_two_scans(tmp_path):
    agent = MonitoringAgent(config={}, system_state={})
    agent._frame_scan_interval = 0.0  # don't throttle in the test
    pcap = tmp_path / "capture-01.cap"
    agent._session_pcap = pcap

    # First scan establishes a baseline; there is no rate yet.
    wrpcap(str(pcap), _beacons(3))
    await agent._refresh_packet_stats()
    assert agent._packet_rate is None
    assert agent._total_packets == {"rx": 3, "tx": 0}
    assert agent._current_rssi == -42

    # The capture grows; the second scan yields a positive rate from the delta.
    wrpcap(str(pcap), _beacons(9))
    await agent._refresh_packet_stats()
    assert agent._total_packets == {"rx": 9, "tx": 0}
    assert agent._packet_rate is not None and agent._packet_rate > 0
    assert agent._packet_breakdown["beacon"]["rx"] > 0


@pytest.mark.asyncio
async def test_a_rotated_capture_does_not_produce_negative_rates(tmp_path):
    agent = MonitoringAgent(config={}, system_state={})
    agent._frame_scan_interval = 0.0
    pcap = tmp_path / "capture-01.cap"
    agent._session_pcap = pcap

    wrpcap(str(pcap), _beacons(10))
    await agent._refresh_packet_stats()
    # Archive rotates the file back to a fresh, smaller capture.
    wrpcap(str(pcap), _beacons(2))
    await agent._refresh_packet_stats()

    assert agent._total_packets == {"rx": 2, "tx": 0}
    # No rate is computed against the stale larger baseline (would be negative).
    if agent._packet_rate is not None:
        assert agent._packet_rate >= 0


def test_server_rssi_falls_back_to_the_strongest_ap_when_hopping():
    from kaiagotchi.ui.web.server import WebServer

    srv = WebServer.__new__(WebServer)
    # Current channel 1, but the only APs are on other channels (radio hopping):
    # on-channel list is empty, so the strongest AP overall fills the history.
    snap = {
        "channel": 1,
        "aps_list": [
            {"bssid": "A", "essid": "x", "channel": 6, "power": "-70"},
            {"bssid": "B", "essid": "y", "channel": 11, "power": "-48"},
        ],
        "stations_list": [],
    }
    out = srv._serialize_snapshot(snap)
    assert out["current_rssi"] == -48


def test_server_prefers_the_agents_measured_rssi():
    from kaiagotchi.ui.web.server import WebServer

    srv = WebServer.__new__(WebServer)
    snap = {
        "channel": 6,
        "current_rssi": -37,
        "aps_list": [{"bssid": "A", "essid": "x", "channel": 6, "power": "-60"}],
        "stations_list": [],
    }
    out = srv._serialize_snapshot(snap)
    assert out["current_rssi"] == -37
