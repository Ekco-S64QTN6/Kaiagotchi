import logging
import pathlib
import os
import sys
import tomlkit
from typing import Dict, Any

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
DEFAULT_BASE_DIR = '/var/lib/kaiagotchi'
DEFAULT_STATE_FILENAME = 'state.json'
# ---

utils_logger = logging.getLogger('utils')


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads application configuration from a TOML file.

    If the config file does not exist, it loads an empty or default configuration.

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
        # ... other default sections ...
    }
    
    # 1. Check if config file exists
    if not os.path.exists(config_path):
        utils_logger.warning(f"Configuration file not found at {config_path}. Using default configuration.")
        return config

    # 2. Read and parse the TOML file
    try:
        with open(config_path, 'r', encoding='utf-8') as fp:
            config_content = fp.read()
            loaded_config = tomlkit.parse(config_content)
        
        # Simple update: Overwrite keys in 'config' with values from 'loaded_config'
        for section, settings in loaded_config.items():
            if section in config and isinstance(config[section], dict):
                config[section].update(settings)
            else:
                config[section] = settings
                
        utils_logger.info(f"Configuration loaded successfully from {config_path}.")

    except Exception as e:
        utils_logger.error(f"Error loading or parsing configuration from {config_path}: {e}", exc_info=True)
        # If parsing fails, fall back to the default config
        utils_logger.warning("Falling back to default configuration.")

    return config


def get_state_path(config: Dict[str, Any], filename: str = DEFAULT_STATE_FILENAME) -> str:
    """
    Determines the full path for a persistent state file based on the application config.

    The path is constructed as: <base_dir>/<filename>

    Args:
        config: The application configuration dictionary.
        filename: The specific name of the state file (e.g., 'state.json', 'log.txt').

    Returns:
        The absolute path to the state file.
    """
    # Extract base directory from config, falling back to default if missing
    base_dir = config.get('main', {}).get('base_dir', DEFAULT_BASE_DIR)
    
    # Ensure the directory exists
    pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)
    
    state_path = str(pathlib.Path(base_dir) / filename)
    utils_logger.debug(f"State path generated: {state_path}")
    return state_path
