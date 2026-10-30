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
    *,
    declared_length: int | None = None,
    trailer_length: int | None = None,
    byte_order_magic: bytes = bytes.fromhex("4d 3c 2b 1a"),
    options: bytes = b"",
    major_version: int = 1,
) -> bytes:
    """Build a synthetic little-endian PCAPNG Section Header Block."""
    actual_length = 28 + len(options)
    if declared_length is None:
        declared_length = actual_length
    if trailer_length is None:
        trailer_length = actual_length
    return (
        bytes.fromhex("0a 0d 0d 0a")
        + struct.pack("<I", declared_length)
        + byte_order_magic
        + struct.pack("<HHq", major_version, 0, -1)
        + options
        + struct.pack("<I", trailer_length)
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



def _pcapng_option(code: int, value: bytes) -> bytes:
    """Build one little-endian PCAPNG option with four-byte value padding."""
    padded_value = value + (b"\x00" * (-len(value) % 4))
    return struct.pack("<HH", code, len(value)) + padded_value


def _pcapng_interface_block(
    options: bytes = b"", *, snaplen: int = 65535
) -> bytes:
    """An IEEE 802.11 Interface Description Block."""
    block_length = 20 + len(options)
    return (
        struct.pack("<IIHHI", 1, block_length, 105, 0, snaplen)
        + options
        + struct.pack("<I", block_length)
    )


def _pcapng_simple_packet_block(
    packet: bytes, *, original_length: int | None = None
) -> bytes:
    """Build a Simple Packet Block, whose interface ID is implicitly zero."""
    padded_packet = packet + (b"\x00" * (-len(packet) % 4))
    block_length = 16 + len(padded_packet)
    if original_length is None:
        original_length = len(packet)
    return (
        struct.pack("<III", 3, block_length, original_length)
        + padded_packet
        + struct.pack("<I", block_length)
    )


def _pcapng_packet_block(
    packet: bytes, *, options: bytes = b"", interface_id: int = 0
) -> bytes:
    """Build an obsolete-style Packet Block to exercise parsing and option framing."""
    padded_packet = packet + (b"\x00" * (-len(packet) % 4))
    block_length = 32 + len(padded_packet) + len(options)
    return (
        struct.pack(
            "<IIHHIIII",
            2,  # Packet Block
            block_length,
            interface_id,  # interface id
            0,  # drops count
            0,  # timestamp high
            0,  # timestamp low
            len(packet),
            len(packet),
        )
        + padded_packet
        + options
        + struct.pack("<I", block_length)
    )


def _pcapng_enhanced_packet_block(
    packet: bytes,
    *,
    declared_length: int | None = None,
    trailer_length: int | None = None,
    captured_length: int | None = None,
    original_length: int | None = None,
    options: bytes = b"",
    interface_id: int = 0,
) -> bytes:
    padded_packet = packet + (b"\x00" * (-len(packet) % 4))
    actual_length = 32 + len(padded_packet) + len(options)
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
            interface_id,  # interface id
            0,  # timestamp high
            0,  # timestamp low
            captured_length,
            original_length,
        )
        + padded_packet
        + options
        + struct.pack("<I", trailer_length)
    )


def _pcapng_name_resolution_record(record_type: int, value: bytes) -> bytes:
    padded_value = value + (bytes([0]) * (-len(value) % 4))
    return struct.pack("<HH", record_type, len(value)) + padded_value


def _pcapng_name_resolution_block(records: bytes, options: bytes = b"") -> bytes:
    block_length = 12 + len(records) + len(options)
    return (
        struct.pack("<II", 4, block_length)
        + records
        + options
        + struct.pack("<I", block_length)
    )


def _pcapng_interface_statistics_block(
    *, interface_id: int = 0, options: bytes = b""
) -> bytes:
    block_length = 24 + len(options)
    return (
        struct.pack("<IIIII", 5, block_length, interface_id, 0, 0)
        + options
        + struct.pack("<I", block_length)
    )


