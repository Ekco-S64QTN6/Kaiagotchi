# kaiagotchi/network/pcap_parser.py
import logging
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scapy.all import (
    EAPOL,
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    Dot11ProbeResp,
    PcapReader,
    rdpcap,
)
from scapy.layers.eap import EAPOL_KEY

# Configure logging for the module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
parser_logger = logging.getLogger('pcap_parser')


# Classic PCAP magic values cover microsecond/nanosecond timestamps in either
# byte order. PCAPNG uses a single section-header block type signature.
_PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
_PCAP_MAGIC_NUMBERS = {
    b"\xd4\xc3\xb2\xa1",
    b"\xa1\xb2\xc3\xd4",
    b"\x4d\x3c\xb2\xa1",
    b"\xa1\xb2\x3c\x4d",
    _PCAPNG_MAGIC,
}


@dataclass
class CaptureData:
    """
    Data class representing a captured Wi-Fi authentication element.
    """
    type: str  # 'WPA Handshake', 'PMKID', 'WPA3 Handshake', etc.
    bssid: str
    ssid: str
    packet_index: int
    source_file: str
    raw_data_present: bool
    client_mac: str | None = None
    timestamp: float | None = None
    handshake_complete: bool = False
    pmkid: str | None = None


@dataclass
class NetworkData:
    """
    Comprehensive network data extracted from PCAP - ALL BSSIDs and stations.
    """
    bssids: dict[str, dict[str, Any]]  # bssid -> {ssid, channel, encryption, etc.}
    stations: dict[str, dict[str, Any]]  # station_mac -> {associated_bssid, etc.}
    handshakes: list[CaptureData]  # Handshake and PMKID captures
    total_packets: int
    total_beacons: int


