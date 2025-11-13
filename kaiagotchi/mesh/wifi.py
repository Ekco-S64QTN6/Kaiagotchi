"""
Wi-Fi channel and frequency utilities for kaiagotchi.
Provides comprehensive channel management and frequency conversion.
"""

from typing import Dict, List, Tuple
import logging

# Global constants
NumChannels: int = 233  # Total number of Wi-Fi channels across all bands

# Channel plans by regulatory domain
CHANNEL_PLANS = {
    'FCC': {  # USA
        '2.4GHz': list(range(1, 12)),  # Channels 1-11
        '5GHz': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165],
        '6GHz': list(range(1, 94))  # Channels 1-93
    },
    'ETSI': {  # Europe
        '2.4GHz': list(range(1, 14)),  # Channels 1-13
        '5GHz': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140],
        '6GHz': list(range(1, 94))  # With restrictions
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
    
    def _generate_channels(self) -> List[int]:
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
            return list(range(1, 94))  # Standard 6GHz channels
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
    Convert a Wi-Fi frequency (in MHz) to its corresponding channel number.
    Supports 2.4 GHz, 5 GHz, and 6 GHz Wi-Fi bands.
    
    Args:
        freq: The frequency in MHz.
        
    Returns:
        The Wi-Fi channel as an integer.
        
    Raises:
        ValueError: If the frequency is invalid.
    """
    # 2.4 GHz Wi-Fi channels
    if 2412 <= freq <= 2472:  # 2.4 GHz standard channels
        return ((freq - 2412) // 5) + 1
    elif freq == 2484:  # Channel 14 (Japan)
        return 14
    
    # 5 GHz Wi-Fi channels
    elif 5150 <= freq <= 5350:  # UNII-1 (36-64)
        return ((freq - 5180) // 20) + 36
    elif 5470 <= freq <= 5725:  # UNII-2 (100-144)
        return ((freq - 5500) // 20) + 100
    elif 5745 <= freq <= 5850:  # UNII-3 (149-165)
        return ((freq - 5745) // 20) + 149
    
    # 6 GHz Wi-Fi channels
    elif 5925 <= freq <= 7125:  # 6 GHz band
        return ((freq - 5950) // 20) + 11
    
    raise ValueError(f"Invalid Wi-Fi frequency: {freq} MHz")


def channel_to_freq(channel: int) -> int:
    """
    Convert a Wi-Fi channel number to its center frequency.
    
    Args:
        channel: The Wi-Fi channel number.
        
    Returns:
        The center frequency in MHz.
        
    Raises:
        ValueError: If the channel is invalid.
    """
    # 2.4 GHz band
    if 1 <= channel <= 13:
        return 2412 + (channel - 1) * 5
    elif channel == 14:
        return 2484
    
    # 5 GHz band
    elif 36 <= channel <= 64:
        return 5180 + (channel - 36) * 20
    elif 100 <= channel <= 144:
        return 5500 + (channel - 100) * 20
    elif 149 <= channel <= 165:
        return 5745 + (channel - 149) * 20
    
    # 6 GHz band
    elif 1 <= channel <= 93:  # 6GHz channels are 1-93
        return 5950 + (channel - 1) * 20
    
    raise ValueError(f"Invalid Wi-Fi channel: {channel}")


def get_band_for_channel(channel: int) -> str:
    """
    Get the frequency band for a given channel.
    
    Args:
        channel: The Wi-Fi channel number.
        
    Returns:
        The band name ('2.4GHz', '5GHz', '6GHz').
    """
    if 1 <= channel <= 14:
        return '2.4GHz'
    elif 36 <= channel <= 165:
        return '5GHz'
    elif 1 <= channel <= 93:  # 6GHz channels overlap with 2.4GHz numbers
        return '6GHz'
    else:
        raise ValueError(f"Unknown band for channel: {channel}")


def get_non_overlapping_channels(regulatory_domain: str = 'FCC') -> List[int]:
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


def is_valid_channel(channel: int, regulatory_domain: str = 'FCC') -> bool:
    """
    Check if a channel is valid for the regulatory domain.
    
    Args:
        channel: The channel number to check.
        regulatory_domain: Regulatory domain to check against.
        
    Returns:
        True if the channel is valid.
    """
    plan = CHANNEL_PLANS.get(regulatory_domain, CHANNEL_PLANS['FCC'])
    
    band = get_band_for_channel(channel)
    return channel in plan.get(band, [])


def get_channel_range(band: str) -> Tuple[int, int]:
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
        '6GHz': (1, 93)
    }
    return bands.get(band, (0, 0))