def _pcapng_decryption_secrets_block(
    secrets_data: bytes,
    *,
    options: bytes = b"",
    declared_secrets_length: int | None = None,
) -> bytes:
    padded_secrets = secrets_data + (bytes([0]) * (-len(secrets_data) % 4))
    if declared_secrets_length is None:
        declared_secrets_length = len(secrets_data)
    block_length = 20 + len(padded_secrets) + len(options)
    return (
        struct.pack("<IIII", 10, block_length, 0x01020304, declared_secrets_length)
        + padded_secrets
        + options
        + struct.pack("<I", block_length)
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
    section_options = _pcapng_option(1, b"synthetic") + _pcapng_option(0, b"")
    interface_options = (
        _pcapng_option(2, b"wlan1")
        + _pcapng_option(9, b"\x06")
        + _pcapng_option(0, b"")
    )
    packet_options = (
        _pcapng_option(1, b"synthetic beacon")
        + _pcapng_option(2, struct.pack("<I", 1))
        + _pcapng_option(0, b"")
    )
    capture.write_bytes(
        _pcapng_section_header(options=section_options)
        + _pcapng_interface_block(options=interface_options)
        + _pcapng_enhanced_packet_block(
            _synthetic_beacon(),
            options=packet_options,
        )
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



@pytest.mark.parametrize(
    ("block_kind", "options", "expected_reason"),
    [
        pytest.param(
            "section",
            struct.pack("<HH", 2, 12) + b"lab\x00",
            "option at offset",
            id="section-option-value-overruns-block",
        ),
        pytest.param(
            "interface",
            struct.pack("<HH", 2, 12) + b"lab\x00",
            "option at offset",
            id="interface-option-value-overruns-block",
        ),
        pytest.param(
            "enhanced-packet",
            struct.pack("<HH", 1, 12) + b"x\x00\x00\x00",
            "option at offset",
            id="packet-option-value-overruns-block",
        ),
        pytest.param(
            "packet",
            struct.pack("<HH", 1, 12) + b"x\x00\x00\x00",
            "option at offset",
            id="legacy-packet-option-value-overruns-block",
        ),
        pytest.param(
            "interface",
            struct.pack("<HH", 0, 4) + b"\x00\x00\x00\x00",
            "end-of-options",
            id="end-of-options-has-nonzero-length",
        ),
        pytest.param(
            "interface",
            struct.pack("<HH", 0, 0) + struct.pack("<HH", 2, 0),
            "data follows end-of-options",
            id="end-of-options-not-last",
        ),
    ],
)
def test_pcapng_preflight_rejects_malformed_option_framing(
    tmp_path, caplog, block_kind, options, expected_reason
):
    capture = tmp_path / f"malformed-options-{block_kind}.pcapng"
    if block_kind == "section":
        capture.write_bytes(_pcapng_section_header(options=options))
    elif block_kind == "interface":
        capture.write_bytes(
            _pcapng_section_header() + _pcapng_interface_block(options=options)
        )
    elif block_kind == "packet":
        capture.write_bytes(
            _pcapng_section_header()
            + _pcapng_interface_block()
            + _pcapng_packet_block(_synthetic_beacon(), options=options)
        )
    else:
        capture.write_bytes(
            _pcapng_section_header()
            + _pcapng_interface_block()
            + _pcapng_enhanced_packet_block(_synthetic_beacon(), options=options)
        )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "invalid options in block" in caplog.text.lower()
    assert expected_reason in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0



def test_pcapng_preflight_accepts_valid_legacy_packet_block_options(tmp_path):
    capture = tmp_path / "valid-legacy-packet-block.pcapng"
    options = _pcapng_option(1, b"legacy packet") + _pcapng_option(0, b"")
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_packet_block(_synthetic_beacon(), options=options)
    )

    result = parse_pcap_comprehensive(str(capture))

    assert result.total_packets == 1
    assert result.total_beacons == 1
    assert "02:00:00:00:00:01" in result.bssids


@pytest.mark.parametrize(
    ("block_kind", "option_code", "value", "expected_reason"),
    [
        pytest.param(
            "interface",
            9,
            b"\x06\x07",
            "option code 9 must have value length 1, got 2",
            id="timestamp-resolution-must-be-one-byte",
        ),
        pytest.param(
            "enhanced-packet",
            2,
            b"\x01\x00",
            "option code 2 must have value length 4, got 2",
            id="packet-flags-must-be-four-bytes",
        ),
    ],
)
def test_pcapng_preflight_rejects_invalid_fixed_size_option_values(
    tmp_path, caplog, block_kind, option_code, value, expected_reason
):
    capture = tmp_path / f"invalid-fixed-option-{block_kind}.pcapng"
    options = _pcapng_option(option_code, value) + _pcapng_option(0, b"")
    if block_kind == "interface":
        blocks = _pcapng_section_header() + _pcapng_interface_block(options=options)
    else:
        blocks = (
            _pcapng_section_header()
            + _pcapng_interface_block()
            + _pcapng_enhanced_packet_block(_synthetic_beacon(), options=options)
        )
    capture.write_bytes(blocks)

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "invalid options in block" in caplog.text.lower()
    assert expected_reason in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0


@pytest.mark.parametrize("packet_kind", ["packet", "enhanced-packet"])
def test_pcapng_preflight_rejects_undeclared_packet_interface_without_partial_results(
    tmp_path, caplog, packet_kind
):
    capture = tmp_path / f"undeclared-interface-{packet_kind}.pcapng"
    good_packet = _pcapng_enhanced_packet_block(_synthetic_beacon())
    if packet_kind == "packet":
        bad_packet = _pcapng_packet_block(
            _synthetic_beacon(), interface_id=1
        )
    else:
        bad_packet = _pcapng_enhanced_packet_block(
            _synthetic_beacon(), interface_id=1
        )
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + good_packet
        + bad_packet
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "references undeclared interface 1" in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0


def test_pcapng_preflight_accepts_packet_referencing_second_declared_interface(
    tmp_path, caplog
):
    capture = tmp_path / "second-interface.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_interface_block()
        + _pcapng_enhanced_packet_block(_synthetic_beacon(), interface_id=1)
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "invalid pcapng block structure" not in caplog.text.lower()
    assert result.total_packets == 1
    assert result.total_beacons == 1


def test_pcapng_preflight_accepts_valid_metadata_blocks(tmp_path):
    capture = tmp_path / "valid-metadata-blocks.pcapng"
    name_records = (
        _pcapng_name_resolution_record(
            1, bytes.fromhex("7f 00 00 01") + b"lab" + bytes([0])
        )
        + _pcapng_name_resolution_record(0, b"")
    )
    name_options = (
        _pcapng_option(3, bytes.fromhex("08 08 08 08"))
        + _pcapng_option(4, bytes(range(16)))
        + _pcapng_option(0, b"")
    )
    statistics_options = (
        _pcapng_option(2, struct.pack("<Q", 1))
        + _pcapng_option(8, struct.pack("<Q", 2))
        + _pcapng_option(0, b"")
    )
    secrets_options = (
        _pcapng_option(1, b"synthetic metadata")
        + _pcapng_option(0, b"")
    )
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_name_resolution_block(name_records, name_options)
        + _pcapng_interface_statistics_block(options=statistics_options)
        + _pcapng_decryption_secrets_block(
            b"synthetic-only-secret-data", options=secrets_options
        )
    )

    assert validate_file(str(capture))


