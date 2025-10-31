import subprocess
import logging
from typing import List, Tuple, Union

# Define the logger for this specific module
system_logger = logging.getLogger('kaiagotchi.system')

class SystemInteractionError(Exception):
    """Custom exception for errors during system command execution."""
    pass

def execute_command(command: List[str], error_message: str) -> str:
    """
    Executes a shell command and returns its output. This function is the primary
    interface for interacting with OS-level tools like 'iw' and 'ip'.

    Raises SystemInteractionError if the command fails for any reason (not found,
    non-zero exit code, timeout).

    Args:
        command: A list of strings representing the command and its arguments.
        error_message: A descriptive message for the log if the command fails.

    Returns:
        The standard output of the executed command as a stripped string.
    """
    try:
        # Check=True will raise CalledProcessError if the command returns a non-zero exit code
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=5  # Enforce a timeout to prevent system commands from hanging
        )
        return result.stdout.strip()
    except FileNotFoundError:
        system_logger.critical(f"Command not found: {command[0]}. Is it installed and in PATH?")
        raise SystemInteractionError(f"Required command '{command[0]}' not found.")
    except subprocess.CalledProcessError as e:
        system_logger.error(f"{error_message}: Command failed with error: {e.stderr.strip()}")
        raise SystemInteractionError(f"{error_message}. Error: {e.stderr.strip()}")
    except subprocess.TimeoutExpired:
        system_logger.error(f"{error_message}: Command timed out after 5 seconds.")
        raise SystemInteractionError(f"{error_message}: Command timed out.")

def get_interface_phy(ifname: str) -> str:
    """
    Finds the physical device name (wiphyX) associated with a network interface.
    
    This is necessary because 'iw list' must be run against the physical device,
    not always the logical interface name.

    Args:
        ifname: The network interface name (e.g., 'wlan0').

    Returns:
        The physical device name (e.g., 'phy0').
    """
    system_logger.debug(f"Finding physical device for interface: {ifname}")
    # Use the 'iw <ifname> info' command
    command = ["/sbin/iw", ifname, "info"]
    error_msg = f"Failed to get wiphy info for interface {ifname}"
    
    output = execute_command(command, error_msg)
    
    for line in output.splitlines():
        if "wiphy" in line:
            # Output format is typically 'wiphy X'
            return line.split()[1] 

    raise SystemInteractionError(f"Could not find wiphy for interface {ifname}.")

def get_available_channels(ifname: str) -> List[int]:
    """
    Returns a list of available wireless channels for a given interface name.

    It first attempts to find the physical device (wiphy) and then runs 
    'iw <wiphy> channels' to get the full list of supported channels.

    Args:
        ifname: The network interface name (e.g., 'wlan0').

    Returns:
        A sorted list of available channel numbers (e.g., [1, 2, ..., 13]).
    """
    channels: List[int] = []
    
    try:
        # 1. Get the physical device name
        phy_name = get_interface_phy(ifname)
    except SystemInteractionError:
        # Fallback if the physical name lookup fails (e.g., if the interface is down)
        phy_name = "list"
        system_logger.warning(f"Could not determine wiphy for {ifname}. Falling back to general 'iw list' for channels.")

    # Use 'iw <phy_name> channels' or 'iw list'
    command = ["/sbin/iw", phy_name, "channels"]
    error_msg = f"Failed to get channel list for interface {ifname}"
    output = execute_command(command, error_msg)

    # Parse the output to find channel numbers
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('Channel '):
            # Example line: 'Channel 1 : 2412 MHz (20.0 dBm)'
            try:
                # Extract the channel number (the part after 'Channel ')
                parts = line.split(':')
                channel_part = parts[0].replace('Channel', '').strip()
                channel_number = int(channel_part)
                
                # Exclude channels marked as "disabled" or "no IR" (no initiate radiation)
                if not any(flag in line for flag in ['(disabled)', '(no IR)']):
                    channels.append(channel_number)
            except ValueError:
                system_logger.debug(f"Skipping unparseable channel line: {line}")
            
    if not channels:
        system_logger.warning(f"No usable channels found for interface {ifname}.")

    # Use set() to ensure uniqueness, then sort the list
    return sorted(list(set(channels)))

def set_interface_mode(ifname: str, mode: str = 'monitor') -> bool:
    """
    Sets the operating mode (e.g., 'monitor' or 'managed') for a network interface.

    NOTE: This operation requires root privileges (sudo) and is a common failure
    point if permissions are incorrect.

    Args:
        ifname: The network interface name (e.g., 'wlan0').
        mode: The desired mode, usually 'monitor' or 'managed'.

    Returns:
        True if the mode was successfully set, False otherwise.
    """
    system_logger.info(f"Attempting to set interface {ifname} to {mode} mode...")
    
    try:
        # 1. Bring the interface down (mandatory for changing mode)
        execute_command(["/sbin/ip", "link", "set", ifname, "down"], 
                        f"Failed to bring interface {ifname} down")

        # 2. Set the desired mode using iw
        execute_command(["/sbin/iw", ifname, "set", "type", mode], 
                        f"Failed to set interface {ifname} type to {mode}")

        # 3. Bring the interface back up
        execute_command(["/sbin/ip", "link", "set", ifname, "up"], 
                        f"Failed to bring interface {ifname} up")
        
        system_logger.info(f"Successfully set interface {ifname} to {mode} mode.")
        return True
    
    except SystemInteractionError as e:
        system_logger.error(f"Failed to change interface mode for {ifname}. Check if root privileges are available: {e}")
        return False
