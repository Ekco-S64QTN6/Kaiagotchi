"""Synthetic tests for interface snapshot collection and merging."""

import queue
import threading
from types import SimpleNamespace

import kaiagotchi.network.interface_monitor as interface_monitor_module
from kaiagotchi.network.interface_monitor import InterfaceMonitor


def make_monitor() -> InterfaceMonitor:
    return InterfaceMonitor(threading.Event(), queue.Queue())


def test_get_iw_data_preserves_string_type_and_channel(monkeypatch):
    output = """phy#0
\tInterface wlan1
\t\tifindex 4
\t\ttype monitor
\t\tchannel 6 (2437 MHz), width: 20 MHz
"""

    monkeypatch.setattr(
        interface_monitor_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=output),
    )

    data = make_monitor()._get_iw_data()

    assert data == {
        "wireless_interfaces": {
            "wlan1": {
                "wireless": True,
                "type": "monitor",
                "channel": "6 (2437 MHz), width: 20 MHz",
            }
        }
    }


def test_merge_interface_data_marks_up_interface_ready():
    monitor = make_monitor()

    merged = monitor._merge_interface_data(
        {
            "interfaces": {
                "wlan1": {
                    "status": "UP",
                    "ipv4_address": "192.0.2.10",
                }
            }
        },
        {"wireless_interfaces": {"wlan1": {"wireless": True, "type": "monitor"}}},
    )

    assert merged["overall_status"] == "READY"
    assert merged["interface_count"] == 1
    assert merged["interfaces"]["wlan1"]["ipv4_address"] == "192.0.2.10"
    assert merged["wireless_interfaces"]["wlan1"]["type"] == "monitor"


def test_merge_interface_data_marks_present_but_down_interfaces():
    merged = make_monitor()._merge_interface_data(
        {"interfaces": {"wlan1": {"status": "DOWN"}}}
    )

    assert merged["overall_status"] == "NET_DOWN"
    assert merged["interface_count"] == 1


def test_merge_interface_data_marks_empty_snapshot_without_interfaces():
    merged = make_monitor()._merge_interface_data(
        {"interfaces": {}},
    )

    assert merged["overall_status"] == "NO_INTERFACES"
    assert merged["interface_count"] == 0


def test_merge_interface_data_preserves_fields_across_sources_for_same_interface():
    merged = make_monitor()._merge_interface_data(
        {
            "interfaces": {
                "wlan0": {
                    "name": "wlan0",
                    "status": "UP",
                    "ipv4_address": "192.0.2.10",
                    "mac_address": "02:00:00:00:00:10",
                    "mtu": 1500,
                    "rx_packets": 17,
                    "tx_packets": 9,
                }
            },
            "wireless_interfaces": {
                "wlan0": {"wireless": True},
            },
            "system_stats": {
                "wlan0": {"bytes_recv": 2048},
            },
        },
        {
            "interfaces": {
                "wlan0": {
                    "ip_addresses": [
                        {"address": "192.0.2.10", "prefixlen": "24"}
                    ],
                    "mtu": 1400,
                }
            },
            "wireless_interfaces": {
                "wlan0": {"type": "monitor", "channel": "6"},
            },
            "system_stats": {
                "wlan0": {"bytes_sent": 1024},
            },
        },
    )

    interface = merged["interfaces"]["wlan0"]
    assert interface["status"] == "UP"
    assert interface["ipv4_address"] == "192.0.2.10"
    assert interface["mac_address"] == "02:00:00:00:00:10"
    assert interface["rx_packets"] == 17
    assert interface["tx_packets"] == 9
    assert interface["mtu"] == 1400  # later source wins only for this field
    assert interface["ip_addresses"] == [
        {"address": "192.0.2.10", "prefixlen": "24"}
    ]
    assert merged["wireless_interfaces"]["wlan0"] == {
        "wireless": True,
        "type": "monitor",
        "channel": "6",
    }
    assert merged["system_stats"]["wlan0"] == {
        "bytes_recv": 2048,
        "bytes_sent": 1024,
    }
    assert merged["overall_status"] == "READY"
    assert merged["interface_count"] == 1


def test_merge_interface_data_keeps_interfaces_found_by_different_sources():
    merged = make_monitor()._merge_interface_data(
        {
            "interfaces": {
                "wlan0": {
                    "status": "UP",
                    "ipv4_address": "192.0.2.10",
                }
            }
        },
        {
            "interfaces": {
                "wlan1": {
                    "status": "UP",
                    "ipv4_address": "192.0.2.11",
                }
            }
        },
    )

    assert merged["interface_count"] == 2
    assert set(merged["interfaces"]) == {"wlan0", "wlan1"}
    assert merged["overall_status"] == "READY"
