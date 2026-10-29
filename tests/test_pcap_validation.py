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
    ],
)
def test_validate_file_accepts_known_signatures(tmp_path, filename, signature):
    capture = tmp_path / filename
    capture.write_bytes(signature)

    assert validate_file(str(capture))


def test_validate_file_rejects_pcapng_signature_without_a_complete_section_header(tmp_path):
    capture = tmp_path / "signature-only.pcapng"
    capture.write_bytes(bytes.fromhex("0a 0d 0d 0a"))

    assert not validate_file(str(capture))


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



def _pcapng_section_header(
    *, declared_length: int = 28, trailer_length: int = 28,
    byte_order_magic: bytes = bytes.fromhex("4d 3c 2b 1a"),
) -> bytes:
    """Build a minimal synthetic little-endian PCAPNG Section Header Block."""
    return (
        bytes.fromhex("0a 0d 0d 0a")
        + struct.pack("<I", declared_length)
        + byte_order_magic
        + struct.pack("<HHqI", 1, 0, -1, trailer_length)
    )


@pytest.mark.parametrize(
    ("filename", "section_header"),
    [
        pytest.param(
            "bad-section-length.pcapng",
            _pcapng_section_header(declared_length=24, trailer_length=24),
            id="section-header-shorter-than-minimum",
        ),
        pytest.param(
            "declared-length-too-long.pcapng",
            _pcapng_section_header(declared_length=32, trailer_length=32),
            id="declared-length-exceeds-file",
        ),
        pytest.param(
            "mismatched-trailer.pcapng",
            _pcapng_section_header(declared_length=28, trailer_length=24),
            id="trailing-length-mismatch",
        ),
        pytest.param(
            "invalid-byte-order.pcapng",
            _pcapng_section_header(byte_order_magic=bytes.fromhex("00 00 00 00")),
            id="invalid-byte-order-magic",
        ),
    ],
)
@pytest.mark.parametrize(
    "parse",
    [parse_pcap, parse_pcap_comprehensive],
    ids=["simple-parser", "comprehensive-parser"],
)
def test_parser_fails_closed_on_malformed_pcapng_section_headers(
    tmp_path, caplog, filename, section_header, parse
):
    capture = tmp_path / filename
    capture.write_bytes(section_header)

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse(str(capture))

    assert "invalid pcapng block structure" in caplog.text.lower()
    if isinstance(result, list):
        assert result == []
    else:
        assert result.bssids == {}
        assert result.stations == {}
        assert result.handshakes == []
        assert result.total_packets == 0
        assert result.total_beacons == 0


@pytest.mark.parametrize(
    "parse",
    [parse_pcap, parse_pcap_comprehensive],
    ids=["simple-parser", "comprehensive-parser"],
)
def test_parser_accepts_minimal_valid_pcapng_section_header(
    tmp_path, caplog, parse
):
    capture = tmp_path / "empty-section.pcapng"
    capture.write_bytes(_pcapng_section_header())

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse(str(capture))

    assert "failed to read pcap file" not in caplog.text.lower()
    if isinstance(result, list):
        assert result == []
    else:
        assert result.total_packets == 0
        assert result.total_beacons == 0



def _pcapng_interface_block() -> bytes:
    """An IEEE 802.11 Interface Description Block."""
    return struct.pack("<IIHHII", 1, 20, 105, 0, 65535, 20)


def _pcapng_enhanced_packet_block(
    packet: bytes,
    *,
    declared_length: int | None = None,
    trailer_length: int | None = None,
    captured_length: int | None = None,
    original_length: int | None = None,
) -> bytes:
    padded_packet = packet + (b"\x00" * (-len(packet) % 4))
    actual_length = 32 + len(padded_packet)
    if declared_length is None:
        declared_length = actual_length
    if trailer_length is None:
        trailer_length = actual_length
    if captured_length is None:
        captured_length = len(packet)
    if original_length is None:
        original_length = len(packet)
    return (
        struct.pack(
            "<IIIIIII",
            6,  # Enhanced Packet Block
            declared_length,
            0,  # interface id
            0,  # timestamp high
            0,  # timestamp low
            captured_length,
            original_length,
        )
        + padded_packet
        + struct.pack("<I", trailer_length)
    )


