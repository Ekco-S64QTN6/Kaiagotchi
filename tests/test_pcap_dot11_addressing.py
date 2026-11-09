from __future__ import annotations

import pytest
from scapy.layers.dot11 import Dot11
from scapy.layers.eap import EAPOL

from kaiagotchi.network import pcap_parser

AP = "02:11:22:33:44:55"
CLIENT = "06:aa:bb:cc:dd:ee"
OTHER = "0a:12:34:56:78:90"


@pytest.mark.parametrize(
    ("fcfield", "addr1", "addr2", "addr3", "expected_bssid", "expected_client"),
    [
        pytest.param(0x01, AP, CLIENT, OTHER, AP, CLIENT, id="station-to-ap"),
        pytest.param(0x02, CLIENT, AP, OTHER, AP, CLIENT, id="ap-to-station"),
        pytest.param(0x00, OTHER, CLIENT, AP, AP, CLIENT, id="no-ds-three-address"),
    ],
)
def test_dot11_address_roles_resolve_bssid_for_each_three_address_direction(
    fcfield, addr1, addr2, addr3, expected_bssid, expected_client
):
    packet = Dot11(
        type=2,
        FCfield=fcfield,
        addr1=addr1,
        addr2=addr2,
        addr3=addr3,
    ) / EAPOL()

    assert pcap_parser._dot11_bssid_client(packet) == (expected_bssid, expected_client)


def test_dot11_wds_frame_does_not_guess_bssid_from_address_three():
    packet = Dot11(
        type=2,
        FCfield=0x03,
        addr1=OTHER,
        addr2=AP,
        addr3=CLIENT,
        addr4="0e:12:34:56:78:90",
    ) / EAPOL()

    assert pcap_parser._dot11_bssid_client(packet) == (None, None)


@pytest.mark.parametrize(
    ("fcfield", "addr1", "addr2", "addr3"),
    [
        pytest.param(0x01, AP, CLIENT, OTHER, id="station-to-ap"),
        pytest.param(0x02, CLIENT, AP, OTHER, id="ap-to-station"),
    ],
)
def test_both_parser_entry_points_group_handshake_and_station_under_real_bssid(
    tmp_path, monkeypatch, fcfield, addr1, addr2, addr3
):
    capture = tmp_path / "synthetic-eapol.pcap"
    capture.write_bytes(b"synthetic test input")
    packet = Dot11(
        type=2,
        FCfield=fcfield,
        addr1=addr1,
        addr2=addr2,
        addr3=addr3,
    ) / EAPOL()

    monkeypatch.setattr(pcap_parser, "validate_file", lambda _path: True)
    monkeypatch.setattr(pcap_parser, "rdpcap", lambda _path: [packet])

    captures = pcap_parser.parse_pcap(str(capture))
    assert len(captures) == 1
    assert captures[0].bssid == AP
    assert captures[0].client_mac == CLIENT

    network = pcap_parser.parse_pcap_comprehensive(str(capture))
    assert len(network.handshakes) == 1
    assert network.handshakes[0].bssid == AP
    assert network.stations[CLIENT]["associated_bssid"] == AP


def test_both_parser_entry_points_skip_ambiguous_wds_eapol(tmp_path, monkeypatch):
    capture = tmp_path / "synthetic-wds.pcap"
    capture.write_bytes(b"synthetic test input")
    packet = Dot11(
        type=2,
        FCfield=0x03,
        addr1=OTHER,
        addr2=AP,
        addr3=CLIENT,
        addr4="0e:12:34:56:78:90",
    ) / EAPOL()

    monkeypatch.setattr(pcap_parser, "validate_file", lambda _path: True)
    monkeypatch.setattr(pcap_parser, "rdpcap", lambda _path: [packet])

    assert pcap_parser.parse_pcap(str(capture)) == []
    network = pcap_parser.parse_pcap_comprehensive(str(capture))
    assert network.handshakes == []
    assert network.stations == {}
