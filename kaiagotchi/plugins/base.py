# kaiagotchi/plugins/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class Plugin(ABC):
    """Abstract base class for Kaiagotchi plugins."""

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    def on_load(self) -> None:
        """Called when the plugin is loaded."""
        pass

    @abstractmethod
    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""
        pass

    def on_event(self, event_name: str, data: Any = None) -> None:
        """Called when an event occurs in the system."""
        pass

    def on_state_update(self, state: Dict[str, Any]) -> None:
        """Called periodically with the full system state."""
        pass
