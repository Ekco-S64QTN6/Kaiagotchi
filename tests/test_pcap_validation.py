"""Synthetic regression tests for lightweight PCAP signature validation."""

import logging
import struct

import pytest

from kaiagotchi.network.pcap_parser import (
    parse_pcap,
    parse_pcap_comprehensive,
    validate_file,
)


@pytest.mark.parametrize(
    ("filename", "signature"),
    [
        ("capture.pcap", bytes.fromhex("d4 c3 b2 a1")),
        ("capture.pcap", bytes.fromhex("a1 b2 c3 d4")),
        ("capture.pcap", bytes.fromhex("4d 3c b2 a1")),
        ("capture.pcap", bytes.fromhex("a1 b2 3c 4d")),
        ("capture.pcapng", bytes.fromhex("0a 0d 0d 0a")),
    ],
)
def test_validate_file_accepts_known_signatures(tmp_path, filename, signature):
    capture = tmp_path / filename
    capture.write_bytes(signature)

    assert validate_file(str(capture))


def test_validate_file_rejects_unknown_signature(tmp_path):
    capture = tmp_path / "not-a-capture.pcap"
    capture.write_bytes(b"this is not a capture")

    assert not validate_file(str(capture))


def test_validate_file_rejects_empty_file(tmp_path):
    capture = tmp_path / "empty.pcap"
    capture.touch()

    assert not validate_file(str(capture))


def test_validate_file_rejects_missing_file(tmp_path):
    assert not validate_file(str(tmp_path / "missing.pcap"))


def test_validate_file_accepts_signature_with_nonstandard_extension(tmp_path, caplog):
    capture = tmp_path / "capture.bin"
    capture.write_bytes(bytes.fromhex("d4 c3 b2 a1"))

    with caplog.at_level(logging.WARNING, logger="pcap_parser"):
        assert validate_file(str(capture))

    assert "extension" in caplog.text.lower()


def _classic_pcap_global_header() -> bytes:
    """Build a synthetic little-endian PCAP header for 802.11 frames."""
    return bytes.fromhex("d4 c3 b2 a1") + struct.pack(
        "<HHIIII",
        2,       # major version
        4,       # minor version
        0,       # thiszone
        0,       # sigfigs
        65535,   # snaplen
        105,     # DLT_IEEE802_11
    )


@pytest.mark.parametrize(
    ("filename", "capture_bytes"),
    [
        pytest.param(
            "signature-only.pcap",
            bytes.fromhex("d4 c3 b2 a1"),
            id="pcap-signature-only",
        ),
        pytest.param(
            "signature-only.pcapng",
            bytes.fromhex("0a 0d 0d 0a"),
            id="pcapng-signature-only",
        ),
        pytest.param(
            "partial-record-header.pcap",
            _classic_pcap_global_header() + b"\x01\x02\x03",
            id="partial-packet-record-header",
        ),
        pytest.param(
            "truncated-record-data.pcap",
            _classic_pcap_global_header()
            + struct.pack("<IIII", 1, 0, 64, 64)
            + b"\x08\x00",
            id="truncated-packet-record-data",
        ),
    ],
)
@pytest.mark.parametrize(
    "parse",
    [parse_pcap, parse_pcap_comprehensive],
    ids=["simple-parser", "comprehensive-parser"],
)
def test_parser_handles_truncated_capture_inputs(
    tmp_path, filename, capture_bytes, parse
):
    """Malformed captures should not escape as parser exceptions or captures."""
    capture = tmp_path / filename
    capture.write_bytes(capture_bytes)

    result = parse(str(capture))

    if isinstance(result, list):
        assert result == []
    else:
        assert result.bssids == {}
        assert result.stations == {}
        assert result.handshakes == []
        assert result.total_beacons == 0
