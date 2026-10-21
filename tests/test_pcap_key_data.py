"""Regression tests for Scapy EAPOL-Key parsing."""

from scapy.layers.eap import EAPOL_KEY

from kaiagotchi.network.pcap_parser import detect_pmkid, is_complete_handshake


def test_detect_pmkid_from_standard_kde():
    pmkid = bytes.fromhex("fe e1 4a 3c f8 09 e0 2e 78 f3 58 1c 07 73 b3 0a")
    packet = EAPOL_KEY(key_data=b"\x01\x02\xdd\x14\x00\x0f\xac\x04" + pmkid)
    assert detect_pmkid(packet) == pmkid.hex()


def test_detect_pmkid_ignores_unrelated_key_data():
    packet = EAPOL_KEY(key_data=b"\x00\x00" + bytes(range(20)))
    assert detect_pmkid(packet) is None


def test_detect_pmkid_rejects_truncated_kde():
    packet = EAPOL_KEY(key_data=b"\xdd\x14\x00\x0f\xac\x04short")
    assert detect_pmkid(packet) is None


def test_complete_handshake_requires_all_four_messages():
    message_1 = EAPOL_KEY(key_type=1, key_ack=1, has_key_mic=0, install=0, secure=0)
    message_2 = EAPOL_KEY(key_type=1, key_ack=0, has_key_mic=1, install=0, secure=0)
    message_3 = EAPOL_KEY(key_type=1, key_ack=1, has_key_mic=1, install=1, secure=1)
    message_4 = EAPOL_KEY(key_type=1, key_ack=0, has_key_mic=1, install=0, secure=1)

    assert is_complete_handshake([message_1, message_2, message_3, message_4])
    assert not is_complete_handshake([message_1, message_2, message_3, message_3])
    assert not is_complete_handshake([message_1, message_2, message_3])
