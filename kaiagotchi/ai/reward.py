"""
Kaiagotchi Reward Engine
------------------------
Evaluates system performance and environment reactivity to produce
a normalized scalar reward in [-1.0, +1.0].

Enhanced with robust data extraction and positive reinforcement
for network discoveries and activity.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger("kaiagotchi.ai.reward")

DEFAULT_WEIGHTS = {
    "handshakes": 2.0,
    "ap_discovery": 0.5,
    "station_discovery": 0.1,
    "ap_growth": 0.5,
    "channel_diversity": 0.2,
    "activity": 0.3,
    "boredom": -0.1,
    "sadness": -0.2,
    "idle_decay": -0.02,
}

DEFAULT_DECAY_PER_MIN = 0.005  # Reduced decay rate


class RewardEngine:
    """Compute reinforcement signals from system state with robust data extraction."""

    EPSILON = 1e-9

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        cfg_weights = (self.config.get("reward", {}) or {}).get("weights", {}) or {}
        self.WEIGHTS = {**DEFAULT_WEIGHTS, **cfg_weights}
        self._last_snapshot: dict[str, Any] = {}
        self._last_reward: float = 0.0
        self._last_eval_ts: float = time.time()
        self._idle_accum: float = 0.0
        self._decay_per_min = self.config.get("reward", {}).get("idle_decay_per_min", DEFAULT_DECAY_PER_MIN)
        self._discovered_aps: set = set()
        self._discovered_stations: set = set()
        self._seen_discovery_events: dict[tuple[str, str], None] = {}
        logger.debug("RewardEngine initialized (weights=%s)", self.WEIGHTS)

    def _safe_iter_agents(self, agents: Any) -> Iterable:
        """Safely iterate over agents collection."""
        if agents is None:
            return []
        if isinstance(agents, dict):
            return agents.values()
        if isinstance(agents, (list, tuple, set)):
            return agents
        return [agents]

    def _extract_handshakes(self, agents: Any) -> int:
        """Extract handshake count from agents with fallbacks."""
        total = 0
        for a in self._safe_iter_agents(agents):
            try:
                val = 0
                if isinstance(a, dict):
                    val = (a.get("handshakes") or
                          a.get("handshakes_secured") or
                          a.get("handshake_count") or
                          a.get("session_metrics", {}).get("handshakes_secured") or 0)
                else:
                    val = (getattr(a, "handshakes", None) or
                          getattr(a, "handshakes_secured", None) or
                          getattr(a, "handshake_count", None) or
                          getattr(getattr(a, "session_metrics", None), "handshakes_secured", None) or 0)
                total += int(val or 0)
            except Exception:
                continue
        return max(0, total)

    def _extract_ap_count(self, state: dict[str, Any]) -> int:
        """Extract AP count from multiple possible locations in state."""
        try:
            # Try direct AP count first
            direct_aps = state.get("aps")
            if direct_aps is not None:
                return int(direct_aps)

            # Try network section
            net = state.get("network", {}) or {}

            # Try access_points dict
            aps_dict = net.get("access_points", {})
            if aps_dict and isinstance(aps_dict, dict):
                return len(aps_dict)

            # Try aps_list
            aps_list = state.get("aps_list") or net.get("aps_list") or []
            if aps_list and isinstance(aps_list, list):
                return len(aps_list)

            # Try monitoring agent data
            if "monitoring_agent" in state:
                monitoring_data = state["monitoring_agent"]
                if isinstance(monitoring_data, dict) and "aps" in monitoring_data:
                    return int(monitoring_data["aps"])

        except Exception as e:
            logger.debug("Failed to extract AP count: %s", e)

        return 0

    def _extract_new_discoveries(self, state: dict[str, Any]) -> tuple[int, int]:
        """Count each newly observed AP/station once, with deduplicated legacy-event fallback."""
        new_aps = 0
        new_stations = 0
        network = state.get("network", {}) or {}

        try:
            # Prefer identity inventories where available. They let us detect a
            # first-seen BSSID/station once, without counting the same recent
            # chatter entry again on every reward evaluation.
            aps_inventory_available = False
            aps_list = state.get("aps_list")
            if isinstance(aps_list, list):
                aps_inventory_available = True
                current_aps = {
                    str(ap.get("bssid")).strip().upper()
                    for ap in aps_list
                    if isinstance(ap, dict) and ap.get("bssid")
                }
            else:
                access_points = (
                    network.get("access_points")
                    if isinstance(network, dict)
                    else None
                )
                if (
                    isinstance(network, dict)
                    and "access_points" in network
                    and isinstance(access_points, dict)
                ):
                    aps_inventory_available = True
                    current_aps = {
                        str(ap.get("bssid") or key).strip().upper()
                        for key, ap in access_points.items()
                        if isinstance(ap, dict) and (ap.get("bssid") or key)
                    }
                else:
                    current_aps = set()

            if aps_inventory_available:
                new_aps += len(current_aps - self._discovered_aps)
                self._discovered_aps.update(current_aps)

            stations_inventory_available = isinstance(state.get("stations_list"), list)
            if stations_inventory_available:
                stations_list = state["stations_list"]
                current_stations = {
                    str(station.get("station_mac") or station.get("mac")).strip().upper()
                    for station in stations_list
                    if isinstance(station, dict)
                    and (station.get("station_mac") or station.get("mac"))
                }
                new_stations += len(current_stations - self._discovered_stations)
                self._discovered_stations.update(current_stations)

            # Older integrations may publish discovery events without an AP or
            # station inventory. Use those messages only for the missing
            # inventory, and remember normalized event identities so a rolling
            # recent_captures buffer cannot reward the same event repeatedly.
            recent_captures = state.get("recent_captures", [])
            if isinstance(recent_captures, list):
                for capture in recent_captures[-5:]:
                    if isinstance(capture, dict):
                        msg = str(capture.get("message") or capture.get("text") or "").strip()
                    elif isinstance(capture, str):
                        msg = capture.strip()
                    else:
                        continue
                    normalized = msg.casefold()
                    category = None
                    if "new network" in normalized or "new ap" in normalized:
                        category = "ap"
                    elif "new station" in normalized:
                        category = "station"
                    if category is None:
                        continue

                    if category == "ap" and aps_inventory_available:
                        continue
                    if category == "station" and stations_inventory_available:
                        continue

                    event_key = (category, normalized)
                    if event_key in self._seen_discovery_events:
                        continue
                    self._seen_discovery_events[event_key] = None
                    if len(self._seen_discovery_events) > 1000:
                        self._seen_discovery_events.pop(next(iter(self._seen_discovery_events)))

                    if category == "ap":
                        new_aps += 1
                    else:
                        new_stations += 1

        except Exception as e:
            logger.debug("Discovery tracking failed: %s", e)

        return new_aps, new_stations

    def _safe_get_value(self, obj: Any, key: str, default: Any = None) -> Any:
        """Safely get value from object whether it's a dict, Pydantic model, or has attributes."""
        try:
            if hasattr(obj, 'model_dump'):
                # Handle Pydantic models
                obj = obj.model_dump()

            if isinstance(obj, dict):
                return obj.get(key, default)
            else:
                # Try to get as attribute
                return getattr(obj, key, default)
        except Exception:
            return default

    def evaluate(self, state: dict[str, Any]) -> float:
        """Evaluate current state and return reward [-1.0, 1.0]."""
        try:
            now = time.time()
            elapsed_min = max(0.0, (now - self._last_eval_ts) / 60.0)
            self._last_eval_ts = now

            # Handle Pydantic models at the top level
            if hasattr(state, "model_dump"):
                state = state.model_dump()

            net = self._safe_get_value(state, "network", {})
            metrics = self._safe_get_value(state, "metrics", {})
            agents = self._safe_get_value(state, "agents", {})

            # Extract current state data with safe access
            num_aps = self._extract_ap_count(state)
            handshakes = self._extract_handshakes(agents)

            # FIX: Use safe access for uptime - handle both dict and Pydantic objects
            uptime = float(self._safe_get_value(metrics, "uptime_seconds", 0.0) or 0.0)

            # FIX: Use safe access for network data
            current_channel = (self._safe_get_value(net, "current_channel") or
                             self._safe_get_value(net, "channel") or "--")

            # Track discoveries
            new_aps, new_stations = self._extract_new_discoveries(state)

            # Get previous state for deltas
            prev_aps = int(self._last_snapshot.get("aps", 0) or 0)
            prev_handshakes = int(self._last_snapshot.get("handshakes", 0) or 0)
            prev_uptime = float(self._last_snapshot.get("uptime", 0.0) or 0.0)
            prev_channel = self._last_snapshot.get("channel", "--") or "--"

            # Calculate deltas
            d_aps = max(0, int(num_aps) - prev_aps)
            d_handshakes = max(0, int(handshakes) - prev_handshakes)
            max(0.0, uptime - prev_uptime)
            channel_changed = 1.0 if current_channel != prev_channel else 0.0

            # Mood-based penalties (reduced severity)
            mood_val = (self._safe_get_value(state, "agent_mood") or
                       self._safe_get_value(self._safe_get_value(state, "agent", {}), "mood", "") or
                       "").lower()
            boredom_penalty = self.WEIGHTS.get("boredom", 0.0) if "bored" in mood_val else 0.0
            sadness_penalty = self.WEIGHTS.get("sadness", 0.0) if "sad" in mood_val else 0.0

            # Activity detection with discovery rewards
            has_activity = any([d_aps, d_handshakes, new_aps, new_stations])

            # Idle penalty (reduced accumulation)
            idle_penalty = 0.0
            if not has_activity:
                self._idle_accum += elapsed_min * self._decay_per_min
                idle_penalty = self.WEIGHTS.get("idle_decay", 0.0) - min(self._idle_accum, 0.1)
            else:
                self._idle_accum = max(0.0, self._idle_accum - 0.05)  # Recover from idle

            # Calculate raw reward with discovery bonuses
            raw_reward = (
                self.WEIGHTS.get("handshakes", 0.0) * float(d_handshakes) +
                self.WEIGHTS.get("ap_discovery", 0.0) * float(new_aps) +
                self.WEIGHTS.get("station_discovery", 0.0) * float(new_stations) +
                self.WEIGHTS.get("ap_growth", 0.0) * float(d_aps) +
                self.WEIGHTS.get("channel_diversity", 0.0) * float(channel_changed) +
                self.WEIGHTS.get("activity", 0.0) * (1.0 if has_activity else 0.0) +
                boredom_penalty +
                sadness_penalty +
                idle_penalty
            )

            # Apply tanh for normalization and clamp
            reward = float(math.tanh(raw_reward))
            reward = max(-1.0, min(1.0, reward))

            # Update snapshot
            self._last_reward = reward
            self._last_snapshot = {
                "aps": int(num_aps),
                "handshakes": int(handshakes),
                "uptime": uptime,
                "channel": current_channel,
            }

            logger.debug(
                "RewardEngine APs=%d(+%d) HS=%d(+%d) discoveries=%d/%d mood=%s raw=%.3f reward=%.3f",
                num_aps, d_aps, handshakes, d_handshakes, new_aps, new_stations,
                mood_val or "n/a", raw_reward, reward
            )

            return reward

        except Exception as e:
            logger.error("RewardEngine.evaluate() failed: %s", e, exc_info=True)
            return float(self._last_reward or 0.0)

    async def tick(self, state: dict[str, Any]) -> float:
        """Async interface for reward evaluation."""
        return self.evaluate(state)

    def last(self) -> float:
        """Get last computed reward."""
        return float(self._last_reward or 0.0)

    def reset_discoveries(self):
        """Reset discovery tracking (useful for new sessions)."""
        self._discovered_aps.clear()
        self._discovered_stations.clear()
        self._seen_discovery_events.clear()
        logger.debug("RewardEngine discoveries reset")
