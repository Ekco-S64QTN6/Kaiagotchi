# filepath: kaiagotchi/agent/decision_engine.py
import logging
import time
from typing import Dict, Any, Optional, TYPE_CHECKING
from enum import Enum, auto
from dataclasses import dataclass
from ..events import EventEmitter

if TYPE_CHECKING:
    from ..network.protocols import ActionManager

decision_logger = logging.getLogger("agent.decider")

@dataclass
class InterfaceCache:
    data: Dict[str, Any]
    timestamp: float

class AgentState(Enum):
    """Defines the core operational states of the Kaiagotchi Agent."""
    INITIALIZING = auto()
    RECON_SCAN = auto()
    TARGETING = auto()
    MAINTENANCE = auto()
    PAUSED = auto()

class DecisionEngine:
    """Core state machine that drives agent behavior."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.current_state = AgentState.INITIALIZING
        self._last_state_change = time.time()
        self._iface_cache: Dict[str, InterfaceCache] = {}
        self._cache_ttl = 5.0
        self.events = EventEmitter()
        
    def _get_interface_info(self, iface: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        now = time.time()
        cache = self._iface_cache.get(iface)
        
        if cache and (now - cache.timestamp) < self._cache_ttl:
            return cache.data
            
        network_state = state.get("network", {})
        iface_data = network_state.get("interfaces", {}).get(iface, {})
        
        if iface_data:
            self._iface_cache[iface] = InterfaceCache(
                data=iface_data.copy(),
                timestamp=now
            )
            return iface_data
        return None

    def process_state(self, state: Dict[str, Any], action_manager: Any) -> AgentState:
        """Process current state and determine next state."""
        if self.current_state == AgentState.INITIALIZING:
            if state.get("network", {}).get("interface_count", 0) > 0:
                self.current_state = AgentState.RECON_SCAN
                
        return self.current_state
