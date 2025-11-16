# kaiagotchi/core/automata.py
"""
Automata — maps numeric rewards into AgentMood and drives the Kaiagotchi's emotional loop.

Enhanced with proper mood mapping to available faces and robust reward handling:
- Uses only valid moods that exist in the faces system
- Proper Epoch integration as primary reward source
- Robust error handling for all reward sources
- Proper mood persistence and UI synchronization
"""

from __future__ import annotations
import time
import logging
import asyncio
import random
from typing import Any, Dict, Optional
from enum import Enum

import kaiagotchi.plugins as plugins

try:
    from kaiagotchi.ai.reward import RewardEngine
except Exception:
    RewardEngine = None

try:
    from kaiagotchi.ai.epoch import Epoch
except Exception:
    Epoch = None

from kaiagotchi.ui.voice import Voice
from kaiagotchi.ui import faces

_LOG = logging.getLogger("kaiagotchi.core.automata")


class AgentMood(Enum):
    """Available moods that match the faces.py definitions."""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    BORED = "bored"
    SAD = "sad"
    FRUSTRATED = "frustrated"
    SLEEPY = "sleepy"
    CONFIDENT = "confident"
    BROKEN = "broken"
    ANGRY = "angry"
    AWAKE = "awake"
    DEBUG = "debug"


