import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from scapy.all import rdpcap, PcapReader, Dot11, EAPOL, Dot11Elt
import struct

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
    client_mac: Optional[str] = None
    timestamp: Optional[float] = None
    handshake_complete: bool = False
    pmkid: Optional[str] = None


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


def detect_pmkid(packet) -> Optional[str]:
    """
    Detect and extract PMKID from EAPOL frames.
    
    Args:
        packet: Scapy packet object
        
    Returns:
        Optional[str]: PMKID as hex string if found, None otherwise
    """
    if packet.haslayer(EAPOL):
        eapol = packet[EAPOL]
        
        # Check if this is a first EAPOL message (Message 1 of 4-way handshake)
        if hasattr(eapol, 'key_info') and eapol.key_info & 0x0080:  # Check for Key MIC bit
            if hasattr(eapol, 'key_data') and eapol.key_data:
                try:
                    # PMKID is typically the first 16 bytes of key_data in message 1
                    key_data = bytes(eapol.key_data)
                    if len(key_data) >= 16:
                        # Look for PMKID KDE (Key Data Encapsulation)
                        if key_data[:2] == b'\x00\x00':  # Often starts with 0x00 0x00
                            if len(key_data) >= 20:  # Minimum length for PMKID KDE
                                pmkid_data = key_data[4:20]  # Extract PMKID
                                if len(pmkid_data) == 16:
                                    return pmkid_data.hex()
                except (AttributeError, IndexError, struct.error):
                    pass
    return None


def is_complete_handshake(eapol_packets) -> bool:
    """
    Basic check for complete 4-way handshake presence.
    
    Args:
        eapol_packets: List of EAPOL packets
        
    Returns:
        bool: True if handshake appears complete
    """
    if len(eapol_packets) < 4:
        return False
        
    # Count unique message types (simplified approach)
    msg_indicators = set()
    for packet in eapol_packets:
        if packet.haslayer(EAPOL):
            eapol = packet[EAPOL]
            if hasattr(eapol, 'key_info'):
                key_info = eapol.key_info
                # Check for various handshake message indicators
                if key_info & 0x0008:  # Install flag (msg3)
                    msg_indicators.add('msg3')
                elif key_info & 0x0100:  # Secure flag (msg2)
                    msg_indicators.add('msg2')
                elif key_info & 0x0080:  # MIC flag (msg2, msg3, msg4)
                    msg_indicators.add('mic')
                    
    return len(msg_indicators) >= 3  # Should have multiple message types


def parse_pcap(filepath: str, use_streaming: bool = False) -> List[CaptureData]:
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
    
    captures: List[CaptureData] = []
    
    # Use dictionaries to track unique BSSIDs and their associated packets
    handshake_packets: Dict[str, List[int]] = {}
    bssid_ssid_map: Dict[str, str] = {}
    bssid_client_map: Dict[str, str] = {}

    try:
        if use_streaming and os.path.getsize(filepath) > 50 * 1024 * 1024:  # 50MB
            parser_logger.info("Using streaming mode for large file")
            packets_reader = PcapReader(filepath)
            packets = packets_reader
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
            
            # Check if we have enough packets for a complete handshake
            handshake_complete = len(packet_indices) >= 4
            
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
    if use_streaming and 'packets_reader' in locals():
        packets_reader.close()

    parser_logger.info(f"Finished parsing {filepath}. Found {len(captures)} unique valid captures.")
    return captures


def parse_pcap_large(filepath: str) -> List[CaptureData]:
    """
    Wrapper function specifically for large PCAP files using streaming mode.
    
    Args:
        filepath: Path to the PCAP file
        
    Returns:
        List of CaptureData objects
    """
    return parse_pcap(filepath, use_streaming=True)


def export_to_hashcat(captures: List[CaptureData], output_dir: str = ".") -> Dict[str, str]:
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
            entry = f"{capture.bssid.replace(':', '')}*{capture.client_mac.replace(':', '') if capture.client_mac else 'ffffffffffff'}*{capture.ssid}*{capture.pmkid}"
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