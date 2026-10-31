import time

from kaiagotchi.storage.persistent_network import PersistentNetwork


def _network(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()
    return network


def test_periodic_scan_persists_state_without_rebuilding_reports(tmp_path, monkeypatch):
    network = _network(tmp_path)
    report_calls = []
    monkeypatch.setattr(network, "generate_reports", lambda: report_calls.append("report"))
    monkeypatch.setattr(network, "_last_reports_generated_at", time.monotonic())

    network.update_from_scan_results(
        aps=[{
            "bssid": "AA:BB:CC:DD:EE:FF",
            "essid": "test-network",
            "channel": "6",
            "packets": 1,
            "beacons": 1,
            "privacy": "WPA2",
        }],
        stations=[],
    )

    assert network.get_bssid_history("AA:BB:CC:DD:EE:FF")["essid"] == "test-network"
    assert report_calls == []


def test_periodic_scan_refreshes_reports_when_interval_has_elapsed(tmp_path, monkeypatch):
    network = _network(tmp_path)
    report_calls = []
    monkeypatch.setattr(network, "generate_reports", lambda: report_calls.append("report"))
    monkeypatch.setattr(network, "_last_reports_generated_at", 0.0)

    network.update_from_scan_results(
        aps=[{"bssid": "AA:BB:CC:DD:EE:FF", "essid": "test-network"}],
        stations=[],
    )

    assert report_calls == ["report"]


def test_explicit_save_still_forces_fresh_reports(tmp_path, monkeypatch):
    network = _network(tmp_path)
    report_calls = []
    monkeypatch.setattr(network, "generate_reports", lambda: report_calls.append("report"))
    monkeypatch.setattr(network, "_last_reports_generated_at", time.monotonic())

    assert network.save()
    assert report_calls == ["report"]



def test_report_generation_tolerates_missing_last_seen_timestamp(tmp_path):
    network = _network(tmp_path)
    network._data["bssids"]["AA:BB:CC:DD:EE:FF"] = {
        "bssid": "AA:BB:CC:DD:EE:FF",
        "essid": "timestamp-free-network",
        "channel": 6,
        "encryption": "WPA2",
        "packets": 0,
        "beacons": 0,
        "last_seen": None,
    }

    network.generate_reports()

    report = (tmp_path / "handshakes_summary.md").read_text(encoding="utf-8")
    assert "timestamp-free-network" in report
    assert "AA:BB:CC:DD:EE:FF" in report
