# kaiagotchi/agent/base.py - Fixed imports and architecture
import asyncio
import logging
import time
from typing import Dict, Any, Optional, Set

# Import with proper error handling
try:
    from kaiagotchi.data.system_types import SystemState, GlobalSystemState
    from kaiagotchi.events import EventEmitter
    from kaiagotchi.agent.decision_engine import DecisionEngine, AgentState
except ImportError as e:
    logging.warning(f"Some imports failed in base.py: {e}")
    # Create minimal fallbacks for development
    class GlobalSystemState:
        BOOTING = "BOOTING"
        MONITORING = "MONITORING"
        TARGETING = "TARGETING"
        MAINTENANCE = "MAINTENANCE"
        SHUTDOWN = "SHUTDOWN"
    
    class SystemState:
        def __init__(self, **kwargs):
            self.current_system_state = kwargs.get('current_system_state', GlobalSystemState.BOOTING)
            self.network = kwargs.get('network', {})
            self.metrics = kwargs.get('metrics', {})
            self.agents = kwargs.get('agents', {})
            self.session_metrics = kwargs.get('session_metrics', {})
            self.last_state_update = time.time()
    
    class EventEmitter:
        async def emit(self, event, data):
            logging.debug(f"Event emitted: {event} - {data}")
    
    class AgentState:
        INITIALIZING = "INITIALIZING"
        RECON_SCAN = "RECON_SCAN"
        TARGETING = "TARGETING"
        MAINTENANCE = "MAINTENANCE"
        PAUSED = "PAUSED"
    
    class DecisionEngine:
        def __init__(self, config):
            self.config = config
            self.current_state = AgentState.INITIALIZING
        
        def process_state(self, state, action_manager):
            return AgentState.RECON_SCAN

# Create module-specific logger
agent_logger = logging.getLogger('kaiagotchi.agent.base')

class KaiagotchiBase:
    """
    The foundational class for the Kaiagotchi Agent. Handles configuration,
    centralized state management, event dispatch, and the main decision loop.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = agent_logger
        self.events = EventEmitter()
        self.decision_engine = DecisionEngine(config)
        self.action_manager = None
        self._running = False
        self._tasks: Set[asyncio.Task] = set()
        
        # Centralized state management with proper initialization
        self.system_state = SystemState(
            current_system_state=GlobalSystemState.BOOTING,
            network={"access_points": {}, "interfaces": {}, "last_scan_time": 0.0},
            metrics={"cpu_usage": 0.0, "memory_usage": 0.0, "disk_free_gb": 0.0, "uptime_seconds": 0.0},
            agents={},
            session_metrics={"duration_seconds": 0.0, "handshakes_secured": 0}
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
                    # Pydantic v2 model
                    self.system_state = self.system_state.model_copy(update=updates)
                else:
                    # Fallback for basic class - deep update
                    for key, value in updates.items():
                        if hasattr(self.system_state, key) and isinstance(getattr(self.system_state, key), dict):
                            getattr(self.system_state, key).update(value)
                        else:
                            setattr(self.system_state, key, value)
                
                # Update timestamp
                self.system_state.last_state_update = time.time()
                
            except Exception as e:
                self.logger.error(f"Failed to update SystemState: {e}")
                return
            
            await self.events.emit("state_updated", self.system_state)

    async def run_decision_cycle(self):
        """
        Runs one decision cycle.
        """
        try:
            # Create state snapshot for decision engine
            if hasattr(self.system_state, 'model_dump'):
                current_state_data = self.system_state.model_dump()
            else:
                current_state_data = {
                    'current_system_state': self.system_state.current_system_state,
                    'network': self.system_state.network,
                    'metrics': self.system_state.metrics,
                    'agents': self.system_state.agents,
                    'session_metrics': self.system_state.session_metrics
                }
            
            new_agent_state = self.decision_engine.process_state(
                current_state_data, 
                self.action_manager
            )
            
            if self.system_state.current_system_state != new_agent_state:
                self.logger.info(f"Agent state changing from {self.system_state.current_system_state} to {new_agent_state}")
                state_update = {"current_system_state": new_agent_state}
                await self.update_state(state_update)
            
        except Exception as e:
            self.logger.error(f"Error in decision cycle: {e}")

    async def _gather_state(self) -> Dict[str, Any]:
        """
        Gather initial system state.
        """
        return {
            "current_system_state": GlobalSystemState.MONITORING,
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
                "access_points": {},
                "last_scan_time": time.time()
            },
            "session_metrics": {
                "duration_seconds": 0.0,
                "handshakes_secured": 0,
                "deauthed_clients": 0,
                "peer_units": 0
            }
        }

    async def start(self):
        """
        Main async loop to start the agent's operation.
        """
        try:
            self._running = True
            self.logger.info("Agent starting up...")
            
            # Initialize system state
            initial_updates = await self._gather_state()
            await self.update_state(initial_updates)
            
            self.logger.info("Initial state established. Starting decision loop.")
            
            # Main agent loop
            while self._running:
                await self.run_decision_cycle()
                await asyncio.sleep(self.config.get("decision_cycle_delay", 5.0))
                
        except asyncio.CancelledError:
            self.logger.info("Agent stopping gracefully...")
        except Exception as e:
            self.logger.critical(f"Unhandled exception in agent loop: {e}")
        finally:
            self._running = False

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

    async def stop(self):
        """
        Stop the agent gracefully.
        """
        self.logger.info("Stopping agent...")
        self._running = False
        
        # Cancel any running tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Update state to shutdown
        await self.update_state({"current_system_state": GlobalSystemState.SHUTDOWN})