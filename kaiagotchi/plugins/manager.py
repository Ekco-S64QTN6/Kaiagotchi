# kaiagotchi/plugins/manager.py
import os
import importlib
import logging
import sys
from typing import Dict, List, Type, Any
from .base import Plugin

_LOG = logging.getLogger("kaiagotchi.plugins.manager")

class PluginManager:
    """Manages the lifecycle of Kaiagotchi plugins."""

    def __init__(self, plugin_dir: str = "kaiagotchi/plugins"):
        self.plugin_dir = plugin_dir
        self.plugins: Dict[str, Plugin] = {}
        self._sys_path_added = False

    def discover_and_load(self, config: Dict[str, Any] = None):
        """Discover and load plugins from the plugin directory."""
        config = config or {}
        
        # Ensure plugin dir is in sys.path
        abs_plugin_dir = os.path.abspath(self.plugin_dir)
        if abs_plugin_dir not in sys.path:
            sys.path.append(abs_plugin_dir)
            self._sys_path_added = True

        if not os.path.exists(abs_plugin_dir):
            _LOG.warning(f"Plugin directory not found: {abs_plugin_dir}")
            return

        # Iterate over subdirectories in plugin_dir
        for item in os.listdir(abs_plugin_dir):
            item_path = os.path.join(abs_plugin_dir, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, "__init__.py")):
                try:
                    module_name = f"kaiagotchi.plugins.{item}"
                    module = importlib.import_module(module_name)
                    
                    # Look for a 'Plugin' subclass in the module
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                            plugin_instance = attr(name=item, config=config.get(item, {}))
                            self.register_plugin(plugin_instance)
                            _LOG.info(f"Loaded plugin: {item}")
                            break
                except Exception as e:
                    _LOG.error(f"Failed to load plugin {item}: {e}", exc_info=True)

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

    def dispatch_state_update(self, state: Dict[str, Any]):
        """Dispatch state update to all enabled plugins."""
        for plugin in self.plugins.values():
            if plugin.enabled:
                try:
                    plugin.on_state_update(state)
                except Exception as e:
                    _LOG.error(f"Error in on_state_update for plugin {plugin.name}: {e}")
