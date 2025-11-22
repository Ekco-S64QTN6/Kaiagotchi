# kaiagotchi/agent/decision_engine.py
"""
DecisionEngine — Operational state controller for Kaiagotchi.

Simplified to focus purely on operational state transitions without
duplicating emotional state management. Emotional state is handled
by the main Automata instance in the Agent.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, Any, Callable, Optional
from enum import Enum, auto
from dataclasses import dataclass

from kaiagotchi.core.events import EventEmitter
from kaiagotchi.data.system_types import GlobalSystemState

log = logging.getLogger("kaiagotchi.agent.decision_engine")


class AgentState(Enum):
    """Defines operational states for Kaiagotchi's behavioral loop."""
    INITIALIZING = auto()
    RECON_SCAN = auto()
    TARGETING = auto()
    MAINTENANCE = auto()
    PAUSED = auto()


@dataclass
class InterfaceCache:
    data: Dict[str, Any]
    timestamp: float


class DecisionEngine:
    """High-level FSM (Finite State Machine) for Kaiagotchi operational behavior."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.current_state: AgentState = AgentState.INITIALIZING
        self._last_state_change: float = time.time()
        self._last_channel_hop: float = time.time()
        self._iface_cache: Dict[str, InterfaceCache] = {}
        self._cache_ttl: float = float(self.config.get("iface_cache_ttl", 5.0))
        self._state_history: list = []

        # Runtime metrics
        self._ap_count: int = 0
        self._handshake_count: int = 0
        self._error_count: int = 0

        # Async event system
        self.events = EventEmitter()

        # Timers
        self.init_timeout: float = float(self.config.get("init_timeout", 20.0))
        self.recon_cycle_time: float = float(self.config.get("recon_cycle_time", 120.0))
        self.target_time: float = float(self.config.get("target_time", 60.0))
        self.maintenance_time: float = float(self.config.get("maintenance_time", 20.0))
        self.hop_interval: float = float(self.config.get("personality", {}).get("hop_recon_time", 10.0))

        # External bindings
        self.view: Optional[Any] = None
        self.automata: Optional[Any] = None  # Reference to main automata instance

        log.debug("DecisionEngine initialized (hop interval %.1fs)", self.hop_interval)

    # ------------------------------------------------------------------
    def set_view(self, view: Any) -> None:
        """Attach a View instance for UI updates."""
        self.view = view

    def set_automata(self, automata: Any) -> None:
        """Attach main Automata instance for emotional state reference."""
        self.automata = automata
        log.debug("DecisionEngine: Main Automata instance attached")

    # -------------------------
    async def _safe_emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Safely emit events (awaits if coroutine)."""
        try:
            result = self.events.emit(event_name, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            log.exception("Event emission failed for %s", event_name)

    def _safe_schedule_coro(self, coro_factory: Callable[[], Any], *, name: str = "<task>") -> None:
        async def _runner():
            try:
                coro = coro_factory()
                if asyncio.iscoroutine(coro):
                    await coro
            except Exception:
                log.exception("Scheduled task %s raised an exception", name)

        try:
            asyncio.create_task(_runner())
        except Exception:
            log.exception("Failed to schedule task %s", name)

    # -------------------------
    async def _transition_to(self, new_state: AgentState, reason: str) -> AgentState:
        """Perform safe FSM transition."""
        old_state = self.current_state
        if new_state == old_state:
            return old_state

        self.current_state = new_state
        self._last_state_change = time.time()
        self._state_history.append((self._last_state_change, old_state, new_state, reason))
        if len(self._state_history) > 100:
            self._state_history.pop(0)

        # Change from INFO to DEBUG to reduce log spam
        log.debug("State: %s → %s (%s)", old_state.name, new_state.name, reason)
        
        # Emit state change event
        asyncio.create_task(self._safe_emit("state_changed", {
            "old_state": old_state.name,
            "new_state": new_state.name,
            "reason": reason,
            "timestamp": self._last_state_change
        }))

        # Trigger UI update if view available
        if getattr(self.view, "force_redraw", None):
            try:
                fr = self.view.force_redraw
                await fr() if asyncio.iscoroutinefunction(fr) else fr()
            except Exception:
                log.debug("View redraw failed", exc_info=True)

        return new_state

    # -------------------------
    async def process_state(self, state: Dict[str, Any], action_manager: Any) -> AgentState:
        """Decide next operational state based on system context."""
        try:
            global_state = state.get("current_system_state", GlobalSystemState.BOOTING)
            if isinstance(global_state, str):
                try:
                    global_state = GlobalSystemState[global_state]
                except KeyError:
                    pass

            network_state = state.get("network", {}) or {}
            if hasattr(network_state, "model_dump"):
                network_state = network_state.model_dump()

            metrics = state.get("metrics", {}) or {}
            if hasattr(metrics, "model_dump"):
                metrics = metrics.model_dump()

            # Extract AP count from multiple possible locations
            ap_count = 0
            try:
                # Try direct AP count
                ap_count = state.get("aps", 0)
                if not ap_count:
                    # Try network access points
                    aps_dict = network_state.get("access_points", {})
                    if aps_dict and isinstance(aps_dict, dict):
                        ap_count = len(aps_dict)
                    # Try aps_list
                    aps_list = state.get("aps_list", [])
                    if aps_list and isinstance(aps_list, list):
                        ap_count = len(aps_list)
            except Exception:
                ap_count = 0

            # Shutdown handling
            if global_state == GlobalSystemState.SHUTDOWN:
                return await self._transition_to(AgentState.PAUSED, "Shutdown requested")

            # Paused state handling
            if self.current_state == AgentState.PAUSED:
                if global_state == GlobalSystemState.MONITORING:
                    return await self._transition_to(AgentState.RECON_SCAN, "Resuming monitoring")
                return AgentState.PAUSED

            # Initialization state
            if self.current_state == AgentState.INITIALIZING:
                interfaces = network_state.get("interfaces", {}) or {}
                ready = [i for i in interfaces.values() if i.get("is_up", False)]
                if ready:
                    return await self._transition_to(AgentState.RECON_SCAN, "Interfaces ready")
                if (time.time() - self._last_state_change) > self.init_timeout:
                    return await self._transition_to(AgentState.MAINTENANCE, "Init timeout")

            # Recon Scan state
            elif self.current_state == AgentState.RECON_SCAN:
                # Channel hopping
                # Adjust hop interval based on mood
                current_interval = self.hop_interval
                if self.automata:
                    try:
                        mood = self.automata.current_mood.value
                        if mood == "bored":
                            current_interval *= 0.5  # Scan faster if bored
                        elif mood in ("happy", "confident"):
                            current_interval *= 1.5  # Linger if happy/confident
                        elif mood == "frustrated":
                            current_interval *= 0.8  # Erratic/fast if frustrated
                    except Exception:
                        pass

                if (time.time() - self._last_channel_hop) > current_interval:
                    if action_manager and hasattr(action_manager, "hop_channel"):
                        self._safe_schedule_coro(lambda: action_manager.hop_channel(), name="hop_channel")
                        self._last_channel_hop = time.time()

                # Transition to targeting if we found networks
                if ap_count > 0 and (time.time() - self._last_state_change) > 20:
                    return await self._transition_to(AgentState.TARGETING, f"Found {ap_count} targets")

                # Cycle maintenance
                if (time.time() - self._last_state_change) > self.recon_cycle_time:
                    return await self._transition_to(AgentState.MAINTENANCE, "Recon complete")

            # Targeting state
            elif self.current_state == AgentState.TARGETING:
                # Check system load
                cpu = float(metrics.get("cpu_usage", 0.0) or 0.0)
                if cpu > 0.85:
                    return await self._transition_to(AgentState.MAINTENANCE, "High load")
                
                # Time-based targeting completion
                if (time.time() - self._last_state_change) > self.target_time:
                    return await self._transition_to(AgentState.RECON_SCAN, "Targeting done")

            # Maintenance state
            elif self.current_state == AgentState.MAINTENANCE:
                if (time.time() - self._last_state_change) > self.maintenance_time:
                    return await self._transition_to(AgentState.RECON_SCAN, "Maintenance done")

            return self.current_state

        except Exception:
            log.exception("DecisionEngine.process_state failed; reverting to RECON_SCAN")
            return await self._transition_to(AgentState.RECON_SCAN, "Recovery fallback")

    # -------------------------
    def get_state_info(self) -> Dict[str, Any]:
        """Return diagnostic info."""
        try:
            # Get current mood from main automata if available
            current_mood = "unknown"
            if self.automata:
                try:
                    # Use the property accessor from the updated automata
                    current_mood = self.automata.current_mood.value
                except (AttributeError, ValueError):
                    # Fallback to direct attribute access with string default
                    try:
                        mood_obj = getattr(self.automata, '_current_mood', None)
                        if mood_obj and hasattr(mood_obj, 'value'):
                            current_mood = mood_obj.value
                        else:
                            current_mood = "calm"
                    except (AttributeError, ValueError):
                        current_mood = "calm"

            return {
                "current_state": getattr(self.current_state, "name", str(self.current_state)),
                "uptime_in_state": round(time.time() - self._last_state_change, 2),
                "recent_transitions": list(self._state_history[-10:]),
                "hop_interval": self.hop_interval,
                "mood": current_mood,  # Reference to main automata mood (string value)
            }
        except Exception:
            return {
                "current_state": getattr(self.current_state, "name", str(self.current_state)),
                "uptime_in_state": 0.0,
                "recent_transitions": [],
                "hop_interval": self.hop_interval,
                "mood": "calm",  # Default to calm on error
            }

    # -------------------------
    def get_operational_summary(self) -> Dict[str, Any]:
        """Get comprehensive operational summary."""
        return {
            "current_operational_state": self.current_state.name,
            "state_duration": time.time() - self._last_state_change,
            "total_state_changes": len(self._state_history),
            "hop_interval": self.hop_interval,
            "timers": {
                "init_timeout": self.init_timeout,
                "recon_cycle_time": self.recon_cycle_time,
                "target_time": self.target_time,
                "maintenance_time": self.maintenance_time,
            }
        }

    # -------------------------
    def get_available_moods(self) -> list[str]:
        """Return list of available moods for reference (from faces.py)."""
        return [
            "neutral", "calm", "happy", "curious", "bored", 
            "sad", "frustrated", "sleepy", "confident", 
            "broken", "angry", "awake", "debug"
        ]