# kaiagotchi/plugins/manager.py
import importlib
import logging
from pathlib import Path
from typing import Any

from .base import Plugin

_LOG = logging.getLogger("kaiagotchi.plugins.manager")


class PluginManager:
    """Manages the lifecycle of Kaiagotchi plugins.

    A plugin is a subpackage of :mod:`kaiagotchi.plugins` (a directory with an
    ``__init__.py`` exposing a :class:`~kaiagotchi.plugins.base.Plugin`
    subclass). Discovered plugins are loaded unless their config sets
    ``enabled = false``.
    """

    def __init__(self, plugin_dir: str | Path | None = None):
        # Resolve relative to this package so discovery works regardless of CWD.
        self.plugin_dir = Path(plugin_dir) if plugin_dir else Path(__file__).resolve().parent
        self.plugins: dict[str, Plugin] = {}

    def discover_and_load(self, config: dict[str, Any] | None = None):
        """Discover and load plugin subpackages from the plugin directory."""
        config = config or {}

        if not self.plugin_dir.is_dir():
            _LOG.warning("Plugin directory not found: %s", self.plugin_dir)
            return

        for item_path in sorted(self.plugin_dir.iterdir()):
            if not (item_path.is_dir() and (item_path / "__init__.py").exists()):
                continue
            name = item_path.name
            plugin_config = config.get(name, {})
            if plugin_config.get("enabled") is False:
                _LOG.debug("Plugin %s disabled via config; skipping", name)
                continue
            try:
                module = importlib.import_module(f"kaiagotchi.plugins.{name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                        self.register_plugin(attr(name=name, config=plugin_config))
                        _LOG.info("Loaded plugin: %s", name)
                        break
            except Exception as e:
                _LOG.error("Failed to load plugin %s: %s", name, e, exc_info=True)

    def register_plugin(self, plugin: Plugin):
        """Register a plugin instance."""
        if plugin.name in self.plugins:
            _LOG.warning(f"Plugin {plugin.name} already registered. Overwriting.")
        self.plugins[plugin.name] = plugin
        try:
            plugin.on_load()
        except Exception as e:
            _LOG.error(f"Error in on_load for plugin {plugin.name}: {e}")

    def unload_all(self):
        """Unload all plugins."""
        for name, plugin in self.plugins.items():
            try:
                plugin.on_unload()
            except Exception as e:
                _LOG.error(f"Error in on_unload for plugin {name}: {e}")
        self.plugins.clear()

    def dispatch_event(self, event_name: str, data: Any = None):
        """Dispatch an event to all enabled plugins."""
        for plugin in self.plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_event(event_name, data)
                except Exception as e:
                    _LOG.error(f"Error in on_event for plugin {plugin.name}: {e}")

    def dispatch_state_update(self, state: dict[str, Any]):
        """Dispatch state update to all enabled plugins."""
        for plugin in self.plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_state_update(state)
                except Exception as e:
                    _LOG.error(f"Error in on_state_update for plugin {plugin.name}: {e}")
