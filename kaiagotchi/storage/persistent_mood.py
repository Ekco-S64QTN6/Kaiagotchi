# kaiagotchi/storage/persistent_mood.py
from __future__ import annotations

import logging
import os
import stat
import threading
import time
from copy import deepcopy
from datetime import datetime
from typing import Any
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

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = os.path.expanduser(storage_dir) if storage_dir else os.path.dirname(__file__)
        self.filepath = os.path.join(self.storage_dir, DEFAULT_FILENAME)

        # Epoch runs in a worker thread while the monitoring loop may also update
        # mood state. Keep mutations short under _state_lock and serialize disk
        # snapshots with _save_lock, never holding the state lock during I/O.
        self._state_lock = threading.RLock()
        self._save_lock = threading.Lock()

        # FIXED: Add mood state management to prevent rapid changes
        self._current_mood = "neutral"
        self._last_mood_change = time.time()
        self._min_mood_duration = 3.0  # Minimum 3 seconds between mood changes
        self._last_reward_time = 0.0
        self._reward_debounce_interval = 1.0  # Minimum 1 second between rewards

        self._data: dict[str, Any] = {
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

    def _ensure_permissions(self) -> None:
        """Restrict a regular mood-state file without following symlinks."""
        descriptor: int | None = None
        try:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            descriptor = os.open(self.filepath, flags)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                LOGGER.warning(
                    "Refusing to adjust non-regular mood-state path %s",
                    self.filepath,
                )
                return

            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            try:
                os.fchown(descriptor, os.getuid(), os.getgid())
            except PermissionError:
                # An unprivileged process may not be able to change ownership.
                pass
        except FileNotFoundError:
            LOGGER.debug("Mood state file is not present yet: %s", self.filepath)
        except OSError as exc:
            LOGGER.warning(
                "Could not safely adjust permissions on %s: %s",
                self.filepath,
                exc,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load mood state file; restore defaults if missing/corrupted."""
        data = load_data(self.filepath, default={})
        if not isinstance(data, dict) or not data:
            LOGGER.warning("Mood state file missing or corrupted; resetting defaults.")
            self.save()
            return
        with self._state_lock:
            self._data.update(deepcopy(data))
            self._current_mood = self._data.get("mood", "neutral")

    def save(self) -> bool:
        """Persist one detached, serialized snapshot without holding the state lock over I/O."""
        try:
            with self._save_lock:
                with self._state_lock:
                    self._data["mood"] = self._current_mood
                    self._data["_last_updated"] = self._now_iso()
                    payload = deepcopy(self._data)

                ok = atomically_save_data(self.filepath, payload, fmt="json")
                if ok:
                    self._ensure_permissions()
                return ok
        except Exception:
            LOGGER.exception("Failed to save persistent mood state")
            return False

    # ------------------------------------------------------------------
    # Getters - ARCHITECTURE FIX: Added methods for Agent compatibility
    def get_state(self) -> dict[str, Any]:
        """Return a detached view so callers cannot mutate persisted state."""
        with self._state_lock:
            return deepcopy(self._data)

    def get_mood(self) -> str:
        """Return the currently tracked mood."""
        with self._state_lock:
            return self._current_mood

    def get_last_mood(self) -> str:
        """Get last saved mood - used by Agent for restoration."""
        with self._state_lock:
            return self._current_mood

    def get_reward_points(self) -> float:
        with self._state_lock:
            return float(self._data.get("reward_points", 0.0))

    def get_last_reward(self) -> float:
        """Get last reward value - used by Agent for restoration."""
        with self._state_lock:
            return float(self._data.get("last_reward", 0.0))

    # ------------------------------------------------------------------
    # Mutators
    def set(self, mood: str, reward: float = 0.0, energy: float | None = None, curiosity: float | None = None) -> None:
        """Update persisted values while rate-limiting only mood transitions."""
        with self._state_lock:
            current_time = time.time()
            old_mood = self._current_mood
            change_allowed = current_time - self._last_mood_change >= self._min_mood_duration

            if mood != old_mood and change_allowed:
                self._current_mood = mood
                self._last_mood_change = current_time
            elif mood != old_mood:
                LOGGER.debug(
                    "Mood change too rapid: %s -> %s; keeping current mood",
                    old_mood,
                    mood,
                )

            # The anti-flicker guard must not discard reward/energy/curiosity
            # updates. Callers such as set_and_save() rely on these values being
            # persisted even when a requested mood transition is throttled.
            self._data["mood"] = self._current_mood
            self._data["reward_points"] = float(reward)
            self._data["last_reward"] = float(reward)
            if energy is not None:
                self._data["energy"] = float(max(0.0, min(1.0, energy)))
            if curiosity is not None:
                self._data["curiosity"] = float(max(0.0, min(1.0, curiosity)))
            self._data["_last_updated"] = self._now_iso()

            if old_mood != self._current_mood:
                LOGGER.debug("[mood] Mood changed %s → %s", old_mood, self._current_mood)

    def set_and_save(self, mood: str, reward: float = 0.0, energy: float | None = None, curiosity: float | None = None) -> bool:
        """Convenience wrapper for set() + save()."""
        self.set(mood, reward, energy, curiosity)
        return self.save()

    # ------------------------------------------------------------------
    # Emotional logic - ARCHITECTURE FIX: Enhanced for EpochTracker compatibility
    def apply_reward(self, points: float, event: str | None = None, epoch_data: dict[str, Any] | None = None) -> None:
        """
        Increment rewards and gently shift mood based on performance.

        The state lock protects the complete in-memory transition. The actual
        JSON write occurs after releasing that lock via save(), which snapshots
        state and serializes writers independently.
        """
        current_time = time.time()
        with self._state_lock:
            if current_time - self._last_reward_time < self._reward_debounce_interval:
                LOGGER.debug("Reward too rapid: %s for %s, ignoring", points, event)
                return

            self._last_reward_time = current_time

            if epoch_data is not None:
                epoch_mood = epoch_data.get("mood")
                if epoch_mood and epoch_mood != self._current_mood:
                    self.set(epoch_mood, self._data.get("reward_points", 0.0))
                    LOGGER.debug("[mood] Updated from epoch: %s", epoch_mood)

            current_reward = self._data.get("reward_points", 0.0)
            new_reward = max(0.0, current_reward + points)
            self._data["reward_points"] = round(new_reward, 3)
            self._data["last_reward"] = float(points)
            self._data["_last_updated"] = self._now_iso()

            if epoch_data is None or "mood" not in epoch_data:
                if current_time - self._last_mood_change >= self._min_mood_duration:
                    if points > 0:
                        self._data["curiosity"] = min(
                            1.0, self._data.get("curiosity", 0.5) + 0.05
                        )
                        self._data["energy"] = min(
                            1.0, self._data.get("energy", 0.75) + 0.02
                        )
                        new_mood = (
                            "happy" if self._data["curiosity"] > 0.6 else "curious"
                        )
                        if new_mood != self._current_mood:
                            self.set(new_mood, new_reward)
                    elif points < 0:
                        self._data["energy"] = max(
                            0.0, self._data.get("energy", 0.75) - 0.05
                        )
                        new_mood = (
                            "sleepy" if self._data["energy"] < 0.4 else "bored"
                        )
                        if new_mood != self._current_mood:
                            self.set(new_mood, new_reward)
                    else:
                        # Idle / zero-drift decay
                        self._data["curiosity"] = max(
                            0.0, self._data.get("curiosity", 0.5) - 0.01
                        )
                        self._data["energy"] = max(
                            0.0, self._data.get("energy", 0.75) - 0.01
                        )
                        if (
                            self._data["curiosity"] < 0.3
                            and self._current_mood != "bored"
                        ):
                            self.set("bored", new_reward)
                        elif (
                            self._data["energy"] < 0.2
                            and self._current_mood != "sleepy"
                        ):
                            self.set("sleepy", new_reward)

            mood = self._current_mood
            total_reward = new_reward

        event_str = f" ({event})" if event else ""
        LOGGER.info(
            "[mood] %s%.2f reward%s → mood=%s (total=%.2f)",
            "+" if points > 0 else "",
            points,
            event_str,
            mood,
            total_reward,
        )
        self.save()

    def update_mood(self, new_mood: str) -> None:
        """Update mood manually while preserving the current reward total."""
        with self._state_lock:
            self.set(new_mood, self._data.get("reward_points", 0.0))

    # ------------------------------------------------------------------
    def sync_from_epoch(self, epoch_data: dict[str, Any]) -> None:
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