def _validate_pcapng_block_framing(path: Path, file_size: int) -> bool:
    """Validate PCAPNG block boundaries without loading packet payloads.

    Scapy treats some block-trailer EOF errors as ordinary end-of-file. Verify
    each declared block length and trailing length first so a corrupt later block
    cannot silently turn a damaged capture into a successful partial parse.
    This checks framing only; Scapy still parses block contents and packets.
    """
    def reject(reason: str) -> bool:
        parser_logger.error(
            "Invalid PCAPNG block structure in %s: %s", path, reason
        )
        return False

    def alignment_padding_error(
        data_offset: int,
        value_length: int,
        padded_length: int,
        description: str,
    ) -> str | None:
        """Check only the at-most-three alignment bytes required to be zero."""
        padding_length = padded_length - value_length
        if padding_length <= 0:
            return None
        capture_file.seek(data_offset + value_length)
        padding = capture_file.read(padding_length)
        if len(padding) != padding_length:
            return f"{description} has truncated alignment padding"
        if any(padding):
            return f"{description} has nonzero alignment padding"
        return None

    def option_error(
        options_start: int, options_end: int, block_type_value: int | None
    ) -> str | None:
        """Validate option framing and known fixed-size/type-dependent values."""
        fixed_lengths_by_block = {
            # Interface Description Block options.
            1: {
                4: 8, 5: 17, 6: 6, 7: 8, 8: 8, 9: 1, 10: 4,
                13: 1, 14: 8, 16: 8, 17: 8,
            },
            # Legacy Packet Block options.
            2: {2: 4, 4: 8},
            # Name Resolution Block DNS-address options.
            4: {3: 4, 4: 16},
            # Interface Statistics Block counters and timestamps.
            5: {2: 8, 3: 8, 4: 8, 5: 8, 6: 8, 7: 8, 8: 8},
            # Enhanced Packet Block options.
            6: {2: 4, 4: 8, 5: 8, 6: 4, 8: 8, 0x8001: 4, 0x8003: 4},
        }
        minimum_lengths_by_block = {
            1: {11: 1},  # if_filter includes a one-byte filter-type identifier.
            2: {3: 1},  # pack_hash starts with its algorithm identifier.
            6: {
                3: 1,  # epb_hash starts with its algorithm identifier.
                7: 1,  # epb_verdict starts with its verdict-type identifier.
            },
        }
        # Only enforce multiplicity for standardized options whose current
        # PCAPNG definition explicitly disallows repeats. Unknown/vendor options
        # remain opaque, and common comments/custom options remain repeatable.
        single_occurrence_options_by_block = {
            None: {2, 3, 4},  # Section Header Block.
            1: {2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18},
            2: {2, 4},  # Obsolete Packet Block.
            4: {2, 3, 4},  # Name Resolution Block.
            5: {2, 3, 4, 5, 6, 7, 8},  # Interface Statistics Block.
            6: {2, 4, 5, 6, 8},  # Enhanced Packet Block.
        }
        custom_option_codes = {2988, 2989, 19372, 19373}
        seen_option_codes: set[int] = set()
        interface_speed_values: dict[int, int] = {}
        option_offset = options_start
        while option_offset < options_end:
            if options_end - option_offset < 4:
                return f"truncated option header at offset {option_offset}"

            capture_file.seek(option_offset)
            option_header = capture_file.read(4)
            if len(option_header) != 4:
                return f"truncated option header at offset {option_offset}"
            option_code, option_length = struct.unpack(endian + "HH", option_header)

            if option_code == 0:
                if option_length != 0:
                    return f"end-of-options at offset {option_offset} has nonzero length"
                if option_offset + 4 != options_end:
                    return f"data follows end-of-options at offset {option_offset}"
                break

            padded_length = option_length + (-option_length % 4)
            option_end = option_offset + 4 + padded_length
            if option_end > options_end:
                return f"option at offset {option_offset} exceeds its block boundary"

            padding_problem = alignment_padding_error(
                option_offset + 4,
                option_length,
                padded_length,
                f"option at offset {option_offset}",
            )
            if padding_problem is not None:
                return padding_problem

            if (
                option_code
                in single_occurrence_options_by_block.get(block_type_value, set())
                and option_code in seen_option_codes
            ):
                return f"option code {option_code} may appear only once in this block"
            seen_option_codes.add(option_code)

            if option_code in custom_option_codes and option_length < 4:
                return (
                    f"custom option code {option_code} must have value length "
                    f"at least 4, got {option_length}"
                )

            fixed_lengths = fixed_lengths_by_block.get(block_type_value, {})
            expected_length = fixed_lengths.get(option_code)
            if expected_length is not None and option_length != expected_length:
                return (
                    f"option code {option_code} must have value length "
                    f"{expected_length}, got {option_length}"
                )

            minimum_length = minimum_lengths_by_block.get(
                block_type_value, {}
            ).get(option_code)
            if minimum_length is not None and option_length < minimum_length:
                return (
                    f"option code {option_code} must have value length at least "
                    f"{minimum_length}, got {option_length}"
                )

            if block_type_value in {2, 6} and option_code == 3:
                capture_file.seek(option_offset + 4)
                option_value = capture_file.read(option_length)
                if len(option_value) != option_length:
                    return f"truncated option value at offset {option_offset}"
                hash_lengths = {2: 4, 3: 16, 4: 20, 5: 4}
                expected_hash_length = hash_lengths.get(option_value[0])
                if (
                    expected_hash_length is not None
                    and option_length != expected_hash_length + 1
                ):
                    return (
                        f"option code 3 hash algorithm {option_value[0]} must have "
                        f"value length {expected_hash_length + 1}, got {option_length}"
                    )

            if block_type_value == 6 and option_code == 7:
                capture_file.seek(option_offset + 4)
                option_value = capture_file.read(option_length)
                if len(option_value) != option_length:
                    return f"truncated option value at offset {option_offset}"
                verdict_lengths = {1: 8, 2: 8}
                expected_verdict_length = verdict_lengths.get(option_value[0])
                if (
                    expected_verdict_length is not None
                    and option_length != expected_verdict_length + 1
                ):
                    return (
                        f"option code 7 verdict type {option_value[0]} must have "
                        f"value length {expected_verdict_length + 1}, got {option_length}"
                    )

            if block_type_value == 1 and option_code in {8, 16, 17}:
                capture_file.seek(option_offset + 4)
                speed_value = capture_file.read(8)
                if len(speed_value) != 8:
                    return f"truncated interface speed option at offset {option_offset}"
                interface_speed_values[option_code] = struct.unpack(
                    endian + "Q", speed_value
                )[0]

            option_offset = option_end

        if block_type_value == 1:
            if 8 in interface_speed_values and (
                16 in interface_speed_values or 17 in interface_speed_values
            ):
                return (
                    "interface if_speed option code 8 cannot be combined with "
                    "directional if_txspeed/if_rxspeed options"
                )
            if (
                16 in interface_speed_values
                and 17 in interface_speed_values
                and interface_speed_values[16] == interface_speed_values[17]
            ):
                return (
                    "interface if_txspeed and if_rxspeed must not both be used "
                    "when their values are equal; use if_speed instead"
                )

        # PCAPNG permits option lists to end at the end of their enclosing block
        # without an explicit end-of-options marker.
        return None

    endian: str | None = None
    offset = 0
    section_end_offset: int | None = None
    interface_count = 0
    interface_snaplens: list[int] = []
    try:
        with path.open("rb") as capture_file:
            while offset < file_size:
                capture_file.seek(offset)
                block_type = capture_file.read(4)
                if len(block_type) != 4:
                    return reject("truncated block type")

                length_bytes = capture_file.read(4)
                if len(length_bytes) != 4:
                    return reject("truncated block length")

                is_section_header = block_type == _PCAPNG_MAGIC
                if is_section_header:
                    if (
                        section_end_offset is not None
                        and offset != section_end_offset
                    ):
                        return reject(
                            f"section at offset {offset} begins before or after "
                            f"the previous section's declared end "
                            f"{section_end_offset}"
                        )
                    byte_order_magic = capture_file.read(4)
                    if byte_order_magic == b"\x1a\x2b\x3c\x4d":
                        endian = ">"
                    elif byte_order_magic == b"\x4d\x3c\x2b\x1a":
                        endian = "<"
                    else:
                        return reject("invalid section-header byte-order magic")
                    # Interface IDs are section-scoped and restart at each SHB.
                    interface_count = 0
                    interface_snaplens = []
                    minimum_length = 28
                else:
                    if endian is None:
                        return reject("first block is not a section header")
                    minimum_length = 12

                block_length = struct.unpack(endian + "I", length_bytes)[0]
                if block_length < minimum_length:
                    return reject(
                        f"block at offset {offset} is shorter than {minimum_length} bytes"
                    )
                if block_length % 4:
                    return reject(
                        f"block at offset {offset} has a non-aligned length"
                    )

                block_end = offset + block_length
                if block_end > file_size:
                    return reject(
                        f"block at offset {offset} extends beyond end of file"
                    )
                if not is_section_header and section_end_offset is not None:
                    if offset >= section_end_offset:
                        return reject(
                            f"block at offset {offset} starts at or beyond the "
                            f"declared section end {section_end_offset}"
                        )
                    if block_end > section_end_offset:
                        return reject(
                            f"block at offset {offset} extends beyond the declared "
                            f"section end {section_end_offset}"
                        )

                if is_section_header:
                    capture_file.seek(offset + 12)
                    version_bytes = capture_file.read(4)
                    if len(version_bytes) != 4:
                        return reject("section header has a truncated version")
                    major_version, _minor_version = struct.unpack(
                        endian + "HH", version_bytes
                    )
                    if major_version != 1:
                        return reject(
                            f"unsupported section header major version {major_version}"
                        )

                    capture_file.seek(offset + 16)
                    section_length_bytes = capture_file.read(8)
                    if len(section_length_bytes) != 8:
                        return reject("section header has a truncated section length")
                    section_length = struct.unpack(
                        endian + "q", section_length_bytes
                    )[0]
                    if section_length == -1:
                        section_end_offset = None
                    elif section_length < 0:
                        return reject(
                            f"section header at offset {offset} has invalid negative "
                            f"section length {section_length}"
                        )
                    elif section_length % 4:
                        return reject(
                            f"section header at offset {offset} has a section length "
                            f"that is not a multiple of four: {section_length}"
                        )
                    else:
                        section_end_offset = block_end + section_length
                        if section_end_offset > file_size:
                            return reject(
                                f"section header at offset {offset} declares an end "
                                f"beyond the end of the file"
                            )

                block_type_value = (
                    None
                    if is_section_header
                    else struct.unpack(endian + "I", block_type)[0]
                )
                options_start: int | None = None
                interface_snaplen: int | None = None

                if is_section_header:
                    # Section Header Block options follow version/section-length.
                    options_start = offset + 24
                elif block_type_value == 1:
                    if block_length < 20:
                        return reject(
                            f"interface description block at offset {offset} is too short"
                        )
                    capture_file.seek(offset + 12)
                    snaplen_bytes = capture_file.read(4)
                    if len(snaplen_bytes) != 4:
                        return reject(
                            f"interface description block at offset {offset} has a truncated snaplen"
                        )
                    interface_snaplen = struct.unpack(endian + "I", snaplen_bytes)[0]
                    options_start = offset + 16
                elif block_type_value in {2, 6}:
                    if block_length < 32:
                        return reject(
                            f"packet block at offset {offset} is too short"
                        )
                    # Legacy Packet Blocks use a 16-bit interface ID; EPBs use
                    # a 32-bit field. Both IDs must resolve inside this section.
                    capture_file.seek(offset + 8)
                    interface_id_size = 2 if block_type_value == 2 else 4
                    interface_id_data = capture_file.read(interface_id_size)
                    if len(interface_id_data) != interface_id_size:
                        return reject(
                            f"packet block at offset {offset} has a truncated interface ID"
                        )
                    interface_id_format = "H" if block_type_value == 2 else "I"
                    interface_id = struct.unpack(
                        endian + interface_id_format, interface_id_data
                    )[0]
                    if interface_id >= interface_count:
                        return reject(
                            f"packet block at offset {offset} references undeclared "
                            f"interface {interface_id} (section has {interface_count})"
                        )

                    # Packet Block and Enhanced Packet Block share the captured
                    # and original length offsets, then padded packet bytes.
                    capture_file.seek(offset + 20)
                    packet_lengths = capture_file.read(8)
                    if len(packet_lengths) != 8:
                        return reject(
                            f"packet block at offset {offset} has truncated packet lengths"
                        )
                    captured_length, original_length = struct.unpack(
                        endian + "II", packet_lengths
                    )
                    if captured_length > original_length:
                        return reject(
                            f"packet block at offset {offset} has captured length greater than original length"
                        )
                    padded_capture_length = captured_length + (-captured_length % 4)
                    available_packet_bytes = block_length - 32
                    if padded_capture_length > available_packet_bytes:
                        return reject(
                            f"packet block at offset {offset} has captured length exceeding available block data"
                        )
                    padding_problem = alignment_padding_error(
                        offset + 28,
                        captured_length,
                        padded_capture_length,
                        f"packet data in block at offset {offset}",
                    )
                    if padding_problem is not None:
                        return reject(padding_problem)
                    options_start = offset + 28 + padded_capture_length
                elif block_type_value == 3:
                    if block_length < 16:
                        return reject(
                            f"simple packet block at offset {offset} is too short"
                        )
                    # SPBs have no interface field and implicitly use interface 0.
                    if interface_count == 0 or not interface_snaplens:
                        return reject(
                            f"simple packet block at offset {offset} references "
                            "undeclared interface 0 (section has no interfaces)"
                        )

                    capture_file.seek(offset + 8)
                    original_length_bytes = capture_file.read(4)
                    if len(original_length_bytes) != 4:
                        return reject(
                            f"simple packet block at offset {offset} has a truncated original length"
                        )
                    original_length = struct.unpack(
                        endian + "I", original_length_bytes
                    )[0]
                    snaplen = interface_snaplens[0]
                    # Per PCAPNG, a zero snaplen means no limit; otherwise the
                    # captured packet length is min(original length, snaplen).
                    captured_length = (
                        original_length
                        if snaplen == 0
                        else min(original_length, snaplen)
                    )
                    padded_capture_length = captured_length + (-captured_length % 4)
                    expected_block_length = 16 + padded_capture_length
                    if block_length != expected_block_length:
                        return reject(
                            f"simple packet block at offset {offset} has a block length "
                            f"inconsistent with original length and interface snaplen "
                            f"(expected {expected_block_length}, got {block_length})"
                        )
                    padding_problem = alignment_padding_error(
                        offset + 12,
                        captured_length,
                        padded_capture_length,
                        f"simple packet data in block at offset {offset}",
                    )
                    if padding_problem is not None:
                        return reject(padding_problem)

                elif block_type_value == 4:
                    # Name Resolution Blocks contain a record TLV list followed
                    # by optional block options. The end record is mandatory and
                    # separates those two areas.
                    record_offset = offset + 8
                    records_end = block_end - 4
                    end_record_found = False
                    options_start = records_end
                    minimum_record_lengths = {1: 6, 2: 18, 3: 8, 4: 10}
                    while record_offset < records_end:
                        if records_end - record_offset < 4:
                            return reject(
                                f"name resolution block at offset {offset} has a truncated record header"
                            )
                        capture_file.seek(record_offset)
                        record_header = capture_file.read(4)
                        if len(record_header) != 4:
                            return reject(
                                f"name resolution block at offset {offset} has a truncated record header"
                            )
                        record_type, record_length = struct.unpack(
                            endian + "HH", record_header
                        )
                        if record_type == 0:
                            if record_length != 0:
                                return reject(
                                    f"name resolution block at offset {offset} has an end record with nonzero length"
                                )
                            record_offset += 4
                            options_start = record_offset
                            end_record_found = True
                            break

                        padded_record_length = (
                            record_length + (-record_length % 4)
                        )
                        record_value_end = record_offset + 4 + record_length
                        record_end = record_offset + 4 + padded_record_length
                        if record_end > records_end:
                            return reject(
                                f"name resolution block at offset {offset} has a record exceeding its block boundary"
                            )

                        padding_problem = alignment_padding_error(
                            record_offset + 4,
                            record_length,
                            padded_record_length,
                            f"name resolution record at offset {record_offset}",
                        )
                        if padding_problem is not None:
                            return reject(padding_problem)

                        minimum_length = minimum_record_lengths.get(record_type)
                        if minimum_length is not None:
                            if record_length < minimum_length:
                                return reject(
                                    f"name resolution record type {record_type} must have value length at least {minimum_length}, got {record_length}"
                                )
                            capture_file.seek(record_value_end - 1)
                            if capture_file.read(1) != bytes([0]):
                                return reject(
                                    f"name resolution record type {record_type} is not NUL terminated"
                                )

                        record_offset = record_end

                    if not end_record_found:
                        return reject(
                            f"name resolution block at offset {offset} is missing its end record"
                        )
                elif block_type_value == 5:
                    if block_length < 24:
                        return reject(
                            f"interface statistics block at offset {offset} is too short"
                        )
                    capture_file.seek(offset + 8)
                    interface_id_bytes = capture_file.read(4)
                    if len(interface_id_bytes) != 4:
                        return reject(
                            f"interface statistics block at offset {offset} has a truncated interface ID"
                        )
                    interface_id = struct.unpack(
                        endian + "I", interface_id_bytes
                    )[0]
                    if interface_id >= interface_count:
                        return reject(
                            f"interface statistics block at offset {offset} references undeclared "
                            f"interface {interface_id} (section has {interface_count})"
                        )
                    options_start = offset + 20
                elif block_type_value == 10:
                    if block_length < 20:
                        return reject(
                            f"decryption secrets block at offset {offset} is too short"
                        )
                    capture_file.seek(offset + 12)
                    secrets_length_bytes = capture_file.read(4)
                    if len(secrets_length_bytes) != 4:
                        return reject(
                            f"decryption secrets block at offset {offset} has a truncated secrets length"
                        )
                    secrets_length = struct.unpack(
                        endian + "I", secrets_length_bytes
                    )[0]
                    padded_secrets_length = secrets_length + (
                        -secrets_length % 4
                    )
                    options_start = offset + 16 + padded_secrets_length
                    if options_start > block_end - 4:
                        return reject(
                            f"decryption secrets block at offset {offset} has secrets data exceeding its block boundary"
                        )
                    padding_problem = alignment_padding_error(
                        offset + 16,
                        secrets_length,
                        padded_secrets_length,
                        f"decryption secrets data in block at offset {offset}",
                    )
                    if padding_problem is not None:
                        return reject(padding_problem)

                if options_start is not None:
                    options_end = block_end - 4
                    invalid_options = option_error(
                        options_start, options_end, block_type_value
                    )
                    if invalid_options is not None:
                        return reject(
                            f"invalid options in block at offset {offset}: {invalid_options}"
                        )

                capture_file.seek(block_end - 4)
                trailing_length = capture_file.read(4)
                if len(trailing_length) != 4:
                    return reject(f"block at offset {offset} has no trailing length")
                if struct.unpack(endian + "I", trailing_length)[0] != block_length:
                    return reject(
                        f"block at offset {offset} has a mismatched trailing length"
                    )

                if block_type_value == 1:
                    if interface_snaplen is None:
                        return reject(
                            f"interface description block at offset {offset} has no snaplen"
                        )
                    interface_snaplens.append(interface_snaplen)
                    interface_count += 1
                offset = block_end
    except OSError as exc:
        parser_logger.error("Unable to validate PCAPNG structure in %s: %s", path, exc)
        return False

    if offset != file_size:
        return reject("capture scan did not end at the file boundary")
    if section_end_offset is not None and section_end_offset != file_size:
        return reject(
            f"final section ends at {section_end_offset}, not end of file {file_size}"
        )
    return True


