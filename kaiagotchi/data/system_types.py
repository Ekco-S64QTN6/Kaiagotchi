import time
from enum import Enum
from typing import Dict, List, Optional, Annotated, Set, Any
from pydantic import BaseModel, Field, ConfigDict, validator, field_validator
from ipaddress import IPv4Address, IPv6Address

# --- CUSTOM PYDANTIC TYPES (Pydantic V2 Idiom for Constraints) ---
# Defining these custom types resolves common IDE warnings and improves clarity.
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
NetworkChannel = Annotated[int, Field(ge=1, le=165)]
FrequencyMHz = Annotated[int, Field(ge=2400)]
Percentage = Annotated[float, Field(ge=0.0, le=100.0)]
MACAddress = Annotated[str, Field(pattern=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')]
BSSID = MACAddress  # Alias for clarity
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
    PAUSED = "PAUSED"  # New state for temporary suspension

class GlobalSystemState(str, Enum):
    """
    Defines the global state of the entire Kaia system.
    """
    BOOTING = "BOOTING"
    MONITORING = "MONITORING"
    TARGETING = "TARGETING"  # More precise than "ATTACKING"
    ATTACKING = "ATTACKING"  # Keep for backward compatibility
    MAINTENANCE = "MAINTENANCE"  # New state for system upkeep
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
    WPA_WPA2 = "WPA/WPA2"  # Mixed mode
    UNKNOWN = "Unknown"

class AccessPointType(str, Enum):
    """
    Defines the network type.
    """
    INFRASTRUCTURE = "Infrastructure"
    ADHOC = "Ad-Hoc"
    CLIENT = "Client"
    MESH = "Mesh"  # Additional type
    UNKNOWN = "Unknown"

class InterfaceMode(str, Enum):
    """
    Defines the operating mode of a wireless interface.
    """
    MONITOR = "monitor"
    MANAGED = "managed"
    AP = "ap"
    IBSS = "ibss"  # Ad-hoc mode
    UNKNOWN = "unknown"

class SecurityLevel(str, Enum):
    """
    Defines the security assessment level for targets.
    """
    LOW = "LOW"      # Open/WEP networks
    MEDIUM = "MEDIUM" # WPA networks
    HIGH = "HIGH"    # WPA2/WPA3 networks
    UNKNOWN = "UNKNOWN"

# --- NETWORK MODELS ---

class WirelessClient(BaseModel):
    """Represents a wireless client (station)."""
    model_config = ConfigDict(strict=True)
    
    mac: MACAddress = Field(..., description="Client MAC address")
    vendor: Optional[str] = Field(None, description="Hardware vendor from OUI")
    first_seen: NonNegativeFloat = Field(default_factory=time.time, description="First detection timestamp")
    last_seen: NonNegativeFloat = Field(default_factory=time.time, description="Last detection timestamp")
    power: int = Field(0, description="Signal power in dBm")
    packets: NonNegativeInt = Field(0, description="Number of packets observed")
    is_associated: bool = Field(False, description="Whether client is associated with an AP")

class AccessPoint(BaseModel):
    """Represents a discovered Access Point."""
    model_config = ConfigDict(strict=True)
    
    bssid: BSSID = Field(..., description="Hardware address (BSSID).")
    ssid: Optional[str] = Field(None, description="Network name (ESSID).")
    protocol: AccessPointProtocol = Field(AccessPointProtocol.UNKNOWN, description="Security protocol in use.")
    ap_type: AccessPointType = Field(AccessPointType.UNKNOWN, description="Type of network device.")
    channel: NetworkChannel = Field(1, description="Current channel of operation.")
    frequency: FrequencyMHz = Field(2412, description="Frequency in MHz.")
    power: int = Field(0, description="Signal strength in dBm")
    privacy: bool = Field(False, description="True if network uses encryption")
    cipher: Optional[str] = Field(None, description="Encryption cipher suite")
    first_seen: NonNegativeFloat = Field(default_factory=time.time, description="First detection timestamp")
    last_seen: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last packet capture.")
    clients: Dict[str, WirelessClient] = Field(default_factory=dict, description="Associated clients")
    handshakes_captured: NonNegativeInt = Field(0, description="Number of full handshakes captured.")
    pmkid_captured: bool = Field(False, description="Whether PMKID was captured")
    is_target: bool = Field(False, description="Flag if this AP is currently being actively targeted.")
    security_level: SecurityLevel = Field(SecurityLevel.UNKNOWN, description="Assessed security level")
    
    @field_validator('ssid')
    @classmethod
    def validate_ssid(cls, v: Optional[str]) -> Optional[str]:
        """Validate and clean SSID."""
        if v is None:
            return v
        # Remove non-printable characters
        cleaned = ''.join(char for char in v if char.isprintable())
        return cleaned.strip() or None

class InterfaceState(BaseModel):
    """Represents the operational status of a single network interface."""
    model_config = ConfigDict(strict=True)
    
    name: str = Field(..., description="Interface name (e.g., wlan0, mon0).")
    mode: InterfaceMode = Field(InterfaceMode.UNKNOWN, description="Current operational mode.")
    is_up: bool = Field(False, description="True if the interface is link-up.")
    mac_address: MACAddress = Field("00:00:00:00:00:00", description="MAC address.")
    active_channel: Optional[NetworkChannel] = Field(None, description="Currently tuned channel.")
    tx_power: Optional[int] = Field(None, description="Transmit power in dBm")
    supported_modes: List[InterfaceMode] = Field(default_factory=list, description="Supported interface modes")
    driver: Optional[str] = Field(None, description="Wireless driver name")
    phy: Optional[str] = Field(None, description="Physical device identifier")
    
class NetworkState(BaseModel):
    """The composite state of the entire network environment."""
    model_config = ConfigDict(strict=True)
    
    interfaces: Dict[str, InterfaceState] = Field(default_factory=dict, description="Status of all known network interfaces.")
    access_points: Dict[str, AccessPoint] = Field(default_factory=dict, description="A registry of all discovered access points by BSSID.")
    last_scan_time: NonNegativeFloat = Field(0.0, description="Timestamp of the last comprehensive network scan.")
    scan_in_progress: bool = Field(False, description="Whether a scan is currently running")
    total_aps_discovered: NonNegativeInt = Field(0, description="Total unique APs discovered this session")
    total_clients_discovered: NonNegativeInt = Field(0, description="Total unique clients discovered this session")

# --- AGENT & METRICS MODELS ---

class AgentStatus(BaseModel):
    """Status metrics for a single Kaiagotchi Agent."""
    model_config = ConfigDict(strict=True)
    
    agent_id: str = Field(..., description="Unique identifier for the agent.")
    status: AgentState = Field(AgentState.IDLE, description="The current state of the agent.")
    description: str = Field("Initialized", description="A short, human-readable status message.")
    last_action: Optional[str] = Field(None, description="A description of the last significant action taken.")
    last_update: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of the last status update.")
    error_count: NonNegativeInt = Field(0, description="Number of errors encountered")
    restart_count: NonNegativeInt = Field(0, description="Number of times agent has been restarted")
    health_score: Percentage = Field(100.0, description="Agent health score (0-100%)")

class SessionMetrics(BaseModel):
    """Metrics specific to the current operational session."""
    model_config = ConfigDict(strict=True)
    
    session_start: NonNegativeFloat = Field(default_factory=time.time, description="Session start timestamp")
    deauthed_clients: NonNegativeInt = Field(0, description="Total clients deauthenticated in the current session.")
    associated_aps: NonNegativeInt = Field(0, description="Total APs associated with in the current session.")
    handshakes_secured: NonNegativeInt = Field(0, description="Total verified handshakes secured this session.")
    pmkids_captured: NonNegativeInt = Field(0, description="Total PMKIDs captured this session")
    peer_units: NonNegativeInt = Field(0, description="Number of peer Kaia units detected.")
    duration_seconds: NonNegativeFloat = Field(0.0, description="Total duration of the current session in seconds.")
    targets_identified: NonNegativeInt = Field(0, description="Number of targets identified")
    successful_attacks: NonNegativeInt = Field(0, description="Number of successful attacks")
    failed_attacks: NonNegativeInt = Field(0, description="Number of failed attacks")

class SystemMetrics(BaseModel):
    """General system and resource usage metrics."""
    model_config = ConfigDict(strict=True)
    
    cpu_usage: Percentage = Field(0.0, description="Current system-wide CPU utilization percentage.")
    memory_usage: Percentage = Field(0.0, description="Current system-wide memory utilization percentage.")
    disk_free_gb: NonNegativeFloat = Field(0.0, description="Free disk space in Gigabytes.")
    uptime_seconds: NonNegativeFloat = Field(0.0, description="Time since the Kaia system was initiated.")
    temperature: Optional[float] = Field(None, description="System temperature in Celsius")
    network_throughput_rx: NonNegativeFloat = Field(0.0, description="Network receive throughput in MB/s")
    network_throughput_tx: NonNegativeFloat = Field(0.0, description="Network transmit throughput in MB/s")
    battery_level: Optional[Percentage] = Field(None, description="Battery level percentage if applicable")

# --- CORE SYSTEM STATE (Pydantic Model) ---

class SystemState(BaseModel):
    """
    The centralized, single source of truth for the entire Kaia system (Pydantic Model).
    This object is shared and mutated by all components (Agents, Engine, Manager).
    """
    model_config = ConfigDict(
        strict=True,
        validate_assignment=True,  # Validate on attribute assignment
        extra='forbid'  # Prevent extra fields
    )
    
    current_system_state: GlobalSystemState = Field(GlobalSystemState.BOOTING, description="The overall operational state of Kaia.")
    network: NetworkState = Field(default_factory=NetworkState, description="The observed state of the network environment.")
    agents: Dict[str, AgentStatus] = Field(default_factory=dict, description="The latest status for all active agents.")
    metrics: SystemMetrics = Field(default_factory=SystemMetrics, description="Resource and performance metrics.")
    session_metrics: SessionMetrics = Field(default_factory=SessionMetrics, description="Metrics specific to the current operational session.")
    last_state_update: NonNegativeFloat = Field(default_factory=time.time, description="Timestamp of last state update")
    config_hash: Optional[str] = Field(None, description="Hash of current configuration for change detection")
    
    @field_validator('current_system_state')
    @classmethod
    def validate_state_transitions(cls, v: GlobalSystemState, info: Any) -> GlobalSystemState:
        """Validate state transitions (basic sanity checks)."""
        # Could implement more sophisticated state transition logic here
        valid_transitions = {
            GlobalSystemState.BOOTING: {GlobalSystemState.MONITORING, GlobalSystemState.ERROR},
            GlobalSystemState.MONITORING: {GlobalSystemState.TARGETING, GlobalSystemState.MAINTENANCE, GlobalSystemState.SHUTDOWN},
            GlobalSystemState.TARGETING: {GlobalSystemState.MONITORING, GlobalSystemState.MAINTENANCE},
            GlobalSystemState.ATTACKING: {GlobalSystemState.MONITORING, GlobalSystemState.MAINTENANCE},
            GlobalSystemState.MAINTENANCE: {GlobalSystemState.MONITORING},
            GlobalSystemState.CLEANUP: {GlobalSystemState.SHUTDOWN},
            GlobalSystemState.SHUTDOWN: set()
        }
        # Implementation would require previous state context
        return v

# --- EVENT MODELS ---

class SystemEvent(BaseModel):
    """Base model for system events."""
    model_config = ConfigDict(strict=True)
    
    event_id: str = Field(..., description="Unique event identifier")
    event_type: str = Field(..., description="Type of event")
    timestamp: NonNegativeFloat = Field(default_factory=time.time, description="Event occurrence time")
    source: str = Field(..., description="Component that generated the event")
    severity: str = Field("INFO", description="Event severity level")
    details: Dict[str, Any] = Field(default_factory=dict, description="Event-specific details")

class HandshakeCaptureEvent(SystemEvent):
    """Event emitted when a handshake is captured."""
    bssid: BSSID = Field(..., description="AP BSSID")
    client_mac: Optional[MACAddress] = Field(None, description="Client MAC if applicable")
    handshake_type: str = Field(..., description="Type of handshake captured")
    file_path: Optional[str] = Field(None, description="Path to handshake file")