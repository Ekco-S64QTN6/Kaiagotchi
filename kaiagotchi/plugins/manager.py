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
                        plugin = attr(name=name, config=plugin_config)
                        if self.register_plugin(plugin):
                            _LOG.info("Loaded plugin: %s", name)
                        break
            except Exception as e:
                _LOG.error("Failed to load plugin %s: %s", name, e, exc_info=True)

    def register_plugin(self, plugin: Plugin) -> bool:
        """Load and register a plugin, rejecting instances whose startup fails."""
        existing = self.plugins.get(plugin.name)
        if existing is plugin:
            _LOG.debug("Plugin %s is already registered as this instance", plugin.name)
            return True

        # Load the candidate before disturbing an existing working instance.
        # A failed same-name update must not take down the last known-good plugin.
        try:
            plugin.on_load()
        except Exception:
            _LOG.error("Error in on_load for plugin %s", plugin.name, exc_info=True)
            # A hook may have acquired resources before raising, so give it a
            # best-effort cleanup opportunity but never dispatch to it as loaded.
            try:
                plugin.on_unload()
            except Exception:
                _LOG.error(
                    "Error cleaning up plugin %s after failed on_load",
                    plugin.name,
                    exc_info=True,
                )
            return False

        if existing is not None:
            _LOG.warning(
                "Plugin %s already registered; replacing after successful load.",
                plugin.name,
            )
            try:
                existing.on_unload()
            except Exception:
                _LOG.error(
                    "Error in on_unload for replaced plugin %s",
                    plugin.name,
                    exc_info=True,
                )

        self.plugins[plugin.name] = plugin
        return True

    def unload_all(self):
        """Unload all plugins."""
        for name, plugin in tuple(self.plugins.items()):
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