def validate_file(filepath: str) -> bool:
    """
    Perform a lightweight PCAP/PCAPNG preflight check before processing.

    The capture signature is authoritative; the file extension is advisory.
    This catches obviously wrong inputs without loading the capture into memory,
    but does not replace Scapy's structural parsing and corruption checks.
    """
    path = Path(filepath)
    try:
        file_size = path.stat().st_size
        if file_size == 0:
            parser_logger.error("File is empty: %s", filepath)
            return False
        with path.open("rb") as capture_file:
            signature = capture_file.read(4)
    except OSError as exc:
        parser_logger.error("Unable to access capture file %s: %s", filepath, exc)
        return False

    if signature not in _PCAP_MAGIC_NUMBERS:
        parser_logger.error(
            "File does not have a recognized PCAP/PCAPNG signature: %s",
            filepath,
        )
        return False

    if signature == _PCAPNG_MAGIC and not _validate_pcapng_block_framing(
        path, file_size
    ):
        return False

    if path.suffix.lower() not in {".pcap", ".pcapng"}:
        parser_logger.warning(
            "File extension may not be standard PCAP format: %s",
            filepath,
        )

    return True


def extract_ssid(packet) -> str:
    """
    Extract SSID from 802.11 management frames.

    Args:
        packet: Scapy packet object

    Returns:
        str: SSID name or "Hidden or Unknown"
    """
    if packet.haslayer(Dot11Elt):
        elt = packet[Dot11Elt]
        while isinstance(elt, Dot11Elt):
            if elt.ID == 0:  # SSID element
                if elt.info and len(elt.info) > 0:
                    try:
                        return elt.info.decode('utf-8', errors='ignore').strip()
                    except (UnicodeDecodeError, AttributeError):
                        return "Hidden or Unknown"
            elt = elt.payload
    return "Hidden or Unknown"


