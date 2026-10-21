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



def test_capture_storage_permissions_are_owner_only(tmp_path):
    import stat

    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    pcap_dir = Path(network.pcaps_dir)
    assert stat.S_IMODE(pcap_dir.stat().st_mode) == 0o700

    capture = pcap_dir / "private-capture.pcap"
    capture.write_bytes(b"test capture")
    network._ensure_file_permissions(str(capture))
    assert stat.S_IMODE(capture.stat().st_mode) == 0o600

    assert network.save()
    assert stat.S_IMODE(Path(network.filepath).stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "handshakes_summary.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "handshakes_summary.md").stat().st_mode) == 0o600

def test_analysis_getter_returns_detached_nested_records(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()

    record = {
        "bssid": "00:11:22:33:44:55",
        "analysis": [{"type": "PMKID", "metadata": {"ssid": "Test-AP"}}],
    }
    with network._state_lock:
        network._data.setdefault("pcaps", {})["snapshot.pcap"] = record

    result = network.get_analysis_for_bssid("00:11:22:33:44:55")
    result[0]["metadata"]["ssid"] = "mutated outside lock"

    stored = network.get_analysis_for_bssid("00:11:22:33:44:55")
    assert stored[0]["metadata"]["ssid"] == "Test-AP"




def test_initialization_fails_if_private_pcap_directory_cannot_be_enforced(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    import pytest

    import kaiagotchi.storage.persistent_network as persistent_network_module

    storage = tmp_path / "storage"
    pcap_dir = storage / "pcaps"
    real_chmod = os.chmod

    def fail_private_pcap_chmod(path, mode):
        if Path(path) == pcap_dir and mode == 0o700:
            raise PermissionError("simulated chmod denial")
        return real_chmod(path, mode)

    monkeypatch.setattr(persistent_network_module.os, "chmod", fail_private_pcap_chmod)

    with pytest.raises(PermissionError, match="Could not secure PCAP storage directory"):
        PersistentNetwork(storage_dir=str(storage))
