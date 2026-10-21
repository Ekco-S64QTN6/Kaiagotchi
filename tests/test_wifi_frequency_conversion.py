import pytest

from kaiagotchi.mesh.wifi import (
    channel_to_freq,
    freq_to_channel,
    get_band_for_channel,
    get_channel_range,
    is_valid_channel,
)


@pytest.mark.parametrize(
    ("channel", "freq"),
    [
        (1, 2412),
        (6, 2437),
        (11, 2462),
        (14, 2484),
        (36, 5180),
        (40, 5200),
        (44, 5220),
        (64, 5320),
        (100, 5500),
        (104, 5520),
        (144, 5720),
        (149, 5745),
        (153, 5765),
        (165, 5825),
    ],
)
def test_24_and_5ghz_channel_center_round_trips(channel, freq):
    assert channel_to_freq(channel) == freq
    assert freq_to_channel(freq) == channel


@pytest.mark.parametrize(
    ("channel", "freq"),
    [
        (1, 5955),
        (5, 5975),
        (37, 6135),
        (93, 6415),
        (149, 6695),
        (233, 7115),
    ],
)
def test_6ghz_channel_center_round_trips_when_band_is_explicit(channel, freq):
    assert channel_to_freq(channel, band="6GHz") == freq
    assert freq_to_channel(freq, band="6GHz") == channel
    assert get_band_for_channel(channel, band="6GHz") == "6GHz"


def test_overlapping_channels_keep_legacy_inference_but_allow_explicit_band():
    assert get_band_for_channel(5) == "2.4GHz"
    assert channel_to_freq(5) == 2432
    assert channel_to_freq(5, band="6GHz") == 5975
    assert get_band_for_channel(149) == "5GHz"
    assert channel_to_freq(149, band="6GHz") == 6695


@pytest.mark.parametrize("frequency", [5190, 5201, 5970, 7120, 2483])
def test_invalid_or_off_grid_frequencies_are_rejected(frequency):
    with pytest.raises(ValueError):
        freq_to_channel(frequency)


@pytest.mark.parametrize("channel", [0, 15, 35, 38, 166, 234])
def test_unsupported_channels_are_rejected(channel):
    with pytest.raises(ValueError):
        channel_to_freq(channel)


def test_regulatory_channel_validation_respects_band_disambiguation():
    assert is_valid_channel(5, "FCC")
    assert is_valid_channel(5, "FCC", band="2.4GHz")
    assert is_valid_channel(5, "FCC", band="6GHz")
    assert is_valid_channel(233, "FCC", band="6GHz")
    assert not is_valid_channel(233, "ETSI", band="6GHz")
    assert not is_valid_channel(15, "FCC")


def test_nominal_6ghz_channel_range_extends_to_233():
    assert get_channel_range("6GHz") == (1, 233)
