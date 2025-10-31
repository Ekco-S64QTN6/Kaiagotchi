# filepath: kaiagotchi/network/action_manager.py
import asyncio
import logging
import re
from typing import Dict, Any, List

class InterfaceActionManager:
    """Manages network interface operations for Linux systems."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._interface = config.get('main', {}).get('iface', 'wlan0')

    async def set_monitor_mode(self, interface: str) -> bool:
        """Enable monitor mode on interface using airmon-ng."""
        try:
            # Stop interfering processes
            proc = await asyncio.create_subprocess_exec(
                'airmon-ng', 'check', 'kill',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

            # Start monitor mode
            proc = await asyncio.create_subprocess_exec(
                'airmon-ng', 'start', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                self.logger.info(f"Monitor mode enabled on {interface}")
                return True
            else:
                self.logger.error(f"Failed to enable monitor mode: {stderr.decode()}")
                return False
                
        except FileNotFoundError:
            self.logger.error("airmon-ng not found. Please install aircrack-ng package.")
            return False
        except Exception as e:
            self.logger.error(f"Monitor mode failed: {e}")
            return False

    async def set_managed_mode(self, interface: str) -> bool:
        """Restore managed mode on interface."""
        try:
            # Remove monitor interface
            if 'mon' in interface:
                base_iface = interface.rstrip('mon')
                proc = await asyncio.create_subprocess_exec(
                    'airmon-ng', 'stop', interface,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                
                # Restart network manager
                proc = await asyncio.create_subprocess_exec(
                    'systemctl', 'restart', 'NetworkManager',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                return True
            return True
        except Exception as e:
            self.logger.error(f"Managed mode failed: {e}")
            return False

    async def cleanup(self):
        """Cleanup resources and restore managed mode."""
        try:
            if self._interface:
                await self.set_managed_mode(self._interface)
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")

    async def get_access_points(self) -> List[Dict[str, Any]]:
        """Scan for access points using airodump-ng."""
        try:
            # Use a short scan to get AP list
            proc = await asyncio.create_subprocess_exec(
                'timeout', '10s', 'airodump-ng', '--output-format', 'csv', 
                '-w', '/tmp/scan', self._interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            # Parse the CSV output
            return self._parse_airodump_output(stdout.decode())
            
        except FileNotFoundError:
            self.logger.error("airodump-ng not found. Please install aircrack-ng package.")
            return []
        except Exception as e:
            self.logger.error(f"Error scanning networks: {e}")
            return []

    def _parse_airodump_output(self, output: str) -> List[Dict[str, Any]]:
        """Parse airodump-ng CSV output into structured data."""
        networks = []
        
        # Skip header lines and find the start of AP data
        lines = output.split('\n')
        in_ap_section = False
        
        for line in lines:
            line = line.strip()
            
            # Detect start of AP section
            if 'BSSID' in line and 'First time seen' in line:
                in_ap_section = True
                continue
                
            # Detect start of client section (end of AP section)
            if 'Station MAC' in line and 'First time seen' in line:
                break
                
            if in_ap_section and line and ',' in line:
                parts = [part.strip() for part in line.split(',')]
                if len(parts) >= 14:
                    try:
                        network = {
                            'mac': parts[0],
                            'hostname': parts[13] if len(parts) > 13 else 'Unknown',
                            'encryption': self._parse_encryption(parts[5]),
                            'rssi': int(parts[8]) if parts[8] else -100,
                            'channel': int(parts[3]) if parts[3] else 1
                        }
                        networks.append(network)
                    except (ValueError, IndexError) as e:
                        self.logger.debug(f"Failed to parse AP line: {line} - {e}")
                        continue
        
        return networks

    def _parse_encryption(self, enc_str: str) -> str:
        """Parse encryption type from airodump-ng output."""
        if not enc_str:
            return 'OPEN'
        enc_str = enc_str.upper()
        
        if 'WPA2' in enc_str:
            return 'WPA2'
        elif 'WPA' in enc_str:
            return 'WPA'
        elif 'WEP' in enc_str:
            return 'WEP'
        else:
            return 'OPEN'

    async def get_interface_info(self, interface: str) -> Dict[str, Any]:
        """Get interface information using iwconfig."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'iwconfig', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                return self._parse_iwconfig_output(stdout.decode(), interface)
            return {}
        except Exception as e:
            self.logger.error(f"Error getting interface info: {e}")
            return {}

    def _parse_iwconfig_output(self, output: str, interface: str) -> Dict[str, Any]:
        """Parse iwconfig output for interface details."""
        info = {
            'interface': interface,
            'mode': 'unknown',
            'frequency': 0,
            'channel': 0,
            'tx_power': 0
        }
        
        # Parse mode
        mode_match = re.search(r'Mode:(\w+)', output)
        if mode_match:
            info['mode'] = mode_match.group(1).lower()
            
        # Parse frequency/channel
        freq_match = re.search(r'Frequency:([\d.]+) GHz', output)
        if freq_match:
            freq_ghz = float(freq_match.group(1))
            info['frequency'] = int(freq_ghz * 1000)  # Convert to MHz
            info['channel'] = self._frequency_to_channel(freq_ghz)
            
        # Parse TX power
        tx_match = re.search(r'Tx-Power=([\d.]+) dBm', output)
        if tx_match:
            info['tx_power'] = int(float(tx_match.group(1)))
            
        return info

    def _frequency_to_channel(self, freq_ghz: float) -> int:
        """Convert frequency in GHz to WiFi channel."""
        # Common 2.4GHz channels
        if 2.4 <= freq_ghz <= 2.5:
            return int((freq_ghz - 2.407) / 0.005) + 1
        # Common 5GHz channels (simplified)
        elif 5.0 <= freq_ghz <= 6.0:
            return int((freq_ghz - 5.0) / 0.005) + 36
        return 0