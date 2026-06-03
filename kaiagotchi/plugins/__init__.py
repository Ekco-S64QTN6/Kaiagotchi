# kaiagotchi/plugins/__init__.py
"""
Plugin system for Kaiagotchi.
Exposes Plugin base class, PluginManager, and event dispatch.
"""
from .base import Plugin
from .manager import PluginManager

_manager: PluginManager | None = None


def set_manager(manager: PluginManager) -> None:
    """Set the global plugin manager instance."""
    global _manager
    _manager = manager


def on(event: str, *args, **kwargs) -> None:
    """Dispatch an event to all loaded plugins via the global manager."""
    if _manager:
        _manager.dispatch_event(event, {"args": args, **kwargs})


__all__ = ["Plugin", "PluginManager", "set_manager", "on"]
