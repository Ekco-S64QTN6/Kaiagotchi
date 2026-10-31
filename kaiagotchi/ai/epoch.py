# kaiagotchi/ai/epoch.py
"""
Epoch Tracker — temporal backbone of Kaiagotchi's reinforcement system.

Enhanced with robust network data integration and proper reward flow:
- Integrates actual network data from monitoring agent into reward calculations
- Properly connects AP discoveries and station data to RewardEngine
- Maintains accurate activity tracking and mood persistence
- Ensures reward system receives comprehensive state data

ARCHITECTURE FIX: Removed duplicate RewardEngine and PersistentMood creation
- Now uses shared instances injected by Agent
- Added proper setter methods for dependency injection
"""

import logging
import threading
import time
from typing import Any

from kaiagotchi.ai.reward import RewardEngine
from kaiagotchi.core.system import cpu_load, mem_usage, temperature
from kaiagotchi.mesh import NumChannels
from kaiagotchi.storage.persistent_mood import PersistentMood

_LOG = logging.getLogger("kaiagotchi.ai.epoch")


class Epoch:
    def __init__(self, config: dict[str, Any]):
        self.epoch = 0
        self.config = config or {}

        # Activity counters
        self.inactive_for = 0
        self.active_for = 0
        self.blind_for = 0
        self.sad_for = 0
        self.bored_for = 0

        # Action counters
        self.did_deauth = False
        self.num_deauths = 0
        self.did_associate = False
        self.num_assocs = 0
        self.num_missed = 0
        self.did_handshakes = False
        self.num_shakes = 0
        self.num_hops = 0
        self.num_slept = 0
        self.num_peers = 0

        # Network state tracking
        self.current_aps = 0
        self.current_stations = 0
        self.aps_list: list[dict[str, Any]] = []
        self.stations_list: list[dict[str, Any]] = []
        self.recent_captures: list[dict[str, Any]] = []

        # Emotional bonding
        self.tot_bond_factor = 0.0
        self.avg_bond_factor = 0.0
        self.any_activity = False

        # Timing
        self.epoch_started = time.time()
        self.epoch_duration: float = 0.0

        # Channel histogram tracking
        self.non_overlapping_channels = {1: 0, 6: 0, 11: 0}
        self._observation = {
            "aps_histogram": [0.0] * NumChannels,
            "sta_histogram": [0.0] * NumChannels,
            "peers_histogram": [0.0] * NumChannels,
        }

        # Thread/event setup
        self._observation_ready = threading.Event()
        self._epoch_data_ready = threading.Event()
        self._lock = threading.Lock()
        # Serialize epoch transitions without holding the shared state lock
        # across synchronous persistence I/O.
        self._next_lock = threading.Lock()

        # ARCHITECTURE FIX: Remove duplicate instances - use shared ones from Agent
        self._reward_engine: RewardEngine | None = None  # Will be set by Agent
        self._persistent_mood: PersistentMood | None = None  # Will be set by Agent
        self._epoch_data: dict[str, Any] = {}
        self._last_reward = 0.0
        self._last_mood = "neutral"

        _LOG.debug("EpochTracker initialized (awaiting shared RewardEngine and PersistentMood)")

    # --------------------------------------------------------------
    # ARCHITECTURE FIX: Add dependency injection methods
    def set_reward_engine(self, reward_engine: RewardEngine) -> None:
        """Set shared RewardEngine instance from Agent."""
        self._reward_engine = reward_engine
        _LOG.info("EpochTracker: Shared RewardEngine attached")

    def set_persistent_mood(self, persistent_mood: PersistentMood) -> None:
        """Set shared PersistentMood instance from Agent."""
        self._persistent_mood = persistent_mood
        _LOG.info("EpochTracker: Shared PersistentMood attached")

    # --------------------------------------------------------------
    def wait_for_epoch_data(self, with_observation: bool = True, timeout: float | None = None) -> dict[str, Any]:
        """Wait for epoch data to be ready and return it."""
        self._epoch_data_ready.wait(timeout)
        self._epoch_data_ready.clear()
        return (
            self._epoch_data
            if not with_observation
            else {**self._observation, **self._epoch_data}
        )

    def data(self) -> dict[str, Any]:
        """Get current epoch data."""
        return self._epoch_data

    # --------------------------------------------------------------
    def update_network_state(self, aps_list: list[dict[str, Any]], stations_list: list[dict[str, Any]],
                           recent_captures: list[dict[str, Any]]) -> None:
        """Update epoch with current network state from monitoring agent."""
        with self._lock:
            self.aps_list = aps_list or []
            self.stations_list = stations_list or []
            self.recent_captures = recent_captures or []
            self.current_aps = len(self.aps_list)
            self.current_stations = len(self.stations_list)

            # Update activity flag based on network discoveries
            if self.current_aps > 0 or self.current_stations > 0:
                self.any_activity = True

    # --------------------------------------------------------------
    def observe(self, aps: list, peers: list) -> None:
        """Update observation histograms from AP + peer lists."""
        if not isinstance(aps, list) or not isinstance(peers, list):
            _LOG.error("observe() requires list inputs for aps and peers")
            return

        with self._lock:
            num_aps = len(aps)
            self.blind_for = self.blind_for + 1 if num_aps == 0 else 0

            bond_unit_scale = float(self.config.get("personality", {}).get("bond_encounters_factor", 1.0))
            self.num_peers = len(peers)
            num_peers = self.num_peers + 1e-10

            self.tot_bond_factor = sum(getattr(p, "encounters", 0) for p in peers) / bond_unit_scale
            self.avg_bond_factor = self.tot_bond_factor / num_peers

            aps_per_chan = [0.0] * NumChannels
            sta_per_chan = [0.0] * NumChannels
            peers_per_chan = [0.0] * NumChannels

            for ap in aps:
                ch = ap.get("channel", 0)
                if 1 <= ch <= NumChannels:
                    aps_per_chan[ch - 1] += 1.0
                    sta_per_chan[ch - 1] += len(ap.get("clients", []))

            for peer in peers:
                ch = getattr(peer, "last_channel", 0)
                if 1 <= ch <= NumChannels:
                    peers_per_chan[ch - 1] += 1.0

            aps_norm = [a / (num_aps + 1e-10) for a in aps_per_chan]
            sta_norm = [s / (sum(sta_per_chan) + 1e-10) for s in sta_per_chan]
            peer_norm = [p / num_peers for p in peers_per_chan]

            self._observation = {
                "aps_histogram": aps_norm,
                "sta_histogram": sta_norm,
                "peers_histogram": peer_norm,
            }
            self._observation_ready.set()

    # --------------------------------------------------------------
    def track(self, deauth=False, assoc=False, handshake=False, hop=False, sleep=False, miss=False, inc=1):
        """Track specific actions and update activity flags."""
        with self._lock:
            if deauth:
                self.num_deauths += inc
                self.did_deauth = True
                self.any_activity = True
            if assoc:
                self.num_assocs += inc
                self.did_associate = True
                self.any_activity = True
            if handshake:
                self.num_shakes += inc
                self.did_handshakes = True
                self.any_activity = True
            if hop:
                self.num_hops += inc
                self.did_deauth = False
                self.did_associate = False
            if sleep:
                self.num_slept += inc
            if miss:
                self.num_missed += inc

    # --------------------------------------------------------------
    def next(self) -> None:
        """Advance the epoch, then persist its reward outside the shared state lock."""
        # A separate lock prevents concurrent next() calls from overwriting the
        # epoch snapshot while its reward is being persisted. Ordinary activity
        # tracking can still acquire _lock during that I/O.
        with self._next_lock:
            with self._lock:
                if self._reward_engine is None:
                    _LOG.error("EpochTracker.next() called before RewardEngine was set!")
                    return

                if self._persistent_mood is None:
                    _LOG.error("EpochTracker.next() called before PersistentMood was set!")
                    return

                # Detect activity using both action tracking and network state.
                network_activity = self.current_aps > 0 or self.current_stations > 0
                has_activity = self.any_activity or network_activity or self.did_handshakes

                if not has_activity:
                    self.inactive_for += 1
                    self.active_for = 0
                else:
                    self.active_for += 1
                    self.inactive_for = 0
                    self.sad_for = 0
                    self.bored_for = 0

                sad_thresh = self.config.get("personality", {}).get("sad_num_epochs", 5)
                bored_thresh = self.config.get("personality", {}).get("bored_num_epochs", 3)

                mood = "neutral"
                if self.inactive_for >= sad_thresh:
                    self.sad_for += 1
                    mood = "sad"
                elif self.inactive_for >= bored_thresh:
                    self.bored_for += 1
                    mood = "bored"
                elif self.active_for > 0:
                    mood = "curious"

                now = time.time()
                cpu = self._safe_metric(cpu_load, "load")
                mem = self._safe_metric(mem_usage, "usage")
                temp = temperature() or 0.0
                self.epoch_duration = now - self.epoch_started

                reward_state = {
                    "metrics": {"uptime_seconds": self.epoch_duration},
                    "network": {
                        "access_points": {ap.get("bssid", ""): ap for ap in self.aps_list},
                        "current_channel": self._get_current_channel(),
                    },
                    "agents": {
                        "epoch": {
                            "handshakes": self.num_shakes,
                            "handshakes_secured": self.num_shakes,
                        }
                    },
                    "agent_mood": mood,
                    "aps": self.current_aps,
                    "aps_list": self.aps_list,
                    "stations_list": self.stations_list,
                    "recent_captures": self.recent_captures,
                    "session_metrics": {
                        "handshakes_secured": self.num_shakes,
                        "duration_seconds": self.epoch_duration,
                    },
                }

                reward = float(self._reward_engine.evaluate(reward_state))
                self._last_reward = reward
                self._last_mood = mood

                # Store a detached, flat snapshot for persistence after _lock is released.
                self._epoch_data = {
                    "epoch": self.epoch,
                    "duration_secs": self.epoch_duration,
                    "inactive_for_epochs": self.inactive_for,
                    "active_for_epochs": self.active_for,
                    "sad_for_epochs": self.sad_for,
                    "bored_for_epochs": self.bored_for,
                    "cpu_load": cpu,
                    "mem_usage": mem,
                    "temperature": temp,
                    "mood": mood,
                    "reward": reward,
                    "aps_count": self.current_aps,
                    "stations_count": self.current_stations,
                    "handshakes": self.num_shakes,
                    "deauths": self.num_deauths,
                    "associations": self.num_assocs,
                }
                persistent_mood = self._persistent_mood
                epoch_data = dict(self._epoch_data)

                # Capture log values before opening the next epoch.
                log_epoch = self.epoch
                log_duration = self.epoch_duration
                log_inactive = self.inactive_for
                log_sad = self.sad_for
                log_bored = self.bored_for
                log_aps = self.current_aps

                # Close this epoch while the state lock is held so activity that
                # arrives during persistence belongs to the next one.
                self._reset_counters()
                self.epoch += 1
                self.epoch_started = now

            # PersistentMood.save() performs synchronous filesystem I/O. It must
            # not hold _lock, which is also needed by monitor/action updates.
            try:
                persistent_mood.apply_reward(reward, epoch_data=epoch_data)
                _LOG.debug("Shared PersistentMood updated with reward: %.3f", reward)
            except Exception as exc:
                _LOG.warning("Failed to sync shared PersistentMood: %s", exc)

            self._epoch_data_ready.set()
            _LOG.info(
                "[epoch %03d] mood=%-7s dur=%.1fs inactive=%d sad=%d bored=%d aps=%d reward=%.3f",
                log_epoch,
                mood,
                log_duration,
                log_inactive,
                log_sad,
                log_bored,
                log_aps,
                reward,
            )

    def _get_current_channel(self) -> str:
        """Extract current channel from network data."""
        try:
            if self.aps_list:
                # Use the first AP's channel as current
                first_channel = self.aps_list[0].get("channel")
                if first_channel:
                    return str(first_channel)
        except Exception:
            pass
        return "--"

    # --------------------------------------------------------------
    def _safe_metric(self, func, key: str) -> float:
        """Safely extract metric values with fallbacks."""
        try:
            val = func()
            if isinstance(val, dict):
                return float(val.get(key, 0.0))
            if val is None:
                return 0.0
            return float(val)
        except Exception:
            return 0.0

    # --------------------------------------------------------------
    def _reset_counters(self):
        """Reset per-epoch counters while preserving network state."""
        self.did_deauth = self.did_associate = self.did_handshakes = False
        self.num_deauths = self.num_assocs = 0
        self.num_hops = self.num_slept = 0
        self.tot_bond_factor = self.avg_bond_factor = 0.0
        self.any_activity = False
        self.num_missed = 0
        # Note: num_shakes is preserved for cumulative handshake tracking
        # Note: Network state (aps_list, stations_list) is preserved between epochs

    # --------------------------------------------------------------
    def get_summary(self) -> dict[str, Any]:
        """Get comprehensive epoch summary for debugging and UI."""
        return {
            "epoch": self.epoch,
            "current_mood": self._last_mood,
            "last_reward": self._last_reward,
            "network_activity": {
                "aps": self.current_aps,
                "stations": self.current_stations,
                "handshakes": self.num_shakes,
            },
            "emotional_state": {
                "inactive_epochs": self.inactive_for,
                "active_epochs": self.active_for,
                "sad_epochs": self.sad_for,
                "bored_epochs": self.bored_for,
            },
            "timing": {
                "epoch_duration": self.epoch_duration,
                "uptime": time.time() - self.epoch_started,
            }
        }


# Public alias — the class is exported as EpochTracker throughout the package.
EpochTracker = Epoch
