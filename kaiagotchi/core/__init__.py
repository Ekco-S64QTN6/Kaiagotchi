# kaiagotchi/core/__init__.py
"""
Core runtime subsystems for Kaiagotchi.
"""
from .automata import Automata
from .manager import Manager
from .system import SystemTicker

__all__ = ["Manager", "Automata", "SystemTicker"]
