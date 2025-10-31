import subprocess
import logging
import re
from typing import List, Tuple, Union, Sequence

# Define the logger for this specific module
system_logger = logging.getLogger('kaiagotchi.system')

class SystemInteractionError(Exception):
    """Custom exception for errors during system command execution."""
    pass

def execute_command(command: Sequence[str], error_message: str, *, timeout: Union[int, None] = 5) -> str:
    """
    Executes a shell command and returns its output. This function is the primary
    interface for interacting with OS-level tools like 'iw' and 'ip'.

    Raises SystemInteractionError if the command fails for any reason (not found,
    non-zero exit code, timeout).

    Args:
        command: A list of strings representing the command and its arguments.
        error_message: A descriptive message for the log if the command fails.
        timeout: Optional timeout in seconds.

    Returns:
        The standard output of the executed command as a stripped string.
    """
    if not isinstance(command, (list, tuple)):
        raise TypeError("command must be a list/tuple of arguments")

    try:
        # check=True will raise CalledProcessError if the command returns a non-zero exit code
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout
        )
        return result.stdout.strip()
    except FileNotFoundError:
        system_logger.critical(f"Command not found: {command[0]}. Is it installed and in PATH?")
        raise SystemInteractionError(f"Required command '{command[0]}' not found.")
    except subprocess.CalledProcessError as e:
        system_logger.error(f"{error_message}: Command {' '.join(command)} failed with return code {e.returncode}. Stderr: {e.stderr.strip()}")
        raise SystemInteractionError(f"{error_message}. Command failed.")
    except subprocess.TimeoutExpired:
        system_logger.error(f"{error_message}: Command {' '.join(command)} timed out after {timeout} seconds.")
        raise SystemInteractionError(f"{error_message}. Command timed out.")
    except Exception as e:
        system_logger.exception(f"{error_message}: An unexpected error occurred.")
        raise SystemInteractionError(f"{error_message}. Unexpected error: {e}")

def get_interface_channels(ifname: str) -> List[int]:
    """
    Returns a list of available wireless channels for a given interface name.
    This replaces the unsafe subprocess.getoutput usage from utils.py.

    Args:
        ifname: The network interface name (e.g., 'wlan0').

    Returns:
        A sorted list of available channel numbers.
    """
    channels = []
    try:
        # 1. Find the physical device name (wiphyX)
        output = execute_command(
            ["/sbin/iw", ifname, "info"],
            f"Failed to get info for interface {ifname}"
        )
        match = re.search(r"wiphy (\d+)", output)
        if not match:
            system_logger.error(f"Could not find wiphy identifier for interface {ifname}.")
            return []

        phy = f"phy{match.group(1)}"
        system_logger.debug(f"Interface {ifname} maps to physical device {phy}.")

        # 2. Get all non-disabled channels from iw output
        output = execute_command(
            ["/sbin/iw", phy, "channels"],
            f"Failed to list channels for physical device {phy}"
        )
        
        # Parse the output: Channels are on lines starting with '*' or 'Channel'
        for line in output.splitlines():
            if line.strip().startswith('*') or line.strip().startswith('Channel'):
                 if 'disabled' in line:
                    continue
                 
                 # Extract the channel number, which is usually the second token
                 parts = line.strip().split()
                 if len(parts) > 1 and parts[1].isdigit():
                     channels.append(int(parts[1]))

    except SystemInteractionError:
        # Error already logged by execute_command
        return []

    # Ensure uniqueness and return sorted list
    return sorted(list(set(channels)))


def set_interface_mode(ifname: str, mode: str = 'monitor') -> bool:
    """
    Sets the operating mode (e.g., 'monitor' or 'managed') for a network interface.
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
        system_logger.error(f"Failed to change mode for {ifname}: {e}")
        return False

def set_interface_channel(ifname: str, channel: int) -> bool:
    """
    Sets the operating channel for a network interface using iw.
    """
    system_logger.info(f"Attempting to set interface {ifname} to channel {channel}...")
    try:
        # The 'iw' command to set the channel
        execute_command(
            ["/sbin/iw", ifname, "set", "channel", str(channel)],
            f"Failed to set channel {channel} for interface {ifname}"
        )
        system_logger.info(f"Successfully set channel {channel} for interface {ifname}.")
        return True
    except SystemInteractionError:
        system_logger.error(f"Failed to set channel {channel} on {ifname}.")
        return False
