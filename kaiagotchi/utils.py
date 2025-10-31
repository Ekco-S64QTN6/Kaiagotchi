import subprocess
import logging
import pathlib
import os
import sys
import tomlkit
import glob
from typing import List, Tuple, Union, Dict, Any

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
DEFAULT_BASE_DIR = '/var/lib/kaiagotchi'
DEFAULT_STATE_FILENAME = 'state.json'
# ---

utils_logger = logging.getLogger('utils')


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads application configuration from a TOML file.

    If the config file does not exist, it loads a default configuration.

    Args:
        config_path: The path to the TOML configuration file.

    Returns:
        A dictionary containing the application configuration.
    """
    # Base/Default Configuration
    config: Dict[str, Any] = {
        'main': {
            'name': 'Kaiagotchi',
            'base_dir': DEFAULT_BASE_DIR,
            'plugin_dirs': ['/etc/kaiagotchi/plugins'],
        },
        'ui': {'enabled': True},
        'log': {'level': 'INFO'}
    }

    # 1. Check if config file exists
    if not os.path.exists(config_path):
        utils_logger.warning(f"Configuration file not found at {config_path}. Using default configuration.")
        return config

    # 2. Load and merge configuration
    try:
        with open(config_path, 'r', encoding='utf-8') as fp:
            loaded_config = tomlkit.load(fp)

        # Merge loaded config into default config
        for section, settings in loaded_config.items():
            if section in config and isinstance(config[section], dict):
                config[section].update(settings)
            else:
                config[section] = settings

        utils_logger.info(f"Configuration loaded successfully from {config_path}.")

    except Exception as e:
        utils_logger.error(f"Error loading or parsing configuration from {config_path}: {e}", exc_info=True)
        utils_logger.warning("Falling back to default configuration.")

    return config


def get_state_path(config: Dict[str, Any], filename: str = DEFAULT_STATE_FILENAME) -> str:
    """
    Determines the full path for a persistent state file based on the application config.

    The path is constructed as: <base_dir>/<filename>
    """
    base_dir = config.get('main', {}).get('base_dir', DEFAULT_BASE_DIR)

    # Ensure the directory exists
    pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)

    state_path = str(pathlib.Path(base_dir) / filename)
    utils_logger.debug(f"Determined state path: {state_path}")
    return state_path


def parse_version(version: str) -> Tuple[str, ...]:
    """Converts a version str to tuple for comparison."""
    return tuple(version.split('.'))


def secs_to_hhmmss(secs: Union[int, float]) -> str:
    """Converts seconds into HH:MM:SS format."""
    secs = int(secs)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    return '%02d:%02d:%02d' % (hours, mins, secs)


def total_unique_handshakes(path: str) -> int:
    """Returns the count of unique handshakes (files ending in .pcap) in a directory."""
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))


def iface_channels(ifname: str) -> List[int]:
    """Returns a list of available wireless channels for a given interface name."""
    channels = []
    # Find the physical device name
    phy = subprocess.getoutput(f"/sbin/iw {ifname} info | grep wiphy | cut -d ' ' -f 2")

    # Get all non-disabled channels from iw output
    output = subprocess.getoutput(f"/sbin/iw phy {phy} channels | grep -v disabled | grep -v DFS")

    for line in output.split('\n'):
        if '[' in line and ']' in line:
            try:
                channel = int(line.split('[')[1].split(']')[0].strip())
                channels.append(channel)
            except ValueError:
                continue

    return channels