class Automata:
    def __init__(self, config: Dict[str, Any], view: Any, reward_engine: Optional[Any] = None, epoch_tracker: Optional[Any] = None):
        self._config = config or {}
        self._view = view

        # Initialize reward + epoch subsystems
        self._reward = reward_engine
        self._epoch = epoch_tracker  # Use provided epoch tracker

        # Mood / reward smoothing
        self._alpha = float(self._config.get("personality", {}).get("reward_alpha", 0.25))
        self._ema_reward: Optional[float] = None
        self._last_reward: Optional[float] = None

        # Emotional logic
        self._current_mood: AgentMood = getattr(
            AgentMood,
            self._config.get("personality", {}).get("default_mood", "NEUTRAL").upper(),
            AgentMood.NEUTRAL,
        )
        self._last_mood_change = time.time()
        self._last_drift_time = time.time()
        self._min_mood_duration = float(self._config.get("personality", {}).get("min_mood_duration", 15.0))
        self._hysteresis = float(self._config.get("personality", {}).get("mood_hysteresis", 0.15))

        # UI / voice bridge
        self._voice = Voice()
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._state_getter = None

        # Mood coordination and debouncing
        self._mood_change_lock = asyncio.Lock()
        self._mood_update_in_progress = False
        self._last_mood_check = 0
        self._mood_check_interval = 2.0  # Only check mood every 2 seconds

        _LOG.debug(
            "Automata initialized (alpha=%.2f, min_dur=%.1fs, hysteresis=%.2f)",
            self._alpha,
            self._min_mood_duration,
            self._hysteresis,
        )

    # -----------------------------------------------------
    def _smooth_reward(self, reward: float) -> float:
        """Apply exponential moving average to incoming reward."""
        if self._ema_reward is None:
            self._ema_reward = reward
        else:
            self._ema_reward = (self._alpha * reward) + ((1.0 - self._alpha) * self._ema_reward)
        return self._ema_reward

    # -----------------------------------------------------
    def _map_reward_to_mood(self, r: float) -> AgentMood:
        """Map numeric reward → AgentMood with hysteresis to prevent rapid flipping."""
        # Apply hysteresis - require movement beyond threshold + hysteresis to change
        current_mood_value = self._get_mood_numeric_value(self._current_mood)
        if abs(r - current_mood_value) < self._hysteresis:
            return self._current_mood

        pos_high = float(self._config.get("personality", {}).get("threshold_excited", 0.6))
        pos_mid = float(self._config.get("personality", {}).get("threshold_happy", 0.25))
        pos_low = float(self._config.get("personality", {}).get("threshold_curious", 0.05))
        neg_high = float(self._config.get("personality", {}).get("threshold_sad", -0.6))
        neg_mid = float(self._config.get("personality", {}).get("threshold_frustrated", -0.25))
        neg_low = float(self._config.get("personality", {}).get("threshold_bored", -0.05))

        if r >= pos_high:
            return AgentMood.HAPPY
        if r >= pos_mid:
            return AgentMood.HAPPY
        if r >= pos_low:
            return AgentMood.CURIOUS
        if neg_low < r < pos_low:
            return AgentMood.NEUTRAL
        if r <= neg_high:
            return AgentMood.SAD
        if r <= neg_mid:
            return AgentMood.FRUSTRATED
        if r <= neg_low:
            return AgentMood.BORED
        return self._current_mood

    def _get_mood_numeric_value(self, mood: AgentMood) -> float:
        """Convert mood to numeric value for hysteresis calculations."""
        mood_values = {
            AgentMood.HAPPY: 0.5,
            AgentMood.CURIOUS: 0.3,
            AgentMood.NEUTRAL: 0.0,
            AgentMood.BORED: -0.3,
            AgentMood.FRUSTRATED: -0.5,
            AgentMood.SAD: -0.8,
            AgentMood.SLEEPY: -0.2,
            AgentMood.CONFIDENT: 0.4,
            AgentMood.ANGRY: -0.6,
            AgentMood.AWAKE: 0.1,
            AgentMood.DEBUG: 0.0,
            AgentMood.BROKEN: -1.0,
        }
        return mood_values.get(mood, 0.0)

    # -----------------------------------------------------
    async def _apply_mood(self, new_mood: AgentMood) -> None:
        """Apply mood and propagate to UI + plugins (async-safe)."""
        async with self._mood_change_lock:
            if self._mood_update_in_progress:
                _LOG.debug("Mood update already in progress, skipping")
                return
                
            self._mood_update_in_progress = True
            
            try:
                now = time.time()
                if new_mood == self._current_mood:
                    return
                    
                since_change = now - self._last_mood_change
                if since_change < self._min_mood_duration:
                    _LOG.debug("Mood change suppressed (%.1fs < %.1fs)", since_change, self._min_mood_duration)
                    return

                old_mood = self._current_mood
                self._current_mood = new_mood
                self._last_mood_change = now
                self._last_drift_time = now

                _LOG.info("💫 Mood transition: %s → %s", old_mood.name, new_mood.name)

                # CRITICAL: Update view with comprehensive state
                if self._view:
                    try:
                        # Use both update methods to ensure propagation
                        mood_value = new_mood.value
                        
                        # Method 1: Direct mood update (preferred)
                        if hasattr(self._view, "update_mood"):
                            try:
                                if asyncio.iscoroutinefunction(self._view.update_mood):
                                    await self._view.update_mood(mood_value, reason="automata")
                                else:
                                    self._view.update_mood(mood_value, reason="automata")
                                _LOG.debug(f"Automata: Successfully updated view mood to {mood_value}")
                            except Exception as e:
                                _LOG.warning(f"Direct mood update failed, using fallback: {e}")
                        
                        # Method 2: General state update (fallback)
                        if hasattr(self._view, "async_update"):
                            try:
                                await self._view.async_update({
                                    "agent_mood": mood_value,
                                    "mood": mood_value,  # Set both for compatibility
                                    "face": faces.get_face(mood_value),
                                    "status": self._voice.get_mood_line(mood_value),
                                })
                                _LOG.debug(f"Automata: Successfully updated view state with mood {mood_value}")
                            except Exception as e:
                                _LOG.warning(f"State update fallback also failed: {e}")
                        
                    except Exception as e:
                        _LOG.error(f"Failed to update view mood: {e}", exc_info=True)

                # Notify plugins
                try:
                    plugins.on("mood_change", self, old_mood, new_mood)
                except Exception as e:
                    _LOG.debug("Plugin mood change notification failed: %s", e)
                    
            except Exception as e:
                _LOG.error("Automata._apply_mood failed: %s", e, exc_info=True)
            finally:
                self._mood_update_in_progress = False

    # -----------------------------------------------------
    def process_reward(self, reward: float) -> AgentMood:
        """Smooth reward, map to mood, and apply if changed."""
        try:
            # Debounce mood checks
            current_time = time.time()
            if current_time - self._last_mood_check < self._mood_check_interval:
                return self._current_mood
                
            self._last_mood_check = current_time
            
            smoothed = self._smooth_reward(reward)
            _LOG.debug("Automata: reward=%.4f smoothed=%.4f", reward, smoothed)
            target = self._map_reward_to_mood(smoothed)
            
            # Only create task if mood actually changed
            if target != self._current_mood:
                asyncio.create_task(self._apply_mood(target))
                
            self._last_reward = smoothed
            return self._current_mood
        except Exception as e:
            _LOG.error("Automata.process_reward failed: %s", e, exc_info=True)
            return self._current_mood

    # -----------------------------------------------------
    async def _maybe_drift(self):
        """Trigger gentle mood drift if idle too long in NEUTRAL."""
        current_time = time.time()
        if current_time - self._last_mood_check < self._mood_check_interval:
            return
            
        if current_time - self._last_mood_change < (self._min_mood_duration * 2):
            return
        if self._ema_reward is None or self._last_reward is None:
            return
            
        drift_interval = 120.0  # 2 minutes neutral window before drift
        if current_time - self._last_drift_time < drift_interval:
            return

        reward_trend = self._ema_reward - self._last_reward
        self._last_drift_time = current_time

        # Only drift if we're in a stable, low-activity state
        if abs(reward_trend) < 0.02 and abs(self._ema_reward) < 0.1:
            if random.random() < 0.4:  # Reduced probability to avoid excessive drifting
                # Base drift options for neutral state
                drift_options = [AgentMood.BORED, AgentMood.CURIOUS, AgentMood.SLEEPY]
                
                # Weight the options based on current state
                if self._ema_reward < -0.05:
                    drift_options = [AgentMood.BORED, AgentMood.SAD, AgentMood.FRUSTRATED]
                elif self._ema_reward > 0.05:
                    drift_options = [AgentMood.CURIOUS, AgentMood.HAPPY, AgentMood.CONFIDENT]
                    
                drift_mood = random.choice(drift_options)
                _LOG.info("🌊 Mood drift triggered: %s → %s", self._current_mood.name, drift_mood.name)
                await self._apply_mood(drift_mood)

    # -----------------------------------------------------
    async def tick(self, state: Dict[str, Any]) -> AgentMood:
        """Async tick: evaluate reward and update mood."""
        try:
            # Debounce mood checks
            current_time = time.time()
            if current_time - self._last_mood_check < self._mood_check_interval:
                return self._current_mood
                
            reward_val = 0.0
            
            # Priority 1: Use Epoch system if available (primary reward source)
            if self._epoch and hasattr(self._epoch, 'next'):
                try:
                    self._epoch.next()
                    epoch_data = self._epoch.data()
                    reward_val = float(epoch_data.get("reward", 0.0))
                    _LOG.debug("Automata.tick: using epoch reward %.4f", reward_val)
                except Exception as e:
                    _LOG.warning("Epoch reward failed, falling back: %s", e)
                    reward_val = 0.0
            
            # Priority 2: Use RewardEngine directly if Epoch failed or unavailable
            if reward_val == 0.0 and self._reward and hasattr(self._reward, 'evaluate'):
                try:
                    reward_val = self._reward.evaluate(state)
                    _LOG.debug("Automata.tick: using direct reward evaluation %.4f", reward_val)
                except Exception as e:
                    _LOG.warning("Direct reward evaluation failed: %s", e)
                    reward_val = 0.0
            
            # Priority 3: Fallback to simple AP-based reward
            if reward_val == 0.0:
                try:
                    net = state.get("network", {}) or {}
                    aps = len(net.get("access_points", {}) or {})
                    # Small positive reward for just seeing networks
                    reward_val = min(aps * 0.01, 0.1)  # Cap at 0.1 for discovery-only
                    _LOG.debug("Automata.tick: using fallback AP reward %.4f", reward_val)
                except Exception as e:
                    _LOG.debug("Fallback reward failed: %s", e)
                    reward_val = 0.0

            _LOG.debug("Automata.tick: final reward %.4f", reward_val)
            self.process_reward(reward_val)
            await self._maybe_drift()
            return self._current_mood
            
        except Exception as e:
            _LOG.error("Automata.tick failed: %s", e, exc_info=True)
            return self._current_mood

    # -----------------------------------------------------
    async def start(self, state_getter):
        """Start the emotional loop."""
        if self._loop_task and not self._loop_task.done():
            _LOG.debug("Automata loop already running")
            return
        self._running = True
        self._state_getter = state_getter
        self._loop_task = asyncio.create_task(self._loop())
        _LOG.info("🧠 Automata emotional loop started")

    async def stop(self):
        """Stop the emotional loop."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        _LOG.info("🧠 Automata emotional loop stopped")

    async def _loop(self):
        """Main emotional loop."""
        interval = float(self._config.get("personality", {}).get("emotion_interval", 5.0))
        while self._running:
            try:
                if callable(self._state_getter):
                    state = (
                        await self._state_getter()
                        if asyncio.iscoroutinefunction(self._state_getter)
                        else self._state_getter()
                    )
                else:
                    state = {}
                await self.tick(state)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOG.debug("Automata._loop iteration failed: %s", e, exc_info=True)
                await asyncio.sleep(interval)  # Ensure we don't spin too fast on errors

    # -----------------------------------------------------
    # Property accessors for external systems
    @property
    def current_mood(self) -> AgentMood:
        """Get current mood (read-only)."""
        return self._current_mood

    @property 
    def last_reward(self) -> float:
        """Get last smoothed reward value."""
        return self._last_reward or 0.0

    @property
    def ema_reward(self) -> float:
        """Get current EMA reward value."""
        return self._ema_reward or 0.0

    # Manual triggers for testing and external events
    async def set_happy(self): await self._apply_mood(AgentMood.HAPPY)
    async def set_curious(self): await self._apply_mood(AgentMood.CURIOUS)
    async def set_bored(self): await self._apply_mood(AgentMood.BORED)
    async def set_sad(self): await self._apply_mood(AgentMood.SAD)
    async def set_frustrated(self): await self._apply_mood(AgentMood.FRUSTRATED)
    async def set_sleepy(self): await self._apply_mood(AgentMood.SLEEPY)
    async def set_confident(self): await self._apply_mood(AgentMood.CONFIDENT)
    async def set_angry(self): await self._apply_mood(AgentMood.ANGRY)
    async def set_neutral(self): await self._apply_mood(AgentMood.NEUTRAL)

    def get_emotional_state(self) -> Dict[str, Any]:
        """Get comprehensive emotional state for debugging."""
        return {
            "current_mood": self._current_mood.value,
            "ema_reward": self._ema_reward,
            "last_reward": self._last_reward,
            "time_since_mood_change": time.time() - self._last_mood_change,
            "min_mood_duration": self._min_mood_duration,
            "hysteresis": self._hysteresis,
            "available_moods": [mood.value for mood in AgentMood],
        }