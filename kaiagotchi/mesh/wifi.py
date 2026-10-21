"""
Wi-Fi channel and frequency utilities for kaiagotchi.
Provides comprehensive channel management and frequency conversion.
"""


# Global constants
NumChannels: int = 233  # Total number of Wi-Fi channels across all bands

# Channel plans by regulatory domain
CHANNEL_PLANS = {
    'FCC': {  # USA
        '2.4GHz': list(range(1, 12)),  # Channels 1-11
        '5GHz': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165],
        '6GHz': sorted([2, *range(1, 234, 4)])  # Includes special channel 2 at 5935 MHz
    },
    'ETSI': {  # Europe
        '2.4GHz': list(range(1, 14)),  # Channels 1-13
        '5GHz': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140],
        '6GHz': list(range(1, 94, 4))  # 20 MHz channels 1, 5, ..., 93 in the ETSI allocation
    },
    # Add more regulatory domains as needed
}


class WiFiBand:
    """Represents a Wi-Fi frequency band."""

    def __init__(self, name: str, start_freq: int, end_freq: int, channel_width: int = 20):
        self.name = name
        self.start_freq = start_freq
        self.end_freq = end_freq
        self.channel_width = channel_width
        self.channels = self._generate_channels()

    def _generate_channels(self) -> list[int]:
        """Generate channel list for this band."""
        if self.name == '2.4GHz':
            return list(range(1, 15))  # Channels 1-14
        elif self.name == '5GHz':
            # Standard 5GHz channels
            channels = []
            # UNII-1 (36-64)
            channels.extend(range(36, 65, 4))
            # UNII-2 (100-144)
            channels.extend(range(100, 145, 4))
            # UNII-3 (149-165)
            channels.extend(range(149, 166, 4))
            return channels
        elif self.name == '6GHz':
            # Channel 2 at 5935 MHz is a special 6 GHz channel.
            return sorted([2, *range(1, 234, 4)])
        else:
            return []

    def contains_frequency(self, freq: int) -> bool:
        return self.start_freq <= freq <= self.end_freq


# Define Wi-Fi bands
BANDS = {
    '2.4GHz': WiFiBand('2.4GHz', 2412, 2484),
    '5GHz': WiFiBand('5GHz', 5150, 5850),
    '6GHz': WiFiBand('6GHz', 5925, 7125)
}


def freq_to_channel(freq: int) -> int:
    """
    Convert a Wi-Fi channel-center frequency in MHz to its channel number.

    Frequency identifies the band, so this conversion is unambiguous even where
    channel numbers overlap between the 2.4 GHz and 6 GHz bands. Only standard
    20 MHz channel centers represented by this module are accepted.

    Raises:
        ValueError: If the frequency is not a supported channel center.
    """
    # 2.4 GHz: channels 1–13 are spaced 5 MHz apart; channel 14 is special.
    if 2412 <= freq <= 2472 and (freq - 2412) % 5 == 0:
        return (freq - 2412) // 5 + 1
    if freq == 2484:
        return 14

    # 5 GHz channel centers follow 5000 + 5 * channel (e.g. ch 40 = 5200 MHz).
    if BANDS['5GHz'].start_freq <= freq <= BANDS['5GHz'].end_freq and (freq - 5000) % 5 == 0:
        channel = (freq - 5000) // 5
        if channel in BANDS['5GHz'].channels:
            return channel

    # Channel 2 is the special 5935 MHz 6 GHz channel.
    if freq == 5935:
        return 2

    # 6 GHz 20 MHz channel centers are 5950 + 5 * channel (ch 1 = 5955 MHz).
    if 5955 <= freq <= 7115 and (freq - 5950) % 5 == 0:
        channel = (freq - 5950) // 5
        # Channel 2 is valid only at its special 5935 MHz center, not 5960 MHz.
        if channel in BANDS['6GHz'].channels and channel != 2:
            return channel

    raise ValueError(f"Invalid Wi-Fi channel-center frequency: {freq} MHz")

def channel_to_freq(channel: int, band: str | None = None) -> int:
    """
    Convert a channel number to its center frequency in MHz.

    When band is omitted, overlapping channel numbers default to their legacy
    interpretation (channels 1–14 are 2.4 GHz). Pass band='6GHz' to convert
    overlapping 6 GHz channels explicitly.

    Raises:
        ValueError: If the channel is unsupported in the requested band.
    """
    resolved_band = get_band_for_channel(channel, band=band)
    if resolved_band == '2.4GHz':
        return 2484 if channel == 14 else 2412 + (channel - 1) * 5
    if resolved_band == '5GHz':
        return 5000 + channel * 5
    # 6 GHz channel 2 is a special 5935 MHz channel.
    if channel == 2:
        return 5935
    # Other 20 MHz centers: channel 1 = 5955 MHz, channel 5 = 5975 MHz, etc.
    return 5950 + channel * 5

def get_band_for_channel(channel: int, band: str | None = None) -> str:
    """
    Resolve the band for a channel number.

    Channel numbers 1–14 overlap between 2.4 GHz and 6 GHz, so omission of
    band preserves the legacy 2.4 GHz interpretation. Supply band to select a
    band explicitly and validate the channel against that band's channel grid.
    """
    if band is not None:
        if band not in BANDS:
            raise ValueError(f"Unknown Wi-Fi band: {band}")
        if channel not in BANDS[band].channels:
            raise ValueError(f"Invalid Wi-Fi channel {channel} for band {band}")
        return band

    # Preserve the API's historic default for ambiguous channel IDs.
    if channel in BANDS['2.4GHz'].channels:
        return '2.4GHz'
    if channel in BANDS['5GHz'].channels:
        return '5GHz'
    if channel in BANDS['6GHz'].channels:
        return '6GHz'
    raise ValueError(f"Unknown band for channel: {channel}")

def get_non_overlapping_channels(regulatory_domain: str = 'FCC') -> list[int]:
    """
    Get non-overlapping channels for efficient scanning.

    Args:
        regulatory_domain: Regulatory domain ('FCC', 'ETSI', etc.)

    Returns:
        List of non-overlapping channels.
    """
    plan = CHANNEL_PLANS.get(regulatory_domain, CHANNEL_PLANS['FCC'])

    # For 2.4GHz, use channels 1, 6, 11 (non-overlapping)
    non_overlapping = [1, 6, 11]

    # Add 5GHz channels (all are non-overlapping with 20MHz bandwidth)
    non_overlapping.extend(plan['5GHz'])

    return non_overlapping


def is_valid_channel(
    channel: int,
    regulatory_domain: str = 'FCC',
    band: str | None = None,
) -> bool:
    """
    Check whether a channel is included in a regulatory domain's plan.

    The optional band argument disambiguates overlapping 2.4 GHz and 6 GHz
    channel numbers. Without it, the legacy 2.4 GHz default is retained.
    """
    plan = CHANNEL_PLANS.get(regulatory_domain, CHANNEL_PLANS['FCC'])
    resolved_band = get_band_for_channel(channel, band=band)
    return channel in plan.get(resolved_band, [])

def get_channel_range(band: str) -> tuple[int, int]:
    """
    Get the channel range for a frequency band.

    Args:
        band: The frequency band ('2.4GHz', '5GHz', '6GHz')

    Returns:
        Tuple of (min_channel, max_channel)
    """
    bands = {
        '2.4GHz': (1, 14),
        '5GHz': (36, 165),
        '6GHz': (1, 233)
    }
    return bands.get(band, (0, 0))
