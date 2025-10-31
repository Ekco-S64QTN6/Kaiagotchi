# filepath: kaiagotchi/agent/base.py
import asyncio
import logging
from typing import Dict, Any
from threading import Lock
from ..events import EventEmitter
from .decision_engine import DecisionEngine

class KaiagotchiBase:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.events = EventEmitter()
        self.decision_engine = DecisionEngine(config)
        self.action_manager = None
        self.state = {}
        self._state_lock = Lock()

    def update_state(self, updates: Dict[str, Any]) -> None:
        """Thread-safe state update method."""
        with self._state_lock:
            self.state.update(updates)
            asyncio.create_task(self.events.emit("state_updated", self.state))

    async def run_decision_cycle(self):
        """Run one decision cycle with current state."""
        try:
            current_state = {}
            with self._state_lock:
                current_state = self.state.copy()
            
            new_state = self.decision_engine.process_state(
                current_state, 
                self.action_manager
            )
            await self.events.emit("state_updated", current_state)
        except Exception as e:
            self.logger.error(f"Error in decision cycle", exc_info=True)

    async def _gather_state(self) -> Dict[str, Any]:
        """Gather current system state."""
        return {
            "network": {
                "interface_count": 1  # Placeholder
            }
        }

    async def start(self):
        try:
            while True:
                await self.run_decision_cycle()
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            self.logger.info("Agent stopping...")
            if self.action_manager:
                await self.action_manager.cleanup()
