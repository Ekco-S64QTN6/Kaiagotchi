# filepath: kaiagotchi/network/action_manager.py
import asyncio
import logging
import re
import os
import tempfile
from typing import Dict, Any, List, Optional

class InterfaceActionManager:
    """Manages network interface operations for Linux systems with improved error handling."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._interface = config.get('main', {}).get('iface', 'wlan0')
        self._monitor_interface: Optional[str] = None
        self._killed_processes: List[str] = []

    async def set_monitor_mode(self, interface: str, timeout: float = 30.0) -> bool:
        """Enable monitor mode on interface with proper process management."""
        try:
            self.logger.info(f"Attempting to set monitor mode on {interface}")
            
            # Check if interface exists
            if not await self._interface_exists(interface):
                self.logger.error(f"Interface {interface} does not exist")
                return False

            # Stop interfering processes with better tracking
            killed = await self._stop_interfering_processes(interface)
            if killed:
                self._killed_processes = killed
                self.logger.info(f"Stopped {len(killed)} interfering processes")

            # Start monitor mode with timeout
            proc = await asyncio.create_subprocess_exec(
                'airmon-ng', 'start', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                self.logger.error("airmon-ng timeout - terminating process")
                proc.terminate()
                await asyncio.sleep(2)
                if proc.returncode is None:
                    proc.kill()
                return False

            if proc.returncode == 0:
                output = stdout.decode().lower()
                # Extract monitor interface name from output
                monitor_iface = self._extract_monitor_interface(output, interface)
                if monitor_iface:
                    self._monitor_interface = monitor_iface
                    self.logger.info(f"Monitor mode enabled: {interface} -> {monitor_iface}")
                else:
                    self._monitor_interface = interface + 'mon'
                    self.logger.info(f"Monitor mode enabled on {interface} (assuming {self._monitor_interface})")
                return True
            else:
                error_msg = stderr.decode().strip()
                self.logger.error(f"airmon-ng failed (code {proc.returncode}): {error_msg}")
                return False
                
        except FileNotFoundError:
            self.logger.error("airmon-ng not found. Please install aircrack-ng package.")
            return False
        except Exception as e:
            self.logger.error(f"Monitor mode setup failed: {e}")
            return False

    async def _stop_interfering_processes(self, interface: str) -> List[str]:
        """Stop processes that might interfere with monitor mode."""
        try:
            # Get list of processes to kill
            proc = await asyncio.create_subprocess_exec(
                'airmon-ng', 'check', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                return []

            # Parse and return killed process names
            killed = []
            for line in stdout.decode().split('\n'):
                if line.strip() and 'Process' in line:
                    # Extract process names from airmon-ng output
                    parts = line.split()
                    if len(parts) > 1:
                        killed.append(parts[1])
            
            # Actually kill the processes
            if killed:
                kill_proc = await asyncio.create_subprocess_exec(
                    'airmon-ng', 'check', 'kill',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await kill_proc.communicate()
            
            return killed
            
        except Exception as e:
            self.logger.warning(f"Failed to stop interfering processes: {e}")
            return []

    async def _interface_exists(self, interface: str) -> bool:
        """Check if network interface exists."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'ip', 'link', 'show', 'dev', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    def _extract_monitor_interface(self, output: str, base_interface: str) -> Optional[str]:
        """Extract monitor interface name from airmon-ng output."""
        # Look for common patterns in airmon-ng output
        patterns = [
            rf"monitor mode enabled on ({re.escape(base_interface)}\w*)",
            rf"\(mac80211 monitor mode vif enabled for ({re.escape(base_interface)}\w*)",
            rf"interface ({re.escape(base_interface)}\w+) in monitor mode"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None

    async def set_managed_mode(self, interface: str, timeout: float = 30.0) -> bool:
        """Restore managed mode with proper cleanup."""
        try:
            target_interface = interface
            
            # If we have a monitor interface, stop it first
            if self._monitor_interface and await self._interface_exists(self._monitor_interface):
                target_interface = self._monitor_interface
                self.logger.info(f"Stopping monitor interface: {target_interface}")

            proc = await asyncio.create_subprocess_exec(
                'airmon-ng', 'stop', target_interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                self.logger.error("airmon-ng stop timeout")
                proc.terminate()
                return False

            # Restart network services if we killed processes earlier
            if self._killed_processes:
                await self._restart_network_services()
                self._killed_processes.clear()

            self._monitor_interface = None
            self.logger.info(f"Managed mode restored for {interface}")
            return proc.returncode == 0
            
        except Exception as e:
            self.logger.error(f"Managed mode restoration failed: {e}")
            return False

    async def _restart_network_services(self) -> bool:
        """Restart network services that were stopped."""
        try:
            services = ['NetworkManager', 'wpa_supplicant']
            
            for service in services:
                proc = await asyncio.create_subprocess_exec(
                    'systemctl', 'restart', service,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                
                if proc.returncode == 0:
                    self.logger.info(f"Restarted {service}")
                else:
                    self.logger.warning(f"Failed to restart {service}")
            
            return True
        except Exception as e:
            self.logger.error(f"Network service restart failed: {e}")
            return False

    async def get_access_points(self, scan_time: int = 10) -> List[Dict[str, Any]]:
        """Scan for access points with improved parsing and error handling."""
        try:
            with tempfile.NamedTemporaryFile(prefix='airodump_', suffix='.csv', delete=False) as temp_file:
                temp_path = temp_file.name

            try:
                # Run airodump-ng with specific channel hopping disabled for faster results
                proc = await asyncio.create_subprocess_exec(
                    'timeout', f'{scan_time}s', 'airodump-ng',
                    '--output-format', 'csv', '-w', temp_path[:-4],  # Remove .csv extension
                    '--write-interval', '1', '--band', 'abg',
                    self._monitor_interface or self._interface,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await proc.communicate()
                
                if proc.returncode not in [0, 124]:  # 124 is timeout exit code
                    self.logger.error(f"airodump-ng failed: {stderr.decode()}")
                    return []

                # Read and parse the output file
                if os.path.exists(temp_path):
                    with open(temp_path, 'r', errors='ignore') as f:
                        content = f.read()
                    networks = self._parse_airodump_output(content)
                    self.logger.info(f"Found {len(networks)} access points")
                    return networks
                else:
                    self.logger.warning("airodump-ng output file not found")
                    return []
                    
            finally:
                # Cleanup temporary files
                for ext in ['.csv', '.kismet.csv', '.kismet.netxml']:
                    cleanup_file = temp_path[:-4] + ext
                    if os.path.exists(cleanup_file):
                        try:
                            os.remove(cleanup_file)
                        except OSError:
                            pass
                            
        except Exception as e:
            self.logger.error(f"Access point scan failed: {e}")
            return []

    def _parse_airodump_output(self, output: str) -> List[Dict[str, Any]]:
        """Improved airodump-ng CSV parsing with better error handling."""
        networks = []
        lines = output.split('\n')
        in_ap_section = False
        
        for line_num, line in enumerate(lines):
            line = line.strip()
            
            if not line:
                continue
                
            # Detect AP section start
            if line.startswith('BSSID,') and 'First time seen' in line:
                in_ap_section = True
                continue
                
            # Detect client section (end of AP section)
            if line.startswith('Station MAC,') and 'First time seen' in line:
                break
                
            if in_ap_section and line:
                try:
                    # Handle CSV parsing with quoted fields
                    parts = []
                    in_quotes = False
                    current_part = []
                    
                    for char in line:
                        if char == '"':
                            in_quotes = not in_quotes
                        elif char == ',' and not in_quotes:
                            parts.append(''.join(current_part).strip())
                            current_part = []
                        else:
                            current_part.append(char)
                    
                    if current_part:
                        parts.append(''.join(current_part).strip())
                    
                    if len(parts) >= 14:
                        network = {
                            'bssid': parts[0].upper(),
                            'essid': parts[13] if len(parts) > 13 and parts[13] else 'Hidden',
                            'encryption': self._parse_encryption(parts[5]),
                            'rssi': int(parts[8]) if parts[8] and parts[8].lstrip('-').isdigit() else -100,
                            'channel': int(parts[3]) if parts[3] and parts[3].isdigit() else 0,
                            'speed': parts[4] if len(parts) > 4 else '',
                            'beacons': int(parts[6]) if parts[6] and parts[6].isdigit() else 0,
                            'ivs': int(parts[9]) if len(parts) > 9 and parts[9] and parts[9].isdigit() else 0
                        }
                        networks.append(network)
                        
                except (ValueError, IndexError, AttributeError) as e:
                    self.logger.debug(f"Failed to parse AP line {line_num}: {e}")
                    continue
        
        return networks

    def _parse_encryption(self, enc_str: str) -> str:
        """Improved encryption type parsing."""
        if not enc_str:
            return 'OPEN'
            
        enc_str = enc_str.upper()
        
        if 'WPA3' in enc_str:
            return 'WPA3'
        elif 'WPA2' in enc_str:
            return 'WPA2'
        elif 'WPA' in enc_str:
            return 'WPA'
        elif 'WEP' in enc_str:
            return 'WEP'
        elif 'OPN' in enc_str:
            return 'OPEN'
        else:
            return 'UNKNOWN'

    async def get_interface_info(self, interface: str) -> Dict[str, Any]:
        """Get comprehensive interface information using multiple tools."""
        try:
            info = {
                'interface': interface,
                'exists': False,
                'mode': 'unknown',
                'state': 'unknown',
                'mac_address': '',
                'supported_modes': [],
                'frequencies': [],
                'tx_power': 0
            }
            
            # Check if interface exists
            info['exists'] = await self._interface_exists(interface)
            if not info['exists']:
                return info
            
            # Get basic info from iwconfig
            iwconfig_info = await self._get_iwconfig_info(interface)
            info.update(iwconfig_info)
            
            # Get detailed info from iw
            iw_info = await self._get_iw_info(interface)
            info.update(iw_info)
            
            return info
            
        except Exception as e:
            self.logger.error(f"Interface info collection failed: {e}")
            return {'interface': interface, 'exists': False}

    async def _get_iwconfig_info(self, interface: str) -> Dict[str, Any]:
        """Get interface info from iwconfig."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'iwconfig', interface,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                return self._parse_iwconfig_output(stdout.decode())
            return {}
        except Exception as e:
            self.logger.debug(f"iwconfig failed: {e}")
            return {}

    async def _get_iw_info(self, interface: str) -> Dict[str, Any]:
        """Get interface info from iw (more modern)."""
        try:
            # Get interface info
            proc = await asyncio.create_subprocess_exec(
                'iw', 'dev', interface, 'info',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            info = {}
            if proc.returncode == 0:
                iw_output = stdout.decode()
                # Parse iw dev info
                if 'type monitor' in iw_output:
                    info['mode'] = 'monitor'
                elif 'type managed' in iw_output:
                    info['mode'] = 'managed'
            
            # Get supported modes
            proc = await asyncio.create_subprocess_exec(
                'iw', 'list',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0:
                supported_modes = []
                iw_list_output = stdout.decode()
                if 'Supported interface modes' in iw_list_output:
                    for mode in ['monitor', 'managed', 'ap', 'adhoc']:
                        if mode in iw_list_output:
                            supported_modes.append(mode)
                info['supported_modes'] = supported_modes
            
            return info
            
        except Exception as e:
            self.logger.debug(f"iw command failed: {e}")
            return {}

    def _parse_iwconfig_output(self, output: str) -> Dict[str, Any]:
        """Parse iwconfig output with improved regex patterns."""
        info = {
            'mode': 'unknown',
            'frequency': 0,
            'channel': 0,
            'tx_power': 0,
            'state': 'unknown'
        }
        
        # Parse mode
        mode_patterns = [
            r'Mode:(\w+)',
            r'Mode\s*=\s*(\w+)',
            r'(\w+)\s+mode'  # More flexible pattern
        ]
        
        for pattern in mode_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                info['mode'] = match.group(1).lower()
                break
        
        # Parse frequency
        freq_patterns = [
            r'Frequency:([\d.]+)\s*GHz',
            r'Freq:([\d.]+)\s*GHz',
            r'([\d.]+)\s*GHz'  # General GHz pattern
        ]
        
        for pattern in freq_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                try:
                    freq_ghz = float(match.group(1))
                    info['frequency'] = int(freq_ghz * 1000)  # Convert to MHz
                    info['channel'] = self._frequency_to_channel(freq_ghz)
                    break
                except ValueError:
                    continue
        
        # Parse TX power
        tx_patterns = [
            r'Tx-Power=([-\d.]+)\s*dBm',
            r'Tx\s*Power[=:]\s*([-\d.]+)\s*dBm'
        ]
        
        for pattern in tx_patterns:
            match = re.search(pattern, output)
            if match:
                try:
                    info['tx_power'] = int(float(match.group(1)))
                    break
                except ValueError:
                    continue
        
        # Parse interface state
        if 'ESSID:off/any' in output or 'Not-Associated' in output:
            info['state'] = 'disconnected'
        elif 'ESSID:' in output:
            info['state'] = 'connected'
        
        return info

    def _frequency_to_channel(self, freq_ghz: float) -> int:
        """Convert frequency in GHz to WiFi channel with complete mapping."""
        # 2.4 GHz band channels
        if 2.401 <= freq_ghz <= 2.483:
            return int(round((freq_ghz - 2.407) / 0.005)) + 1
        # 5 GHz band channels
        elif 5.150 <= freq_ghz <= 5.350:
            return int(round((freq_ghz - 5.000) / 0.005)) + 36
        elif 5.470 <= freq_ghz <= 5.725:
            return int(round((freq_ghz - 5.000) / 0.005)) + 36
        elif 5.725 <= freq_ghz <= 5.850:
            return int(round((freq_ghz - 5.000) / 0.005)) + 36
        # 6 GHz band (Wi-Fi 6E)
        elif 5.925 <= freq_ghz <= 7.125:
            return int(round((freq_ghz - 5.925) / 0.005)) + 1
        else:
            return 0

    async def cleanup(self):
        """Comprehensive cleanup with proper error handling."""
        try:
            self.logger.info("Performing network cleanup")
            
            # Restore managed mode if in monitor mode
            current_info = await self.get_interface_info(self._interface)
            if current_info.get('mode') == 'monitor':
                await self.set_managed_mode(self._interface)
            
            # Restart network services if we killed any
            if self._killed_processes:
                await self._restart_network_services()
                self._killed_processes.clear()
                
            self._monitor_interface = None
            self.logger.info("Network cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")