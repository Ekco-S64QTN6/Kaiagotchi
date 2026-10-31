# utils.py - Enhanced version
import glob
import hashlib
import json
import logging
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import tomlkit

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
        self._data: dict[str, Any] = {}
        self._data_format = data_format  # Store it even if unused
        self._load()

    def _load(self) -> None:
        """Load a JSON object from the status file, rejecting other root types."""
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as fp:
                    loaded = json.load(fp)
                if isinstance(loaded, dict):
                    self._data = loaded
                else:
                    utils_logger.warning(
                        "Status file %s contains a non-object JSON value; ignoring it",
                        self.path,
                    )
                    self._data = {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            utils_logger.warning("Failed to load status file %s: %s", self.path, e)
            self._data = {}

    def _save(self) -> None:
        """Atomically save a status object, including for a bare relative filename."""
        temp_path: str | None = None
        try:
            destination = os.path.abspath(self.path)
            parent = os.path.dirname(destination)
            os.makedirs(parent, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=f".{os.path.basename(destination)}.",
                suffix=".tmp",
                delete=False,
            ) as fp:
                temp_path = fp.name
                json.dump(self._data, fp)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temp_path, destination)
            temp_path = None
        except (OSError, TypeError, ValueError) as e:
            utils_logger.error("Failed to save status file %s: %s", self.path, e)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    utils_logger.warning("Could not remove temporary status file %s", temp_path)

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

def remove_whitelisted(aps: list[Any], whitelist: list[str]) -> list[Any]:
    """Remove APs whose BSSID, SSID, or ESSID appears in the whitelist."""
    if not whitelist:
        return aps

    def field(ap: Any, name: str) -> Any:
        value = getattr(ap, name, None)
        if value:
            return value
        getter = getattr(ap, "get", None)
        if callable(getter):
            return getter(name, "")
        return ""

    filtered = [
        ap for ap in aps
        if field(ap, "bssid") not in whitelist
        and field(ap, "essid") not in whitelist
        and field(ap, "ssid") not in whitelist
    ]
    utils_logger.debug("Filtered %d APs to %d using whitelist", len(aps), len(filtered))
    return filtered

