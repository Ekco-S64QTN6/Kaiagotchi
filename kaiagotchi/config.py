from typing import Dict, Any, Optional
from dataclasses import dataclass
import yaml

@dataclass
class NetworkConfig:
    iface: str
    channels: list[int]
    handshakes_path: str
    ap_ttl: int = 300
    sta_ttl: int = 300
    min_rssi: int = -80

@dataclass
class Config:
    network: NetworkConfig
    ui: Dict[str, Any]
    
def load_config(path: Optional[str] = None) -> Config:
    """Load and validate configuration."""
    if path:
        with open(path) as f:
            raw_config = yaml.safe_load(f)
    else:
        raw_config = {}
        
    network = NetworkConfig(
        iface=raw_config.get('network', {}).get('iface', 'wlan0'),
        channels=raw_config.get('network', {}).get('channels', [1,6,11]),
        handshakes_path=raw_config.get('network', {}).get('handshakes_path', 'handshakes'),
    )
    
    return Config(
        network=network,
        ui=raw_config.get('ui', {})
    )