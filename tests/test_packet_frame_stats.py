"""Live packet telemetry: count 802.11 frame types and signal from a capture.

Feeds the Cyber-Deck HUD's packet panel (probe/beacon/auth/eapol RX/TX) and the
channel RSSI history, which were blank because the engine never measured them.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaiagotchi.network.pcap_parser import FrameStats, count_frame_stats

scapy_dot11 = pytest.importorskip("scapy.layers.dot11")
from scapy.layers.dot11 import (  # noqa: E402
    Dot11,
    Dot11Auth,
    Dot11Beacon,
    Dot11ProbeReq,
    RadioTap,
)
from scapy.layers.eap import EAPOL  # noqa: E402
from scapy.layers.l2 import LLC, SNAP  # noqa: E402
from scapy.utils import wrpcap  # noqa: E402

AP = "aa:bb:cc:dd:ee:ff"
CLIENT = "11:22:33:44:55:66"


def _write(path: Path, packets) -> str:
    wrpcap(str(path), packets)
    return str(path)


def test_counts_each_frame_type_and_direction(tmp_path):
    packets = [
        # Beacon from the AP (no DS bits) -> beacon, rx.
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=-40) / Dot11(type=0, subtype=8, addr2=AP, addr3=AP) / Dot11Beacon(),
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=-55) / Dot11(type=0, subtype=8, addr2=AP, addr3=AP) / Dot11Beacon(),
        # Probe request from a client -> probe_req, tx.
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=-60) / Dot11(type=0, subtype=4, addr2=CLIENT) / Dot11ProbeReq(),
        # Authentication -> auth.
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=-50) / Dot11(type=0, subtype=11, addr1=CLIENT, addr2=AP) / Dot11Auth(),
        # EAPOL key frame over a data frame -> eapol.
        RadioTap(present="dBm_AntSignal", dBm_AntSignal=-45)
        / Dot11(type=2, subtype=0, FCfield=0x02, addr1=CLIENT, addr2=AP, addr3=AP)
        / LLC() / SNAP() / EAPOL(version=2, type=3),
    ]
    stats = count_frame_stats(_write(tmp_path / "c.cap", packets))

    assert isinstance(stats, FrameStats)
    assert stats.breakdown["beacon"] == {"rx": 2, "tx": 0}
    assert stats.breakdown["probe_req"] == {"rx": 0, "tx": 1}
    assert stats.breakdown["auth"]["rx"] + stats.breakdown["auth"]["tx"] == 1
    assert stats.breakdown["eapol"] == {"rx": 1, "tx": 0}  # from-DS -> rx
    assert stats.total_rx + stats.total_tx == 5
    assert stats.max_signal == -40  # strongest (closest to zero)


def test_as_payload_shape_matches_the_frontend_contract(tmp_path):
    stats = count_frame_stats(
        _write(tmp_path / "b.cap",
               [RadioTap(present="dBm_AntSignal", dBm_AntSignal=-33) / Dot11(type=0, subtype=8, addr2=AP) / Dot11Beacon()])
    )
    payload = stats.as_payload()
    assert set(payload["packet_breakdown"]) == {"probe_req", "beacon", "auth", "eapol"}
    assert payload["total_packets"] == {"rx": 1, "tx": 0}
    assert payload["max_signal"] == -33


def test_missing_or_garbage_file_returns_empty_stats_without_raising(tmp_path):
    empty = count_frame_stats(str(tmp_path / "does-not-exist.cap"))
    assert empty.total_rx == 0 and empty.total_tx == 0 and empty.max_signal is None

    junk = tmp_path / "junk.cap"
    junk.write_bytes(b"not a pcap at all, just bytes")
    stats = count_frame_stats(str(junk))
    assert stats.total_rx == 0 and stats.total_tx == 0


def test_truncated_trailing_record_keeps_the_partial_tally(tmp_path):
    """airodump is still writing the file; a short final record must not lose
    the frames already counted."""
    good = tmp_path / "ok.cap"
    _write(good, [RadioTap(present="dBm_AntSignal", dBm_AntSignal=-40) / Dot11(type=0, subtype=8, addr2=AP) / Dot11Beacon()] * 3)
    data = good.read_bytes()
    truncated = tmp_path / "trunc.cap"
    truncated.write_bytes(data[:-8])  # cut the last record short
    stats = count_frame_stats(str(truncated))
    assert stats.breakdown["beacon"]["rx"] >= 2  # the whole records survived


# ── CaptureFrameCounter: incremental reads over a growing capture ──────────
from kaiagotchi.network.pcap_parser import CaptureFrameCounter  # noqa: E402


def _beacon():
    return RadioTap(present="dBm_AntSignal", dBm_AntSignal=-42) / Dot11(type=0, subtype=8, addr2=AP, addr3=AP) / Dot11Beacon()


def test_counter_tallies_only_frames_appended_since_the_last_update(tmp_path):
    p = tmp_path / "capture-01.cap"
    wrpcap(str(p), [_beacon()] * 3)
    c = CaptureFrameCounter()
    first = c.update(str(p))
    assert first.total_rx == 3

    wrpcap(str(p), [_beacon()] * 2, append=True)  # two more records appended
    second = c.update(str(p))
    assert second.total_rx == 5  # cumulative, not re-counted from zero
    assert second.breakdown["beacon"]["rx"] == 5


def test_counter_returns_independent_snapshots_so_callers_can_diff(tmp_path):
    p = tmp_path / "capture-01.cap"
    wrpcap(str(p), [_beacon()] * 4)
    c = CaptureFrameCounter()
    a = c.update(str(p))
    wrpcap(str(p), [_beacon()] * 3, append=True)
    b = c.update(str(p))
    assert a.total_rx == 4 and b.total_rx == 7  # `a` was not mutated by the second update


def test_counter_resets_on_a_rotated_or_truncated_capture(tmp_path):
    p = tmp_path / "capture-01.cap"
    wrpcap(str(p), [_beacon()] * 10)
    c = CaptureFrameCounter()
    assert c.update(str(p)).total_rx == 10
    wrpcap(str(p), [_beacon()] * 2)  # rewritten smaller -> rotation
    assert c.update(str(p)).total_rx == 2


def test_counter_is_incremental_not_order_n_of_the_whole_file(tmp_path):
    import time
    p = tmp_path / "capture-01.cap"
    wrpcap(str(p), [_beacon()] * 3000)
    c = CaptureFrameCounter()
    t0 = time.perf_counter()
    c.update(str(p))
    full = time.perf_counter() - t0

    wrpcap(str(p), [_beacon()] * 50, append=True)
    t0 = time.perf_counter()
    c.update(str(p))
    incremental = time.perf_counter() - t0

    # Reading 50 new records must be far cheaper than the initial 3000.
    assert incremental < full * 0.25, f"not incremental: full={full:.3f}s incremental={incremental:.3f}s"


def test_counter_on_a_non_pcap_file_reports_nothing_without_raising(tmp_path):
    junk = tmp_path / "x.cap"
    junk.write_bytes(b"\x00\x11\x22\x33 not a pcap header at all")
    c = CaptureFrameCounter()
    s = c.update(str(junk))
    assert s.total_rx == 0 and s.total_tx == 0
    assert c.update(str(tmp_path / "missing.cap")).total_rx == 0
