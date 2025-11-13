# utils.py - Enhanced version
import subprocess
import logging
import pathlib
import os
import sys
import tomlkit
import glob
import time
import stat
import requests
import zipfile
import hashlib
import json
from dataclasses import dataclass
from typing import List, Tuple, Union, Dict, Any, Sequence, Optional

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
DEFAULT_BASE_DIR = '/var/lib/kaiagotchi'
DEFAULT_STATE_FILENAME = 'state.json'
# ---

utils_logger = logging.getLogger('kaiagotchi.utils')

class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass

class FieldNotFoundError(Exception):
    """Raised when a required field is not found."""
    pass

@dataclass
class WifiInfo:
    """Data class for WiFi network information."""
    bssid: str
    essid: str
    channel: int
    rssi: int
    encryption: str = ''
    country: str = ''

class StatusFile:
    """Class for managing plugin status files."""
    
    def __init__(self, path: str, data_format=None):  # Add data_format parameter
        self.path = path
        self._data = {}
        self._data_format = data_format  # Store it even if unused
        self._load()
    
    def _load(self):
        """Load status data from file."""
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r') as f:
                    self._data = json.load(f)
        except Exception as e:
            utils_logger.warning(f"Failed to load status file {self.path}: {e}")
            self._data = {}
    
    def _save(self):
        """Save status data to file."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w') as f:
                json.dump(self._data, f)
        except Exception as e:
            utils_logger.error(f"Failed to save status file {self.path}: {e}")
    
    def get(self, key: str, default=None):
        """Get a status value."""
        return self._data.get(key, default)
    
    def update(self, **kwargs):
        """Update status values."""
        self._data.update(kwargs)
        self._save()
    
    def set(self, key: str, value):
        """Set a status value."""
        self._data[key] = value
        self._save()
    
    def delete(self, key: str):
        """Delete a status value."""
        if key in self._data:
            del self._data[key]
            self._save()

def remove_whitelisted(aps: List[Any], whitelist: List[str]) -> List[Any]:
    """
    Remove access points that are in the whitelist.
    
    Args:
        aps: List of access point objects
        whitelist: List of BSSIDs or ESSIDs to whitelist
        
    Returns:
        Filtered list of access points
    """
    if not whitelist:
        return aps
    
    filtered = []
    for ap in aps:
        # Handle different AP object structures
        bssid = getattr(ap, 'bssid', None) or ap.get('bssid', '') if hasattr(ap, 'get') else ''
        essid = getattr(ap, 'essid', None) or ap.get('essid', '') if hasattr(ap, 'get') else ''
        
        if bssid not in whitelist and essid not in whitelist:
            filtered.append(ap)
    
    utils_logger.debug(f"Filtered {len(aps)} APs to {len(filtered)} using whitelist")
    return filtered

def merge_config(user_config: Dict[str, Any], default_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge user configuration into default configuration.
    
    Args:
        user_config: User-provided configuration
        default_config: Default configuration template
        
    Returns:
        Merged configuration dictionary
    """
    config = default_config.copy()
    
    for key, value in user_config.items():
        if key in config and isinstance(config[key], dict) and isinstance(value, dict):
            # Recursively merge dictionaries
            config[key] = merge_config(value, config[key])
        else:
            # Overwrite with user value
            config[key] = value
    
    return config

def validate_config(config: Dict[str, Any]) -> None:
    """
    Validates critical configuration parameters.
    
    Args:
        config: The configuration dictionary to validate
        
    Raises:
        ConfigValidationError: When required parameters are missing or invalid
    """
    # Check required sections
    required_sections = ['main', 'log']
    for section in required_sections:
        if section not in config:
            raise ConfigValidationError(f"Missing required configuration section: '{section}'")
    
    # Check main section requirements
    main_config = config['main']
    if 'base_dir' not in main_config:
        raise ConfigValidationError("main.base_dir configuration is required")
    
    # Validate paths are writable
    base_dir = main_config['base_dir']
    try:
        pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)
        test_file = pathlib.Path(base_dir) / ".write_test"
        test_file.touch()
        test_file.unlink()
    except (OSError, PermissionError) as e:
        raise ConfigValidationError(f"base_dir '{base_dir}' is not writable: {e}")
    
    # Validate log configuration
    log_config = config.get('log', {})
    if 'path' in log_config:
        log_dir = pathlib.Path(log_config['path']).parent
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            raise ConfigValidationError(f"Log directory '{log_dir}' is not accessible: {e}")
    
    # Validate network interface
    if 'iface' in main_config:
        iface = main_config['iface']
        if not isinstance(iface, str) or len(iface) == 0:
            raise ConfigValidationError("main.iface must be a non-empty string")
    
    utils_logger.debug("Configuration validation passed")

def secure_config_file(config_path: str) -> None:
    """
    Ensure configuration file has secure permissions.
    
    Args:
        config_path: Path to the configuration file
    """
    config_file = pathlib.Path(config_path)
    
    if config_file.exists():
        # Set permissions to owner read/write only (0o600)
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        
        # Get current ownership
        file_stat = config_file.stat()
        current_uid = file_stat.st_uid
        current_gid = file_stat.st_gid
        
        # Warn if file is owned by root but running as different user
        if current_uid == 0 and os.geteuid() != 0:
            utils_logger.warning("Configuration file owned by root but running as different user")
            
    else:
        # Create directory with secure permissions if it doesn't exist
        config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        utils_logger.info(f"Created configuration directory: {config_file.parent}")