def extract_channel(packet) -> str:
    """
    Extract channel from 802.11 packets.

    Args:
        packet: Scapy packet object

    Returns:
        str: Channel number or empty string
    """
    if packet.haslayer(Dot11Elt):
        elt = packet[Dot11Elt]
        while isinstance(elt, Dot11Elt):
            if elt.ID == 3:  # DS Parameter set (contains channel)
                if elt.info:
                    return str(elt.info[0])
            elt = elt.payload
    return ""


def extract_encryption(packet) -> str:
    """
    Extract encryption type from 802.11 packets.

    Args:
        packet: Scapy packet object

    Returns:
        str: Encryption type (WPA2, WPA, WEP, Open)
    """
    encryption = []

    if packet.haslayer(Dot11Elt):
        elt = packet[Dot11Elt]
        while isinstance(elt, Dot11Elt):
            # RSN Information (WPA2)
            if elt.ID == 48:
                encryption.append("WPA2")
            # WPA Information
            elif elt.ID == 221:
                try:
                    if b'\x00P\xf2' in bytes(elt.info):  # WPA OUI
                        encryption.append("WPA")
                except Exception:
                    pass
            elt = elt.payload

    # Check privacy bit in frame control
    if hasattr(packet, 'Dot11') and packet[Dot11].FCfield & 0x40:
        if not encryption:  # If no WPA/WPA2 found but privacy bit is set
            encryption.append("WEP")

    return "/".join(encryption) if encryption else "Open"


