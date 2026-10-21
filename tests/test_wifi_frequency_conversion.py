"""Regression tests for Wi-Fi channel/frequency conversion across bands."""

import pytest

from kaiagotchi.mesh.wifi import (
    BANDS,
    CHANNEL_PLANS,
    channel_to_freq,
    freq_to_channel,
    get_band_for_channel,
    get_channel_range,
    is_valid_channel,
)


@pytest.mark.parametrize(
    ("frequency", "channel"),
    [
        (2412, 1),
        (2437, 6),
        (2472, 13),
        (2484, 14),
        (5180, 36),
        (5200, 40),
        (5320, 64),
        (5500, 100),
        (5520, 104),
        (5720, 144),
        (5745, 149),
        (5825, 165),
        (5935, 2),
        (5955, 1),
        (5975, 5),
        (5995, 9),
        (6415, 93),
        (7115, 233),
    ],
)
def test_frequency_to_channel_uses_standard_channel_center_formula(frequency, channel):
    assert freq_to_channel(frequency) == channel


@pytest.mark.parametrize(
    ("channel", "band", "frequency"),
    [
        (1, "2.4GHz", 2412),
        (6, "2.4GHz", 2437),
        (14, "2.4GHz", 2484),
        (36, "5GHz", 5180),
        (40, "5GHz", 5200),
        (104, "5GHz", 5520),
        (149, "5GHz", 5745),
        (165, "5GHz", 5825),
        (2, "6GHz", 5935),
        (1, "6GHz", 5955),
        (5, "6GHz", 5975),
        (9, "6GHz", 5995),
        (93, "6GHz", 6415),
        (233, "6GHz", 7115),
    ],
)
def test_channel_to_frequency_is_band_aware(channel, band, frequency):
    assert channel_to_freq(channel, band=band) == frequency


def test_legacy_channel_conversion_defaults_are_preserved():
    assert channel_to_freq(5) == 2432
    assert channel_to_freq(40) == 5200
    assert get_band_for_channel(5) == "2.4GHz"


def test_overlapping_channel_numbers_can_be_disambiguated():
    assert get_band_for_channel(5, band="6GHz") == "6GHz"
    assert channel_to_freq(5, band="6GHz") == 5975
    assert is_valid_channel(5, "FCC", band="6GHz")


def test_six_ghz_channel_grids_match_20_mhz_centers():
    six_ghz_grid = sorted([2, *range(1, 234, 4)])
    assert BANDS["6GHz"].channels == six_ghz_grid
    assert CHANNEL_PLANS["FCC"]["6GHz"] == six_ghz_grid
    assert CHANNEL_PLANS["ETSI"]["6GHz"] == list(range(1, 94, 4))
    assert get_channel_range("6GHz") == (1, 233)
    assert is_valid_channel(2, "FCC", band="6GHz")
    assert not is_valid_channel(2, "ETSI", band="6GHz")
    assert is_valid_channel(233, "FCC", band="6GHz")
    assert not is_valid_channel(233, "ETSI", band="6GHz")
    assert is_valid_channel(93, "ETSI", band="6GHz")


@pytest.mark.parametrize(
    "frequency",
    [2400, 2413, 2480, 5185, 5201, 5950, 5960, 7116, 7125],
)
def test_non_channel_center_frequencies_are_rejected(frequency):
    with pytest.raises(ValueError):
        freq_to_channel(frequency)


@pytest.mark.parametrize(
    ("channel", "band"),
    [
        (0, "2.4GHz"),
        (15, "2.4GHz"),
        (37, "5GHz"),
        (14, "6GHz"),
        (234, "6GHz"),
    ],
)
def test_invalid_channels_are_rejected_for_requested_band(channel, band):
    with pytest.raises(ValueError):
        channel_to_freq(channel, band=band)
