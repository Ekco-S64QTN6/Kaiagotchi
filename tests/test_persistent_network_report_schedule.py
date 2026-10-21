from pathlib import Path

import kaiagotchi.storage.persistent_network as persistent_network_module
from kaiagotchi.storage.persistent_network import PersistentNetwork


def _new_network(tmp_path):
    network = PersistentNetwork(storage_dir=str(tmp_path))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()
    return network


def test_save_does_not_regenerate_summary_reports(tmp_path, monkeypatch):
    network = _new_network(tmp_path)
    monkeypatch.setattr(persistent_network_module, "atomically_save_data", lambda *_a, **_k: True)
    monkeypatch.setattr(network, "_ensure_file_permissions", lambda _path: None)

    calls = []
    monkeypatch.setattr(network, "generate_reports", lambda: calls.append("report"))

    assert network.save() is True
    assert calls == []


def test_archiving_pcap_refreshes_reports_once_after_save(tmp_path, monkeypatch):
    network = _new_network(tmp_path)
    source = tmp_path / "incoming.pcap"
    source.write_bytes(b"pcap test fixture")

    monkeypatch.setattr(persistent_network_module, "atomically_save_data", lambda *_a, **_k: True)
    monkeypatch.setattr(network, "_ensure_file_permissions", lambda _path: None)
    monkeypatch.setattr(network, "enforce_storage_limit", lambda: None)

    calls = []
    monkeypatch.setattr(network, "generate_reports", lambda: calls.append("report"))

    archived = network.add_pcap_file(str(source), bssid="AA:BB:CC:DD:EE:FF", analyze=False)

    assert archived is not None
    assert Path(archived).is_file()
    assert calls == ["report"]
