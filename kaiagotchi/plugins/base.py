# kaiagotchi/plugins/base.py
"""Base class for Kaiagotchi plugins.

All lifecycle hooks are optional no-ops so a plugin only needs to override the
callbacks it cares about. A minimal plugin is::

    from kaiagotchi.plugins.base import Plugin

    class MyPlugin(Plugin):
        def on_state_update(self, state):
            ...
"""
from typing import Any


class Plugin:
    """Base class every Kaiagotchi plugin inherits from."""

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = config or {}
        self.enabled = True

    def on_load(self) -> None:
        """Called once when the plugin is loaded."""

    def on_unload(self) -> None:
        """Called once when the plugin is unloaded."""

    def on_event(self, event_name: str, data: Any = None) -> None:
        """Called when a named event is dispatched (e.g. ``mood_change``)."""

    def on_state_update(self, state: dict[str, Any]) -> None:
        """Called periodically with the full system state snapshot."""
