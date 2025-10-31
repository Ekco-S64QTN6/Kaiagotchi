import logging
import subprocess
import re
import os
import time
from typing import List, Optional, Tuple, Set

# Assuming 'utils' is available in the kaiagotchi namespace
from kaiagotchi.utils import iface_channels

# Configure logging for the module
interface_logger = logging.getLogger('network.iface')

# Regex to parse the 'iwconfig' output for mode (managed, monitor, etc.)
# This is a common utility for checking interface capabilities
IWCONFIG_MODE_RE = re.compile(r'Mode:(Managed|Monitor|Master|Ad-Hoc|Auto)')


class InterfaceMonitor:
    """
    A utility class to manage and monitor a specific wireless network interface.

    Handles checking interface status, switching modes (monitor/managed),
    and setting channels, providing a robust interface for the Kaiagotchi agent.
    """

    def __init__(self, ifname: str, channel_timeout_s: int = 1):
        """
        Initializes the monitor for a specific interface.

        Args:
            ifname: The name of the wireless interface (e.g., 'wlan0').
            channel_timeout_s: The duration (in seconds) to stay on a single 
                               channel during scanning.
        """
        self.ifname = ifname
        self.channel_timeout_s = channel_timeout_s
        self._available_channels: List[int] = []

    def _execute_command(self, command: str, ignore_errors: bool = False) -> str:
        """
        Executes a shell command and returns its output, logging errors.

        Args:
            command: The full shell command string.
            ignore_errors: If True, suppresses exceptions for failed commands.

        Returns:
            The stdout output of the command.
        """
        interface_logger.debug(f"Executing: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=not ignore_errors,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode != 0 and not ignore_errors:
                error_msg = f"Command failed (Code {result.returncode}): {command}\n{result.stderr.strip()}"
                interface_logger.error(error_msg)
                raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if not ignore_errors:
                interface_logger.critical(f"OS Command Error: {e}")
                raise
            return ""
        except FileNotFoundError:
            interface_logger.critical("Required system commands (e.g., 'iwconfig', 'ip') not found. Check PATH.")
            raise

    def get_interface_mode(self) -> Optional[str]:
        """
        Determines the current operating mode of the interface (e.g., 'Monitor').

        Returns:
            The mode name as a string, or None if the interface is down/not found.
        """
        output = self._execute_command(f"iwconfig {self.ifname}", ignore_errors=True)
        match = IWCONFIG_MODE_RE.search(output)
        if match:
            return match.group(1)
        
        # Check if the interface is simply not up
        if "No such device" in output or "Device not found" in output:
             interface_logger.warning(f"Interface {self.ifname} does not exist.")
             return None
             
        return "Unknown"

    def set_monitor_mode(self) -> bool:
        """
        Attempts to set the interface to monitor mode.

        Returns:
            True if successful, False otherwise.
        """
        if self.get_interface_mode() == 'Monitor':
            interface_logger.info(f"{self.ifname} is already in Monitor mode.")
            return True

        interface_logger.info(f"Attempting to set {self.ifname} to Monitor mode...")
        try:
            # 1. Bring the interface down
            self._execute_command(f"ip link set {self.ifname} down")
            # 2. Set the mode (using iw is often more reliable than 'iwconfig')
            self._execute_command(f"iw dev {self.ifname} set type monitor")
            # 3. Bring the interface back up
            self._execute_command(f"ip link set {self.ifname} up")
            
            # Verify the change
            time.sleep(0.5) # Give the system a moment to apply changes
            if self.get_interface_mode() == 'Monitor':
                interface_logger.info(f"{self.ifname} successfully set to Monitor mode.")
                return True
            else:
                interface_logger.error(f"Failed to verify Monitor mode for {self.ifname}.")
                return False
        except Exception as e:
            interface_logger.error(f"Failed to set {self.ifname} to Monitor mode: {e}")
            return False

    def get_available_channels(self) -> List[int]:
        """
        Fetches and caches the available channels for the interface.

        Returns:
            A list of channel numbers (e.g., [1, 2, ..., 13]).
        """
        if not self._available_channels:
            try:
                self._available_channels = iface_channels(self.ifname)
                interface_logger.info(f"Found {len(self._available_channels)} available channels for {self.ifname}.")
            except Exception as e:
                interface_logger.error(f"Could not determine available channels: {e}")
                self._available_channels = [] # Ensure it's empty on failure
                
        return self._available_channels

    def set_channel(self, channel: int) -> bool:
        """
        Sets the interface to a specific channel.

        Args:
            channel: The Wi-Fi channel number to set.

        Returns:
            True if successful, False otherwise.
        """
        if channel not in self.get_available_channels():
            interface_logger.warning(f"Channel {channel} is not available for {self.ifname}.")
            return False

        interface_logger.debug(f"Setting {self.ifname} to channel {channel}")
        try:
            # Note: This command requires the interface to be in a mode that supports channel hopping (like Monitor).
            self._execute_command(f"iw dev {self.ifname} set channel {channel}")
            return True
        except Exception as e:
            interface_logger.error(f"Failed to set channel {channel} on {self.ifname}: {e}")
            return False

    def channel_hop(self, callback) -> None:
        """
        Cycles through all available channels, calling a callback function 
        after dwelling on each channel for the specified timeout.
        
        This loop is intended to be called from a separate thread, which is why 
        it does not return a value but executes the scan.

        Args:
            callback: A function to call after setting the channel, typically 
                      used to process packets captured on that channel.
        """
        channels = self.get_available_channels()
        if not channels:
            interface_logger.error(f"Cannot perform channel hop: No available channels for {self.ifname}.")
            return

        interface_logger.info(f"Starting channel hop across {len(channels)} channels.")
        
        for channel in channels:
            if not self.set_channel(channel):
                continue # Skip to next channel if setting failed
            
            # Execute the callback function (e.g., the packet sniffer/parser)
            callback(channel)
            
            # Wait for the dwell time
            time.sleep(self.channel_timeout_s)

        interface_logger.info("Channel hop cycle complete.")

# Example usage stub (for local testing only)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Replace 'wlan0' with a suitable interface name for testing
    TEST_IFACE = "wlan0" 
    
    # Simple callback function for the channel hop demonstration
    def dummy_sniffer_callback(channel: int):
        interface_logger.info(f"Callback executed on Channel {channel}. Simulating packet capture...")
    
    try:
        monitor = InterfaceMonitor(TEST_IFACE, channel_timeout_s=0.5)
        
        # NOTE: The actual OS commands used will require root/sudo privileges 
        # and a compatible wireless card/driver in the host environment.
        interface_logger.info("--- Testing Interface Monitor ---")

        # 1. Check current mode
        current_mode = monitor.get_interface_mode()
        interface_logger.info(f"Current mode of {TEST_IFACE}: {current_mode}")
        
        # 2. Attempt to set monitor mode (will likely fail without root)
        # success = monitor.set_monitor_mode()
        # interface_logger.info(f"Set Monitor Mode success: {success}")
        
        # 3. Get channels
        available_channels = monitor.get_available_channels()
        if available_channels:
            interface_logger.info(f"Channels available: {available_channels}")
            
            # 4. Attempt to set a channel (will likely fail without root/monitor mode)
            # if monitor.set_channel(available_channels[0]):
            #    interface_logger.info(f"Set channel to {available_channels[0]} successfully.")
            
            # 5. Simulate channel hop (without actual command execution)
            interface_logger.info("\n--- Simulating Channel Hop (No actual system calls) ---")
            monitor.channel_hop(dummy_sniffer_callback)
            
    except Exception as e:
        interface_logger.critical(f"Test failed due to an exception: {e}")
