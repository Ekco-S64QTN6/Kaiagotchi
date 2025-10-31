import time
from enum import Enum
from typing import Dict, List, Optional, Annotated
from pydantic import BaseModel, Field, conint, confloat # Kept for potential V1 compatibility, but using new types

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
    Defines the current operational state of a given agent.
    """
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"

class SystemState(str, Enum):
    """
    Defines the global state of the entire Kaia system.
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
    Defines the possible operating modes for a network interface.
    """
    MONITOR = "monitor"
    MANAGED = "managed"
    AP = "AP"
    UNKNOWN = "unknown"

# --- MODEL DEFINITIONS ---

class InterfaceStatus(BaseModel):
    """
    Current status and configuration for a single network interface.
    """
    name: str = Field(..., description="The name of the network interface (e.g., wlan0).")
    mac: str = Field(..., description="The MAC address of the interface.")
    mode: InterfaceMode = Field(..., description="The current mode of the interface (e.g., monitor, managed).")
    channel: NetworkChannel = Field(1, description="The currently tuned channel (1-165).")
    is_up: bool = Field(False, description="True if the interface is active/up.")

class AccessPoint(BaseModel):
    """
    Details of a discovered Access Point or Client.
    """
    bssid: str = Field(..., description="The MAC address (BSSID) of the access point.")
    ssid: str = Field(..., description="The human-readable name (ESSID) of the network.")
    protocol: AccessPointProtocol = Field(AccessPointProtocol.OPEN, description="The security protocol in use (e.g., WPA2).")
    ap_type: AccessPointType = Field(AccessPointType.INFRASTRUCTURE, description="The type of network (e.g., Infrastructure).")
    channel: NetworkChannel = Field(1, description="The operating channel of the AP (1-165).")
    frequency: FrequencyMHz = Field(2400, description="The center frequency of the channel in MHz (e.g., 2412).")
    last_seen: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last observation.")
    clients: Dict[str, 'AccessPoint'] = Field(default_factory=dict, description="A map of connected client MACs to their details.")

# Forward reference for AccessPoint
AccessPoint.model_rebuild()

class NetworkState(BaseModel):
    """
    The current aggregated state of the network environment.
    """
    interfaces: Dict[str, InterfaceStatus] = Field(default_factory=dict, description="Status for all detected network interfaces.")
    access_points: Dict[str, AccessPoint] = Field(default_factory=dict, description="A map of BSSID to AccessPoint details.")
    handshakes_dir: str = Field("/var/lib/kaiagotchi/handshakes", description="Path to the directory where handshakes are stored.")
    channel_hop_interval: PositiveInt = Field(5, description="Interval in seconds between channel hops.")
    # Other network-specific configurations can go here

class AgentStatus(BaseModel):
    """
    Status metrics for an individual agent (e.g., MONITOR, ATTACK).
    """
    agent_id: str = Field(..., description="Unique identifier for the agent.")
    state: AgentState = Field(AgentState.IDLE, description="The current state of the agent (IDLE, RUNNING, etc.).")
    last_action: Optional[str] = Field(None, description="A description of the last significant action taken.")
    last_update: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last status update.")

class SessionMetrics(BaseModel):
    """
    Performance metrics and counts tracked for the current or last operational session.
    (This model was missing, based on the metrics you provided.)
    """
    epochs: NonNegativeInt = Field(0, description="Total epochs completed since start.")
    train_epochs: NonNegativeInt = Field(0, description="Total training epochs completed.")
    avg_reward: NonNegativeFloat = Field(0.0, description="Average reward metric.")
    min_reward: NonNegativeFloat = Field(0.0, description="Minimum reward metric.")
    max_reward: NonNegativeFloat = Field(0.0, description="Maximum reward metric.")
    deauthed: NonNegativeInt = Field(0, description="Number of clients successfully deauthenticated.")
    associated: NonNegativeInt = Field(0, description="Number of networks successfully associated with.")
    handshakes: NonNegativeInt = Field(0, description="Number of unique, verified handshakes captured.")
    peers: NonNegativeInt = Field(0, description="Number of connected peer units.")
    duration_seconds: NonNegativeFloat = Field(0.0, description="Total duration of the current session in seconds.")


class SystemMetrics(BaseModel):
    """
    General system and resource usage metrics.
    """
    cpu_usage: NonNegativeFloat = Field(0.0, description="Current system-wide CPU utilization percentage.")
    memory_usage: NonNegativeFloat = Field(0.0, description="Current system-wide memory utilization percentage.")
    disk_free_gb: NonNegativeFloat = Field(0.0, description="Free disk space in Gigabytes.")
    uptime_seconds: NonNegativeFloat = Field(0.0, description="Time since the Kaia system was initiated.")


class SystemState(BaseModel):
    """
    The centralized, single source of truth for the entire Kaia system.
    This object is shared and mutated by all components (Agents, Engine, Manager).
    """
    current_system_state: SystemState = Field(SystemState.BOOTING, description="The overall operational state of Kaia.")
    network: NetworkState = Field(default_factory=NetworkState, description="The observed state of the network environment.")
    agents: Dict[str, AgentStatus] = Field(default_factory=dict, description="The latest status for all active agents.")
    metrics: SystemMetrics = Field(default_factory=SystemMetrics, description="Resource and performance metrics.")
    session_metrics: SessionMetrics = Field(default_factory=SessionMetrics, description="Metrics specific to the current operational session.")
