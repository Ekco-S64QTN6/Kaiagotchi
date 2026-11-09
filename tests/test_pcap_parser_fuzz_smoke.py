from __future__ import annotations

from pathlib import Path

from kaiagotchi.network.pcap_parser import (
    parse_pcap,
    parse_pcap_comprehensive,
)
from scripts.fuzz_pcap_parser import (
    MAX_INPUT_BYTES,
    SYNTHETIC_SEEDS,
    make_test_one_input,
    write_seed_corpus,
)


def test_seed_corpus_contains_only_minimal_synthetic_file_headers(tmp_path):
    seeds = write_seed_corpus(tmp_path)

    assert {path.name for path in seeds} == set(SYNTHETIC_SEEDS)
    assert all(path.read_bytes() == SYNTHETIC_SEEDS[path.name] for path in seeds)
    assert len((tmp_path / "minimal-classic.pcap").read_bytes()) == 24
    assert len((tmp_path / "minimal-section.pcapng").read_bytes()) == 28


def test_seed_corpus_does_not_overwrite_existing_user_inputs(tmp_path):
    existing = tmp_path / "minimal-classic.pcap"
    existing.write_bytes(b"user corpus input")

    write_seed_corpus(tmp_path)

    assert existing.read_bytes() == b"user corpus input"


def test_fuzz_callback_invokes_both_parser_entry_points(tmp_path):
    seen_pcap: list[bytes] = []
    seen_comprehensive: list[bytes] = []

    def parse_pcap(path: str) -> object:
        seen_pcap.append(Path(path).read_bytes())
        return []

    def parse_comprehensive(path: str) -> object:
        seen_comprehensive.append(Path(path).read_bytes())
        return {}

    target = make_test_one_input(tmp_path, parse_pcap, parse_comprehensive)
    payload = SYNTHETIC_SEEDS["minimal-classic.pcap"]
    target(payload)

    assert seen_pcap == [payload]
    assert seen_comprehensive == [payload]


def test_fuzz_callback_selects_pcapng_extension_for_section_header(tmp_path):
    seen_paths: list[str] = []

    def parse(path: str) -> object:
        seen_paths.append(path)
        return None

    target = make_test_one_input(tmp_path, parse, parse)
    target(SYNTHETIC_SEEDS["minimal-section.pcapng"])

    assert len(seen_paths) == 2
    assert seen_paths[0].endswith(".pcapng")
    assert seen_paths[1] == seen_paths[0]


def test_fuzz_callback_ignores_inputs_over_the_hard_size_limit(tmp_path):
    calls: list[str] = []

    def parse(path: str) -> object:
        calls.append(path)
        return None

    target = make_test_one_input(tmp_path, parse, parse)
    target(b"x" * (MAX_INPUT_BYTES + 1))

    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_synthetic_seed_headers_are_handled_by_both_real_parser_entry_points(tmp_path):
    for filename, seed in SYNTHETIC_SEEDS.items():
        capture = tmp_path / filename
        capture.write_bytes(seed)

        assert parse_pcap(str(capture)) == []
        result = parse_pcap_comprehensive(str(capture))
        assert result.total_packets == 0
        assert result.bssids == {}
        assert result.stations == {}
        assert result.handshakes == []