def sanitize_config_for_logging(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove sensitive information from config before logging.
    
    Args:
        config: Original configuration dictionary
        
    Returns:
        Sanitized configuration with sensitive fields removed/masked
    """
    sanitized = config.copy()
    sensitive_keys = ['password', 'secret', 'key', 'token', 'auth']
    
    def mask_sensitive(data, path=""):
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                if any(sensitive in key.lower() for sensitive in sensitive_keys):
                    data[key] = "***MASKED***"
                else:
                    mask_sensitive(value, current_path)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                mask_sensitive(item, f"{path}[{i}]")
    
    mask_sensitive(sanitized)
    return sanitized

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads application configuration from a TOML file.

    If the config file does not exist, it loads a default configuration.

    Args:
        config_path: The path to the TOML configuration file.

    Returns:
        A dictionary containing the application configuration.
    """
    # CORRECTED: log section is now top-level to satisfy validate_config
    default_config = {
        'main': {
            'base_dir': DEFAULT_BASE_DIR,
            'state_filename': DEFAULT_STATE_FILENAME,
            'language': 'en_US'
        },
        'log': {  # <-- FIX APPLIED HERE: Moved log section to top level
            'path': '/var/log/kaiagotchi/kaiagotchi.log',
            'level': 'INFO'
        },
        'ui': {
            'enabled': False,
            'bind_host': '0.0.0.0',
            'bind_port': 8080,
            'secret_key': 'change-this-secret'
        },
    }

    # Secure the config file
    secure_config_file(config_path)

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
            
            # Validate the configuration - handle validation errors here
            try:
                validate_config(config)
            except ConfigValidationError as e:
                utils_logger.error(f"Configuration validation failed: {e}")
                sys.exit(1)
            
            # Log sanitized config
            sanitized_config = sanitize_config_for_logging(config)
            utils_logger.info(f"Configuration loaded successfully from {config_path}")
            utils_logger.debug(f"Sanitized configuration: {sanitized_config}")
            
            return config
            
    except FileNotFoundError:
        utils_logger.warning(f"Configuration file not found at {config_path}. Using default configuration.")
        validate_config(default_config)
        return default_config
    except Exception as e:
        utils_logger.error(f"Error loading configuration file {config_path}: {e}. Using default configuration.")
        validate_config(default_config)
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

def download_file(url: str, dest: str, timeout: int = 60) -> bool:
    """Downloads a file from a URL to a destination path."""
    utils_logger.info(f"Downloading {url} to {dest}")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        utils_logger.error(f"Failed to download file from {url}: {e}")
        return False

def unzip(src: str, dest: str, strip_dirs: int = 0) -> bool:
    """Unzips an archive, optionally stripping a number of leading directories."""
    utils_logger.info(f"Unzipping {src} to {dest}")
    try:
        with zipfile.ZipFile(src, 'r') as zip_ref:
            # Simple unzip without stripping (for now)
            zip_ref.extractall(dest)
        return True
    except zipfile.BadZipFile:
        utils_logger.error(f"Invalid ZIP file: {src}")
        return False
    except Exception as e:
        utils_logger.error(f"Failed to unzip {src}: {e}")
        return False

def save_config(config: Dict[str, Any], path: str) -> bool:
    """Saves the configuration dictionary to a TOML file."""
    utils_logger.info(f"Saving configuration to {path}")
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(tomlkit.dumps(config))
        return True
    except Exception as e:
        utils_logger.error(f"Failed to save config to {path}: {e}")
        return False

def md5(filename: str) -> Optional[str]:
    """Calculates the MD5 hash of a file."""
    try:
        hash_md5 = hashlib.md5()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        utils_logger.error(f"Failed to calculate MD5 for {filename}: {e}")
        return None

# --- NEW FUNCTION FOR PYLANCE FIX ---
def iface_channels(iface_name: str) -> List[int]:
    """
    Returns a list of supported 802.11 channels for a given interface.
    
    This function is required by the auto_tune plugin's channel management
    fallback logic when agent channels are unavailable.
    
    Args:
        iface_name: The network interface name (e.g., 'wlan0mon').
        
    Returns:
        A list of supported channel numbers (e.g., [1, 2, ..., 14]).
    """
    # In a full project, this would use 'iw list' or 'nl80211' to query the system.
    # Placeholder returns standard 2.4GHz channels 1-14 to satisfy the function contract.
    utils_logger.warning(f"iface_channels called for {iface_name}. Using placeholder channels 1-14.")
    return [c for c in range(1, 15)]
# --- END NEW FUNCTION ---

def get_configured_interface(config: dict) -> str:
    """
    Safely retrieve configured network interface from agent config.
    
    Expected config structure:
    [main]
    name = "kaiagotchi"
    iface = "wlan0mon"  # Interface to be added
    
    Args:
        config: Loaded configuration dictionary
        
    Returns:
        str: Interface name
        
    Raises:
        ValueError: If interface not configured or invalid
    """
    try:
        iface = config.get('main', {}).get('iface')
        if not iface:
            raise ValueError("Network interface not configured. Please set 'iface' in [main] section of config.")
        
        # Basic validation
        if not isinstance(iface, str) or len(iface.strip()) == 0:
            raise ValueError(f"Invalid interface name: {iface}")
            
        return iface.strip()
        
    except Exception as e:
        utils_logger.error(f"Failed to get configured interface: {e}")
        raise

def extract_from_pcap(pcap_file: str) -> Dict[str, Any]:
    """
    Extract handshake information from pcap file.
    Placeholder implementation.
    """
    utils_logger.warning(f"extract_from_pcap is a placeholder for {pcap_file}")
    return {
        'bssid': '00:00:00:00:00:00',
        'essid': 'unknown',
        'handshake': True
    }