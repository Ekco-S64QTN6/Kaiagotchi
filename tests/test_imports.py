# test_imports.py - Place this in your kaiagotchi folder
#!/usr/bin/env python3
"""
Quick test to verify all imports work correctly.
"""

try:
    from kaiagotchi.agent.base import KaiagotchiBase
    print("✓ Successfully imported KaiagotchiBase from agent.base")
except ImportError as e:
    print(f"✗ Failed to import from agent.base: {e}")

try:
    from kaiagotchi.agent import KaiagotchiBase
    print("✓ Successfully imported KaiagotchiBase from agent package")
except ImportError as e:
    print(f"✗ Failed to import from agent package: {e}")

try:
    from kaiagotchi.security import SecurityManager
    print("✓ Successfully imported SecurityManager")
except ImportError as e:
    print(f"✗ Failed to import SecurityManager: {e}")

try:
    from kaiagotchi.utils import load_config
    print("✓ Successfully imported utils.load_config")
except ImportError as e:
    print(f"✗ Failed to import utils.load_config: {e}")

print("\nImport test completed!")