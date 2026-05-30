#config/config.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union
import tomlkit
import logging

_log = logging.getLogger(__name__)

# defaults.toml path
DEFAULTS_PATH = Path(__file__).resolve().parent / "defaults.toml"
SYSTEM_CONFIG_PATH = Path("/etc/kaiagotchi/config.toml")


@dataclass
class NetworkConfig:
    iface: str
    channels: list[int]
    handshakes_path: str
    ap_ttl: int = 300
    sta_ttl: int = 300
    min_rssi: int = -80


def _load_toml(path: Path) -> dict:
    """Safely load a TOML file, returning an empty dictionary if the file is missing or invalid."""
    if not path.exists():
        _log.warning("Config file not found: %s", path)
        return {}
    try:
        data = tomlkit.loads(path.read_text(encoding="utf-8"))
        _log.debug("Loaded config from %s", path)
        return data
    except Exception:
        _log.exception("Failed to parse TOML: %s", path)
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge the override dictionary into the base dictionary."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(system_path: Union[Path, None] = None) -> dict:
    """
    Load the defaults.toml configuration and merge it with the optional system config.

    Args:
        system_path (Path, optional): Path to a system configuration file. If None, 
                                       the default system config path is used.

    Returns:
        dict: The merged configuration.
    """
    # Load the default configuration
    cfg = _load_toml(DEFAULTS_PATH)
    
    # Determine system config path if not provided
    sys_path = Path(system_path) if system_path else SYSTEM_CONFIG_PATH
    # Load the system configuration
    sys_cfg = _load_toml(sys_path)
    
    # Merge system config into defaults
    if sys_cfg:
        cfg = _deep_merge(cfg, sys_cfg)
    
    return cfg


# Global CONFIG object, loaded at module load
CONFIG: dict[str, Any] = load_config()


def reload(system_path: Union[Path, None] = None) -> None:
    """
    Reload the configuration from the disk, merging with the system configuration if provided.

    Args:
        system_path (Path, optional): Path to the system configuration file.
    """
    global CONFIG
    CONFIG = load_config(system_path)