@pytest.mark.parametrize(
    ("records", "expected_reason"),
    [
        pytest.param(
            _pcapng_name_resolution_record(
                1, bytes.fromhex("7f 00 00 01") + b"lab" + bytes([0])
            ),
            "missing its end record",
            id="missing-end-record",
        ),
        pytest.param(
            struct.pack("<HH", 1, 100) + b"short" + bytes(3),
            "record exceeding its block boundary",
            id="record-value-exceeds-block",
        ),
        pytest.param(
            _pcapng_name_resolution_record(1, bytes.fromhex("7f 00 00 01")),
            "must have value length at least 6",
            id="ipv4-record-too-short",
        ),
        pytest.param(
            _pcapng_name_resolution_record(
                1, bytes.fromhex("7f 00 00 01") + b"labx"
            ),
            "is not nul terminated",
            id="ipv4-record-missing-name-terminator",
        ),
        pytest.param(
            struct.pack("<HH", 0, 4) + b"xxxx",
            "end record with nonzero length",
            id="end-record-has-nonzero-length",
        ),
    ],
)
def test_pcapng_preflight_rejects_malformed_name_resolution_records(
    tmp_path, caplog, records, expected_reason
):
    capture = tmp_path / "malformed-name-resolution-records.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_name_resolution_block(records)
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        assert not validate_file(str(capture))

    assert expected_reason in caplog.text.lower()


