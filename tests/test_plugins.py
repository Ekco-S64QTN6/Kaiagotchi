from unittest.mock import MagicMock

import pytest

from kaiagotchi.plugins.base import PLUGIN_API_VERSION, Plugin
from kaiagotchi.plugins.manager import PluginManager


class LifecyclePlugin(Plugin):
    def __init__(self, name, config=None):
        super().__init__(name, config)
        self.load_called = False
        self.event_called = False
        self.state_called = False
        self.unload_called = False

    def on_load(self):
        self.load_called = True

    def on_unload(self):
        self.unload_called = True

    def on_event(self, event_name, data=None):
        self.event_called = True

    def on_state_update(self, state):
        self.state_called = True

def test_plugin_lifecycle():
    manager = PluginManager()
    plugin = LifecyclePlugin("test_plugin")

    manager.register_plugin(plugin)
    assert plugin.load_called

    manager.dispatch_event("test_event")
    assert plugin.event_called

    manager.dispatch_state_update({})
    assert plugin.state_called

def test_plugin_discovery(tmp_path, monkeypatch):
    # Create a dummy plugin in a temporary directory
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()

    (plugin_dir / "__init__.py").touch()

    dummy_plugin_dir = plugin_dir / "dummy"
    dummy_plugin_dir.mkdir()
    (dummy_plugin_dir / "__init__.py").write_text(
        "from kaiagotchi.plugins.base import Plugin\n"
        "class DummyPlugin(Plugin):\n"
        "    def on_load(self): pass\n"
        "    def on_unload(self): pass\n"
    )

    # Mock sys.path to include the parent of plugin_dir so importlib can find 'plugins.dummy'
    # But wait, the manager expects 'kaiagotchi.plugins.dummy'.
    # We need to mock the import logic or structure the temp dir to match package structure.

    # Easier approach: Mock importlib.import_module
    mock_module = MagicMock()
    mock_class = type("DummyPlugin", (Plugin,), {"on_load": lambda s: None, "on_unload": lambda s: None})
    mock_module.DummyPlugin = mock_class

    import importlib
    monkeypatch.setattr(importlib, "import_module", lambda name: mock_module)

    manager = PluginManager(plugin_dir=str(plugin_dir))
    manager.discover_and_load()

    assert "dummy" in manager.plugins

def test_duplicate_registration_unloads_replaced_instance():
    manager = PluginManager()
    original = LifecyclePlugin("duplicate")
    replacement = LifecyclePlugin("duplicate")

    assert manager.register_plugin(original) is True
    assert manager.register_plugin(replacement) is True

    assert original.unload_called is True
    assert manager.plugins["duplicate"] is replacement

    manager.dispatch_event("test_event")
    assert original.event_called is False
    assert replacement.event_called is True

def test_failed_plugin_load_is_cleaned_up_and_not_registered():
    class BrokenPlugin(Plugin):
        def __init__(self):
            super().__init__("broken")
            self.cleaned_up = False
            self.event_called = False

        def on_load(self):
            raise RuntimeError("simulated load failure")

        def on_unload(self):
            self.cleaned_up = True

        def on_event(self, event_name, data=None):
            self.event_called = True

    manager = PluginManager()
    plugin = BrokenPlugin()

    assert manager.register_plugin(plugin) is False
    assert "broken" not in manager.plugins
    assert plugin.cleaned_up is True

    manager.dispatch_event("test_event")
    assert plugin.event_called is False

def test_unload_all_continues_after_one_plugin_fails():
    class BrokenUnloadPlugin(LifecyclePlugin):
        def on_unload(self):
            raise RuntimeError("simulated unload failure")

    manager = PluginManager()
    broken = BrokenUnloadPlugin("broken-unload")
    healthy = LifecyclePlugin("healthy")
    manager.register_plugin(broken)
    manager.register_plugin(healthy)

    manager.unload_all()

    assert manager.plugins == {}
    assert healthy.unload_called is True

def test_failed_plugin_replacement_keeps_existing_plugin_active():
    class BrokenReplacement(Plugin):
        def __init__(self):
            super().__init__("stable")
            self.cleaned_up = False

        def on_load(self):
            raise RuntimeError("replacement startup failed")

        def on_unload(self):
            self.cleaned_up = True

    manager = PluginManager()
    original = LifecyclePlugin("stable")
    replacement = BrokenReplacement()

    assert manager.register_plugin(original) is True
    assert manager.register_plugin(replacement) is False

    assert manager.plugins["stable"] is original
    assert original.unload_called is False
    assert replacement.cleaned_up is True

    manager.dispatch_event("test_event")
    assert original.event_called is True

def test_unload_all_rejects_plugin_registration_from_unload_hooks():
    manager = PluginManager()
    replacement = LifecyclePlugin("late-plugin")
    load_calls = []

    class RegisteringOnUnloadPlugin(LifecyclePlugin):
        def on_unload(self):
            self.unload_called = True
            load_calls.append(manager.register_plugin(replacement))

    current = RegisteringOnUnloadPlugin("current")
    assert manager.register_plugin(current) is True

    manager.unload_all()

    assert current.unload_called is True
    assert load_calls == [False]
    assert replacement.name not in manager.plugins
    assert replacement.event_called is False

def test_unload_all_ignores_reentrant_unload_call():
    manager = PluginManager()

    class ReentrantPlugin(LifecyclePlugin):
        def on_unload(self):
            self.unload_called = True
            manager.unload_all()

    plugin = ReentrantPlugin("reentrant")
    assert manager.register_plugin(plugin) is True

    manager.unload_all()

    assert plugin.unload_called is True
    assert manager.plugins == {}
    assert manager._unloading is False


def test_legacy_plugin_inherits_current_api_version_without_changes():
    plugin = LifecyclePlugin("legacy-plugin")
    manager = PluginManager()

    assert LifecyclePlugin.PLUGIN_API_VERSION == PLUGIN_API_VERSION
    assert manager.register_plugin(plugin) is True
    assert plugin.load_called is True


def test_incompatible_plugin_version_is_rejected_before_load_or_replacement():
    class IncompatiblePlugin(LifecyclePlugin):
        PLUGIN_API_VERSION = 2

    manager = PluginManager()
    original = LifecyclePlugin("versioned")
    incompatible = IncompatiblePlugin("versioned")

    assert manager.register_plugin(original) is True
    assert manager.register_plugin(incompatible) is False

    # Compatibility is checked before lifecycle hooks; the existing instance is
    # not unloaded or replaced by a plugin the host cannot support.
    assert incompatible.load_called is False
    assert incompatible.unload_called is False
    assert original.unload_called is False
    assert manager.plugins["versioned"] is original


@pytest.mark.parametrize(
    "api_version",
    [True, "1", None],
    ids=["boolean", "string", "missing"],
)
def test_malformed_plugin_api_version_is_rejected_before_load(api_version):
    class MalformedPlugin(LifecyclePlugin):
        pass

    MalformedPlugin.PLUGIN_API_VERSION = api_version
    plugin = MalformedPlugin("malformed-version")
    manager = PluginManager()

    assert manager.register_plugin(plugin) is False
    assert plugin.load_called is False
    assert plugin.unload_called is False
    assert "malformed-version" not in manager.plugins