def detect_pmkid(packet) -> str | None:
    """
    Extract a PMKID from an RSN PMKID KDE in an EAPOL-Key frame.

    The KDE is encoded as 0xdd, length 0x14, OUI 00:0f:ac, type 0x04,
    followed by the 16-byte PMKID. Scanning for the complete marker avoids
    treating unrelated key-data bytes as a PMKID.
    """
    if not packet.haslayer(EAPOL_KEY):
        return None

    try:
        key_data = bytes(packet[EAPOL_KEY].key_data or b"")
    except (AttributeError, TypeError, ValueError):
        return None

    marker = b"\xdd\x14\x00\x0f\xac\x04"
    offset = key_data.find(marker)
    if offset < 0:
        return None

    start = offset + len(marker)
    pmkid = key_data[start:start + 16]
    return pmkid.hex() if len(pmkid) == 16 else None


def is_complete_handshake(eapol_packets) -> bool:
    """
    Return True only when all four distinct EAPOL-Key handshake messages exist.

    Scapy exposes the individual Key Information flags on EAPOL_KEY, not on the
    EAPOL header. Use its key-number helper rather than testing unrelated bits
    of the header or counting arbitrary combinations of flag bits.
    """
    message_numbers: set[int] = set()
    for packet in eapol_packets:
        if not packet.haslayer(EAPOL_KEY):
            continue
        try:
            message_number = int(packet[EAPOL_KEY].guess_key_number())
        except (AttributeError, TypeError, ValueError):
            continue
        if message_number in {1, 2, 3, 4}:
            message_numbers.add(message_number)
    return message_numbers == {1, 2, 3, 4}


def _close_stream_reader(reader: PcapReader | None, filepath: str) -> None:
    """Close a streaming reader without letting cleanup errors escape parsing."""
    if reader is None:
        return
    try:
        reader.close()
    except Exception as exc:
        parser_logger.warning(
            "Failed to close streaming reader for %s: %s", filepath, exc
        )


