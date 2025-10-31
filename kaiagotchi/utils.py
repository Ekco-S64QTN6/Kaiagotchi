import subprocess
import logging
import pathlib
import os
import sys
import tomlkit
import glob
import time
from typing import List, Tuple, Union, Dict, Any, Sequence

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
DEFAULT_BASE_DIR = '/var/lib/kaiagotchi'
DEFAULT_STATE_FILENAME = 'state.json'
# ---

utils_logger = logging.getLogger('kaiagotchi.utils')

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads application configuration from a TOML file.

    If the config file does not exist, it loads a default configuration.

    Args:
        config_path: The path to the TOML configuration file.

    Returns:
        A dictionary containing the application configuration.
    """
    default_config = {
        'main': {
            'log': {
                'path': '/var/log/kaiagotchi/kaiagotchi.log',
                'level': 'INFO'
            },
            'base_dir': DEFAULT_BASE_DIR,
            'state_filename': DEFAULT_STATE_FILENAME,
            'language': 'en_US'
        },
        'ui': {
            'enabled': False,
            'bind_host': '0.0.0.0',
            'bind_port': 8080,
            'secret_key': 'change-this-secret'
        },
        # Add more default sections as needed
    }

    try:
        with open(config_path, 'r') as f:
            # Load the user's config
            user_config = tomlkit.load(f)
            
            # Merge: Use default settings unless overridden by user config
            config = default_config.copy()
            for key, value in user_config.items():
                if key in config and isinstance(config[key], dict) and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value
            
            utils_logger.info(f"Configuration loaded successfully from {config_path}.")
            return config
            
    except FileNotFoundError:
        utils_logger.warning(f"Configuration file not found at {config_path}. Using default configuration.")
        return default_config
    except tomlkit.exceptions.ParseError as e:
        utils_logger.error(f"Error parsing configuration file {config_path}: {e}. Using default configuration.")
        return default_config
    except Exception as e:
        utils_logger.exception(f"An unexpected error occurred while loading config. Using default configuration.")
        return default_config

def get_state_path(config: Dict[str, Any]) -> str:
    """
    Calculates the full, absolute path for the application's state file.

    Args:
        config: The application's configuration dictionary.

    Returns:
        The full path to the state file.
    """
    base_dir = config.get('main', {}).get('base_dir', DEFAULT_BASE_DIR)
    filename = config.get('main', {}).get('state_filename', DEFAULT_STATE_FILENAME)
    
    # Ensure the directory exists
    try:
        pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        utils_logger.error(f"Failed to create base directory {base_dir}: {e}")
        # Fallback to a temporary directory if base_dir cannot be created
        base_dir = '/tmp/kaiagotchi'
        pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)


    state_path = str(pathlib.Path(base_dir) / filename)
    utils_logger.debug(f"Determined state path: {state_path}")
    return state_path


def parse_version(version: str) -> Tuple[str, ...]:
    """Converts a version str to tuple for comparison."""
    return tuple(version.split('.'))


def secs_to_hhmmss(secs: Union[int, float]) -> str:
    """Converts seconds into HH:MM:SS format."""
    # Ensure input is an integer
    secs = int(secs)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    return '%02d:%02d:%02d' % (hours, mins, secs)


def total_unique_handshakes(path: str) -> int:
    """Returns the count of unique handshakes (files ending in .pcap) in a directory."""
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))
