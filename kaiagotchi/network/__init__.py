# kaiagotchi/network/__init__.py - SIMPLE
"""
Network package for kaiagotchi - contains protocols, action management, and utilities.
"""

from .action_manager import InterfaceActionManager
from .utils import iface_channels, total_unique_handshakes

__all__ = ['InterfaceActionManager', 'iface_channels', 'total_unique_handshakes']