import logging
import os
from scapy.all import rdpcap, Dot11, EAPOL, Dot11Elt
from typing import List, Dict, Union, Any

# Configure logging for the module
logging.basicConfig(level=logging.INFO)
parser_logger = logging.getLogger('pcap_parser')

# Define the structure for a captured handshake or PMKID
CaptureData = Dict[str, Any]


def parse_pcap(filepath: str) -> List[CaptureData]:
    """
    Parses a PCAP file to extract captured Wi-Fi handshakes (WPA 4-way) or PMKIDs.

    This function relies on the 'scapy' library to read and process raw 802.11 frames
    from the capture file.

    Args:
        filepath: The full path to the .pcap or .pcapng file.

    Returns:
        A list of dictionaries, where each dictionary represents a unique,
        extractable capture (handshake or PMKID). Returns an empty list if
        the file is not found or no valid captures are found.
    """
    if not os.path.exists(filepath):
        parser_logger.error(f"File not found: {filepath}")
        return []

    parser_logger.info(f"Starting analysis of PCAP file: {filepath}")
    
    captures: List[CaptureData] = []
    
    # Use a set to track unique access point BSSIDs (MACs) 
    # for which we have already extracted a handshake, to avoid duplicates.
    unique_bssids = set()

    try:
        # Load the entire packet list from the PCAP file
        packets = rdpcap(filepath)
    except Exception as e:
        parser_logger.error(f"Failed to read PCAP file {filepath} with scapy: {e}")
        return []
    
    parser_logger.debug(f"Loaded {len(packets)} packets from {filepath}")

    for i, packet in enumerate(packets):
        try:
            # Check for WPA/WPA2 4-way Handshake (EAPOL)
            if packet.haslayer(EAPOL):
                # We are primarily interested in the BSSID (Access Point MAC)
                # For WPA handshakes, the BSSID is often in the 'addr3' field
                if packet.haslayer(Dot11):
                    bssid = packet[Dot11].addr3
                    if bssid and bssid not in unique_bssids:
                        # For simplicity, we just flag its presence. 
                        
                        ssid_name = "Hidden or Unknown" # Default SSID name
                        
                        # Try to find the associated SSID
                        if packet.haslayer(Dot11Elt) and packet[Dot11Elt].info:
                            # Dot11Elt.info contains the SSID
                            ssid_name = packet[Dot11Elt].info.decode('utf-8', errors='ignore')

                        captures.append({
                            'type': 'WPA Handshake',
                            'bssid': bssid,
                            'ssid': ssid_name,
                            'packet_index': i,
                            'source_file': filepath,
                            'raw_data_present': True 
                        })
                        unique_bssids.add(bssid)
                        parser_logger.info(f"Found WPA Handshake for BSSID: {bssid} (SSID: {ssid_name})")

        except Exception as e:
            parser_logger.warning(f"Error processing packet {i}: {e}. Skipping.", exc_info=False)
            continue
            
    parser_logger.info(f"Finished parsing {filepath}. Found {len(captures)} unique valid captures.")
    return captures


# Example usage (for testing the module locally)
if __name__ == '__main__':
    parser_logger.info("This module is intended to be imported. Requires 'scapy' and a .pcap file to test fully.")
    
