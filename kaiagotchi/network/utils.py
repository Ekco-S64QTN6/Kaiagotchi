# kaiagotchi/network/utils.py
import logging

logger = logging.getLogger(__name__)

def iface_channels(interface: str) -> list[int]:
    """Get supported channels for a wireless interface."""
    try:
        return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    except Exception as e:
        logger.warning(f"Could not determine channels for {interface}: {e}")
        return [1, 6, 11]

