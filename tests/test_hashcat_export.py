from pathlib import Path

from kaiagotchi.network.pcap_parser import CaptureData, export_to_hashcat


def test_export_to_hashcat_writes_valid_22000_and_legacy_pmkid_formats(tmp_path):
    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=False,
        pmkid="0102030405060708090a0b0c0d0e0f10",
    )

    files = export_to_hashcat([capture], str(tmp_path))

    assert Path(files["pmkid_22000"]).read_text(encoding="utf-8").strip() == (
        "WPA*01*0102030405060708090a0b0c0d0e0f10*"
        "001122334455*aabbccddeeff*546573742d4150***"
    )
    assert Path(files["pmkid_16800"]).read_text(encoding="utf-8").strip() == (
        "0102030405060708090a0b0c0d0e0f10*"
        "001122334455*aabbccddeeff*546573742d4150"
    )
    assert files["pmkid"] == files["pmkid_16800"]


def test_handshake_export_is_explicitly_metadata_not_hashcat_input(tmp_path):
    capture = CaptureData(
        type="WPA Handshake (Complete)",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=True,
    )

    files = export_to_hashcat([capture], str(tmp_path))

    assert files["handshake_info"] == files["handshake"]
    assert "Handshake for 00:11:22:33:44:55" in Path(files["handshake_info"]).read_text(
        encoding="utf-8"
    )
    assert "pmkid_22000" not in files



def test_unknown_ssid_pmkid_is_not_exported_as_a_fake_hash(tmp_path):
    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Hidden or Unknown",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=False,
        pmkid="0102030405060708090a0b0c0d0e0f10",
    )

    files = export_to_hashcat([capture], str(tmp_path))

    assert files == {}
    assert list(tmp_path.iterdir()) == []



def test_pmkid_without_client_mac_is_not_exported_as_a_fake_hash(tmp_path):
    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac=None,
        handshake_complete=False,
        pmkid="0102030405060708090a0b0c0d0e0f10",
    )

    files = export_to_hashcat([capture], str(tmp_path))

    assert files == {}
    assert list(tmp_path.iterdir()) == []



def test_malformed_pmkid_is_not_exported(tmp_path):
    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=False,
        pmkid="not-a-pmkid",
    )

    files = export_to_hashcat([capture], str(tmp_path))

    assert files == {}
    assert list(tmp_path.iterdir()) == []


def test_hashcat_exports_are_owner_only(tmp_path):
    import stat

    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=False,
        pmkid="0102030405060708090a0b0c0d0e0f10",
    )

    files = export_to_hashcat([capture], str(tmp_path))
    for key in ("pmkid_16800", "pmkid_22000"):
        assert stat.S_IMODE(Path(files[key]).stat().st_mode) == 0o600


def test_hashcat_export_replaces_symlink_without_modifying_its_target(tmp_path):
    import stat

    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    protected = tmp_path / "protected.txt"
    protected.write_text("do not overwrite", encoding="utf-8")
    pmkid_file = output_dir / "pmkid_hashes.txt"
    pmkid_file.symlink_to(protected)

    capture = CaptureData(
        type="PMKID",
        bssid="00:11:22:33:44:55",
        ssid="Test-AP",
        packet_index=12,
        source_file="capture.pcap",
        raw_data_present=True,
        client_mac="AA:BB:CC:DD:EE:FF",
        handshake_complete=False,
        pmkid="0102030405060708090a0b0c0d0e0f10",
    )
    files = export_to_hashcat([capture], str(output_dir))

    assert protected.read_text(encoding="utf-8") == "do not overwrite"
    assert not pmkid_file.is_symlink()
    assert Path(files["pmkid_16800"]).read_text(encoding="utf-8").startswith(
        "0102030405060708090a0b0c0d0e0f10*"
    )
    assert stat.S_IMODE(pmkid_file.stat().st_mode) == 0o600
