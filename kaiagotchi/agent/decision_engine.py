# kaiagotchi/agent/decision_engine.py - Fixed enum
import logging
import time
from typing import Dict, Any, Optional
from enum import Enum, auto
from dataclasses import dataclass

# Use relative import for EventEmitter
try:
    from ..events import EventEmitter
except ImportError:
    # Fallback
    class EventEmitter:
        def emit_sync(self, event, data):
            pass

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
        
    def _transition_to(self, new_state: AgentState, reason: str) -> AgentState:
        if self.current_state != new_state:
            decision_logger.info(f"STATE TRANSITION: {self.current_state.name} -> {new_state.name}. Reason: {reason}")
            self.current_state = new_state
            self._last_state_change = time.time()
            self.events.emit_sync("state_changed", new_state.name)
        return new_state

    def process_state(self, state: Dict[str, Any], action_manager: Any) -> AgentState:
        """
        Process current system state and determine the next operational state.
        """
        # Simplified version for now - remove complex logic that depends on missing modules
        global_pause = state.get("global_control", {}).get("pause", False)
        
        if global_pause and self.current_state != AgentState.PAUSED:
            return self._transition_to(AgentState.PAUSED, "Global pause command received.")
        
        if self.current_state == AgentState.PAUSED:
            if not global_pause:
                return self._transition_to(AgentState.RECON_SCAN, "Global pause lifted.")
            return AgentState.PAUSED

        # Basic state transitions
        if self.current_state == AgentState.INITIALIZING:
            ready_interfaces = state.get("network", {}).get("ready_interfaces", [])
            if ready_interfaces:
                return self._transition_to(AgentState.RECON_SCAN, "Network interfaces ready.")
            if (time.time() - self._last_state_change) > 60:
                return self._transition_to(AgentState.MAINTENANCE, "Initialization timeout.")

        # For now, just cycle through states for testing
        elif self.current_state == AgentState.RECON_SCAN:
            if (time.time() - self._last_state_change) > 30:
                return self._transition_to(AgentState.MAINTENANCE, "Reconnaissance cycle complete.")
        
        elif self.current_state == AgentState.MAINTENANCE:
            if (time.time() - self._last_state_change) > 10:
                return self._transition_to(AgentState.RECON_SCAN, "Maintenance complete.")

        return self.current_state