def parse_pcap_comprehensive(filepath: str, use_streaming: bool = False) -> NetworkData:
    """
    Comprehensive PCAP parsing that extracts ALL BSSIDs, stations, and handshakes.

    Args:
        filepath: The full path to the .pcap or .pcapng file.
        use_streaming: Use streaming mode for large files (memory efficient)

    Returns:
        NetworkData object containing all BSSIDs, stations, and handshakes found.
    """
    if not validate_file(filepath):
        return NetworkData(bssids={}, stations={}, handshakes=[], total_packets=0, total_beacons=0)

    parser_logger.info(f"Starting comprehensive analysis of PCAP file: {filepath}")

    bssids: dict[str, dict[str, Any]] = {}
    stations: dict[str, dict[str, Any]] = {}
    handshake_packets: dict[str, list[tuple[int, Any]]] = {}
    handshake_captures: list[CaptureData] = []

    total_packets = 0
    total_beacons = 0

    reader: PcapReader | None = None
    try:
        if use_streaming and os.path.getsize(filepath) > 50 * 1024 * 1024:  # 50MB
            parser_logger.info("Using streaming mode for large file")
            reader = PcapReader(filepath)
            packets = reader
        else:
            packets = rdpcap(filepath)

    except Exception as e:
        parser_logger.error(f"Failed to read PCAP file {filepath} with scapy: {e}")
        return NetworkData(bssids={}, stations={}, handshakes=[], total_packets=0, total_beacons=0)

    parser_logger.info(f"Loaded packets from {filepath}")

    # Process all packets to extract comprehensive network data
    try:
        for i, packet in enumerate(packets):
            try:
                total_packets += 1

                if i % 5000 == 0 and i > 0:
                    parser_logger.info(f"Processed {i} packets...")

                # Check for management frames (beacons, probe responses)
                if packet.haslayer(Dot11):
                    dot11 = packet[Dot11]
                    bssid = dot11.addr3
                    transmitter = dot11.addr2
                    receiver = dot11.addr1

                    # Process beacon frames (all access points)
                    if packet.haslayer(Dot11Beacon):
                        total_beacons += 1
                        if bssid and bssid != "ff:ff:ff:ff:ff:ff":
                            ssid = extract_ssid(packet)
                            channel = extract_channel(packet)
                            encryption = extract_encryption(packet)

                            if bssid not in bssids:
                                bssids[bssid] = {
                                    'bssid': bssid,
                                    'essid': ssid,
                                    'channel': channel,
                                    'encryption': encryption,
                                    'first_seen': i,
                                    'last_seen': i,
                                    'beacons': 1,
                                    'packets': 1
                                }
                            else:
                                bssids[bssid]['last_seen'] = i
                                bssids[bssid]['beacons'] += 1
                                bssids[bssid]['packets'] += 1
                                # Update SSID if we found a better one
                                if ssid != "Hidden or Unknown" and bssids[bssid]['essid'] == "Hidden or Unknown":
                                    bssids[bssid]['essid'] = ssid

                    # Process probe responses
                    elif packet.haslayer(Dot11ProbeResp):
                        if bssid and bssid != "ff:ff:ff:ff:ff:ff":
                            ssid = extract_ssid(packet)
                            channel = extract_channel(packet)
                            encryption = extract_encryption(packet)

                            if bssid not in bssids:
                                bssids[bssid] = {
                                    'bssid': bssid,
                                    'essid': ssid,
                                    'channel': channel,
                                    'encryption': encryption,
                                    'first_seen': i,
                                    'last_seen': i,
                                    'beacons': 0,
                                    'packets': 1
                                }
                            else:
                                bssids[bssid]['last_seen'] = i
                                bssids[bssid]['packets'] += 1

                    # Track stations (clients) from data frames
                    if dot11.type == 2:  # Data frames
                        if transmitter and transmitter != "ff:ff:ff:ff:ff:ff" and not transmitter.startswith("01:00:5e"):
                            # This is likely a station
                            if transmitter not in stations:
                                stations[transmitter] = {
                                    'station_mac': transmitter,
                                    'associated_bssid': bssid,
                                    'first_seen': i,
                                    'last_seen': i,
                                    'packets': 1
                                }
                            else:
                                stations[transmitter]['last_seen'] = i
                                stations[transmitter]['packets'] += 1

                    # Check for EAPOL packets (WPA handshakes) - your existing handshake logic
                    if packet.haslayer(EAPOL) and bssid and bssid != "ff:ff:ff:ff:ff:ff":
                        client_mac = receiver if receiver != bssid else transmitter

                        if bssid not in handshake_packets:
                            handshake_packets[bssid] = []
                        handshake_packets[bssid].append((i, packet))

                        # Extract SSID for this BSSID if not already known
                        if bssid not in bssids:
                            ssid = extract_ssid(packet)
                            bssids[bssid] = {
                                'bssid': bssid,
                                'essid': ssid,
                                'channel': '',
                                'encryption': '',
                                'first_seen': i,
                                'last_seen': i,
                                'beacons': 0,
                                'packets': 1
                            }

            except Exception as e:
                parser_logger.warning(f"Error processing packet {i}: {e}. Skipping.", exc_info=False)
                continue
    except Exception as e:
        parser_logger.error(
            "Failed while iterating PCAP file %s with scapy: %s",
            filepath,
            e,
        )
        return NetworkData(
            bssids={}, stations={}, handshakes=[], total_packets=0, total_beacons=0
        )
    finally:
        _close_stream_reader(reader, filepath)

    # Process handshake data (your existing logic)
    parser_logger.info("Analyzing collected handshake data...")

    for bssid, packet_records in handshake_packets.items():
        try:
            ssid = bssids.get(bssid, {}).get('essid', "Hidden or Unknown")
            client_mac = None

            # Find a client MAC from the handshake packets
            for _packet_idx, packet in packet_records[:5]:  # Check first few EAPOL packets
                if packet and packet.haslayer(Dot11):
                    dot11 = packet[Dot11]
                    if dot11.addr1 != bssid and dot11.addr1 != "ff:ff:ff:ff:ff:ff":
                        client_mac = dot11.addr1
                        break
                    elif dot11.addr2 != bssid and dot11.addr2 != "ff:ff:ff:ff:ff:ff":
                        client_mac = dot11.addr2
                        break

            # Use actual EAPOL key-flag validation instead of naive packet count
            eapol_pkts = [packet for _packet_idx, packet in packet_records]
            handshake_complete = is_complete_handshake(eapol_pkts)
            pmkid = None

            # Check for PMKID in the first handshake packet
            if packet_records:
                first_packet_idx, first_packet = packet_records[0]
                if first_packet:
                    pmkid = detect_pmkid(first_packet)

            # Determine capture type
            if pmkid:
                capture_type = "PMKID"
            elif handshake_complete:
                capture_type = "WPA Handshake (Complete)"
            else:
                capture_type = "WPA Handshake (Partial)"

            # Create capture data object
            capture = CaptureData(
                type=capture_type,
                bssid=bssid,
                ssid=ssid,
                packet_index=packet_records[0][0],
                source_file=filepath,
                raw_data_present=True,
                client_mac=client_mac,
                handshake_complete=handshake_complete,
                pmkid=pmkid
            )

            handshake_captures.append(capture)
            parser_logger.info(f"Found {capture_type} for BSSID: {bssid} (SSID: {ssid})")

        except Exception as e:
            parser_logger.warning(f"Error analyzing handshake for BSSID {bssid}: {e}")
            continue

    # Close reader if we used streaming mode
    # (No longer needed since we collect into list, but kept for safety)

    parser_logger.info(
        f"Comprehensive analysis complete: {len(bssids)} BSSIDs, "
        f"{len(stations)} stations, {len(handshake_captures)} handshakes, "
        f"{total_packets} total packets, {total_beacons} beacons"
    )

    return NetworkData(
        bssids=bssids,
        stations=stations,
        handshakes=handshake_captures,
        total_packets=total_packets,
        total_beacons=total_beacons
    )


