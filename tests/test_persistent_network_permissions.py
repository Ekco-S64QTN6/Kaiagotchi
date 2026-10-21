from __future__ import annotations

import os
import stat
from pathlib import Path

from kaiagotchi.storage.persistent_network import PersistentNetwork


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _wait_for_sync(network: PersistentNetwork) -> None:
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive(), "startup PCAP sync did not finish"


def test_archived_pcap_history_and_reports_are_owner_only(tmp_path):
    storage = tmp_path / "storage"
    network = PersistentNetwork(storage_dir=str(storage))
    _wait_for_sync(network)

    source = tmp_path / "incoming.pcap"
    source.write_bytes(b"not a real pcap; parsing is disabled for this fixture")
    source.chmod(0o644)

    archived = network.add_pcap_file(str(source), analyze=False)
    assert archived is not None

    pcap_path = Path(archived)
    assert pcap_path.exists()
    assert _mode(Path(network.pcaps_dir)) == 0o700
    assert _mode(pcap_path) == 0o600
    assert _mode(Path(network.filepath)) == 0o600
    assert _mode(storage / "handshakes_summary.json") == 0o600
    assert _mode(storage / "handshakes_summary.md") == 0o600


def test_startup_sync_restricts_permissions_on_preexisting_pcaps(tmp_path):
    storage = tmp_path / "storage"
    pcaps = storage / "pcaps"
    pcaps.mkdir(parents=True)
    pcap = pcaps / "old-capture.pcap"
    pcap.write_bytes(b"existing capture")
    pcap.chmod(0o644)
    pcaps.chmod(0o755)

    network = PersistentNetwork(storage_dir=str(storage))
    _wait_for_sync(network)

    assert _mode(pcaps) == 0o700
    assert _mode(pcap) == 0o600
    assert pcap.name in network.get_pcap_records()
