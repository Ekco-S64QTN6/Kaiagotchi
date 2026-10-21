# kaiagotchi/network/pcap_parser.py
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from scapy.all import (
    EAPOL,
    EAPOL_KEY,
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    Dot11ProbeResp,
    PcapReader,
    rdpcap,
)

# Configure logging for the module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
parser_logger = logging.getLogger('pcap_parser')


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


def validate_file(filepath: str) -> bool:
    """
    Validate PCAP file before processing.

    Args:
        filepath: Path to the PCAP file

    Returns:
        bool: True if file is valid, False otherwise
    """
    if not os.path.exists(filepath):
        parser_logger.error(f"File not found: {filepath}")
        return False

    if os.path.getsize(filepath) == 0:
        parser_logger.error("File is empty")
        return False

    if not filepath.lower().endswith(('.pcap', '.pcapng')):
        parser_logger.warning("File extension may not be standard PCAP format")

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

    marker = b"\\xdd\\x14\\x00\\x0f\\xac\\x04"
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
    handshake_packets: dict[str, list[int]] = {}
    handshake_captures: list[CaptureData] = []

    total_packets = 0
    total_beacons = 0

    try:
        if use_streaming and os.path.getsize(filepath) > 50 * 1024 * 1024:  # 50MB
            parser_logger.info("Using streaming mode for large file")
            packets = list(PcapReader(filepath))
        else:
            packets = rdpcap(filepath)

    except Exception as e:
        parser_logger.error(f"Failed to read PCAP file {filepath} with scapy: {e}")
        return NetworkData(bssids={}, stations={}, handshakes=[], total_packets=0, total_beacons=0)

    parser_logger.info(f"Loaded packets from {filepath}")

    # Process all packets to extract comprehensive network data
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
                    handshake_packets[bssid].append(i)

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

    # Process handshake data (your existing logic)
    parser_logger.info("Analyzing collected handshake data...")

    for bssid, packet_indices in handshake_packets.items():
        try:
            ssid = bssids.get(bssid, {}).get('essid', "Hidden or Unknown")
            client_mac = None

            # Find a client MAC from the handshake packets
            for packet_idx in packet_indices[:5]:  # Check first few packets
                packet = packets[packet_idx] if hasattr(packets, '__getitem__') else None
                if packet and packet.haslayer(Dot11):
                    dot11 = packet[Dot11]
                    if dot11.addr1 != bssid and dot11.addr1 != "ff:ff:ff:ff:ff:ff":
                        client_mac = dot11.addr1
                        break
                    elif dot11.addr2 != bssid and dot11.addr2 != "ff:ff:ff:ff:ff:ff":
                        client_mac = dot11.addr2
                        break

            # Use actual EAPOL key-flag validation instead of naive packet count
            eapol_pkts = [packets[idx] for idx in packet_indices if idx < len(packets)]
            handshake_complete = is_complete_handshake(eapol_pkts)
            pmkid = None

            # Check for PMKID in the first handshake packet
            if packet_indices:
                first_packet_idx = packet_indices[0]
                first_packet = packets[first_packet_idx] if hasattr(packets, '__getitem__') else None
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
                packet_index=packet_indices[0],
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
    handshake_packets: dict[str, list[int]] = {}
    bssid_ssid_map: dict[str, str] = {}
    bssid_client_map: dict[str, str] = {}

    try:
        if use_streaming and os.path.getsize(filepath) > 50 * 1024 * 1024:  # 50MB
            parser_logger.info("Using streaming mode for large file")
            packets = list(PcapReader(filepath))
        else:
            packets = rdpcap(filepath)

    except Exception as e:
        parser_logger.error(f"Failed to read PCAP file {filepath} with scapy: {e}")
        return []

    parser_logger.info(f"Loaded packets from {filepath}")

    # First pass: Collect all potential handshake packets and map BSSIDs to SSIDs
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
                    handshake_packets[bssid].append(i)

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

    # Second pass: Analyze collected handshakes and check for PMKIDs
    parser_logger.info("Analyzing collected handshake data...")

    for bssid, packet_indices in handshake_packets.items():
        try:
            # Get SSID for this BSSID
            ssid = bssid_ssid_map.get(bssid, "Hidden or Unknown")
            client_mac = bssid_client_map.get(bssid, "Unknown")

            # Use actual EAPOL key-flag validation instead of naive packet count
            eapol_pkts = [packets[idx] for idx in packet_indices if idx < len(packets)]
            handshake_complete = is_complete_handshake(eapol_pkts)

            # Check for PMKID in the first handshake packet
            pmkid = None
            first_packet_idx = packet_indices[0]
            first_packet = packets[first_packet_idx] if hasattr(packets, '__getitem__') else None

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
                packet_index=packet_indices[0],  # Reference to first packet
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

    # Export PMKIDs for hashcat mode 16800
    pmkid_entries = []
    for capture in captures:
        if capture.pmkid:
            bssid_clean = capture.bssid.replace(':', '') if capture.bssid else 'ffffffffffff'
            client_clean = capture.client_mac.replace(':', '') if capture.client_mac else 'ffffffffffff'
            ssid_hex = capture.ssid.encode('utf-8', errors='ignore').hex() if capture.ssid else ''
            entry = f"{capture.pmkid}*{bssid_clean}*{client_clean}*{ssid_hex}"
            pmkid_entries.append(entry)

    if pmkid_entries:
        pmkid_file = os.path.join(output_dir, "pmkid_hashes.txt")
        with open(pmkid_file, 'w') as f:
            f.write('\n'.join(pmkid_entries))
        output_files['pmkid'] = pmkid_file
        parser_logger.info(f"Exported {len(pmkid_entries)} PMKID hashes to {pmkid_file}")

    # Export handshakes for hashcat mode 22000 (could be enhanced with actual packet data)
    handshake_entries = []
    for capture in captures:
        if capture.handshake_complete and not capture.pmkid:
            # Note: This would need actual EAPOL message extraction for full hashcat support
            handshake_entries.append(f"Handshake for {capture.bssid} (SSID: {capture.ssid})")

    if handshake_entries:
        handshake_file = os.path.join(output_dir, "handshake_info.txt")
        with open(handshake_file, 'w') as f:
            f.write('\n'.join(handshake_entries))
        output_files['handshake'] = handshake_file
        parser_logger.info(f"Exported {len(handshake_entries)} handshake info entries to {handshake_file}")

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