def test_pcapng_preflight_rejects_invalid_name_resolution_option_length(
    tmp_path, caplog
):
    capture = tmp_path / "invalid-name-resolution-option.pcapng"
    records = _pcapng_name_resolution_record(0, b"")
    options = _pcapng_option(3, bytes([1, 2]))
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_name_resolution_block(records, options)
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        assert not validate_file(str(capture))

    assert "option code 3 must have value length 4, got 2" in caplog.text.lower()


@pytest.mark.parametrize(
    ("interface_id", "options", "expected_reason"),
    [
        pytest.param(
            1, b"", "references undeclared interface 1",
            id="statistics-interface-not-declared",
        ),
        pytest.param(
            0,
            _pcapng_option(2, bytes([0, 1, 2, 3])),
            "option code 2 must have value length 8, got 4",
            id="statistics-start-time-has-invalid-length",
        ),
    ],
)
def test_pcapng_preflight_rejects_invalid_interface_statistics_block(
    tmp_path, caplog, interface_id, options, expected_reason
):
    capture = tmp_path / "invalid-interface-statistics.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_interface_statistics_block(
            interface_id=interface_id, options=options
        )
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        assert not validate_file(str(capture))

    assert expected_reason in caplog.text.lower()


def test_pcapng_preflight_rejects_decryption_secrets_length_beyond_block(
    tmp_path, caplog
):
    capture = tmp_path / "invalid-decryption-secrets-length.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_decryption_secrets_block(
            b"short", declared_secrets_length=40
        )
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        assert not validate_file(str(capture))

    assert "secrets data exceeding its block boundary" in caplog.text.lower()


def test_pcapng_preflight_rejects_malformed_decryption_secrets_options(
    tmp_path, caplog
):
    capture = tmp_path / "invalid-decryption-secrets-options.pcapng"
    options = struct.pack("<HH", 1, 12) + b"x" + bytes(3)
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_decryption_secrets_block(b"synthetic", options=options)
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        assert not validate_file(str(capture))

    assert "invalid options in block" in caplog.text.lower()
    assert "exceeds its block boundary" in caplog.text.lower()


@pytest.mark.parametrize(
    "parse",
    [parse_pcap, parse_pcap_comprehensive],
    ids=["simple-parser", "comprehensive-parser"],
)
def test_parser_rejects_malformed_metadata_block_without_partial_packets(
    tmp_path, caplog, parse
):
    capture = tmp_path / "malformed-metadata-after-beacon.pcapng"
    good_packet = _pcapng_enhanced_packet_block(_synthetic_beacon())
    malformed_nrb = _pcapng_name_resolution_block(
        _pcapng_name_resolution_record(
            1, bytes.fromhex("7f 00 00 01") + b"lab" + bytes([0])
        )
    )
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + good_packet
        + malformed_nrb
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse(str(capture))

    assert "missing its end record" in caplog.text.lower()
    if isinstance(result, list):
        assert result == []
    else:
        assert result.bssids == {}
        assert result.stations == {}
        assert result.handshakes == []
        assert result.total_packets == 0
        assert result.total_beacons == 0


