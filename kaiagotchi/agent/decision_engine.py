# kaiagotchi/agent/decision_engine.py - Fixed implementation
import asyncio
import logging
import time
from typing import Dict, Any, Optional
from enum import Enum, auto
from dataclasses import dataclass

# Use proper imports with fallbacks
try:
    from kaiagotchi.events import EventEmitter
    from kaiagotchi.data.system_types import GlobalSystemState
except ImportError:
    # Fallback implementations
    class EventEmitter:
        async def emit(self, event, data):
            logging.debug(f"Event: {event} - {data}")
    
    class GlobalSystemState:
        BOOTING = "BOOTING"
        MONITORING = "MONITORING"
        TARGETING = "TARGETING"
        MAINTENANCE = "MAINTENANCE"
        SHUTDOWN = "SHUTDOWN"

# Module-specific logger
decision_logger = logging.getLogger("kaiagotchi.agent.decision_engine")

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
        self._state_history = []
        
    def _transition_to(self, new_state: AgentState, reason: str) -> AgentState:
        """Safely transition to a new state with logging and event emission."""
        if self.current_state != new_state:
            decision_logger.info(f"STATE TRANSITION: {self.current_state.name} -> {new_state.name}. Reason: {reason}")
            
            # Record state history (keep last 10 transitions)
            self._state_history.append({
                'from': self.current_state.name,
                'to': new_state.name,
                'timestamp': time.time(),
                'reason': reason
            })
            self._state_history = self._state_history[-10:]
            
            self.current_state = new_state
            self._last_state_change = time.time()
            
            # Emit state change event
            asyncio.create_task(self.events.emit("state_changed", {
                'previous_state': self.current_state.name,
                'new_state': new_state.name,
                'reason': reason,
                'timestamp': time.time()
            }))
            
        return new_state

    def process_state(self, state: Dict[str, Any], action_manager: Any) -> AgentState:
        """
        Process current system state and determine the next operational state.
        
        Args:
            state: Current system state dictionary
            action_manager: Action manager for network operations
            
        Returns:
            New agent state to transition to
        """
        try:
            # Extract relevant state information
            current_global_state = state.get('current_system_state', GlobalSystemState.BOOTING)
            network_state = state.get('network', {})
            metrics = state.get('metrics', {})
            session_metrics = state.get('session_metrics', {})
            
            # Check for global pause/stop conditions
            if current_global_state == GlobalSystemState.SHUTDOWN:
                return self._transition_to(AgentState.PAUSED, "System shutdown requested")
            
            # Handle paused state
            if self.current_state == AgentState.PAUSED:
                if current_global_state == GlobalSystemState.MONITORING:
                    return self._transition_to(AgentState.RECON_SCAN, "Resuming from pause")
                return AgentState.PAUSED

            # State transition logic
            if self.current_state == AgentState.INITIALIZING:
                # Check if we have working network interfaces
                interfaces = network_state.get('interfaces', {})
                ready_interfaces = [iface for iface in interfaces.values() if iface.get('is_up', False)]
                
                if ready_interfaces:
                    return self._transition_to(AgentState.RECON_SCAN, "Network interfaces ready for reconnaissance")
                
                # Timeout initialization if taking too long
                if (time.time() - self._last_state_change) > 60:
                    return self._transition_to(AgentState.MAINTENANCE, "Initialization timeout - entering maintenance")

            elif self.current_state == AgentState.RECON_SCAN:
                # Check if we found any interesting targets
                access_points = network_state.get('access_points', {})
                interesting_aps = [ap for ap in access_points.values() 
                                 if ap.get('is_target', False) or ap.get('handshakes_captured', 0) > 0]
                
                if interesting_aps and (time.time() - self._last_state_change) > 30:
                    return self._transition_to(AgentState.TARGETING, "Found interesting targets for engagement")
                
                # Cycle to maintenance after extended reconnaissance
                if (time.time() - self._last_state_change) > 120:
                    return self._transition_to(AgentState.MAINTENANCE, "Reconnaissance cycle complete")

            elif self.current_state == AgentState.TARGETING:
                # Check if we should return to reconnaissance
                if (time.time() - self._last_state_change) > 60:
                    return self._transition_to(AgentState.RECON_SCAN, "Targeting cycle complete")
                
                # Check for system issues that require maintenance
                cpu_usage = metrics.get('cpu_usage', 0.0)
                if cpu_usage > 0.8:  # 80% CPU usage
                    return self._transition_to(AgentState.MAINTENANCE, "High system load detected")

            elif self.current_state == AgentState.MAINTENANCE:
                # Return to normal operation after maintenance
                if (time.time() - self._last_state_change) > 30:
                    return self._transition_to(AgentState.RECON_SCAN, "Maintenance complete")

            # Default: remain in current state
            return self.current_state

        except Exception as e:
            decision_logger.error(f"Error in state processing: {e}")
            # Fallback to safe state
            return AgentState.RECON_SCAN

    def get_state_info(self) -> Dict[str, Any]:
        """Get current state information for debugging/monitoring."""
        return {
            'current_state': self.current_state.name,
            'time_in_state': time.time() - self._last_state_change,
            'state_history': self._state_history[-5:],  # Last 5 transitions
            'cache_size': len(self._iface_cache)
        }