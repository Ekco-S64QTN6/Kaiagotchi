# kaiagotchi/storage/persistent_mood.py
from __future__ import annotations
import logging
import os
import time
from typing import Any, Dict, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from .file_io import atomically_save_data, load_data

LOGGER = logging.getLogger(__name__)

DEFAULT_FILENAME = "mood_state.json"
TZ = ZoneInfo("America/Chicago")


class PersistentMood:
    """
    Persistent store for Kaiagotchi's emotional and reward state.

    ARCHITECTURE FIX: Updated method signatures to match EpochTracker usage
    - Added get_last_reward() and get_last_mood() methods for Agent compatibility
    - Enhanced apply_reward() to accept epoch_data parameter
    - Maintains backward compatibility with existing calls
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = os.path.expanduser(storage_dir) if storage_dir else os.path.dirname(__file__)
        self.filepath = os.path.join(self.storage_dir, DEFAULT_FILENAME)

        # FIXED: Add mood state management to prevent rapid changes
        self._current_mood = "neutral"
        self._last_mood_change = time.time()
        self._min_mood_duration = 3.0  # Minimum 3 seconds between mood changes
        self._last_reward_time = 0.0
        self._reward_debounce_interval = 1.0  # Minimum 1 second between rewards

        self._data: Dict[str, Any] = {
            "mood": "neutral",
            "energy": 0.75,
            "curiosity": 0.5,
            "reward_points": 0.0,
            "last_reward": 0.0,  # ARCHITECTURE FIX: Track last reward separately
            "_last_updated": self._now_iso(),
        }
        self.load()
        self._ensure_permissions()
        LOGGER.debug("PersistentMood initialized with shared instance pattern")

    # ------------------------------------------------------------------
    def _now_iso(self) -> str:
        return datetime.now(tz=TZ).isoformat()

    def _ensure_permissions(self):
        """Ensure file exists with user-writable permissions."""
        try:
            if not os.path.exists(self.filepath):
                open(self.filepath, "a").close()
            os.chmod(self.filepath, 0o644)
            try:
                os.chown(self.filepath, os.getuid(), os.getgid())
            except Exception:
                pass
        except Exception:
            LOGGER.warning(f"Could not adjust permissions on {self.filepath}")

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load mood state file; restore defaults if missing/corrupted."""
        data = load_data(self.filepath, default={})
        if not isinstance(data, dict) or not data:
            LOGGER.warning("Mood state file missing or corrupted; resetting defaults.")
            self.save()
            return
        self._data.update(data)
        # FIXED: Sync internal state with loaded data
        self._current_mood = self._data.get("mood", "neutral")

    def save(self) -> bool:
        """Atomically save current state (with safe permissions)."""
        # FIXED: Ensure internal state is saved
        self._data["mood"] = self._current_mood
        self._data["_last_updated"] = self._now_iso()
        ok = atomically_save_data(self.filepath, self._data, fmt="json")
        if ok:
            self._ensure_permissions()
        return ok

    # ------------------------------------------------------------------
    # Getters - ARCHITECTURE FIX: Added methods for Agent compatibility
    def get_state(self) -> Dict[str, Any]:
        return dict(self._data)

    def get_mood(self) -> str:
        return self._current_mood  # FIXED: Use tracked mood state
    
    def get_last_mood(self) -> str:
        """Get last saved mood - used by Agent for restoration."""
        return self._current_mood  # FIXED: Use tracked mood state

    def get_reward_points(self) -> float:
        return float(self._data.get("reward_points", 0.0))
    
    def get_last_reward(self) -> float:
        """Get last reward value - used by Agent for restoration."""
        return float(self._data.get("last_reward", 0.0))

    # ------------------------------------------------------------------
    # Mutators
    def set(self, mood: str, reward: float = 0.0, energy: Optional[float] = None, curiosity: Optional[float] = None) -> None:
        """Directly set values in memory."""
        # FIXED: Add mood change validation
        current_time = time.time()
        if current_time - self._last_mood_change < self._min_mood_duration:
            LOGGER.debug(f"Mood change too rapid: {self._current_mood} -> {mood}, ignoring")
            return
            
        old_mood = self._current_mood
        self._current_mood = mood
        self._last_mood_change = current_time
        
        self._data["mood"] = mood
        self._data["reward_points"] = float(reward)
        self._data["last_reward"] = float(reward)  # ARCHITECTURE FIX: Track last reward
        if energy is not None:
            self._data["energy"] = float(max(0.0, min(1.0, energy)))
        if curiosity is not None:
            self._data["curiosity"] = float(max(0.0, min(1.0, curiosity)))
        self._data["_last_updated"] = self._now_iso()
        
        if old_mood != mood:
            LOGGER.debug(f"[mood] Mood changed {old_mood} → {mood}")

    def set_and_save(self, mood: str, reward: float = 0.0, energy: Optional[float] = None, curiosity: Optional[float] = None) -> bool:
        """Convenience wrapper for set() + save()."""
        self.set(mood, reward, energy, curiosity)
        return self.save()

    # ------------------------------------------------------------------
    # Emotional logic - ARCHITECTURE FIX: Enhanced for EpochTracker compatibility
    def apply_reward(self, points: float, event: Optional[str] = None, epoch_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Increment rewards and gently shift mood based on performance.
        Enhanced to accept epoch_data parameter from EpochTracker.
        """
        # FIXED: Add reward debouncing
        current_time = time.time()
        if current_time - self._last_reward_time < self._reward_debounce_interval:
            LOGGER.debug(f"Reward too rapid: {points} for {event}, ignoring")
            return
            
        self._last_reward_time = current_time

        # ARCHITECTURE FIX: Handle epoch_data if provided
        if epoch_data is not None:
            # Use mood from epoch_data if available
            epoch_mood = epoch_data.get("mood")
            if epoch_mood and epoch_mood != self._current_mood:
                # Use set method to ensure proper mood change handling
                self.set(epoch_mood, self._data.get("reward_points", 0.0))
                LOGGER.debug(f"[mood] Updated from epoch: {epoch_mood}")

        current_reward = self._data.get("reward_points", 0.0)
        new_reward = max(0.0, current_reward + points)
        self._data["reward_points"] = round(new_reward, 3)
        self._data["last_reward"] = float(points)  # ARCHITECTURE FIX: Track last reward
        self._data["_last_updated"] = self._now_iso()

        # FIXED: Only update mood if not overridden by epoch_data and enough time has passed
        if epoch_data is None or "mood" not in epoch_data:
            if current_time - self._last_mood_change >= self._min_mood_duration:
                if points > 0:
                    self._data["curiosity"] = min(1.0, self._data.get("curiosity", 0.5) + 0.05)
                    self._data["energy"] = min(1.0, self._data.get("energy", 0.75) + 0.02)
                    new_mood = "happy" if self._data["curiosity"] > 0.6 else "curious"
                    if new_mood != self._current_mood:
                        self.set(new_mood, new_reward)
                elif points < 0:
                    self._data["energy"] = max(0.0, self._data.get("energy", 0.75) - 0.05)
                    new_mood = "tired" if self._data["energy"] < 0.4 else "bored"
                    if new_mood != self._current_mood:
                        self.set(new_mood, new_reward)
                else:
                    # Idle / zero-drift decay
                    self._data["curiosity"] = max(0.0, self._data.get("curiosity", 0.5) - 0.01)
                    self._data["energy"] = max(0.0, self._data.get("energy", 0.75) - 0.01)
                    if self._data["curiosity"] < 0.3 and self._current_mood != "bored":
                        self.set("bored", new_reward)
                    elif self._data["energy"] < 0.2 and self._current_mood != "tired":
                        self.set("tired", new_reward)

        event_str = f" ({event})" if event else ""
        LOGGER.info(
            f"[mood] {'+' if points > 0 else ''}{points:.2f} reward{event_str} → mood={self._current_mood} (total={new_reward:.2f})"
        )

        self.save()

    def update_mood(self, new_mood: str) -> None:
        """
        Update mood manually with internal energy/curiosity drift logic.
        """
        # FIXED: Use set method for proper mood change handling
        self.set(new_mood, self._data.get("reward_points", 0.0))

    # ------------------------------------------------------------------
    def sync_from_epoch(self, epoch_data: Dict[str, Any]) -> None:
        """
        Merge reward & mood context from Epoch cycles into persistent state.
        - epoch_data: {"reward": float, "mood": str, ...}
        
        ARCHITECTURE FIX: Now uses enhanced apply_reward method
        """
        try:
            reward = float(epoch_data.get("reward", 0.0))
            # Use the enhanced apply_reward which now handles epoch_data
            self.apply_reward(reward * 0.1, event="epoch_sync", epoch_data=epoch_data)
        except Exception:
            LOGGER.exception("sync_from_epoch failed")