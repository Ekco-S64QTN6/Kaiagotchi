import threading

import kaiagotchi.storage.persistent_network as persistent_network_module
from kaiagotchi.storage.persistent_network import PersistentNetwork


def test_save_serializes_a_detached_nested_snapshot(tmp_path, monkeypatch):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()
    network._data["bssids"]["00:11:22:33:44:55"] = {
        "bssid": "00:11:22:33:44:55",
        "essid": "Original SSID",
        "first_seen": "2026-10-21T12:00:00-05:00",
        "last_seen": "2026-10-21T12:00:00-05:00",
        "packets": 1,
        "beacons": 1,
    }

    def mutate_payload(_path, payload, fmt="json"):
        assert fmt == "json"
        assert payload["bssids"]["00:11:22:33:44:55"]["essid"] == "Original SSID"
        payload["bssids"]["00:11:22:33:44:55"]["essid"] = "Mutated outside snapshot"
        assert network._data["bssids"]["00:11:22:33:44:55"]["essid"] == "Original SSID"
        return True

    monkeypatch.setattr(persistent_network_module, "atomically_save_data", mutate_payload)
    monkeypatch.setattr(network, "generate_reports", lambda: None)

    assert network.save()
    assert network._data["bssids"]["00:11:22:33:44:55"]["essid"] == "Original SSID"


def test_state_update_waits_for_short_critical_section(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    started = threading.Event()
    completed = threading.Event()

    def update():
        started.set()
        network.update_bssid(
            bssid="00:11:22:33:44:55",
            essid="Serialized update",
            packets=1,
            beacons=1,
        )
        completed.set()

    worker = threading.Thread(target=update)
    with network._state_lock:
        worker.start()
        assert started.wait(timeout=1.0)
        assert not completed.wait(timeout=0.05)

    assert completed.wait(timeout=2.0)
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert network.get_bssid_record("00:11:22:33:44:55")["essid"] == "Serialized update"
