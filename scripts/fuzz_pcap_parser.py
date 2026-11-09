#!/usr/bin/env python3
"""Coverage-guided fuzz harness for Kaiagotchi's PCAP/PCAPNG parsers.

Install the optional dependency with:
    python -m pip install -e ".[dev,fuzz]"

Run a bounded campaign with:
    python scripts/fuzz_pcap_parser.py /tmp/kaiagotchi-pcap-corpus \
        -max_len=1048576 -atheris_runs=10000

The committed seeds are minimal synthetic file headers, never real captures.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

MAX_INPUT_BYTES = 1024 * 1024
PCAPNG_MAGIC = bytes.fromhex("0a0d0d0a")
SYNTHETIC_SEEDS = {
    # Classic PCAP, little-endian, v2.4, snaplen 65535, IEEE 802.11 link type.
    "minimal-classic.pcap": bytes.fromhex(
        "d4c3b2a1020004000000000000000000ffff000069000000"
    ),
    # PCAPNG Section Header Block, little-endian, v1.0, unspecified section length.
    "minimal-section.pcapng": bytes.fromhex(
        "0a0d0d0a1c0000004d3c2b1a01000000ffffffffffffffff1c000000"
    ),
}

Parser = Callable[[str], object]


def write_seed_corpus(corpus_dir: Path) -> list[Path]:
    """Create minimal synthetic seed files without overwriting a user's corpus."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, content in SYNTHETIC_SEEDS.items():
        seed_path = corpus_dir / filename
        if not seed_path.exists():
            seed_path.write_bytes(content)
        paths.append(seed_path)
    return paths


def make_test_one_input(
    work_dir: Path,
    parse_pcap: Parser,
    parse_pcap_comprehensive: Parser,
) -> Callable[[bytes], None]:
    """Build an Atheris-compatible callback for both parser entry points.

    Each invocation writes only one bounded input to a temporary file. A PCAPNG
    signature gets a .pcapng suffix; all other inputs use .pcap. Parser exceptions
    are intentionally not swallowed here: an unexpected uncaught exception is a
    finding for the fuzzer to retain and minimize.
    """
    def test_one_input(data: bytes) -> None:
        if len(data) > MAX_INPUT_BYTES:
            return

        suffix = ".pcapng" if data.startswith(PCAPNG_MAGIC) else ".pcap"
        capture_path = work_dir / f"fuzz-input{suffix}"
        capture_path.write_bytes(data)
        parse_pcap(str(capture_path))
        parse_pcap_comprehensive(str(capture_path))

    return test_one_input


def main(argv: list[str] | None = None) -> None:
    """Start Atheris using the supplied corpus directory and libFuzzer flags."""
    args = list(sys.argv if argv is None else argv)
    if len(args) < 2 or args[1].startswith("-"):
        raise SystemExit(
            "usage: python scripts/fuzz_pcap_parser.py CORPUS_DIR "
            "[-max_len=1048576] [-atheris_runs=N]"
        )

    corpus_dir = Path(args[1]).expanduser().resolve()
    write_seed_corpus(corpus_dir)

    try:
        import atheris
    except ImportError as exc:
        raise SystemExit(
            'Atheris is optional; install it with: '
            'python -m pip install -e ".[dev,fuzz]"'
        ) from exc

    # Import the parser inside Atheris' instrumentation context so Python code
    # in the parser contributes coverage feedback to the mutation engine.
    with atheris.instrument_imports():
        from kaiagotchi.network.pcap_parser import (
            parse_pcap,
            parse_pcap_comprehensive,
        )

    with tempfile.TemporaryDirectory(prefix="kaiagotchi-pcap-fuzz-") as directory:
        target = make_test_one_input(
            Path(directory),
            parse_pcap,
            parse_pcap_comprehensive,
        )
        target = atheris.instrument_func(target)
        fuzzer_args = [args[0], str(corpus_dir), *args[2:]]
        atheris.Setup(fuzzer_args, target)
        atheris.Fuzz()


if __name__ == "__main__":
    main()
