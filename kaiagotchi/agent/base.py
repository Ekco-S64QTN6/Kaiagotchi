# filepath: kaiagotchi/agent/base.py
import asyncio
import logging
from typing import Dict, Any
from kaiagotchi.data.system_types import SystemState # Import SystemState Pydantic model
from ..events import EventEmitter
from .decision_engine import DecisionEngine

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
        self.action_manager = None # Will be initialized externally
        
        # Centralized state management using Pydantic model for validation
        self.state: SystemState = SystemState(config_hash="initial") 
        # Use asyncio.Lock for protection within the async environment
        self._state_lock = asyncio.Lock() 

    async def update_state(self, updates: Dict[str, Any]) -> None:
        """
        Asynchronously update the central SystemState Pydantic model.
        This method ensures the state object is protected during updates 
        and validates the incoming data structure.
        
        Args:
            updates: A dictionary of fields to update on the SystemState model.
        """
        async with self._state_lock:
            # Pydantic's model_copy is used for a shallow copy to prevent 
            # race conditions during the update and emit.
            current_state_data = self.state.model_dump()
            
            # Since pydantic v2, `model_copy(update=...)` is the preferred way 
            # to create a new instance with updated values.
            try:
                # Assuming 'updates' can directly update top-level fields 
                # or nested models (like 'network', 'agents').
                self.state = self.state.model_copy(update=updates)
                
            except Exception as e:
                self.logger.error(f"Failed to update SystemState with updates: {updates}", exc_info=True)
                return
            
            # Emit the newly updated, validated state
            await self.events.emit("state_updated", self.state)


    async def run_decision_cycle(self):
        """
        Runs one decision cycle: reads current state, passes it to the engine,
        receives the next state, and updates the system state.
        """
        try:
            # 1. Get current state safely
            async with self._state_lock:
                # Use model_dump to provide a mutable dict representation to the engine
                current_state_data = self.state.model_dump()
            
            # 2. Process state (DecisionEngine determines next action/state)
            # The decision engine processes a copy of the state data
            new_state_data = self.decision_engine.process_state(
                current_state_data, 
                self.action_manager
            )
            
            # 3. Update the agent's internal state safely
            # Note: new_state_data must be compliant with the SystemState model
            async with self._state_lock:
                self.state = SystemState.model_validate(new_state_data)
                
            # 4. Notify listeners of the state change
            await self.events.emit("state_updated", self.state)
            
        except Exception as e:
            self.logger.error(f"Critical error in decision cycle", exc_info=True)

    async def _gather_state(self) -> Dict[str, Any]:
        """
        Gather initial system state (e.g., interface count, current metrics).
        This method will likely be moved to a dedicated MetricsAgent later.
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
                        "mac_address": "00:11:22:33:44:55"
                    }
                }
            }
        }

    async def start(self):
        """
        Main loop to start the agent's operation.
        """
        try:
            self.logger.info("Agent starting up...")
            
            # Initialize state with gathered system information
            initial_updates = await self._gather_state()
            await self.update_state(initial_updates)
            
            self.logger.info("Initial state established. Starting decision loop.")
            
            while True:
                await self.run_decision_cycle()
                # Configurable delay to prevent constant thrashing
                await asyncio.sleep(self.config.get("decision_cycle_delay", 5.0)) 
                
        except asyncio.CancelledError:
            self.logger.info("Agent stopping gracefully...")
            if self.action_manager:
                await self.action_manager.cleanup()
        except Exception as e:
            self.logger.critical(f"Unhandled exception in agent start loop.", exc_info=True)
            if self.action_manager:
                await self.action_manager.cleanup()
