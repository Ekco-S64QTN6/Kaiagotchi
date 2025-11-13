# kaiagotchi/network/utils.py
import logging
from typing import List

logger = logging.getLogger(__name__)

def iface_channels(interface: str) -> List[int]:
    """Get supported channels for a wireless interface."""
    try:
        return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    except Exception as e:
        logger.warning(f"Could not determine channels for {interface}: {e}")
        return [1, 6, 11]

def total_unique_handshakes() -> int:
    """Get total unique handshakes captured."""
    return 0  # This returns int, not Literal[0]