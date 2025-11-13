# kaiagotchi/storage/persistent_mood.py
from __future__ import annotations
import logging
import os
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

    Enhancements:
      - Integrates periodic sync from Epoch rewards.
      - Applies idle decay when rewards stagnate.
      - Guarantees user-level file permissions (chmod 644).
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = os.path.expanduser(storage_dir) if storage_dir else os.path.dirname(__file__)
        self.filepath = os.path.join(self.storage_dir, DEFAULT_FILENAME)

        self._data: Dict[str, Any] = {
            "mood": "neutral",
            "energy": 0.75,
            "curiosity": 0.5,
            "reward_points": 0.0,
            "_last_updated": self._now_iso(),
        }
        self.load()
        self._ensure_permissions()

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

    def save(self) -> bool:
        """Atomically save current state (with safe permissions)."""
        self._data["_last_updated"] = self._now_iso()
        ok = atomically_save_data(self.filepath, self._data, fmt="json")
        if ok:
            self._ensure_permissions()
        return ok

    # ------------------------------------------------------------------
    # Getters
    def get_state(self) -> Dict[str, Any]:
        return dict(self._data)

    def get_mood(self) -> str:
        return self._data.get("mood", "neutral")

    def get_reward_points(self) -> float:
        return float(self._data.get("reward_points", 0.0))

    # ------------------------------------------------------------------
    # Mutators
    def set(self, mood: str, reward: float = 0.0, energy: Optional[float] = None, curiosity: Optional[float] = None) -> None:
        """Directly set values in memory."""
        self._data["mood"] = mood
        self._data["reward_points"] = float(reward)
        if energy is not None:
            self._data["energy"] = float(max(0.0, min(1.0, energy)))
        if curiosity is not None:
            self._data["curiosity"] = float(max(0.0, min(1.0, curiosity)))
        self._data["_last_updated"] = self._now_iso()

    def set_and_save(self, mood: str, reward: float = 0.0, energy: Optional[float] = None, curiosity: Optional[float] = None) -> bool:
        """Convenience wrapper for set() + save()."""
        self.set(mood, reward, energy, curiosity)
        return self.save()

    # ------------------------------------------------------------------
    # Emotional logic
    def apply_reward(self, points: float, event: Optional[str] = None) -> None:
        """
        Increment rewards and gently shift mood based on performance.
        """
        current_reward = self._data.get("reward_points", 0.0)
        new_reward = max(0.0, current_reward + points)
        self._data["reward_points"] = round(new_reward, 3)
        self._data["_last_updated"] = self._now_iso()

        if points > 0:
            self._data["curiosity"] = min(1.0, self._data.get("curiosity", 0.5) + 0.05)
            self._data["energy"] = min(1.0, self._data.get("energy", 0.75) + 0.02)
            self._data["mood"] = "happy" if self._data["curiosity"] > 0.6 else "curious"
        elif points < 0:
            self._data["energy"] = max(0.0, self._data.get("energy", 0.75) - 0.05)
            self._data["mood"] = "tired" if self._data["energy"] < 0.4 else "bored"
        else:
            # Idle / zero-drift decay
            self._data["curiosity"] = max(0.0, self._data.get("curiosity", 0.5) - 0.01)
            self._data["energy"] = max(0.0, self._data.get("energy", 0.75) - 0.01)
            if self._data["curiosity"] < 0.3:
                self._data["mood"] = "bored"
            if self._data["energy"] < 0.2:
                self._data["mood"] = "tired"

        LOGGER.info(
            f"[mood] {'+' if points > 0 else ''}{points:.2f} reward → mood={self._data['mood']} (total={new_reward:.2f})"
        )

        self.save()

    def update_mood(self, new_mood: str) -> None:
        """
        Update mood manually with internal energy/curiosity drift logic.
        """
        prev = self._data.get("mood", "neutral")
        self._data["mood"] = new_mood
        self._data["_last_updated"] = self._now_iso()

        if new_mood == "curious":
            self._data["curiosity"] = min(1.0, self._data["curiosity"] + 0.1)
            self._data["energy"] = max(0.5, self._data["energy"] - 0.02)
        elif new_mood == "tired":
            self._data["energy"] = max(0.0, self._data["energy"] - 0.1)
        elif new_mood == "happy":
            self._data["curiosity"] = min(1.0, self._data["curiosity"] + 0.05)
            self._data["energy"] = min(1.0, self._data["energy"] + 0.05)
        elif new_mood == "neutral":
            self._data["energy"] = min(0.9, self._data["energy"] + 0.01)

        LOGGER.debug(f"[mood] Mood changed {prev} → {new_mood}")
        self.save()

    # ------------------------------------------------------------------
    def sync_from_epoch(self, epoch_data: Dict[str, Any]) -> None:
        """
        Merge reward & mood context from Epoch cycles into persistent state.
        - epoch_data: {"reward": float, "mood": str, ...}
        """
        try:
            reward = float(epoch_data.get("reward", 0.0))
            mood = epoch_data.get("mood") or self._data.get("mood", "neutral")

            # Apply as a subtle influence rather than direct overwrite
            self.apply_reward(reward * 0.1, event="epoch_sync")
            self.update_mood(mood)
        except Exception:
            LOGGER.exception("sync_from_epoch failed")