def merge_config(user_config: dict[str, Any], default_config: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge user settings into independent copies of the defaults."""
    config = deepcopy(default_config)

    for key, value in user_config.items():
        if key in config and isinstance(config[key], dict) and isinstance(value, dict):
            config[key] = merge_config(value, config[key])
        else:
            config[key] = deepcopy(value)

    return config

def validate_config(config: dict[str, Any]) -> None:
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

    # Validate paths are writable using a unique temporary file. A fixed
    # ".write_test" name can collide with user data or be raced by another local
    # process while this configuration code may be running with elevated rights.
    base_dir = main_config['base_dir']
    try:
        base_path = pathlib.Path(base_dir)
        base_path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".kaiagotchi-write-probe-",
            dir=base_path,
            delete=True,
        ) as probe:
            probe.write("probe")
            probe.flush()
    except OSError as e:
        raise ConfigValidationError(f"base_dir '{base_dir}' is not writable: {e}") from e

    # Validate log configuration
    log_config = config.get('log', {})
    if 'path' in log_config:
        log_dir = pathlib.Path(log_config['path']).parent
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            raise ConfigValidationError(f"Log directory '{log_dir}' is not accessible: {e}") from e

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

        # Warn if file is owned by root but running as different user
        if current_uid == 0 and os.geteuid() != 0:
            utils_logger.warning("Configuration file owned by root but running as different user")

    else:
        # Create directory with secure permissions if it doesn't exist
        config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        utils_logger.info(f"Created configuration directory: {config_file.parent}")

def sanitize_config_for_logging(config: dict[str, Any]) -> dict[str, Any]:
    """
    Remove sensitive information from config before logging.

    Args:
        config: Original configuration dictionary

    Returns:
        Sanitized configuration with sensitive fields removed/masked
    """
    sanitized = deepcopy(config)
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

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """
    Loads application configuration from a TOML file.

    If the config file does not exist, it loads a default configuration.

    Args:
        config_path: The path to the TOML configuration file.

    Returns:
        A dictionary containing the application configuration.
    """
    # CORRECTED: log section is now top-level to satisfy validate_config
    default_config: dict[str, Any] = {
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
        with open(config_path) as f:
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

def get_state_path(config: dict[str, Any]) -> str:
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

def parse_version(version: str) -> tuple[str, ...]:
    """Converts a version str to tuple for comparison."""
    return tuple(version.split('.'))

def secs_to_hhmmss(secs: int | float) -> str:
    """Converts seconds into HH:MM:SS format."""
    # Ensure input is an integer
    secs = int(secs)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"

def total_unique_handshakes(path: str) -> int:
    """Returns the count of unique handshakes (files ending in .pcap) in a directory."""
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))

def download_file(url: str, dest: str, timeout: int = 60) -> bool:
    """Download a file, loading the optional requests dependency only when used."""
    try:
        import requests
    except ImportError:
        utils_logger.error(
            "Downloading files requires the optional 'requests' dependency; "
            "install kaiagotchi[net]."
        )
        return False

    utils_logger.info("Downloading %s to %s", url, dest)
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(dest, "wb") as output:
                for chunk in response.iter_content(chunk_size=8192):
                    output.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        utils_logger.error("Failed to download file from %s: %s", url, e)
        return False

def unzip(src: str, dest: str, strip_dirs: int = 0) -> bool:
    """
    Safely extract a ZIP archive and optionally strip leading path components.

    Validate all members before writing anything. Reject absolute paths,
    parent traversal, and symlink entries so malicious archives cannot escape
    the destination directory.
    """
    utils_logger.info("Unzipping %s to %s", src, dest)
    if strip_dirs < 0:
        utils_logger.error("strip_dirs must be non-negative")
        return False

    root = pathlib.Path(dest).resolve()
    try:
        with zipfile.ZipFile(src, "r") as zip_ref:
            entries: list[tuple[zipfile.ZipInfo, pathlib.Path, bool]] = []
            for info in zip_ref.infolist():
                raw_name = info.filename
                posix_name = PurePosixPath(raw_name)
                windows_name = PureWindowsPath(raw_name)

                if (
                    not raw_name
                    or posix_name.is_absolute()
                    or windows_name.is_absolute()
                    or bool(windows_name.drive)
                    or ".." in posix_name.parts
                    or ".." in windows_name.parts
                ):
                    raise ValueError(f"Unsafe ZIP member path: {raw_name!r}")

                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Symlink ZIP member is not allowed: {raw_name!r}")

                parts = [part for part in posix_name.parts if part not in ("", ".")]
                if len(parts) <= strip_dirs:
                    continue

                relative_path = pathlib.Path(*parts[strip_dirs:])
                target = (root / relative_path).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f"ZIP member escapes destination: {raw_name!r}")

                entries.append((info, target, info.is_dir()))

            # Don't extract any files until the entire archive passes validation.
            root.mkdir(parents=True, exist_ok=True)
            for info, target, is_dir in entries:
                if is_dir:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(info, "r") as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)

        return True
    except zipfile.BadZipFile:
        utils_logger.error("Invalid ZIP file: %s", src)
        return False
    except (OSError, ValueError, RuntimeError) as e:
        utils_logger.error("Failed to safely unzip %s: %s", src, e)
        return False
    except Exception as e:
        utils_logger.error("Failed to unzip %s: %s", src, e)
        return False

def save_config(config: dict[str, Any], path: str) -> bool:
    """Atomically save a TOML configuration file."""
    temp_path: str | None = None
    try:
        destination = os.path.abspath(path)
        parent = os.path.dirname(destination)
        os.makedirs(parent, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{os.path.basename(destination)}.",
            suffix=".tmp",
            delete=False,
        ) as fp:
            temp_path = fp.name
            fp.write(tomlkit.dumps(config))
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp_path, destination)
        temp_path = None
        try:
            os.chmod(destination, 0o600)
        except OSError as e:
            utils_logger.warning("Could not secure permissions for %s: %s", destination, e)
        return True
    except Exception as e:
        utils_logger.error("Failed to save config to %s: %s", path, e)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                utils_logger.warning("Could not remove temporary config file %s", temp_path)
        return False

def md5(filename: str) -> str | None:
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
def iface_channels(iface_name: str) -> list[int]:
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
    return list(range(1, 15))
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

def extract_from_pcap(pcap_file: str) -> dict[str, Any]:
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
