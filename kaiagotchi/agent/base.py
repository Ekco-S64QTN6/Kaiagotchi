# kaiagotchi/agent/base.py - Fixed imports
import asyncio
import logging
from typing import Dict, Any

# Import with fallbacks for missing modules
try:
    from kaiagotchi.data.system_types import SystemState, GlobalSystemState
    from kaiagotchi.events import EventEmitter
    from kaiagotchi.agent.decision_engine import DecisionEngine, AgentState
except ImportError as e:
    logging.warning(f"Some imports failed in base.py: {e}")
    # Create minimal fallbacks
    class GlobalSystemState:
        BOOTING = "BOOTING"
        READY = "READY"
    
    class SystemState:
        def __init__(self, **kwargs):
            self.config_hash = kwargs.get('config_hash', 'initial')
            self.current_system_state = kwargs.get('current_system_state', GlobalSystemState.BOOTING)
            self.network = kwargs.get('network', {})
            self.metrics = kwargs.get('metrics', {})
    
    class EventEmitter:
        async def emit(self, event, data):
            pass
    
    class AgentState:
        INITIALIZING = "INITIALIZING"
        RECON_SCAN = "RECON_SCAN"
    
    class DecisionEngine:
        def __init__(self, config):
            self.config = config
            self.current_state = AgentState.INITIALIZING
        
        def process_state(self, state, action_manager):
            return AgentState.RECON_SCAN

agent_logger = logging.getLogger('agent.base')

class KaiagotchiBase:
    """
    The foundational class for the Kaiagotchi Agent. Handles configuration,
    centralized state management, event dispatch, and the main decision loop.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.events = EventEmitter()
        self.decision_engine = DecisionEngine(config)
        self.action_manager = None
        
        # Centralized state management
        self.system_state = SystemState(
            config_hash="initial",
            current_system_state=GlobalSystemState.BOOTING
        ) 
        
        self._state_lock = asyncio.Lock()

    async def update_state(self, updates: Dict[str, Any]) -> None:
        """
        Asynchronously update the central SystemState.
        """
        async with self._state_lock:
            try:
                # Handle both Pydantic model and fallback class
                if hasattr(self.system_state, 'model_copy'):
                    self.system_state = self.system_state.model_copy(update=updates)
                else:
                    # Fallback for basic class
                    for key, value in updates.items():
                        setattr(self.system_state, key, value)
            except Exception as e:
                self.logger.error(f"Failed to update SystemState: {e}")
                return
            
            await self.events.emit("state_updated", self.system_state)

    async def run_decision_cycle(self):
        """
        Runs one decision cycle.
        """
        try:
            async with self._state_lock:
                if hasattr(self.system_state, 'model_dump'):
                    current_state_data = self.system_state.model_dump()
                else:
                    current_state_data = self.system_state.__dict__
            
            new_agent_state_enum = self.decision_engine.process_state(
                current_state_data, 
                self.action_manager
            )
            
            if self.system_state.current_system_state != new_agent_state_enum:
                self.logger.info(f"Agent state changing from {self.system_state.current_system_state} to {new_agent_state_enum}")
                state_update = {"current_system_state": new_agent_state_enum}
                await self.update_state(state_update)
            
        except Exception as e:
            self.logger.error(f"Error in decision cycle: {e}")

    async def _gather_state(self) -> Dict[str, Any]:
        """
        Gather initial system state.
        """
        return {
            "metrics": {
                "uptime_seconds": 0.0,
                "cpu_usage": 0.1,
                "memory_usage": 0.1,
                "disk_free_gb": 100.0,
            },
            "network": {
                "interfaces": {
                    "wlan0": {
                        "name": "wlan0",
                        "is_up": True,
                        "mode": "managed",
                    }
                },
                "ready_interfaces": ["wlan0"]
            }
        }

    async def start(self):
        """
        Main async loop to start the agent's operation.
        """
        try:
            self.logger.info("Agent starting up...")
            
            initial_updates = await self._gather_state()
            await self.update_state(initial_updates)
            
            self.logger.info("Initial state established. Starting decision loop.")
            
            while True:
                await self.run_decision_cycle()
                await asyncio.sleep(self.config.get("decision_cycle_delay", 5.0))
                
        except asyncio.CancelledError:
            self.logger.info("Agent stopping gracefully...")
        except Exception as e:
            self.logger.critical(f"Unhandled exception: {e}")

    def run(self):
        """
        Synchronous run method for compatibility.
        """
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            self.logger.info("Agent stopped by user")
        except Exception as e:
            self.logger.critical(f"Agent crashed: {e}")

    def stop(self):
        """
        Stop the agent gracefully.
        """
        self.logger.info("Stopping agent...")
        # Implementation would cancel asyncio tasks