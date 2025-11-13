"""Basic import tests to catch dependency/enum issues early."""
import importlib
import unittest

class TestImports(unittest.TestCase):
    """Test suite to verify all critical modules can be imported."""

    def test_import_all_modules(self):
        """Test that core modules can be imported without errors."""
        modules = [
            "kaiagotchi.agent.agent",
            "kaiagotchi.agent.decision_engine",
            "kaiagotchi.ui.terminal_display", 
            "kaiagotchi.ui.voice.voice",
            "kaiagotchi.ui.view",
            "kaiagotchi.core.automata",
            "kaiagotchi.core.events",
            "kaiagotchi.data.system_types",
        ]

        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module, f"Failed to import {module_name}")
            except Exception as e:
                self.fail(f"Failed to import {module_name}: {str(e)}")
                
if __name__ == '__main__':
    unittest.main()