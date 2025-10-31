from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import tomlkit
import logging

_log = logging.getLogger(__name__)

DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "defaults.toml"
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
    if not path.exists():
        return {}
    try:
        return tomlkit.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("Failed to load TOML: %s", path)
        return {}

def load_config(system_path: Path | None = None) -> dict:
    cfg = {}
    cfg.update(_load_toml(DEFAULTS_PATH))
    sys_path = Path(system_path) if system_path else SYSTEM_CONFIG_PATH
    cfg.update(_load_toml(sys_path))
    return cfg

# global CONFIG: modules import from kaiagotchi.config import CONFIG
CONFIG: dict[str, Any] = load_config()
# allow reloading
def reload(system_path: Path | None = None) -> None:
    global CONFIG
    CONFIG = load_config(system_path)