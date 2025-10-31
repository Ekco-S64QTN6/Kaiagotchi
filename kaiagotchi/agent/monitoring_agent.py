import asyncio
import random
from typing import ClassVar
from kaiagotchi.agent.base_agent import BaseAgent
from kaiagotchi.data.system_types import SystemState
from kaiagotchi.data.system_types import AccessPoint, AccessPointType, AccessPointProtocol

class MonitoringAgent(BaseAgent):
    """
    The Monitoring Agent is responsible for continuous, passive network scanning
    to discover and maintain the list of known Access Points (APs) in the shared state.

    NOTE: The current implementation uses mock methods for scanning and hardware control.
    """
    AGENT_ID: ClassVar[str] = "MONITOR"
    SCAN_INTERVAL_SECONDS: ClassVar[int] = 5

    def __init__(self, state: SystemState) -> None:
        super().__init__(state)
        # Mock interface name, assuming it's already in monitor mode.
        self.active_interface: str = "wlan0mon" 

    async def start(self) -> None:
        """
        The main asynchronous loop for the Monitoring Agent.
        This loop runs until the stop event is set.
        """
        self.log(f"Starting network monitoring loop on interface {self.active_interface}...")
        while not self.stop_event.is_set():
            await self._perform_scan()
            try:
                # Wait for the next scan interval, allowing for immediate stop if signaled
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.SCAN_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                # Timeout means the stop event wasn't set, so continue the loop
                continue
            except Exception as e:
                self.log(f"An unexpected error occurred in the scan loop: {e}")
                break

    async def cleanup(self) -> None:
        """
        Performs interface cleanup. (Mocked: resetting monitor mode).
        """
        self.log(f"Cleaning up network interface {self.active_interface}. Resetting mode...")
        await asyncio.sleep(0.5) # Simulate time taken for interface reset
        self.log("Cleanup complete.")

    async def _perform_scan(self) -> None:
        """
        Mocks the execution of a network scan and updates the system state.
        This updates the shared SystemState object, which is visible to all other agents.
        """
        self.log("Executing mock scan for new Access Points...")
        new_aps = self._mock_new_aps()

        # Update the centralized system state (atomic operation is assumed for the whole block)
        current_aps = self.state.network.access_points
        updated_count = 0
        new_count = 0

        for ap in new_aps:
            if ap.bssid in current_aps:
                # Mock update existing AP properties (only updating last_seen)
                current_aps[ap.bssid].last_seen = ap.last_seen
                updated_count += 1
            else:
                # Add new AP
                current_aps[ap.bssid] = ap
                new_count += 1

        total_aps = len(current_aps)
        self.log(f"Scan complete. Found {total_aps} total APs. ({new_count} new, {updated_count} refreshed).")


    def _mock_new_aps(self) -> list[AccessPoint]:
        """
        Generates a list of mock AccessPoint objects for simulation.
        This function simulates both new AP discovery and updates to existing APs.
        """
        mock_data = []
        # Simulate discovering a few new APs periodically
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
        
        # Also return a few existing BSSIDs to simulate updates (refreshing last_seen)
        existing_bssid_keys = list(self.state.network.access_points.keys())
        if existing_bssid_keys:
             for bssid in random.sample(existing_bssid_keys, k=min(len(existing_bssid_keys), 2)):
                 # Note: model_copy is used to easily create a copy for mutation/update
                 mock_data.append(self.state.network.access_points[bssid].model_copy(update={'last_seen': asyncio.get_event_loop().time()}))

        return mock_data
