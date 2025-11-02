# filepath: kaiagotchi/network/__init__.py
"""
Network package for Kaiagotchi - contains protocols, action management, and utilities.
"""

# Export key components for easy access from the kaiagotchi.network package
from .action_manager import InterfaceActionManager
# Assuming 'utils' is still needed for iface_channels/total_unique_handshakes
# from .utils import iface_channels, total_unique_handshakes 

# Although not strictly required in __init__.py for the imports in agent.py
# (since agent.py is using relative imports from its own level: `from .network...`), 
# adding exports here is a good practice for package structure.

__all__ = ['InterfaceActionManager'] 
# You will likely need to create utils.py and export its functions as well if you 
# haven't already and the import is still failing.