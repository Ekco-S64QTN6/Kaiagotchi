"""Synthetic regression tests for lightweight PCAP signature validation."""

import logging

import pytest

from kaiagotchi.network.pcap_parser import validate_file


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
