from pathlib import Path
import threading

import kaiagotchi.storage.persistent_network as persistent_network_module
from kaiagotchi.storage.persistent_network import MAX_PCAP_STORAGE_BYTES, PersistentNetwork


def _network(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()
    return network


def test_concurrent_saves_do_not_persist_an_older_snapshot_last(tmp_path, monkeypatch):
    network = _network(tmp_path)
    bssid = "AA:BB:CC:DD:EE:FF"
    network._data["bssids"][bssid] = {"version": 1}

    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    second_write_entered = threading.Event()
    persisted_versions = []
    errors = []

    def fake_atomic_save(_filepath, payload, fmt):
        assert fmt == "json"
        version = payload["bssids"][bssid]["version"]
        if version == 1:
            first_write_entered.set()
            if not release_first_write.wait(timeout=5):
                raise RuntimeError("timed out waiting to release first save")
        elif version == 2:
            second_write_entered.set()
        persisted_versions.append(version)
        return True

    monkeypatch.setattr(persistent_network_module, "atomically_save_data", fake_atomic_save)
    monkeypatch.setattr(network, "_ensure_file_permissions", lambda _path: None)
    monkeypatch.setattr(network, "generate_reports", lambda: None)

    def do_save():
        try:
            assert network.save()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=do_save)
    first.start()
    assert first_write_entered.wait(timeout=5)

    with network._state_lock:
        network._data["bssids"][bssid]["version"] = 2

    second = threading.Thread(target=do_save)
    second.start()
    # With serialized saves, the second snapshot must not reach disk while the
    # first snapshot is blocked in its write.
    second_reached_writer_early = second_write_entered.wait(timeout=0.2)

    release_first_write.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert not second_reached_writer_early
    assert persisted_versions == [1, 2]


def test_pruning_retains_metadata_when_file_deletion_fails(tmp_path, monkeypatch):
    network = _network(tmp_path)
    filename = "protected-capture.pcap"
    capture = Path(network.pcaps_dir) / filename
    capture.write_bytes(b"capture")

    record = {
        "bssid": "AA:BB:CC:DD:EE:FF",
        "created": "2026-10-21T12:00:00-05:00",
        "size": capture.stat().st_size,
        "path": str(capture),
    }
    with network._state_lock:
        network._data["pcaps"][filename] = record

    real_unlink = Path.unlink

    def fail_capture_unlink(path, *args, **kwargs):
        if path == capture:
            raise PermissionError("simulated unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_capture_unlink)
    monkeypatch.setattr(network, "_calculate_pcap_storage", lambda: MAX_PCAP_STORAGE_BYTES + 1)
    monkeypatch.setattr(network, "save", lambda: True)

    network._prune_old_pcaps()

    assert capture.exists()
    assert network.get_pcap_records()[filename] == record
