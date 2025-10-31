# filepath: tests/conftest.py
import pytest
from unittest.mock import AsyncMock, create_autospec
from kaiagotchi.network.action_manager import InterfaceActionManager

@pytest.fixture
def config():
    return {
        'main': {'iface': 'wlan0'},
        'network': {
            'channels': [1, 6, 11],
            'handshakes_path': 'handshakes'
        }
    }

@pytest.fixture
def mock_action_manager():
    """Synchronous fixture returning an async mock."""
    manager = create_autospec(InterfaceActionManager, instance=True)
    manager.get_interfaces = AsyncMock(return_value=[
        {"name": "wlan0", "mode": "monitor"}
    ])
    manager.set_monitor_mode = AsyncMock(return_value=True)
    manager.cleanup = AsyncMock()
    return manager
