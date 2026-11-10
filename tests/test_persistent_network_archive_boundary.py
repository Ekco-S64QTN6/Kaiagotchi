"""Archive-boundary tests for PCAP registration and reanalysis."""

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import kaiagotchi.storage.persistent_network as persistent_network_module
from kaiagotchi.storage.persistent_network import PersistentNetwork


def _network(storage_dir: Path) -> PersistentNetwork:
    network = PersistentNetwork(storage_dir=str(storage_dir))
    network._sync_thread.join(timeout=5.0)
    assert not network._sync_thread.is_alive()
    return network


def _synthetic_parser(parsed_paths: list[str]):
    def parse(path: str):
        parsed_paths.append(path)
        return SimpleNamespace(bssids={}, stations={}, handshakes=[])

    return parse


def test_add_pcap_record_rejects_external_and_symlink_paths(tmp_path, monkeypatch):
    network = _network(tmp_path / "storage")
    parsed_paths: list[str] = []
    monkeypatch.setattr(
        persistent_network_module,
        "parse_pcap_comprehensive",
        _synthetic_parser(parsed_paths),
    )

    external_capture = tmp_path / "external.pcap"
    external_capture.write_bytes(b"external synthetic capture")
    external_capture.chmod(0o644)
    symlink = Path(network.pcaps_dir) / "linked.pcap"
    symlink.symlink_to(external_capture)
    managed_capture = Path(network.pcaps_dir) / "managed.pcap"
    managed_capture.write_bytes(b"managed synthetic capture")

    # The analysis helper is independently guarded for future call sites.
    network._analyze_pcap_into_record(external_capture, {})
    network.add_pcap_record(
        external_capture,
        "AA:BB:CC:DD:EE:FF",
        external_capture.stat().st_size,
        "2026-11-09T12:00:00-06:00",
        analyze=True,
    )
    network.add_pcap_record(
        symlink,
        "BB:CC:DD:EE:FF:00",
        external_capture.stat().st_size,
        "2026-11-09T12:00:00-06:00",
        analyze=True,
    )

    assert parsed_paths == []
    assert network.get_pcap_records() == {}
    assert stat.S_IMODE(external_capture.stat().st_mode) == 0o644
    assert external_capture.read_bytes() == b"external synthetic capture"

    network.add_pcap_record(
        managed_capture,
        "CC:DD:EE:FF:00:11",
        managed_capture.stat().st_size,
        "2026-11-09T12:00:00-06:00",
        analyze=True,
    )

    records = network.get_pcap_records()
    assert list(records) == ["managed.pcap"]
    assert records["managed.pcap"]["path"] == str(managed_capture.resolve())
    assert parsed_paths == [str(managed_capture.resolve())]
    assert stat.S_IMODE(managed_capture.stat().st_mode) == 0o600


def test_reanalyze_all_pcaps_skips_persisted_external_and_symlink_paths(
    tmp_path, monkeypatch
):
    network = _network(tmp_path / "storage")
    parsed_paths: list[str] = []
    monkeypatch.setattr(
        persistent_network_module,
        "parse_pcap_comprehensive",
        _synthetic_parser(parsed_paths),
    )

    external_capture = tmp_path / "external.pcap"
    external_capture.write_bytes(b"external synthetic capture")
    external_capture.chmod(0o644)
    symlink = Path(network.pcaps_dir) / "linked.pcap"
    symlink.symlink_to(external_capture)
    managed_capture = Path(network.pcaps_dir) / "managed.pcap"
    managed_capture.write_bytes(b"managed synthetic capture")

    network._data["pcaps"] = {
        "external-record.pcap": {
            "bssid": "AA:BB:CC:DD:EE:FF",
            "created": "2026-11-09T12:00:00-06:00",
            "analysis": [],
            "path": str(external_capture),
        },
        "linked.pcap": {
            "bssid": "BB:CC:DD:EE:FF:00",
            "created": "2026-11-09T12:00:00-06:00",
            "analysis": [],
            "path": str(symlink),
        },
        "managed.pcap": {
            "bssid": "CC:DD:EE:FF:00:11",
            "created": "2026-11-09T12:00:00-06:00",
            "analysis": [],
            "path": str(managed_capture),
        },
    }

    network.reanalyze_all_pcaps()

    assert parsed_paths == [str(managed_capture.resolve())]
    assert stat.S_IMODE(external_capture.stat().st_mode) == 0o644
    assert external_capture.read_bytes() == b"external synthetic capture"


def test_initialization_rejects_symlinked_private_archive_root_without_chmodding_target(
    tmp_path,
):
    external_archive = tmp_path / "external-archive"
    external_archive.mkdir()
    external_archive.chmod(0o755)

    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "pcaps").symlink_to(external_archive, target_is_directory=True)

    with pytest.raises(
        PermissionError, match="Could not secure PCAP storage directory"
    ):
        PersistentNetwork(storage_dir=str(storage))

    assert stat.S_IMODE(external_archive.stat().st_mode) == 0o755
    assert external_archive.is_dir()
