"""
User interface layer for Kaiagotchi.
Provides unified access to:
- View: orchestrates the display and voice system.
- TerminalDisplay: renders the ASCII UI in the terminal.
- Voice: centralized mood/message/face engine.
"""

from .view import View
from .terminal_display import TerminalDisplay
from .voice import Voice  # unified voice + mood + face logic

__all__ = ["View", "TerminalDisplay", "Voice"]
