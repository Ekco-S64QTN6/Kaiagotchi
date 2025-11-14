"""
- Robust Agent for Kaiagotchi.
- Integrates Automata.start/stop for live emotional feedback.
- Ensures MonitoringAgent and ActionManager both share the View reference.
- Adds early UI state propagation when entering MONITORING.
- Integrates monitoring_agent state updates directly into the unified SystemState.
- Keeps throttled and non-flickering UI update loop behavior.
- Adds missing _update_view_state method.
- Automatically creates persistent View + TerminalDisplay if none provided.
- Loads/saves persistent mood and reward (PersistentMood)
- Initializes PersistentNetwork for long-term BSSID/Station tracking
- Automatically saves mood, reward, and network state on shutdown
- Integrates EpochTracker and RewardEngine with MonitoringAgent
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Tuple, Any as AnyType

from kaiagotchi.network.action_manager import InterfaceActionManager
from kaiagotchi.core.events import EventEmitter
from kaiagotchi.storage.last_session import LastSession
from kaiagotchi.data.system_types import SystemState, GlobalSystemState, AgentMood
from kaiagotchi.core.automata import Automata  # ← Emotion engine
from kaiagotchi.ui.view import View
from kaiagotchi.ui.terminal_display import TerminalDisplay

# Persistence systems
from kaiagotchi.storage.persistent_mood import PersistentMood
from kaiagotchi.storage.persistent_network import PersistentNetwork

# AI systems
from kaiagotchi.ai.epoch import Epoch
from kaiagotchi.ai.reward import RewardEngine

from .base import kaiagotchiBase
from .monitoring_agent import MonitoringAgent

_log = logging.getLogger("kaiagotchi.agent.agent")


class Agent(kaiagotchiBase):
    """Main Kaiagotchi agent — orchestrates monitoring, decisions, emotions, and UI sync."""

    state_lock: asyncio.Lock
    _update_task: Optional[asyncio.Task[AnyType]]
    _decision_task: Optional[asyncio.Task[AnyType]]
    _monitor_task: Optional[asyncio.Task[AnyType]]

    def __init__(
        self,
        config: Dict[str, Any],
        view=None,
        keypair: Optional[Tuple[str, str]] = None,
        system_state: Optional[SystemState] = None,
        state_lock: Optional[asyncio.Lock] = None,
    ):
        super().__init__(config, system_state, state_lock)

        self.config = config or {}
        self.logger = _log
        self.state_lock = self._state_lock
        self._started_at = time.time()
        self._running = False

        # ------------------------------------------------------------------
        # 🧩 Initialize persistence subsystems
        self.persistent_mood = PersistentMood()
        self.persistent_network = PersistentNetwork()
        self.logger.info("PersistentMood and PersistentNetwork initialized.")

        # ------------------------------------------------------------------
        # 🧠 Initialize AI subsystems - SINGLE SOURCE OF TRUTH
        # Create RewardEngine FIRST (core calculator)
        self.reward_engine = RewardEngine(self.config)
        
        # Create EpochTracker SECOND with shared RewardEngine
        self.epoch_tracker = Epoch(self.config)
        self.epoch_tracker.set_reward_engine(self.reward_engine)
        self.epoch_tracker.set_persistent_mood(self.persistent_mood)
        self.logger.info("AI subsystems initialized with shared RewardEngine.")

        # ------------------------------------------------------------------
        # 🖥️ Ensure persistent TerminalDisplay + View
        if view is None:
            display = TerminalDisplay()
            self._view = View(display=display)
            self.logger.info("Created default TerminalDisplay and View for agent.")
        else:
            self._view = view

        # UI timing setup
        self.ui_fps = float(self.config.get("ui", {}).get("fps", 2.0) or 2.0)
        if self.ui_fps <= 0:
            self.logger.error(f"Config 'ui.fps' invalid ({self.ui_fps}), clamping to 2.0 FPS.")
            self.ui_fps = 2.0
        self.ui_delay = 1.0 / self.ui_fps

        # Initialize helpers
        self.action_manager = InterfaceActionManager(config)
        self.last_session = LastSession()
        try:
            self.last_session.load()
            self.logger.info("Last session loaded successfully.")
        except Exception as e:
            self.logger.error(f"Failed to load last session: {e}")

        # Create monitoring agent and pass shared references
        self.monitoring_agent = MonitoringAgent(
            config=config,
            system_state=self.system_state,
            state_lock=self.state_lock,
            view=self._view,
        )

        # Connect all persistence and AI systems to monitoring agent
        self.monitoring_agent.set_persistence(self.persistent_network)
        self.monitoring_agent.set_mood_persistence(self.persistent_mood)
        self.monitoring_agent.set_epoch_tracker(self.epoch_tracker)
        # MonitoringAgent does NOT get RewardEngine - it updates EpochTracker instead
        self.logger.info("All persistence systems connected to MonitoringAgent.")

        # Initialize Automata for emotional state
        self.automata = Automata(self.config, self._view)
        self.logger.info("Automata emotional engine initialized.")

        # Restore last mood and reward from persistence
        last_mood = self.persistent_mood.get_last_mood()
        last_reward = self.persistent_mood.get_last_reward()
        if last_mood or last_reward is not None:
            self.logger.info(f"Restoring last mood={last_mood}, reward={last_reward}")
            if hasattr(self.system_state, "mood"):
                self.system_state.mood = last_mood or AgentMood.NEUTRAL.value
            if hasattr(self.automata, "restore_state"):
                self.automata.restore_state(mood=last_mood, reward=last_reward)
                self.logger.info("Automata state restored from persistence.")

        # Connect view references across subsystems
        if self._view:
            self.monitoring_agent.view = self._view
            self.action_manager.view = self._view
            self.logger.info("View references connected to all subsystems.")

        self._interface_ready = False

        # Connect View and DecisionEngine
        if self._view:
            if hasattr(self._view, "set_agent"):
                self._view.set_agent(self)
            self.decision_engine.view = self._view
            self.logger.info("DecisionEngine connected to View.")

        try:
            iface_name = getattr(self, "interface_name", None) or getattr(self, "interface", "unknown")
        except Exception:
            iface_name = "unknown"
        self.logger.info(f"Agent initialized with interface: {iface_name}")
        self.logger.info(f"View provided: {view is not None}")

        self._update_task = None
        self._decision_task = None
        self._monitor_task = None

        # Subscribe to system state updates
        async def _on_state_updated(new_state):
            """Handle MONITORING state entry → UI and Automata startup."""
            cs = getattr(new_state, "current_system_state", None)
            if isinstance(cs, str):
                try:
                    cs = GlobalSystemState(cs)
                except Exception:
                    pass

            if cs == GlobalSystemState.MONITORING:
                self._interface_ready = True
                self.logger.info("System state MONITORING: interface ready, initializing UI + emotions.")

                # Draw early minimal UI before automata mood loop starts
                if self._view:
                    await self._view.async_update({
                        "status": "Monitoring Wi-Fi traffic...",
                        "mode": "MONITORING",
                        "substatus": "Live scanning active.",
                    })

                # Start emotional loop once monitoring is live
                if self.automata and not self.automata._running:
                    await self.automata.start(self.get_state)
                    self.logger.info("Automata emotional loop started.")

        self.events.on("state_updated", lambda s: asyncio.create_task(_on_state_updated(s)))
        self.logger.info("State update event handler registered.")

    # ------------------------------------------------------------------
    def get_state(self) -> Dict[str, Any]:
        """Get current system state for Automata emotional engine."""
        return {
            "current_system_state": getattr(self.system_state, "current_system_state", None),
            "network": {
                "access_points": getattr(self.system_state.network, "access_points", {}),
                "interfaces": getattr(self.system_state.network, "interfaces", {}),
            },
            "metrics": getattr(self.system_state, "metrics", {}),
            "session_metrics": getattr(self.system_state, "session_metrics", {}),
            "aps": getattr(self.system_state, "aps", 0),
            "mode": getattr(self.system_state, "mode", "AUTO"),
            "status": getattr(self.system_state, "status", ""),
            "mood": getattr(self.system_state, "mood", AgentMood.NEUTRAL.value),
        }

    # ------------------------------------------------------------------
    async def update_state(self, updates: Dict[str, Any]) -> None:
        """Override base update_state to trigger UI refresh for important changes."""
        await super().update_state(updates)

        important_keys = {"aps", "mode", "status", "mood"}
        if self._view and any(k in updates for k in important_keys):
            await self._view.async_update(updates)

    # ------------------------------------------------------------------
    async def start_async(self):
        """Main asynchronous agent runner with emotional loop start."""
        self._running = True
        self.logger.info("Agent main run loop starting...")

        # Start the network monitor
        self._monitor_task = asyncio.create_task(self.monitoring_agent.start())
        self.logger.info("MonitoringAgent started.")

        # Start emotional loop (fallback if not already started by MONITORING event)
        if self.automata and not self.automata._running:
            await self.automata.start(self.get_state)
            self.logger.info("Automata emotional loop started (fallback).")

        # Start decision and UI loops
        decision_delay = float(self.config.get("decision_cycle_delay", 5.0) or 5.0)
        self._decision_task = asyncio.create_task(self._decision_loop(decision_delay))
        self._update_task = asyncio.create_task(self._update_loop())
        self.logger.info(f"Decision loop (delay={decision_delay}s) and UI update loop started.")

        try:
            await asyncio.wait(
                [t for t in (self._monitor_task, self._decision_task, self._update_task) if t is not None],
                return_when=asyncio.FIRST_EXCEPTION,
            )
        except asyncio.CancelledError:
            self.logger.info("Agent tasks cancelled.")
        except Exception as e:
            self.logger.error(f"Unhandled exception in Agent.run(): {e}")
            raise
        finally:
            await self.stop()

    async def start(self):
        """Compatibility wrapper."""
        await self.start_async()

    # ------------------------------------------------------------------
    async def _decision_loop(self, delay: float):
        """Decision loop; robust to exceptions."""
        self.logger.debug("Decision loop started (delay=%s)", delay)
        while self._running:
            try:
                if hasattr(super(), "run_decision_cycle"):
                    func = getattr(super(), "run_decision_cycle")
                    if asyncio.iscoroutinefunction(func):
                        await func()
                    else:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, func)
                else:
                    # Use the actual decision engine instead of fallback
                    state_dict = {
                        "current_system_state": getattr(self.system_state, "current_system_state", None),
                        "network": {
                            "access_points": getattr(self.system_state.network, "access_points", {}),
                            "interfaces": getattr(self.system_state.network, "interfaces", {}),
                        },
                        "metrics": getattr(self.system_state, "metrics", {}),
                        "session_metrics": getattr(self.system_state, "session_metrics", {}),
                    }
                    result = self.decision_engine.process_state(state_dict, self.action_manager)
                    if hasattr(result, "name"):
                        self.logger.debug("DecisionEngine state: %s", result.name)
                
                # Advance epoch after each decision cycle - uses shared RewardEngine
                if self.epoch_tracker:
                    await self.epoch_tracker.next()
                    self.logger.debug("Epoch advanced with shared RewardEngine")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in decision cycle: {e}")
                raise
            finally:
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    def __init_ui_state(self):
        """Initialize UI fields and tracking."""
        self._last_ui_state = {
            "aps": "0",
            "channel": "--",
            "status": "",
            "face": "",
            "uptime": "00:00:00",
            "mode": "AUTO",
            "mood": AgentMood.NEUTRAL.value,
        }
        self._next_update_time = 0.0
        self._last_status_rotate = 0.0
        self._status_rotate_interval = 3.0
        self._min_update_interval = 0.5

    async def _update_loop(self):
        """UI update loop with throttling."""
        self.logger.debug("UI update loop started (fps=%.1f)", self.ui_fps)
        self.__init_ui_state()
        iteration = 0

        while self._running:
            try:
                now = time.time()
                if now < self._next_update_time:
                    await asyncio.sleep(self._next_update_time - now)

                rotate = (now - self._last_status_rotate) >= self._status_rotate_interval
                await self._update_view_state(iteration, force_status_rotate=rotate)

                if rotate:
                    self._last_status_rotate = now
                self._next_update_time = now + self._min_update_interval
                iteration += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in UI update loop: {e}")
                raise

    # ------------------------------------------------------------------
    async def _update_view_state(self, iteration: int, force_status_rotate: bool = False):
        """Push periodic updates to the view based on current system_state."""
        if not self._view:
            self.logger.error("No view available for UI updates!")
            return

        uptime = int(time.time() - self._started_at)
        uptime_str = time.strftime("%H:%M:%S", time.gmtime(uptime))

        aps = getattr(self.system_state, "aps", 0)
        mode = getattr(self.system_state, "mode", "AUTO")
        status = getattr(self.system_state, "status", "")
        mood = getattr(self.system_state, "mood", AgentMood.NEUTRAL.value)

        current_snapshot = {
            "aps": str(aps),
            "status": status,
            "uptime": uptime_str,
            "mode": mode,
            "mood": mood,
        }

        if not force_status_rotate and current_snapshot == self._last_ui_state:
            return

        self._last_ui_state = current_snapshot
        await self._view.async_update(current_snapshot)
        self.logger.debug(f"[UI] Updated view (iter={iteration}) aps={aps} mode={mode}")

    # ------------------------------------------------------------------
    async def stop(self):
        """Clean shutdown of Agent and all components, including emotions and persistence."""
        if not self._running:
            self.logger.debug("Agent.stop() called but already stopped")
            return
            
        self.logger.info("Stopping Kaiagotchi agent...")
        self._running = False

        # Stop Automata emotional loop first
        if self.automata:
            await self.automata.stop()
            self.logger.info("Automata emotional loop stopped.")

        # Cancel async loops with proper timeout
        tasks_to_cancel = []
        for name, task in (
            ("update", self._update_task),
            ("decision", self._decision_task),
            ("monitor", self._monitor_task),
        ):
            if task and not task.done():
                tasks_to_cancel.append(task)
                self.logger.debug(f"Cancelling {name} task")

        if tasks_to_cancel:
            for task in tasks_to_cancel:
                task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(*tasks_to_cancel, return_exceptions=True), timeout=5.0)
                self.logger.info("All agent tasks cancelled successfully.")
            except asyncio.TimeoutError:
                self.logger.warning("Some tasks didn't cancel within timeout")
            except Exception as e:
                self.logger.error(f"Error cancelling tasks: {e}")

        # CRITICAL FIX: Stop MonitoringAgent BEFORE saving persistence to ensure PCAP archiving
        if hasattr(self, 'monitoring_agent') and self.monitoring_agent:
            try:
                self.logger.info("Stopping MonitoringAgent...")
                await self.monitoring_agent.stop()
                self.logger.info("MonitoringAgent stopped successfully.")
            except Exception as e:
                self.logger.error(f"Error stopping MonitoringAgent: {e}")

        # Save emotional and network persistence state AFTER MonitoringAgent has archived PCAP
        if self.persistent_mood:
            mood_val = getattr(self.system_state, "mood", AgentMood.NEUTRAL.value)
            reward_val = getattr(self.automata, "last_reward", 0.0) if self.automata else 0.0
            self.persistent_mood.set_and_save(mood_val, reward_val)
            self.logger.info(f"Saved persistent mood={mood_val}, reward={reward_val}")
        
        if self.persistent_network:
            self.persistent_network.save()
            self.logger.info("Persistent network state saved.")

        # Save session data
        try:
            self.last_session.save()
            self.logger.info("Last session saved.")
        except Exception as e:
            self.logger.error(f"Failed to save last session: {e}")

        # Clean up action manager
        await self.action_manager.cleanup()
        self.logger.info("ActionManager cleaned up.")

        # Notify view of shutdown
        if self._view and hasattr(self._view, "on_shutdown"):
            try:
                if asyncio.iscoroutinefunction(self._view.on_shutdown):
                    await self._view.on_shutdown()
                else:
                    self._view.on_shutdown()
                self.logger.info("View on_shutdown() executed")
            except Exception as e:
                self.logger.error(f"View.on_shutdown() failed: {e}")

        self.logger.info("Kaiagotchi agent stopped cleanly.")