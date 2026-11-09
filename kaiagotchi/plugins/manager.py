# kaiagotchi/plugins/manager.py
import hashlib
import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .base import PLUGIN_API_VERSION, Plugin

_LOG = logging.getLogger("kaiagotchi.plugins.manager")


class PluginManager:
    """Manages the lifecycle of Kaiagotchi plugins.

    A bundled plugin is a subpackage of :mod:`kaiagotchi.plugins`; callers may
    also provide an external plugin root containing package directories. Each
    package has an ``__init__.py`` exposing a :class:`~kaiagotchi.plugins.base.Plugin`
    subclass. Discovered plugins are loaded unless their config sets
    ``enabled = false``.
    """

    def __init__(self, plugin_dir: str | Path | None = None):
        # Resolve relative to this package so discovery works regardless of CWD.
        self.plugin_dir = (
            Path(plugin_dir).expanduser().resolve()
            if plugin_dir
            else Path(__file__).resolve().parent
        )
        self._uses_builtin_plugin_package = (
            self.plugin_dir == Path(__file__).resolve().parent
        )
        self.plugins: dict[str, Plugin] = {}
        self._unloading = False

    def discover_and_load(self, config: dict[str, Any] | None = None):
        """Discover and load bundled or external plugin packages from the configured root."""
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
                module = self._import_plugin_module(name, item_path)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                        plugin = attr(name=name, config=plugin_config)
                        if self.register_plugin(plugin):
                            _LOG.info("Loaded plugin: %s", name)
                        break
            except Exception as e:
                _LOG.error("Failed to load plugin %s: %s", name, e, exc_info=True)

    def _import_plugin_module(self, name: str, package_path: Path) -> ModuleType:
        """Import a bundled or externally configured plugin package.

        The bundled package uses its normal import path. A custom plugin root
        receives a stable private namespace so its packages (and relative
        imports) come from that root instead of accidentally resolving to a
        same-named package under :mod:`kaiagotchi.plugins`.
        """
        if self._uses_builtin_plugin_package:
            return importlib.import_module(f"kaiagotchi.plugins.{name}")

        root = self.plugin_dir
        namespace_suffix = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
        namespace_name = f"_kaiagotchi_external_plugins_{namespace_suffix}"
        if namespace_name not in sys.modules:
            namespace = ModuleType(namespace_name)
            namespace.__path__ = [str(root)]  # type: ignore[attr-defined]
            namespace.__package__ = namespace_name
            sys.modules[namespace_name] = namespace

        module_name = f"{namespace_name}.{name}"
        init_file = package_path / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            module_name,
            init_file,
            submodule_search_locations=[str(package_path)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create an import spec for plugin {name!r}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    def register_plugin(self, plugin: Plugin) -> bool:
        """Load and register a plugin, rejecting instances whose startup fails."""
        if self._unloading:
            _LOG.warning(
                "Rejecting registration for plugin %s while unloading all plugins.",
                plugin.name,
            )
            return False

        # V1 is inherited by existing Plugin subclasses, so legacy plugins do not
        # need a source change. Reject incompatible versions before invoking hooks
        # or unloading a working same-name plugin.
        api_version = getattr(type(plugin), "PLUGIN_API_VERSION", PLUGIN_API_VERSION)
        if (
            isinstance(api_version, bool)
            or not isinstance(api_version, int)
            or api_version != PLUGIN_API_VERSION
        ):
            _LOG.error(
                "Rejecting plugin %s: unsupported API version %r (host supports %d).",
                plugin.name,
                api_version,
                PLUGIN_API_VERSION,
            )
            return False

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
        """Unload all plugins once, rejecting re-entrant calls and new registrations."""
        if self._unloading:
            _LOG.debug("Plugin unload already in progress; ignoring re-entrant call")
            return

        self._unloading = True
        try:
            for name, plugin in tuple(self.plugins.items()):
                try:
                    plugin.on_unload()
                except Exception as e:
                    _LOG.error("Error in on_unload for plugin %s: %s", name, e)
        finally:
            self.plugins.clear()
            self._unloading = False

    def dispatch_event(self, event_name: str, data: Any = None):
        """Dispatch an event to a stable snapshot of enabled plugins.

        Plugins registered or replaced by a callback participate on the next
        dispatch pass, not in the pass already in progress.
        """
        for plugin in tuple(self.plugins.values()):
            if plugin.enabled:
                try:
                    plugin.on_event(event_name, data)
                except Exception as e:
                    _LOG.error(f"Error in on_event for plugin {plugin.name}: {e}")

    def dispatch_state_update(self, state: dict[str, Any]):
        """Dispatch state to a stable snapshot of enabled plugins.

        Plugins registered or replaced by a callback participate on the next
        dispatch pass, not in the pass already in progress.
        """
        for plugin in tuple(self.plugins.values()):
            if plugin.enabled:
                try:
                    plugin.on_state_update(state)
                except Exception as e:
                    _LOG.error(f"Error in on_state_update for plugin {plugin.name}: {e}")
