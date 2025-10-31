# filepath: kaiagotchi/network/action_manager.py
import asyncio
import logging
from typing import Dict, Any, List

class InterfaceActionManager:
    """Manages network interface operations."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._interface = config.get('main', {}).get('iface')

    async def set_monitor_mode(self, interface: str) -> bool:
        """Enable monitor mode on interface."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'netsh', 'wlan', 'set', 'hostednetwork', 'mode=allow',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, _ = await proc.communicate()
            return proc.returncode == 0
        except Exception as e:
            self.logger.error(f"Monitor mode failed: {e}")
            return False

    async def cleanup(self):
        """Cleanup resources."""
        try:
            # Restore normal mode
            await asyncio.create_subprocess_exec(
                'netsh', 'wlan', 'set', 'hostednetwork', 'mode=disallow'
            )
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")

    async def get_access_points(self) -> List[Dict[str, Any]]:
        """Scan and parse network data."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'netsh', 'wlan', 'show', 'networks', 'mode=Bssid',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return self._parse_network_list(stdout.decode())
        except Exception as e:
            self.logger.error(f"Error scanning networks: {e}")
            return []

    def _parse_network_list(self, output: str) -> List[Dict[str, Any]]:
        """Parse Windows netsh output into structured data."""
        networks = []
        current = {}
        
        for line in output.split('\n'):
            line = line.strip()
            
            if line.startswith('SSID'):
                if current and 'hostname' in current:
                    networks.append(current.copy())
                current = {}
                ssid = line.split(':', 1)[1].strip()
                current['hostname'] = ssid
                
            elif ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'Authentication':
                    current['encryption'] = value
                elif key == 'BSSID':
                    current['mac'] = value
                elif key == 'Signal':
                    current['rssi'] = self._signal_to_rssi(value)
                    
        if current and 'hostname' in current:
            networks.append(current.copy())
            
        return networks

    def _signal_to_rssi(self, signal: str) -> int:
        """Convert Windows signal strength to RSSI."""
        try:
            percent = int(signal.replace('%', ''))
            return -50 - ((100 - percent) // 2)
        except ValueError:
            return -100