def _synthetic_beacon() -> bytes:
    """Build a synthetic beacon frame; no real network identifiers are used."""
    from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt

    bssid = "02:00:00:00:00:01"
    return bytes(
        Dot11(
            type=0,
            subtype=8,
            addr1="ff:ff:ff:ff:ff:ff",
            addr2=bssid,
            addr3=bssid,
        )
        / Dot11Beacon()
        / Dot11Elt(ID=0, info=b"SyntheticLab")
        / Dot11Elt(ID=3, info=b"\x06")
    )


def test_pcapng_preflight_accepts_valid_interface_and_packet_blocks(tmp_path):
    capture = tmp_path / "valid-beacon.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_enhanced_packet_block(_synthetic_beacon())
    )

    result = parse_pcap_comprehensive(str(capture))

    assert result.total_packets == 1
    assert result.total_beacons == 1
    assert "02:00:00:00:00:01" in result.bssids


@pytest.mark.parametrize(
    ("declared_delta", "trailer_delta", "expected_reason"),
    [
        pytest.param(0, -4, "mismatched trailing length", id="bad-packet-trailer"),
        pytest.param(4, 4, "extends beyond end of file", id="truncated-packet-block"),
    ],
)
def test_pcapng_preflight_rejects_corrupt_later_packet_block_without_partial_results(
    tmp_path, caplog, declared_delta, trailer_delta, expected_reason
):
    capture = tmp_path / "corrupt-late-packet-block.pcapng"
    good_packet = _pcapng_enhanced_packet_block(_synthetic_beacon())
    # A valid first beacon followed by a corrupt second block must not yield a
    # partial network inventory just because Scapy treats trailer EOF as EOF.
    bad_packet_bytes = _synthetic_beacon()
    actual_length = len(_pcapng_enhanced_packet_block(bad_packet_bytes))
    bad_packet = _pcapng_enhanced_packet_block(
        bad_packet_bytes,
        declared_length=actual_length + declared_delta,
        trailer_length=actual_length + trailer_delta,
    )
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + good_packet
        + bad_packet
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "invalid pcapng block structure" in caplog.text.lower()
    assert expected_reason in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0


def test_pcapng_preflight_rejects_epb_captured_length_beyond_packet_body(
    tmp_path, caplog
):
    capture = tmp_path / "captured-length-beyond-body.pcapng"
    good_packet = _pcapng_enhanced_packet_block(_synthetic_beacon())
    packet_bytes = _synthetic_beacon()
    # The enclosing block and trailer stay internally consistent; only caplen
    # lies about how many packet bytes the block body contains.
    bad_packet = _pcapng_enhanced_packet_block(
        packet_bytes,
        captured_length=len(packet_bytes) + 8,
        original_length=len(packet_bytes) + 8,
    )
    capture.write_bytes(
        _pcapng_section_header() + _pcapng_interface_block() + good_packet + bad_packet
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "captured length exceeding available block data" in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0


def test_pcapng_preflight_rejects_captured_length_greater_than_original(
    tmp_path, caplog
):
    capture = tmp_path / "captured-length-greater-than-wire-length.pcapng"
    packet_bytes = _synthetic_beacon()
    bad_packet = _pcapng_enhanced_packet_block(
        packet_bytes,
        captured_length=len(packet_bytes),
        original_length=max(0, len(packet_bytes) - 4),
    )
    capture.write_bytes(
        _pcapng_section_header() + _pcapng_interface_block() + bad_packet
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "captured length greater than original length" in caplog.text.lower()
    assert result.bssids == {}
    assert result.total_packets == 0
    assert result.total_beacons == 0
