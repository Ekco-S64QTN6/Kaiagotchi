# kaiagotchi/agent/monitoring_agent.py - Fixed implementation
import asyncio
import logging
import random
import time
from typing import ClassVar, Dict, Any, List, Optional

from .base import KaiagotchiBase

# Import system types with fallbacks
try:
    from kaiagotchi.data.system_types import AccessPoint, AccessPointType, AccessPointProtocol
except ImportError:
    # Fallback implementations
    class AccessPointType:
        INFRASTRUCTURE = "Infrastructure"
        ADHOC = "Ad-Hoc"
    
    class AccessPointProtocol:
        OPEN = "Open"
        WEP = "WEP" 
        WPA = "WPA"
        WPA2 = "WPA2"
        WPA3 = "WPA3"
    
    class AccessPoint:
        def __init__(self, **kwargs):
            self.bssid = kwargs.get('bssid', '00:00:00:00:00:00')
            self.ssid = kwargs.get('ssid')
            self.protocol = kwargs.get('protocol', AccessPointProtocol.WPA2)
            self.ap_type = kwargs.get('ap_type', AccessPointType.INFRASTRUCTURE)
            self.channel = kwargs.get('channel', 1)
            self.frequency = kwargs.get('frequency', 2412)
            self.last_seen = kwargs.get('last_seen', time.time())
            self.handshakes_captured = kwargs.get('handshakes_captured', 0)
            self.is_target = kwargs.get('is_target', False)
        
        def model_copy(self, update=None):
            """Simple copy method for fallback class."""
            data = self.__dict__.copy()
            if update:
                data.update(update)
            return AccessPoint(**data)
        
        def model_dump(self):
            """Simple dump method for fallback class."""
            return self.__dict__.copy()

# Module-specific logger
monitor_logger = logging.getLogger('kaiagotchi.agent.monitoring')

class MonitoringAgent(KaiagotchiBase):
    """
    The Monitoring Agent is responsible for continuous, passive network scanning
    to discover and maintain the list of known Access Points (APs) in the shared state.
    """
    
    AGENT_ID: ClassVar[str] = "monitoring"
    SCAN_INTERVAL_SECONDS: ClassVar[int] = 10  # Reduced from 5 to 10 for better performance

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self.agent_config = config.get('agents', {}).get(self.AGENT_ID, {})
        self.active_interface: str = self.agent_config.get('interface', "wlan0mon")
        self.scan_interval: int = self.agent_config.get('scan_interval', self.SCAN_INTERVAL_SECONDS)
        self._scan_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """
        The main asynchronous loop for the Monitoring Agent.
        """
        self.logger.info(f"[{self.AGENT_ID}] Starting network monitoring on interface {self.active_interface}")
        
        try:
            # Start the scanning task
            self._scan_task = asyncio.create_task(self._scan_loop())
            self._tasks.add(self._scan_task)
            self._scan_task.add_done_callback(self._tasks.discard)
            
            # Also run the base decision cycle
            await super().start()
            
        except Exception as e:
            self.logger.error(f"[{self.AGENT_ID}] Failed to start monitoring: {e}")
            raise

    async def _scan_loop(self) -> None:
        """Continuous scanning loop."""
        while self._running:
            try:
                await self._perform_scan_cycle()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"[{self.AGENT_ID}] Error in scan loop: {e}")
                await asyncio.sleep(5)  # Brief pause before retry

    async def _perform_scan_cycle(self) -> None:
        """
        Perform a single scan cycle and update system state.
        """
        try:
            # Get mock discovered APs
            mock_discovered_aps = await self._perform_scan()
            
            # Convert to dictionary format for state update
            ap_updates = {}
            for ap in mock_discovered_aps:
                if hasattr(ap, 'model_dump'):
                    ap_data = ap.model_dump()
                else:
                    ap_data = {
                        'bssid': ap.bssid,
                        'ssid': ap.ssid,
                        'protocol': ap.protocol,
                        'ap_type': ap.ap_type,
                        'channel': ap.channel,
                        'frequency': ap.frequency,
                        'last_seen': ap.last_seen,
                        'handshakes_captured': ap.handshakes_captured,
                        'is_target': ap.is_target
                    }
                ap_updates[ap.bssid] = ap_data
            
            # Prepare state updates
            updates = {
                "network": {
                    "access_points": ap_updates,
                    "last_scan_time": time.time()
                }
            }
            
            # Apply updates to shared system state
            await self.update_state(updates)
            
            self.logger.debug(f"[{self.AGENT_ID}] Scan completed: {len(mock_discovered_aps)} APs discovered/updated")
            
        except Exception as e:
            self.logger.error(f"[{self.AGENT_ID}] Error during scan cycle: {e}")

    async def _perform_scan(self) -> List[AccessPoint]:
        """
        [MOCK METHOD] Simulates a network scan and returns a list of AccessPoint objects.
        """
        # Get current APs for updates
        current_aps = getattr(self.system_state.network, 'access_points', {})
        
        mock_data = []
        current_time = time.time()
        
        # Simulate new AP discovery (30% chance)
        if random.random() < 0.3:
            for _ in range(random.randint(1, 3)):
                bssid = f"00:1A:2B:3C:4D:{random.randint(0, 99):02X}"
                ssid = f"Test_Network_{random.randint(100, 999)}"
                protocol = random.choice([
                    AccessPointProtocol.WPA2, 
                    AccessPointProtocol.WPA3, 
                    AccessPointProtocol.OPEN,
                    AccessPointProtocol.WEP
                ])
                
                new_ap = AccessPoint(
                    bssid=bssid,
                    ssid=ssid,
                    protocol=protocol,
                    ap_type=AccessPointType.INFRASTRUCTURE,
                    channel=random.randint(1, 11),
                    frequency=2400 + (random.randint(1, 11) * 5),
                    last_seen=current_time,
                    handshakes_captured=0,
                    is_target=random.random() < 0.2  # 20% chance to be target
                )
                mock_data.append(new_ap)
        
        # Simulate updates to existing APs
        if current_aps:
            existing_bssids = list(current_aps.keys())
            samples_to_update = min(len(existing_bssids), random.randint(1, 3))
            
            for bssid in random.sample(existing_bssids, samples_to_update):
                existing_ap = current_aps[bssid]
                
                # Create updated AP
                updated_ap = existing_ap.model_copy(update={
                    "last_seen": current_time,
                    "handshakes_captured": existing_ap.handshakes_captured + (
                        1 if random.random() < 0.05 else 0  # 5% chance to capture handshake
                    )
                })
                mock_data.append(updated_ap)
                
        return mock_data

    async def stop(self):
        """Stop the monitoring agent gracefully."""
        self.logger.info(f"[{self.AGENT_ID}] Stopping monitoring agent")
        
        # Cancel scan task
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        
        # Call parent stop method
        await super().stop()