# kaiagotchi/core/__init__.py
"""
Core runtime subsystems for Kaiagotchi.
"""
from .manager import Manager
from .automata import Automata
from .system import SystemTicker

__all__ = ["Manager", "Automata", "SystemTicker"]