def parse_pcap(filepath: str, use_streaming: bool = False) -> list[CaptureData]:
    """
    Parses a PCAP file to extract captured Wi-Fi handshakes (WPA 4-way) or PMKIDs.

    This function relies on the 'scapy' library to read and process raw 802.11 frames
    from the capture file.

    Args:
        filepath: The full path to the .pcap or .pcapng file.
        use_streaming: Use streaming mode for large files (memory efficient)

    Returns:
        A list of CaptureData objects, where each object represents a unique,
        extractable capture (handshake or PMKID). Returns an empty list if
        the file is not found or no valid captures are found.
    """
    if not validate_file(filepath):
        return []

    parser_logger.info(f"Starting analysis of PCAP file: {filepath}")

    captures: list[CaptureData] = []

    # Use dictionaries to track unique BSSIDs and their associated packets
    handshake_packets: dict[str, list[tuple[int, Any]]] = {}
    bssid_ssid_map: dict[str, str] = {}
    bssid_client_map: dict[str, str] = {}

    reader: PcapReader | None = None
    try:
        if use_streaming and os.path.getsize(filepath) > 50 * 1024 * 1024:  # 50MB
            parser_logger.info("Using streaming mode for large file")
            reader = PcapReader(filepath)
            packets = reader
        else:
            packets = rdpcap(filepath)

    except Exception as e:
        parser_logger.error(f"Failed to read PCAP file {filepath} with scapy: {e}")
        return []

    parser_logger.info(f"Loaded packets from {filepath}")

    # First pass: Collect all potential handshake packets and map BSSIDs to SSIDs
    try:
        for i, packet in enumerate(packets):
            try:
                if i % 5000 == 0 and i > 0:
                    parser_logger.info(f"Processed {i} packets...")

                # Check for EAPOL packets (WPA handshakes)
                if packet.haslayer(EAPOL) and packet.haslayer(Dot11):
                    bssid = packet[Dot11].addr3
                    client_mac = packet[Dot11].addr1  # Typically client MAC

                    if bssid and bssid != "ff:ff:ff:ff:ff:ff":
                        # Store handshake packet index
                        if bssid not in handshake_packets:
                            handshake_packets[bssid] = []
                        handshake_packets[bssid].append((i, packet))

                        # Map client MAC to BSSID
                        if bssid not in bssid_client_map and client_mac != bssid:
                            bssid_client_map[bssid] = client_mac

                        # Extract and store SSID if available
                        if bssid not in bssid_ssid_map:
                            ssid = extract_ssid(packet)
                            if ssid != "Hidden or Unknown":
                                bssid_ssid_map[bssid] = ssid

            except Exception as e:
                parser_logger.warning(f"Error processing packet {i}: {e}. Skipping.", exc_info=False)
                continue
    except Exception as e:
        parser_logger.error(
            "Failed while iterating PCAP file %s with scapy: %s",
            filepath,
            e,
        )
        return []
    finally:
        _close_stream_reader(reader, filepath)

    # Second pass: Analyze collected handshakes and check for PMKIDs
    parser_logger.info("Analyzing collected handshake data...")

    for bssid, packet_records in handshake_packets.items():
        try:
            # Get SSID for this BSSID
            ssid = bssid_ssid_map.get(bssid, "Hidden or Unknown")
            client_mac = bssid_client_map.get(bssid, "Unknown")

            # Use actual EAPOL key-flag validation instead of naive packet count
            eapol_pkts = [packet for _packet_idx, packet in packet_records]
            handshake_complete = is_complete_handshake(eapol_pkts)

            # Check for PMKID in the first handshake packet
            pmkid = None
            first_packet_idx, first_packet = packet_records[0]

            if first_packet:
                pmkid = detect_pmkid(first_packet)

            # Determine capture type
            if pmkid:
                capture_type = "PMKID"
            elif handshake_complete:
                capture_type = "WPA Handshake (Complete)"
            else:
                capture_type = "WPA Handshake (Partial)"

            # Create capture data object
            capture = CaptureData(
                type=capture_type,
                bssid=bssid,
                ssid=ssid,
                packet_index=packet_records[0][0],  # Original packet index
                source_file=filepath,
                raw_data_present=True,
                client_mac=client_mac if client_mac != "Unknown" else None,
                handshake_complete=handshake_complete,
                pmkid=pmkid
            )

            captures.append(capture)
            parser_logger.info(f"Found {capture_type} for BSSID: {bssid} (SSID: {ssid})")

        except Exception as e:
            parser_logger.warning(f"Error analyzing handshake for BSSID {bssid}: {e}")
            continue

    # Close reader if we used streaming mode
    # (No longer needed since we collect into list, but kept for safety)

    parser_logger.info(f"Finished parsing {filepath}. Found {len(captures)} unique valid captures.")
    return captures


def parse_pcap_large(filepath: str) -> list[CaptureData]:
    """
    Wrapper function specifically for large PCAP files using streaming mode.

    Args:
        filepath: Path to the PCAP file

    Returns:
        List of CaptureData objects
    """
    return parse_pcap(filepath, use_streaming=True)


