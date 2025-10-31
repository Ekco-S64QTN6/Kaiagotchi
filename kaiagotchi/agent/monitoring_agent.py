import asyncio
import random
from typing import ClassVar, Dict, Any
from .base import KaiagotchiBase
from ..data.system_types import SystemState
from ..data.system_types import AccessPoint, AccessPointType, AccessPointProtocol

# NOTE: The base class has been renamed to KaiagotchiBase to reflect its central role
class MonitoringAgent(KaiagotchiBase): 
    """
    The Monitoring Agent is responsible for continuous, passive network scanning
    to discover and maintain the list of known Access Points (APs) in the shared state.

    NOTE: The current implementation uses mock methods for scanning and hardware control.
    """
    AGENT_ID: ClassVar[str] = "MONITOR"
    SCAN_INTERVAL_SECONDS: ClassVar[int] = 5

    # Since KaiagotchiBase's __init__ takes (config), this __init__ must be updated 
    # to pass the config up, or we assume this agent is instantiated with a pre-configured 
    # SystemState instance (as implied by the original code), which conflicts with 
    # the KaiagotchiBase(config) constructor. 
    #
    # Assuming for now it is passed a full config dictionary:
    def __init__(self, config: Dict[str, Any]) -> None: 
        super().__init__(config) # Pass config up to KaiagotchiBase
        self.agent_config = config.get(self.AGENT_ID, {})
        # Mock interface name, assuming it's already in monitor mode.
        self.active_interface: str = self.agent_config.get('interface_name', "wlan0mon") 

    async def start(self) -> None:
        """
        The main asynchronous loop for the Monitoring Agent.
        This loop runs until the stop event is set (not yet implemented in base).
        """
        self.logger.info(f"[{self.AGENT_ID}] Starting network monitoring loop on interface {self.active_interface}...")
        
        # NOTE: Using a simple infinite loop until a stop method is formally added to KaiagotchiBase
        while True: 
            # 1. Perform a scan and get a list of mock AP objects
            mock_discovered_aps = await self._perform_scan()
            
            # 2. Build the state update dictionary
            ap_updates = {ap.bssid: ap.model_dump() for ap in mock_discovered_aps}
            
            updates = {
                "network": {
                    "access_points": ap_updates,
                    "last_scan_time": asyncio.get_event_loop().time()
                }
            }
            
            # 3. Apply the updates to the shared system state
            await self.update_state(updates)
            
            # The decision cycle will run independently in KaiagotchiBase's main loop.
            await asyncio.sleep(self.SCAN_INTERVAL_SECONDS)

    async def _perform_scan(self) -> list[AccessPoint]:
        """
        [MOCK METHOD] Simulates a network scan and returns a list of AccessPoint objects.
        This function simulates both new AP discovery and updates to existing APs.
        """
        # Fetch the current APs for existing BSSIDs to update
        current_aps = self.system_state.network.access_points # Use the corrected name
        
        mock_data = []
        
        # --- Simulate new AP discovery ---
        if random.random() < 0.3:
            for _ in range(random.randint(1, 3)):
                bssid = f"00:1A:2B:3C:4D:{random.randint(0, 99):02X}"
                ssid = f"Hidden_Network_{random.randint(100, 999)}"
                protocol = random.choice([AccessPointProtocol.WPA2, AccessPointProtocol.WPA3, AccessPointProtocol.OPEN])
                
                new_ap = AccessPoint(
                    bssid=bssid,
                    ssid=ssid,
                    protocol=protocol,
                    ap_type=AccessPointType.INFRASTRUCTURE,
                    channel=random.randint(1, 11),
                    frequency=random.randint(2400, 2500)
                )
                mock_data.append(new_ap)
        
        # --- Simulate updates to existing APs (refreshing last_seen) ---
        existing_bssid_keys = list(current_aps.keys())
        if existing_bssid_keys:
             for bssid in random.sample(existing_bssid_keys, k=min(len(existing_bssid_keys), 2)):
                 # Create an updated AP model from the existing one (only update last_seen)
                 updated_ap = current_aps[bssid].model_copy(update={
                     "last_seen": asyncio.get_event_loop().time(),
                     # Optionally simulate a handshake capture
                     "handshakes_captured": current_aps[bssid].handshakes_captured + (1 if random.random() < 0.1 else 0)
                 })
                 mock_data.append(updated_ap)
                 
        return mock_data
