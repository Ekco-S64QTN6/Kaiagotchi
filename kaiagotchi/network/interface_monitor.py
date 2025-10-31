import threading
import queue
import subprocess
import time
import logging
import re
import psutil
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from queue import Queue as QueueType
else:
    QueueType = queue.Queue

monitor_logger = logging.getLogger('network.monitor')

class InterfaceMonitor:
    """
    Enhanced network interface monitor with multiple data sources and better error handling.
    """
    
    def __init__(self, stop_event: threading.Event, update_queue: QueueType[Dict[str, Any]], poll_interval: float = 5.0):
        self._stop_event = stop_event
        self._queue = update_queue
        self._poll_interval = poll_interval
        self._thread = threading.Thread(
            target=self._run, 
            name="InterfaceMonitor", 
            daemon=True
        )
        self._last_state: Dict[str, Any] = {}

    def start(self) -> None:
        """Starts the monitoring thread."""
        monitor_logger.info("Starting enhanced InterfaceMonitor thread.")
        self._thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        """Waits for the monitoring thread to terminate gracefully."""
        monitor_logger.debug("Waiting for InterfaceMonitor thread to join.")
        self._thread.join(timeout)

    def _run(self) -> None:
        """Main monitoring loop with multiple data collection methods."""
        while not self._stop_event.is_set():
            try:
                # Collect data from multiple sources
                ifconfig_data = self._get_ifconfig_data()
                ip_data = self._get_ip_addr_data()
                iw_data = self._get_iw_data()
                system_data = self._get_system_network_data()
                
                # Merge all data sources
                merged_data = self._merge_interface_data(
                    ifconfig_data, ip_data, iw_data, system_data
                )
                
                # Only send update if state changed significantly
                if self._has_state_changed(merged_data):
                    try:
                        update = {"network": merged_data}
                        self._queue.put_nowait(update)
                        self._last_state = merged_data
                        monitor_logger.debug(f"Published network state update with {len(merged_data['interfaces'])} interfaces")
                    except queue.Full:
                        monitor_logger.warning("Agent update queue full. Dropping network update.")
                else:
                    monitor_logger.debug("Network state unchanged, skipping update")
                        
            except Exception as e:
                monitor_logger.error(f"Error in monitor loop: {e}", exc_info=True)
            
            # Controlled sleep with interruptible wait
            self._stop_event.wait(self._poll_interval)
        
        monitor_logger.info("InterfaceMonitor stopped gracefully.")

    def _get_ifconfig_data(self) -> Dict[str, Any]:
        """Get interface data using ifconfig."""
        try:
            proc = subprocess.run(
                ['/sbin/ifconfig'],
                capture_output=True, 
                text=True, 
                timeout=5,
                check=False
            )
            
            if proc.returncode == 0:
                return self._parse_ifconfig_output(proc.stdout)
            else:
                monitor_logger.debug("ifconfig command failed")
                return {"interfaces": {}, "overall_status": "ERROR"}
                
        except subprocess.TimeoutExpired:
            monitor_logger.warning("ifconfig command timed out")
            return {"interfaces": {}, "overall_status": "TIMEOUT"}
        except Exception as e:
            monitor_logger.debug(f"ifconfig data collection failed: {e}")
            return {"interfaces": {}, "overall_status": "ERROR"}

    def _get_ip_addr_data(self) -> Dict[str, Any]:
        """Get interface data using modern ip command."""
        try:
            proc = subprocess.run(
                ['ip', '-o', 'addr', 'show'],
                capture_output=True, 
                text=True, 
                timeout=5,
                check=True
            )
            
            interfaces = {}
            for line in proc.stdout.split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 4:
                        iface = parts[1]
                        if iface not in interfaces:
                            interfaces[iface] = {'ip_addresses': []}
                        
                        if parts[2] == 'inet':
                            ip_info = {
                                'address': parts[3].split('/')[0],
                                'prefixlen': parts[3].split('/')[1] if '/' in parts[3] else '32'
                            }
                            interfaces[iface]['ip_addresses'].append(ip_info)
            
            return {"interfaces": interfaces}
            
        except Exception as e:
            monitor_logger.debug(f"ip addr data collection failed: {e}")
            return {"interfaces": {}}

    def _get_iw_data(self) -> Dict[str, Any]:
        """Get wireless interface data using iw."""
        try:
            proc = subprocess.run(
                ['iw', 'dev'],
                capture_output=True, 
                text=True, 
                timeout=5,
                check=False
            )
            
            wireless_data = {}
            if proc.returncode == 0:
                current_iface = None
                for line in proc.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('Interface'):
                        current_iface = line.split()[1]
                        wireless_data[current_iface] = {'wireless': True}
                    elif 'type' in line and current_iface:
                        wireless_data[current_iface]['type'] = line.split('type ')[1]
                    elif 'channel' in line and current_iface:
                        wireless_data[current_iface]['channel'] = line.split('channel ')[1]
            
            return {"wireless_interfaces": wireless_data}
            
        except Exception as e:
            monitor_logger.debug(f"iw data collection failed: {e}")
            return {"wireless_interfaces": {}}

    def _get_system_network_data(self) -> Dict[str, Any]:
        """Get network data using psutil for cross-platform compatibility."""
        try:
            stats = psutil.net_io_counters(pernic=True)
            interfaces = {}
            
            for iface, counters in stats.items():
                interfaces[iface] = {
                    'bytes_sent': counters.bytes_sent,
                    'bytes_recv': counters.bytes_recv,
                    'packets_sent': counters.packets_sent,
                    'packets_recv': counters.packets_recv,
                    'dropin': counters.dropin,
                    'dropout': counters.dropout
                }
            
            return {"system_stats": interfaces}
            
        except Exception as e:
            monitor_logger.debug(f"System network data collection failed: {e}")
            return {"system_stats": {}}

    def _merge_interface_data(self, *data_sources: Dict[str, Any]) -> Dict[str, Any]:
        """Merge data from multiple sources into unified interface state."""
        merged = {
            "overall_status": "UNKNOWN",
            "interface_count": 0,
            "timestamp": time.time(),
            "interfaces": {},
            "wireless_interfaces": {},
            "system_stats": {}
        }
        
        # Merge all data sources
        for source in data_sources:
            merged.update(source)
        
        # Calculate overall status
        up_interfaces = [
            iface for iface in merged["interfaces"].values() 
            if iface.get("status") == "UP" and iface.get("ipv4_address")
        ]
        
        if up_interfaces:
            merged["overall_status"] = "READY"
        elif merged["interfaces"]:
            merged["overall_status"] = "NET_DOWN"
        else:
            merged["overall_status"] = "NO_INTERFACES"
        
        merged["interface_count"] = len(merged["interfaces"])
        return merged

    def _has_state_changed(self, new_state: Dict[str, Any]) -> bool:
        """Check if network state has changed significantly since last update."""
        if not self._last_state:
            return True
        
        # Compare interface counts
        if len(new_state["interfaces"]) != len(self._last_state.get("interfaces", {})):
            return True
        
        # Compare overall status
        if new_state.get("overall_status") != self._last_state.get("overall_status"):
            return True
        
        # Compare key interface states
        for iface_name, iface_data in new_state["interfaces"].items():
            if iface_name not in self._last_state.get("interfaces", {}):
                return True
            
            last_iface = self._last_state["interfaces"][iface_name]
            key_fields = ["status", "ipv4_address", "rx_packets", "tx_packets"]
            for field in key_fields:
                if iface_data.get(field) != last_iface.get(field):
                    return True
        
        return False

    def _parse_ifconfig_output(self, output: str) -> Dict[str, Any]:
        """Parse ifconfig output with improved error handling."""
        interfaces = {}
        current_iface = None
        
        for line in output.split('\n'):
            line = line.strip()
            
            # Interface header detection
            if line and not line.startswith(' ') and ':' in line.split()[0]:
                iface_name = line.split(':')[0]
                current_iface = iface_name
                
                interfaces[current_iface] = {
                    "name": current_iface,
                    "flags": [],
                    "mtu": 1500,
                    "status": "DOWN",
                    "mac_address": None,
                    "ipv4_address": None,
                    "netmask": None,
                    "rx_packets": 0,
                    "tx_packets": 0,
                }
                
                # Parse flags and MTU from header
                flags_match = re.search(r'flags=\d+<([^>]+)>', line)
                if flags_match:
                    interfaces[current_iface]["flags"] = flags_match.group(1).split(',')
                    interfaces[current_iface]["status"] = "UP" if "UP" in flags_match.group(1) else "DOWN"
                
                mtu_match = re.search(r'mtu\s+(\d+)', line)
                if mtu_match:
                    interfaces[current_iface]["mtu"] = int(mtu_match.group(1))
                
                continue
            
            if not current_iface:
                continue
                
            # Parse IP address
            inet_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(\d+\.\d+\.\d+\.\d+)', line)
            if inet_match:
                interfaces[current_iface]["ipv4_address"] = inet_match.group(1)
                interfaces[current_iface]["netmask"] = inet_match.group(2)
            
            # Parse MAC address
            mac_match = re.search(r'ether\s+([0-9a-fA-F:]{17})', line)
            if mac_match:
                interfaces[current_iface]["mac_address"] = mac_match.group(1).lower()
            
            # Parse packet statistics
            rx_match = re.search(r'RX packets\s+(\d+)', line)
            if rx_match:
                interfaces[current_iface]["rx_packets"] = int(rx_match.group(1))
            
            tx_match = re.search(r'TX packets\s+(\d+)', line)
            if tx_match:
                interfaces[current_iface]["tx_packets"] = int(tx_match.group(1))
        
        return {"interfaces": interfaces}