def _write_private_text(path: str | Path, text: str) -> None:
    """Atomically write a private export without following an existing symlink."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        # os.replace replaces a destination symlink itself rather than opening
        # and following its target. The temporary file is owner-only throughout.
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def export_to_hashcat(captures: list[CaptureData], output_dir: str = ".") -> dict[str, str]:
    """
    Export captured data to formats compatible with hashcat.

    Args:
        captures: List of CaptureData objects
        output_dir: Output directory for hash files

    Returns:
        Dictionary mapping output types to file paths
    """
    output_files = {}

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Keep the legacy mode-16800 export for backwards compatibility.
    # Mode 16800 is deprecated in favor of Hashcat's 22000 format.
    pmkid_entries_16800 = []
    pmkid_entries_22000 = []
    for capture in captures:
        if capture.pmkid:
            pmkid_clean = str(capture.pmkid).strip().lower()
            if len(pmkid_clean) != 32 or any(
                char not in "0123456789abcdef" for char in pmkid_clean
            ):
                parser_logger.warning(
                    "Skipping PMKID export for %s: PMKID must be 16 bytes of hexadecimal data",
                    capture.bssid,
                )
                continue

            ssid = (capture.ssid or "").strip()
            if not ssid or ssid.casefold() in {"hidden or unknown", "unknown", "<hidden>", "--"}:
                parser_logger.warning(
                    "Skipping PMKID export for %s: a known SSID is required for Hashcat input",
                    capture.bssid,
                )
                continue

            def clean_mac(value: str | None) -> str | None:
                if not value:
                    return None
                normalized = value.strip().replace(':', '').replace('-', '').replace('.', '')
                if len(normalized) != 12 or any(
                    char not in "0123456789abcdefABCDEF" for char in normalized
                ):
                    return None
                return normalized.lower()

            bssid_clean = clean_mac(capture.bssid)
            client_clean = clean_mac(capture.client_mac)
            if bssid_clean is None or client_clean is None:
                parser_logger.warning(
                    "Skipping PMKID export for %s: valid AP and client MACs are required",
                    capture.bssid,
                )
                continue

            ssid_hex = ssid.encode('utf-8', errors='ignore').hex()
            pmkid_entries_16800.append(
                f"{pmkid_clean}*{bssid_clean}*{client_clean}*{ssid_hex}"
            )
            # Hashcat 22000 PMKID format has empty ANONCE and EAPOL fields,
            # represented by the required three trailing separators.
            pmkid_entries_22000.append(
                f"WPA*01*{pmkid_clean}*{bssid_clean}*{client_clean}*{ssid_hex}***"
            )

    if pmkid_entries_16800:
        pmkid_file = os.path.join(output_dir, "pmkid_hashes.txt")
        _write_private_text(pmkid_file, '\n'.join(pmkid_entries_16800) + '\n')
        # Preserve the existing key for callers relying on the legacy export.
        output_files['pmkid'] = pmkid_file
        output_files['pmkid_16800'] = pmkid_file
        parser_logger.info("Exported %d legacy mode-16800 PMKIDs to %s", len(pmkid_entries_16800), pmkid_file)

        pmkid_22000_file = os.path.join(output_dir, "pmkid_hashes.hc22000")
        _write_private_text(pmkid_22000_file, '\n'.join(pmkid_entries_22000) + '\n')
        output_files['pmkid_22000'] = pmkid_22000_file
        parser_logger.info("Exported %d mode-22000 PMKIDs to %s", len(pmkid_entries_22000), pmkid_22000_file)

    # This parser does not retain the raw EAPOL/nonce data needed to construct
    # a valid WPA*02* Hashcat record. Keep this as human-readable metadata only.
    handshake_info_entries = [
        f"Handshake for {capture.bssid} (SSID: {capture.ssid})"
        for capture in captures
        if capture.handshake_complete and not capture.pmkid
    ]

    if handshake_info_entries:
        handshake_file = os.path.join(output_dir, "handshake_info.txt")
        _write_private_text(handshake_file, '\n'.join(handshake_info_entries) + '\n')
        # Legacy key retained for backwards compatibility; this file is not a
        # Hashcat hash file because the source model lacks raw EAPOL data.
        output_files['handshake'] = handshake_file
        output_files['handshake_info'] = handshake_file
        parser_logger.info(
            "Exported %d handshake metadata entries (not crackable hashes) to %s",
            len(handshake_info_entries),
            handshake_file,
        )

    return output_files


# Example usage and testing
if __name__ == '__main__':
    parser_logger.info("PCAP Parser Module - Test Mode")

    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        if validate_file(test_file):
            # Test comprehensive parsing
            parser_logger.info("=== Testing Comprehensive Parsing ===")
            network_data = parse_pcap_comprehensive(test_file)
            parser_logger.info(f"Found {len(network_data.bssids)} BSSIDs, {len(network_data.stations)} stations, {len(network_data.handshakes)} handshakes")

            # Test original parsing for backward compatibility
            parser_logger.info("=== Testing Original Parsing ===")
            captures = parse_pcap(test_file)
            parser_logger.info(f"Found {len(captures)} captures:")
            for i, capture in enumerate(captures):
                parser_logger.info(f"  {i+1}. {capture.type} - BSSID: {capture.bssid} - SSID: {capture.ssid}")

            # Export to hashcat format if any captures found
            if captures:
                export_to_hashcat(captures, "hashcat_output")
        else:
            parser_logger.error("Invalid file provided")
    else:
        parser_logger.info("Usage: python pcap_parser.py <pcap_file>")
        parser_logger.info("This module is intended to be imported. Requires 'scapy' and a .pcap file to test fully.")
