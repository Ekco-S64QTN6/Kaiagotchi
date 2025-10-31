import threading
import queue
import subprocess
import time
import logging
import re # Added for robust text parsing
from typing import Dict, Any, TYPE_CHECKING

# Type checking import for Queue type hint to avoid circular dependencies
if TYPE_CHECKING:
    from queue import Queue as QueueType
else:
    QueueType = queue.Queue

monitor_logger = logging.getLogger('network.monitor')

# --- Regular Expressions for ifconfig/ip command parsing ---
# 1. Regex to capture the start of a new interface block: (name) and (flags)
IFACE_HEADER_RE = re.compile(r"^(\w+):\s+flags=\d+<([^>]+)>\s+mtu\s+(\d+)")

# 2. Regex to capture IPv4 address and netmask
INET_RE = re.compile(r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+netmask\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")

# 3. Regex to capture MAC address
MAC_RE = re.compile(r"ether\s+([0-9a-fA-F:]+)")

# 4. Regex to capture packet statistics
RX_TX_RE = re.compile(r"(RX|TX)\s+packets\s+(\d+)\s+bytes\s+(\d+)\s+\(([^)]+)\)")
# -----------------------------------------------------------


class InterfaceMonitor:
    """
    Runs in a dedicated background thread to periodically execute blocking
    OS commands (like ifconfig) and report state changes back to the 
    main agent via a queue.
    """
    
    # We will use the 'ifconfig' command for initial state gathering
    OS_COMMAND = ["/sbin/ifconfig"]

    def __init__(self, stop_event: threading.Event, update_queue: QueueType[Dict[str, Any]], poll_interval: float = 5.0):
        """
        Args:
            stop_event: The threading.Event shared with the main agent to signal shutdown.
            update_queue: The queue used to safely hand off data back to the main agent thread.
            poll_interval: The time in seconds between checks.
        """
        self._stop_event = stop_event
        self._queue = update_queue
        self._poll_interval = poll_interval
        self._thread = threading.Thread(
            target=self._run, 
            name="InterfaceMonitor", 
            daemon=True
        )

    def start(self) -> None:
        """Starts the monitoring thread."""
        monitor_logger.info("Starting InterfaceMonitor thread.")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        """Waits for the monitoring thread to terminate gracefully."""
        monitor_logger.debug("Waiting for InterfaceMonitor thread to join.")
        self._thread.join(timeout)

    def _run(self) -> None:
        """The main loop for the monitoring thread."""
        while not self._stop_event.is_set():
            try:
                # --- 1. Execute Blocking OS Command ---
                proc = subprocess.run(
                    self.OS_COMMAND, 
                    capture_output=True, 
                    text=True, 
                    timeout=5,
                    check=False # Check is handled manually as ifconfig may fail if interfaces are down
                )
                
                # If command execution fails
                if proc.returncode != 0:
                     monitor_logger.error(f"OS command failed with code {proc.returncode}: {proc.stderr.strip()}")
                     # Skip parsing and wait for next poll
                     self._stop_event.wait(self._poll_interval)
                     continue

                # --- 2. Parse Data and Prepare Update ---
                parsed_data = self._parse_output(proc.stdout)
                
                # --- 3. Publish to Queue ---
                try:
                    # Key the update under a unique monitor namespace
                    update = {"network": parsed_data}
                    self._queue.put_nowait(update)
                    monitor_logger.debug(f"Published network state update to queue with {len(parsed_data['interfaces'])} interfaces.")
                except queue.Full:
                    monitor_logger.warning("Agent update queue is full. Dropping network status update.")
            
            # --- 4. Handle Errors ---
            except subprocess.TimeoutExpired:
                monitor_logger.warning(f"OS command '{self.OS_COMMAND[0]}' timed out after 5s.")
            except Exception as e:
                monitor_logger.critical(f"Unhandled exception in monitor loop: {e}", exc_info=True)

            # --- 5. Controlled Sleep ---
            self._stop_event.wait(self._poll_interval)
        
        monitor_logger.info("InterfaceMonitor stopped gracefully.")

    def _parse_output(self, output: str) -> Dict[str, Any]:
        """
        Parses the multi-line output of the ifconfig command into a structured dictionary.
        
        The returned dictionary is namespaced and ready to be merged into the
        main agent's state.
        
        Args:
            output: The raw stdout string from the ifconfig subprocess call.
            
        Returns:
            A dictionary containing the parsed interface data.
        """
        interfaces: Dict[str, Dict[str, Any]] = {}
        current_iface_name: str | None = None
        
        for line in output.split('\n'):
            line = line.strip()

            # 1. Look for the start of a new interface block (Interface Header)
            header_match = IFACE_HEADER_RE.match(line)
            if header_match:
                current_iface_name = header_match.group(1)
                flags = header_match.group(2).split(',')
                mtu = int(header_match.group(3))
                
                # Initialize the new interface entry
                interfaces[current_iface_name] = {
                    "name": current_iface_name,
                    "flags": flags,
                    "mtu": mtu,
                    "status": "UP" if "UP" in flags else "DOWN",
                    "mac_address": None,
                    "ipv4_address": None,
                    "rx_packets": 0,
                    "tx_packets": 0,
                }
                continue # Move to the next line

            # Must be inside an interface block to continue parsing
            if not current_iface_name or current_iface_name not in interfaces:
                continue

            # Reference the current interface dictionary
            current_iface = interfaces[current_iface_name]

            # 2. Look for IPv4 and Netmask
            inet_match = INET_RE.search(line)
            if inet_match:
                current_iface["ipv4_address"] = inet_match.group(1)
                current_iface["netmask"] = inet_match.group(2)
                continue

            # 3. Look for MAC Address
            mac_match = MAC_RE.search(line)
            if mac_match:
                current_iface["mac_address"] = mac_match.group(1)
                continue
            
            # 4. Look for RX/TX Statistics
            rx_tx_match = RX_TX_RE.search(line)
            if rx_tx_match:
                direction = rx_tx_match.group(1)
                packets = int(rx_tx_match.group(2))
                
                if direction == "RX":
                    current_iface["rx_packets"] = packets
                elif direction == "TX":
                    current_iface["tx_packets"] = packets
                continue


        # Compile the final result structure for the 'network' state key
        overall_status = "READY" if any(i.get('ipv4_address') for i in interfaces.values()) else "NET_DOWN"
        
        return {
            "overall_status": overall_status,
            "interface_count": len(interfaces),
            "timestamp": time.time(),
            # Convert dictionary of interfaces to a list for easier iteration if needed, 
            # or keep as a dict keyed by interface name (preferred for direct access)
            "interfaces": interfaces 
        }