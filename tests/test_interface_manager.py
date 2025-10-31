import pytest
from unittest.mock import patch, AsyncMock
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

@pytest.mark.asyncio
async def test_monitor_mode_success(config):
    manager = InterfaceActionManager(config)
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b'', b'')
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc
        
        result = await manager.set_monitor_mode('wlan0')
        assert result == True
        
        mock_exec.assert_called_once_with(
            'netsh', 'wlan', 'set', 'hostednetwork', 'mode=allow',
            stdout=-1, stderr=-1
        )

@pytest.mark.asyncio
async def test_get_access_points(config):
    manager = InterfaceActionManager(config)
    
    test_output = '''
SSID 1 : TestNetwork
    Network type            : Infrastructure
    Authentication         : WPA2-Personal
    Encryption             : CCMP
    BSSID                 : aa:bb:cc:dd:ee:ff
    Signal                : 85%
    Channel              : 1
'''
    
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (test_output.encode(), b'')
        mock_exec.return_value = mock_proc
        
        aps = await manager.get_access_points()
        assert len(aps) == 1
        assert aps[0] == {
            'hostname': 'TestNetwork',
            'encryption': 'WPA2-Personal',
            'mac': 'aa:bb:cc:dd:ee:ff',
            'rssi': -57
        }