def test_pcapng_preflight_rejects_simple_packet_without_declared_interface(
    tmp_path, caplog
):
    capture = tmp_path / "simple-packet-without-interface.pcapng"
    capture.write_bytes(
        _pcapng_section_header() + _pcapng_simple_packet_block(_synthetic_beacon())
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "simple packet block" in caplog.text.lower()
    assert "undeclared interface 0" in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0


@pytest.mark.parametrize(
    ("snaplen", "captured_length"),
    [
        pytest.param(65535, None, id="full-capture"),
        pytest.param(12, 12, id="snaplen-truncation"),
        pytest.param(0, None, id="zero-means-no-limit"),
    ],
)
def test_pcapng_preflight_accepts_simple_packet_snaplen_semantics(
    tmp_path, snaplen, captured_length
):
    capture = tmp_path / "valid-simple-packet.pcapng"
    original_packet = _synthetic_beacon()
    captured_packet = (
        original_packet[:captured_length]
        if captured_length is not None
        else original_packet
    )
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block(snaplen=snaplen)
        + _pcapng_simple_packet_block(
            captured_packet, original_length=len(original_packet)
        )
    )

    assert validate_file(str(capture))


@pytest.mark.parametrize(
    ("snaplen", "original_length_delta"),
    [
        pytest.param(0, 8, id="original-length-exceeds-available-payload"),
        pytest.param(12, 0, id="payload-exceeds-snaplen"),
    ],
)
@pytest.mark.parametrize(
    "parse",
    [parse_pcap, parse_pcap_comprehensive],
    ids=["simple-parser", "comprehensive-parser"],
)
def test_pcapng_preflight_rejects_inconsistent_simple_packet_payload_length(
    tmp_path, caplog, snaplen, original_length_delta, parse
):
    capture = tmp_path / "invalid-simple-packet-length.pcapng"
    packet = _synthetic_beacon()
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block(snaplen=snaplen)
        + _pcapng_simple_packet_block(
            packet, original_length=len(packet) + original_length_delta
        )
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse(str(capture))

    assert "simple packet block" in caplog.text.lower()
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
def test_pcapng_preflight_rejects_unsupported_section_major_version(
    tmp_path, caplog, parse
):
    capture = tmp_path / "unsupported-major-version.pcapng"
    capture.write_bytes(_pcapng_section_header(major_version=2))

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse(str(capture))

    assert "unsupported section header major version 2" in caplog.text.lower()
    if isinstance(result, list):
        assert result == []
    else:
        assert result.bssids == {}
        assert result.stations == {}
        assert result.handshakes == []
        assert result.total_packets == 0
        assert result.total_beacons == 0


def test_pcapng_preflight_resets_interface_count_at_new_section(
    tmp_path, caplog
):
    capture = tmp_path / "section-interface-reset.pcapng"
    capture.write_bytes(
        _pcapng_section_header()
        + _pcapng_interface_block()
        + _pcapng_enhanced_packet_block(_synthetic_beacon())
        + _pcapng_section_header()
        + _pcapng_enhanced_packet_block(_synthetic_beacon(), interface_id=0)
    )

    with caplog.at_level(logging.ERROR, logger="pcap_parser"):
        result = parse_pcap_comprehensive(str(capture))

    assert "references undeclared interface 0" in caplog.text.lower()
    assert result.bssids == {}
    assert result.stations == {}
    assert result.handshakes == []
    assert result.total_packets == 0
    assert result.total_beacons == 0
