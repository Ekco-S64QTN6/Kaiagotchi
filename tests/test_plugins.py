import pytest
from unittest.mock import MagicMock
from kaiagotchi.plugins.base import Plugin
from kaiagotchi.plugins.manager import PluginManager

class TestPlugin(Plugin):
    def __init__(self, name, config=None):
        super().__init__(name, config)
        self.load_called = False
        self.event_called = False
        self.state_called = False

    def on_load(self):
        self.load_called = True

    def on_unload(self):
        pass

    def on_event(self, event_name, data=None):
        self.event_called = True

    def on_state_update(self, state):
        self.state_called = True

def test_plugin_lifecycle():
    manager = PluginManager()
    plugin = TestPlugin("test_plugin")
    
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
