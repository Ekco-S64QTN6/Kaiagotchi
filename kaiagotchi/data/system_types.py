import time
from enum import Enum
from typing import Dict, List, Optional, Annotated
from pydantic import BaseModel, Field, conint, confloat 

# --- CUSTOM PYDANTIC TYPES (Pydantic V2 Idiom for Constraints) ---
# Defining these custom types resolves common IDE warnings and improves clarity.
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
NetworkChannel = Annotated[int, Field(ge=1, le=165)]
FrequencyMHz = Annotated[int, Field(ge=2400)]
# ------------------------------------------------------------------

# --- ENUM DEFINITIONS ---

class AgentState(str, Enum):
    """
    Defines the current operational state of a given agent (e.g., MonitoringAgent).
    """
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"

class GlobalSystemState(str, Enum):
    """
    Defines the global state of the entire Kaia system.
    (Renamed from 'SystemState' to avoid Pydantic Model name conflict)
    """
    BOOTING = "BOOTING"
    MONITORING = "MONITORING"
    ATTACKING = "ATTACKING"
    CLEANUP = "CLEANUP"
    SHUTDOWN = "SHUTDOWN"

class AccessPointProtocol(str, Enum):
    """
    Defines the security protocol of an Access Point.
    """
    OPEN = "Open"
    WEP = "WEP"
    WPA = "WPA"
    WPA2 = "WPA2"
    WPA3 = "WPA3"

class AccessPointType(str, Enum):
    """
    Defines the network type.
    """
    INFRASTRUCTURE = "Infrastructure"
    ADHOC = "Ad-Hoc"
    CLIENT = "Client" # Treat clients as their own AP type temporarily

class InterfaceMode(str, Enum):
    """
    Defines the operating mode of a wireless interface.
    """
    MONITOR = "monitor"
    MANAGED = "managed"
    AP = "ap"

# --- NETWORK MODELS ---

class AccessPoint(BaseModel):
    """Represents a discovered Access Point."""
    bssid: str = Field(..., description="Hardware address (BSSID).")
    ssid: Optional[str] = Field(None, description="Network name (ESSID).")
    protocol: AccessPointProtocol = Field(AccessPointProtocol.OPEN, description="Security protocol in use.")
    ap_type: AccessPointType = Field(AccessPointType.INFRASTRUCTURE, description="Type of network device.")
    channel: NetworkChannel = Field(1, description="Current channel of operation.")
    frequency: FrequencyMHz = Field(2412, description="Frequency in MHz.")
    last_seen: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last packet capture.")
    handshakes_captured: NonNegativeInt = Field(0, description="Number of full handshakes captured.")
    is_target: bool = Field(False, description="Flag if this AP is currently being actively targeted.")

class InterfaceState(BaseModel):
    """Represents the operational status of a single network interface."""
    name: str = Field(..., description="Interface name (e.g., wlan0, mon0).")
    mode: InterfaceMode = Field(InterfaceMode.MANAGED, description="Current operational mode (managed, monitor, etc.).")
    is_up: bool = Field(False, description="True if the interface is link-up.")
    mac_address: str = Field("00:00:00:00:00:00", description="MAC address.")
    active_channel: Optional[NetworkChannel] = Field(None, description="Currently tuned channel.")
    
class NetworkState(BaseModel):
    """The composite state of the entire network environment."""
    interfaces: Dict[str, InterfaceState] = Field(default_factory=dict, description="Status of all known network interfaces.")
    access_points: Dict[str, AccessPoint] = Field(default_factory=dict, description="A registry of all discovered access points by BSSID.")
    last_scan_time: NonNegativeFloat = Field(0.0, description="Timestamp of the last comprehensive network scan.")

# --- AGENT & METRICS MODELS ---

class AgentStatus(BaseModel):
    """Status metrics for a single Kaiagotchi Agent."""
    agent_id: str = Field(..., description="Unique identifier for the agent.")
    status: AgentState = Field(AgentState.IDLE, description="The current state of the agent (IDLE, RUNNING, etc.).")
    description: str = Field("Initialized", description="A short, human-readable status message.")
    last_action: Optional[str] = Field(None, description="A description of the last significant action taken.")
    last_update: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last status update.")

class SessionMetrics(BaseModel):
    """Metrics specific to the current operational session."""
    deauthed_clients: NonNegativeInt = Field(0, description="Total clients deauthenticated in the current session.")
    associated_aps: NonNegativeInt = Field(0, description="Total APs associated with in the current session.")
    handshakes_secured: NonNegativeInt = Field(0, description="Total verified handshakes secured this session.")
    peer_units: NonNegativeInt = Field(0, description="Number of peer Kaia units detected.")
    duration_seconds: NonNegativeFloat = Field(0.0, description="Total duration of the current session in seconds.")


class SystemMetrics(BaseModel):
    """General system and resource usage metrics."""
    cpu_usage: NonNegativeFloat = Field(0.0, description="Current system-wide CPU utilization percentage.")
    memory_usage: NonNegativeFloat = Field(0.0, description="Current system-wide memory utilization percentage.")
    disk_free_gb: NonNegativeFloat = Field(0.0, description="Free disk space in Gigabytes.")
    uptime_seconds: NonNegativeFloat = Field(0.0, description="Time since the Kaia system was initiated.")

# --- CORE SYSTEM STATE (Pydantic Model) ---

class SystemState(BaseModel):
    """
    The centralized, single source of truth for the entire Kaia system (Pydantic Model).
    This object is shared and mutated by all components (Agents, Engine, Manager).
    """
    current_system_state: GlobalSystemState = Field(GlobalSystemState.BOOTING, description="The overall operational state of Kaia.")
    network: NetworkState = Field(default_factory=NetworkState, description="The observed state of the network environment.")
    agents: Dict[str, AgentStatus] = Field(default_factory=dict, description="The latest status for all active agents.")
    metrics: SystemMetrics = Field(default_factory=SystemMetrics, description="Resource and performance metrics.")
    session_metrics: SessionMetrics = Field(default_factory=SessionMetrics, description="Metrics specific to the current operational session.")