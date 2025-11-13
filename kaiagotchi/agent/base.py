# kaiagotchi/agent/base.py - fixed SystemState snapshot reference and safe state updates
"""
Foundational base class for Kaiagotchi Agents.

Key improvements:
- Supports injection of a single shared View (prevents duplicate UIs).
- Fixes SystemState snapshot reference and update merging.
- Adds safe network merge logic.
- Cleans up redundant exception blocks.
- Full lifecycle and CSV parsing stability.
"""

from __future__ import annotations

import asyncio
import logging
import time
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Set

from kaiagotchi.data.system_types import (
    SystemState,
    GlobalSystemState,
    NetworkState,
    SystemMetrics,
    SessionMetrics,
)
from kaiagotchi.core.events import EventEmitter
from kaiagotchi.agent.decision_engine import DecisionEngine, AgentState

agent_logger = logging.getLogger("kaiagotchi.agent.base")


class kaiagotchiBase:
    """Foundational base class for Kaiagotchi Agents."""

    def __init__(
        self,
        config: Dict[str, Any],
        system_state: Optional[SystemState] = None,
        state_lock: Optional[asyncio.Lock] = None,
        view: Optional[Any] = None,
    ):
        """
        Args:
            config: Agent configuration dictionary
            system_state: shared SystemState (Pydantic model)
            state_lock: asyncio.Lock used for thread-safe state updates
            view: optional shared View instance (prevents duplicate UIs)
        """
        self.config = config
        self.logger = agent_logger
        self.events = EventEmitter()
        self.decision_engine = DecisionEngine(config)
        self.action_manager = None
        self._running = False
        self._tasks: Set[asyncio.Task] = set()
        self.interface_name: str = config.get("main", {}).get("iface", "wlan0")

        # Handle shared View injection
        if view is not None:
            self.view = view
            self.logger.debug("kaiagotchiBase: using provided shared view instance")
        else:
            self.view = None
            self.logger.debug("kaiagotchiBase: no view provided (no duplicate UI created)")

        # Initialize SystemState
        if system_state is None:
            config_hash = hashlib.md5(str(config).encode()).hexdigest()
            self.system_state = SystemState(
                config_hash=config_hash,
                current_system_state=GlobalSystemState.BOOTING,
                network=NetworkState(access_points={}, interfaces={}, last_scan_time=0.0),
                metrics=SystemMetrics(
                    cpu_usage=0.0, memory_usage=0.0, disk_free_gb=0.0, uptime_seconds=0.0
                ),
                agents={},
                session_metrics=SessionMetrics(duration_seconds=0.0, handshakes_secured=0),
            )
        else:
            self.system_state = system_state

        self._state_lock = state_lock or asyncio.Lock()

    # ======================================================
    # ================ SYSTEM STATE UPDATER ================
    # ======================================================
    def _debug_log_state(self, prefix: str = "Current"):
        """Logs detailed state info for debugging."""
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        try:
            self.logger.debug(f"{prefix} state details:")
            self.logger.debug(f"  SystemState type: {type(self.system_state)}")

            if hasattr(self.system_state, "network"):
                self.logger.debug(f"  Network type: {type(self.system_state.network)}")
                aps = getattr(self.system_state.network, "access_points", {})
                self.logger.debug(f"  Access points: {len(aps)} entries")
        except Exception:
            self.logger.debug("Failed to log detailed SystemState", exc_info=True)

    async def update_state(self, updates: Dict[str, Any]) -> None:
        """
        Thread-safe update of global SystemState.
        Merges network updates and coerces enums safely.
        """
        async with self._state_lock:
            try:
                self.logger.debug(f"State update requested: {list(updates.keys())}")
                self._debug_log_state("Pre-update")

                # Handle current_system_state coercion
                if "current_system_state" in updates:
                    value = updates["current_system_state"]
                    if isinstance(value, str):
                        try:
                            updates["current_system_state"] = GlobalSystemState[value]
                        except KeyError:
                            try:
                                updates["current_system_state"] = GlobalSystemState(value)
                            except Exception:
                                self.logger.warning(
                                    f"Invalid GlobalSystemState '{value}', defaulting to BOOTING"
                                )
                                updates["current_system_state"] = GlobalSystemState.BOOTING

                # Merge network updates if provided
                if "network" in updates and isinstance(updates["network"], dict):
                    self.logger.debug("Processing network state update...")

                    if isinstance(self.system_state.network, dict):
                        self.logger.warning("Fixing corrupted network state (was dict)")
                        try:
                            self.system_state.network = NetworkState(**self.system_state.network)
                        except Exception:
                            self.system_state.network = NetworkState(
                                access_points={}, interfaces={}, last_scan_time=0.0
                            )

                    network_updates = updates["network"]
                    current_net = (
                        self.system_state.network.model_dump()
                        if hasattr(self.system_state.network, "model_dump")
                        else dict(self.system_state.network)
                    )
                    current_net.update(network_updates)

                    aps = current_net.get("access_points", {}) or {}
                    if hasattr(aps, "model_dump"):
                        try:
                            aps = aps.model_dump()
                        except Exception:
                            aps = dict(aps)
                    current_net["access_points"] = aps
                    current_net["last_scan_time"] = current_net.get("last_scan_time", time.time())

                    updates["network"] = NetworkState(**current_net)

                # Merge into SystemState
                if hasattr(self.system_state, "model_copy"):
                    self.system_state = self.system_state.model_copy(update=updates)
                else:
                    for k, v in updates.items():
                        setattr(self.system_state, k, v)

                self.system_state.last_state_update = time.time()

                self._debug_log_state("Post-update")

                await self.events.emit("state_updated", self.system_state)
                self.logger.debug("State update completed.")

            except Exception as e:
                self.logger.error(f"Failed to update SystemState: {e}", exc_info=True)
                raise

    # ======================================================
    # ================ DECISION LOOP =======================
    # ======================================================
    async def run_decision_cycle(self):
        """Runs one decision cycle and syncs AgentState → GlobalSystemState."""
        try:
            current_state_data = (
                self.system_state.model_dump()
                if hasattr(self.system_state, "model_dump")
                else {}
            )
            new_agent_state = await self.decision_engine.process_state(
                current_state_data, self.action_manager
            )

            # Normalize return
            from kaiagotchi.agent.decision_engine import AgentState as _AgentState
            if isinstance(new_agent_state, str):
                try:
                    new_agent_state = _AgentState[new_agent_state.upper()]
                except Exception:
                    new_agent_state = _AgentState.RECON_SCAN
                    self.logger.warning("DecisionEngine return coerced to RECON_SCAN")

            elif not isinstance(new_agent_state, _AgentState):
                self.logger.warning(
                    f"Unexpected type {type(new_agent_state)}; defaulting to RECON_SCAN"
                )
                new_agent_state = _AgentState.RECON_SCAN

            # Map AgentState → GlobalSystemState
            mapping = {
                AgentState.INITIALIZING: GlobalSystemState.BOOTING,
                AgentState.RECON_SCAN: GlobalSystemState.MONITORING,
                AgentState.TARGETING: GlobalSystemState.MONITORING,
                AgentState.MAINTENANCE: GlobalSystemState.MAINTENANCE,
                AgentState.PAUSED: GlobalSystemState.SHUTDOWN,
            }

            current = self.system_state.current_system_state
            if isinstance(current, str):
                try:
                    current = GlobalSystemState(current)
                except Exception:
                    current = GlobalSystemState.BOOTING

            mapped = mapping.get(new_agent_state, GlobalSystemState.BOOTING)

            if current != mapped:
                self.logger.info(f"Agent state changing from {current.name} -> {mapped.name}")
                await self.update_state({"current_system_state": mapped})

        except Exception as e:
            self.logger.error(f"Error in decision cycle: {e}", exc_info=True)

    # ======================================================
    # ================ SAFE CSV PARSER =====================
    # ======================================================
    async def _safe_parse_airodump_csv_and_update(
        self, csv_path: str, min_size: int = 200, stable_time: float = 0.5
    ) -> bool:
        """
        Waits for airodump-ng CSV to stabilize, parses it, and updates SystemState.
        """
        try:
            path = Path(csv_path)
            if not path.exists():
                return False

            # Wait until file size stabilizes
            last_size = path.stat().st_size
            start = time.time()
            while True:
                await asyncio.sleep(0.3)
                if not path.exists():
                    return False
                new_size = path.stat().st_size
                if new_size == last_size and (time.time() - start) > stable_time:
                    break
                last_size = new_size

            text = path.read_text(errors="ignore")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            parsed_aps = {}

            for line in lines:
                if not line or "," not in line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 6:
                    continue
                bssid = parts[0]
                if len(bssid.split(":")) != 6:
                    continue

                ssid = parts[-1] if len(parts) > 13 else None
                try:
                    channel = int(parts[3]) if parts[3].isdigit() else 1
                except Exception:
                    channel = 1
                power = (
                    int(parts[8]) if len(parts) > 8 and parts[8].lstrip("-").isdigit() else 0
                )

                parsed_aps[bssid] = {
                    "essid": ssid,
                    "channel": channel,
                    "rssi": power,
                    "last_seen": time.time(),
                }

            if parsed_aps:
                async with self._state_lock:
                    aps = dict(
                        getattr(self.system_state.network, "access_points", {}) or {}
                    )
                    aps.update(parsed_aps)
                    self.system_state = self.system_state.model_copy(
                        update={
                            "network": {
                                "access_points": aps,
                                "last_scan_time": time.time(),
                            }
                        }
                    )
                    await self.events.emit("state_updated", self.system_state)
                    self.logger.debug(f"Updated {len(parsed_aps)} APs from CSV {csv_path}")

            return True

        except Exception as e:
            self.logger.error(f"Safe CSV parse/update failed: {e}", exc_info=True)
            return False

    # ======================================================
    # ================ LIFECYCLE HELPERS ====================
    # ======================================================
    async def start(self):
        """Base start hook."""
        self._running = True
        self.logger.debug(f"{self.__class__.__name__} start() called")

    async def stop(self):
        """Cancels tasks and stops agent cleanly."""
        self._running = False
        self.logger.debug(
            f"{self.__class__.__name__} stopping, cancelling {len(self._tasks)} tasks"
        )
        for t in list(self._tasks):
            if not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._tasks.clear()
        self.logger.debug(f"{self.__class__.__name__}: stopped cleanly")
