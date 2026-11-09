from __future__ import annotations

import struct

import pytest
from scapy.layers.dot11 import Dot11
from scapy.layers.eap import EAPOL
from scapy.layers.l2 import LLC, SNAP
from scapy.utils import PcapWriter

from kaiagotchi.core.utils import extract_from_pcap

BSSID = "02:11:22:33:44:55"
CLIENT = "06:aa:bb:cc:dd:ee"


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        pytest.param("empty.pcap", b"", id="empty-file"),
        pytest.param("malformed.pcap", b"not a capture", id="malformed-file"),
        pytest.param(
            "truncated.pcap",
            bytes.fromhex("d4 c3 b2 a1"),
            id="truncated-classic-header",
        ),
    ],
)
def test_extract_from_pcap_reports_no_capture_for_invalid_files(tmp_path, filename, payload):
    capture = tmp_path / filename
    capture.write_bytes(payload)

    result = extract_from_pcap(str(capture))

    assert result == {
        "bssid": None,
        "essid": None,
        "handshake": False,
        "handshake_complete": False,
        "capture_type": None,
        "client_mac": None,
        "pmkid": None,
        "capture_count": 0,
    }


def test_extract_from_pcap_reports_no_capture_for_missing_file(tmp_path):
    result = extract_from_pcap(str(tmp_path / "missing.pcap"))

    assert result["bssid"] is None
    assert result["essid"] is None
    assert result["handshake"] is False
    assert result["capture_count"] == 0


def test_extract_from_pcap_returns_real_fields_for_synthetic_partial_handshake(tmp_path):
    capture_path = tmp_path / "synthetic-eapol.pcap"
    packet = (
        Dot11(
            type=2,
            FCfield=0x01,  # station-to-AP / ToDS
            addr1=BSSID,
            addr2=CLIENT,
            addr3=BSSID,
        )
        / LLC()
        / SNAP(code=0x888E)
        / EAPOL()
    )
    writer = PcapWriter(str(capture_path), linktype=105, sync=True)
    writer.write(packet)
    writer.close()

    result = extract_from_pcap(str(capture_path))

    assert result["bssid"] == BSSID
    assert result["client_mac"] == CLIENT
    assert result["capture_type"] == "WPA Handshake (Partial)"
    assert result["handshake"] is False
    assert result["handshake_complete"] is False
    assert result["pmkid"] is None
    assert result["capture_count"] == 1


def test_extract_from_pcap_does_not_invent_a_handshake_for_valid_empty_pcapng(tmp_path):
    capture_path = tmp_path / "empty-section.pcapng"
    capture_path.write_bytes(
        bytes.fromhex("0a 0d 0d 0a")
        + struct.pack("<I", 28)
        + bytes.fromhex("4d 3c 2b 1a")
        + struct.pack("<HHq", 1, 0, -1)
        + struct.pack("<I", 28)
    )

    result = extract_from_pcap(str(capture_path))

    assert result["bssid"] is None
    assert result["handshake"] is False
    assert result["capture_count"] == 0
