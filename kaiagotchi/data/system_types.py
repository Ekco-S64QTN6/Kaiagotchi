#data/system_types.py
from __future__ import annotations
import time
import logging
import warnings
from enum import Enum
from typing import Dict, List, Optional, Annotated, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator

# --- GLOBAL WARNING FILTER (critical for UI) ---
warnings.filterwarnings("ignore", message="PydanticSerializationUnexpectedValue")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

# --- CUSTOM PYDANTIC TYPES ---
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
NetworkChannel = Annotated[int, Field(ge=1, le=165)]
FrequencyMHz = Annotated[int, Field(ge=2400)]
Percentage = Annotated[float, Field(ge=0.0, le=100.0)]
MACAddress = Annotated[str, Field(pattern=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')]
BSSID = MACAddress
# ------------------------------------------------------------------

# --- ENUM DEFINITIONS ---
class AgentState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    PAUSED = "PAUSED"

class GlobalSystemState(str, Enum):
    INITIALIZING = "INITIALIZING"
    BOOTING = "BOOTING"
    MONITORING = "MONITORING"
    TARGETING = "TARGETING"
    ATTACKING = "ATTACKING"
    MAINTENANCE = "MAINTENANCE"
    CLEANUP = "CLEANUP"
    SHUTDOWN = "SHUTDOWN"
    ERROR = "ERROR"

class AccessPointProtocol(str, Enum):
    OPEN = "Open"
    WEP = "WEP"
    WPA = "WPA"
    WPA2 = "WPA2"
    WPA3 = "WPA3"
    WPA_WPA2 = "WPA/WPA2"
    UNKNOWN = "Unknown"

class AgentMood(str, Enum):
    """Defines the emotional states of the Kaiagotchi agent.

    Usage notes:
    - UI (faces/messages): maps moods to face and voice pools
    - Voice: selects mood-appropriate lines
    - DecisionEngine / reward: mood drift and reinforcement
    - Epoch/reward: boredom/sadness influence
    """
    # Core States that match faces.py exactly
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    BORED = "bored"
    SAD = "sad"
    FRUSTRATED = "frustrated"
    SLEEPY = "sleepy"
    CONFIDENT = "confident"
    BROKEN = "broken"
    ANGRY = "angry"
    AWAKE = "awake"
    DEBUG = "debug"

class AccessPointType(str, Enum):
    INFRASTRUCTURE = "Infrastructure"
    ADHOC = "Ad-Hoc"
    CLIENT = "Client"
    MESH = "Mesh"
    UNKNOWN = "Unknown"

class InterfaceMode(str, Enum):
    MONITOR = "monitor"
    MANAGED = "managed"
    AP = "ap"
    IBSS = "ibss"
    UNKNOWN = "unknown"

class SecurityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"

# --- NETWORK MODELS ---
class WirelessClient(BaseModel):
    model_config = ConfigDict(strict=True)
    mac: MACAddress
    vendor: Optional[str] = None
    first_seen: NonNegativeFloat = Field(default_factory=time.time)
    last_seen: NonNegativeFloat = Field(default_factory=time.time)
    power: int = 0
    packets: NonNegativeInt = 0
    is_associated: bool = False

class AccessPoint(BaseModel):
    model_config = ConfigDict(strict=True)
    bssid: BSSID
    ssid: Optional[str] = None
    protocol: AccessPointProtocol = AccessPointProtocol.UNKNOWN
    ap_type: AccessPointType = AccessPointType.UNKNOWN
    channel: NetworkChannel = 1
    frequency: FrequencyMHz = 2412
    power: int = 0
    privacy: bool = False
    cipher: Optional[str] = None
    first_seen: NonNegativeFloat = Field(default_factory=time.time)
    last_seen: NonNegativeFloat = Field(default_factory=time.time)
    clients: Dict[str, WirelessClient] = Field(default_factory=dict)
    handshakes_captured: NonNegativeInt = 0
    pmkid_captured: bool = False
    is_target: bool = False
    security_level: SecurityLevel = SecurityLevel.UNKNOWN

    @field_validator("ssid")
    @classmethod
    def validate_ssid(cls, v):
        if v is None:
            return v
        cleaned = "".join(char for char in v if char.isprintable())
        return cleaned.strip() or None

class InterfaceState(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    mode: InterfaceMode = InterfaceMode.UNKNOWN
    is_up: bool = False
    mac_address: MACAddress = "00:00:00:00:00:00"
    active_channel: Optional[NetworkChannel] = None
    tx_power: Optional[int] = None
    supported_modes: List[InterfaceMode] = Field(default_factory=list)
    driver: Optional[str] = None
    phy: Optional[str] = None

class NetworkState(BaseModel):
    model_config = ConfigDict(strict=True)
    interfaces: Dict[str, InterfaceState] = Field(default_factory=dict)
    access_points: Dict[str, AccessPoint] = Field(default_factory=dict)
    last_scan_time: NonNegativeFloat = 0.0
    scan_in_progress: bool = False
    total_aps_discovered: NonNegativeInt = 0
    total_clients_discovered: NonNegativeInt = 0

    @field_validator("access_points", mode="before")
    @classmethod
    def ensure_access_points(cls, v):
        if v is None:
            return {}
        if isinstance(v, dict):
            coerced = {}
            for k, val in v.items():
                try:
                    if isinstance(val, AccessPoint):
                        coerced[k] = val
                    elif isinstance(val, dict):
                        coerced[k] = AccessPoint(**val)
                    else:
                        coerced[k] = AccessPoint(bssid=str(k))
                except Exception as e:
                    logging.getLogger("kaiagotchi.data.types").warning(
                        f"AccessPoint coercion failed for {k}: {e}"
                    )
                    coerced[k] = AccessPoint(bssid=str(k))
            return coerced
        return {}

# --- AGENT & METRICS MODELS ---
class AgentStatus(BaseModel):
    model_config = ConfigDict(strict=True)
    agent_id: str
    status: AgentState = AgentState.IDLE
    description: str = "Initialized"
    last_action: Optional[str] = None
    last_update: NonNegativeFloat = Field(default_factory=time.time)
    error_count: NonNegativeInt = 0
    restart_count: NonNegativeInt = 0
    health_score: Percentage = 100.0

class SessionMetrics(BaseModel):
    model_config = ConfigDict(strict=True)
    session_start: NonNegativeFloat = Field(default_factory=time.time)
    deauthed_clients: NonNegativeInt = 0
    associated_aps: NonNegativeInt = 0
    handshakes_secured: NonNegativeInt = 0
    pmkids_captured: NonNegativeInt = 0
    peer_units: NonNegativeInt = 0
    duration_seconds: NonNegativeFloat = 0.0
    targets_identified: NonNegativeInt = 0
    successful_attacks: NonNegativeInt = 0
    failed_attacks: NonNegativeInt = 0

class SystemMetrics(BaseModel):
    model_config = ConfigDict(strict=True)
    cpu_usage: Percentage = 0.0
    memory_usage: Percentage = 0.0
    disk_free_gb: NonNegativeFloat = 0.0
    uptime_seconds: NonNegativeFloat = 0.0
    temperature: Optional[float] = None
    network_throughput_rx: NonNegativeFloat = 0.0
    network_throughput_tx: NonNegativeFloat = 0.0
    battery_level: Optional[Percentage] = None

# --- CORE SYSTEM STATE ---
class SystemState(BaseModel):
    model_config = ConfigDict(
        strict=True,
        validate_assignment=True,
        extra="allow",
        arbitrary_types_allowed=True
    )

    current_system_state: GlobalSystemState = GlobalSystemState.BOOTING
    network: NetworkState = Field(default_factory=NetworkState)
    agents: Dict[str, AgentStatus] = Field(default_factory=dict)
    metrics: SystemMetrics = Field(default_factory=SystemMetrics)
    session_metrics: SessionMetrics = Field(default_factory=SessionMetrics)
    last_state_update: NonNegativeFloat = Field(default_factory=time.time)
    config_hash: Optional[str] = None

    @field_validator("current_system_state", mode="before")
    @classmethod
    def ensure_enum(cls, v):
        if isinstance(v, GlobalSystemState):
            return v
        if isinstance(v, str):
            try:
                return GlobalSystemState(v)
            except ValueError:
                return GlobalSystemState.BOOTING
        return GlobalSystemState.BOOTING

    @field_validator("network", mode="before")
    @classmethod
    def ensure_network_state(cls, v):
        if isinstance(v, NetworkState):
            return v
        if isinstance(v, dict):
            try:
                return NetworkState(**v)
            except Exception as e:
                logging.getLogger("kaiagotchi.data.types").error(
                    f"NetworkState coercion failed: {e}"
                )
        return NetworkState()

    @field_validator("agents", mode="before")
    @classmethod
    def ensure_agents(cls, v):
        if not v:
            return {}
        if isinstance(v, dict):
            coerced = {}
            for aid, val in v.items():
                try:
                    if isinstance(val, AgentStatus):
                        coerced[aid] = val
                    elif isinstance(val, dict):
                        coerced[aid] = AgentStatus(**val)
                    else:
                        coerced[aid] = AgentStatus(agent_id=str(aid))
                except Exception as e:
                    logging.getLogger("kaiagotchi.data.types").warning(
                        f"AgentStatus coercion failed for {aid}: {e}"
                    )
                    coerced[aid] = AgentStatus(agent_id=str(aid))
            return coerced
        return {}

    def safe_dump(self) -> dict:
        """Dump safely, ensuring no pydantic serializer warnings."""
        try:
            self.agents = self.ensure_agents(self.agents)
            self.network = self.ensure_network_state(self.network)
            return super().model_dump()
        except Exception as e:
            logging.getLogger("kaiagotchi.data.types").error(f"Safe dump failed: {e}")
            return {}

# --- EVENT MODELS ---
class SystemEvent(BaseModel):
    model_config = ConfigDict(strict=True)
    event_id: str
    event_type: str
    timestamp: NonNegativeFloat = Field(default_factory=time.time)
    source: str
    severity: str = "INFO"
    details: Dict[str, Any] = Field(default_factory=dict)

class HandshakeCaptureEvent(SystemEvent):
    bssid: BSSID
    client_mac: Optional[MACAddress] = None
    handshake_type: str
    file_path: Optional[str] = None