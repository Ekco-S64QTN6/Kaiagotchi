from pathlib import Path

from kaiagotchi.storage.persistent_network import PersistentNetwork


def test_sync_does_not_delete_file_appearing_after_initial_listing(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    filename = "race_appears_after_listing.pcap"
    pcap_path = Path(network.pcaps_dir) / filename
    late_record = {
        "bssid": "00:11:22:33:44:55",
        "created": "2026-10-21T12:00:00-05:00",
        "size": 123,
        "path": str(pcap_path),
        "analysis": [{"type": "PMKID", "pmkid": "00" * 16}],
    }

    class FileAppearsAfterSnapshot(dict):
        def keys(self):
            # Called after _sync_pcaps_with_filesystem() has taken its initial
            # Path.glob snapshot, reproducing the add-during-reconciliation race.
            pcap_path.touch()
            return super().keys()

    network._data["pcaps"] = FileAppearsAfterSnapshot({filename: late_record})

    network._sync_pcaps_with_filesystem()

    assert network._data["pcaps"][filename] is late_record


def test_sync_does_not_overwrite_record_updated_during_analysis(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    filename = "race_updated_during_analysis.pcap"
    pcap_path = Path(network.pcaps_dir) / filename
    pcap_path.touch()
    late_record = {
        "bssid": "00:11:22:33:44:55",
        "created": "2026-10-21T12:00:00-05:00",
        "size": 123,
        "path": str(pcap_path),
        "analysis": [{"type": "PMKID", "bssid": "00:11:22:33:44:55", "pmkid": "11" * 16}],
    }

    def insert_newer_record(_path, _record):
        network._data.setdefault("pcaps", {})[filename] = late_record

    network._analyze_pcap_into_record = insert_newer_record
    network._sync_pcaps_with_filesystem()

    assert network._data["pcaps"][filename] is late_record
    assert network._data["pcaps"][filename]["analysis"][0]["pmkid"] == "11" * 16
