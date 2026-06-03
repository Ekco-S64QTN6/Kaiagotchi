from __future__ import annotations

import asyncio
import collections
import copy
from datetime import datetime
import logging
import random
import re
import threading
import time
from typing import Optional, Dict, Any, List

from kaiagotchi.ui.terminal_display import TerminalDisplay
from kaiagotchi.ui.voice.voice import Voice

_log = logging.getLogger("kaiagotchi.ui.view")


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge src into dst in-place and return dst.

    Rules:
    - If both values are dict -> recurse.
    - If dst value is a dict/list and src provides a scalar of different type -> IGNORE src (do not clobber complex types).
    - If both are lists -> replace (incoming intends to replace).
    - Otherwise assign a deep copy of src.
    """
    for k, v in src.items():
        if k in dst:
            existing = dst[k]
            # both dicts -> recurse
            if isinstance(existing, dict) and isinstance(v, dict):
                _deep_merge(existing, v)
                continue
            # both lists -> replace completely
            if isinstance(existing, list) and isinstance(v, list):
                dst[k] = copy.deepcopy(v)
                continue
            # existing is complex but incoming is incompatible scalar -> preserve existing
            if isinstance(existing, (list, dict)) and not isinstance(v, type(existing)):
                _log.debug(
                    "View.merge: preserving existing complex type for key '%s' (incoming=%s, existing=%s)",
                    k,
                    type(v).__name__,
                    type(existing).__name__,
                )
                continue
            # otherwise assign deep copy
            dst[k] = copy.deepcopy(v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


class View:
    """Bridge between the Agent, system state, and the terminal UI."""

    def __init__(self, config: Dict[str, Any], display: Optional[TerminalDisplay] = None):
        self._config = config or {}
        self.display: Optional[TerminalDisplay] = display
        self._agent = None
        self.state: Dict[str, Any] = {}
        self._last_drawn_state: Dict[str, Any] = {}
        self._update_lock = asyncio.Lock()
        self._running = False
        self._update_task: Optional[asyncio.Task] = None
        self._chatter_task: Optional[asyncio.Task] = None
        self._last_draw_time = 0.0
        self._min_interval = 0.5  # Reduced to be more responsive to mood changes

        # Chatter state
        self._current_chatter_msg: Optional[str] = None
        self._last_chatter_change: float = 0.0
        self._chatter_hold: float = 30.0
        self._event_cooldown: float = 0.0  # how long event overrides persist

        self.voice = Voice()
        self._last_announced_captures: List[str] = []
        self._chatter_lines: collections.deque = collections.deque(maxlen=50)

        # AP tracking
        self._max_aps_seen: int = 0

        # Mood state management - FIXED: Add proper mood tracking
        self._current_mood = "neutral"
        self._mood_lock = asyncio.Lock()
        self._last_mood_update = 0.0
        self._mood_debounce_interval = 2.0  # Minimum 2 seconds between mood changes

        self._state_lock = threading.Lock()

        if not self.display:
            _log.warning("No display provided to View; creating fallback TerminalDisplay.")
            self.display = TerminalDisplay(self._config)

        if self.display and hasattr(self.display, "register_state_provider"):
            self.display.register_state_provider(self.get_snapshot_dict)

        _log.debug("View initialized (display linked: %s)", bool(self.display))
        
        # Flag to suppress rendering (e.g. during splash screen)
        self.suppress_output = False

    # ------------------------------------------------------------------
    def set_agent(self, agent):
        """Attach an Agent reference (for state sync)."""
        self._agent = agent
        if self.display and hasattr(self.display, "set_agent"):
            try:
                self.display.set_agent(agent)
            except Exception:
                _log.exception("View.set_agent: display.set_agent failed")
        _log.debug("View linked to agent: %s", type(agent).__name__)

    # ------------------------------------------------------------------
    def _ensure_normalized(self, st: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure certain keys have the expected types. Return a shallow copy
        with normalized types so displays always receive consistent values.
        """
        s = dict(st)  # shallow copy to avoid mutating original
        # Ensure aps_list and stations_list are always lists
        for key in ("aps_list", "stations_list"):
            val = s.get(key)
            if val is None:
                s[key] = []
            elif not isinstance(val, list):
                _log.debug("Normalizing key '%s' to list (was %s)", key, type(val).__name__)
                s[key] = []  # set as empty list if not already a list
        # Ensure chatter/recent captures lists
        for key in ("recent_captures", "chatter_log"):
            val = s.get(key)
            if val is None:
                s[key] = []
            elif not isinstance(val, list):
                _log.debug("Normalizing key '%s' to list (was %s)", key, type(val).__name__)
                s[key] = []  # set as empty list if not already a list
        # agent_mood & face & status presence - CHANGED: default to "neutral" (not "calm")
        if "agent_mood" not in s:
            s["agent_mood"] = self._current_mood  # Use tracked mood state
        if "face" not in s:
            s["face"] = self.voice.get_face_for_mood(self._current_mood)
        if not s.get("status"):
            s["status"] = s.get("status", "Monitoring signals...")
        return s

    # ------------------------------------------------------------------
    def get_snapshot_dict(self) -> Dict[str, Any]:
        """Thread-safe snapshot getter for the curses display thread."""
        with self._state_lock:
            now = time.time()
            mood = self._current_mood
            
            # Idle chatter check
            mood_interval = self.voice.get_chatter_interval(mood)
            base_hold = max(10.0, min(90.0, mood_interval))
            
            cooldown_active = False
            if hasattr(self, "_event_cooldown_expiry"):
                cooldown_active = (now < self._event_cooldown_expiry)
                
            if not cooldown_active:
                last_change = getattr(self, "_last_chatter_change", 0.0)
                hold_dur = getattr(self, "_chatter_hold", 25.0)
                if not getattr(self, "_current_chatter_msg", None) or (now - last_change > hold_dur):
                    new_msg = self.voice.get_mood_line(mood) or "..."
                    if new_msg != getattr(self, "_current_chatter_msg", None):
                        self._current_chatter_msg = new_msg
                        self._last_chatter_change = now
                        self._chatter_hold = random.uniform(base_hold * 0.8, base_hold * 1.2)
                        
                        ts = datetime.now().strftime("%H:%M:%S")
                        self._chatter_lines.append(f"[{ts}] {new_msg}")
                        self.state["face"] = self.voice.get_face_for_mood(mood)

            # Normalize and construct state dict
            normalized = self._ensure_normalized(self.state)
            
            # Chatter log
            normalized["chatter_log"] = list(self._chatter_lines)
            
            # Status is the latest entry from chatter log (stripped of timestamp)
            if self._chatter_lines:
                latest = self._chatter_lines[-1]
                match = re.match(r"^\[\d{2}:\d{2}:\d{2}\]\s*(.*)$", latest)
                if match:
                    normalized["status"] = match.group(1)
                else:
                    normalized["status"] = latest
            else:
                normalized["status"] = "Monitoring signals..."
                
            return normalized

    # ------------------------------------------------------------------
    async def async_update(self, state: Dict[str, Any]):
        """Async state update called by Agent. Thread-safe aggregation."""
        now = time.time()
        with self._state_lock:
            # Extract mood BEFORE merging to avoid race conditions
            incoming_mood = state.get("agent_mood") or state.get("mood")
            if incoming_mood and incoming_mood != self._current_mood:
                mood_name = getattr(incoming_mood, "name", str(incoming_mood)).lower()
                if now - self._last_mood_update >= self._mood_debounce_interval:
                    _log.info(f"🎭 View async_update: Updating mood to {mood_name} from state")
                    self._current_mood = mood_name
                    self._last_mood_update = now

            current_mood_before_merge = self._current_mood

            # Deep merge
            try:
                if not isinstance(self.state, dict):
                    self.state = {}
                _deep_merge(self.state, state)
                self.state["agent_mood"] = current_mood_before_merge
                self.state["mood"] = current_mood_before_merge
            except Exception:
                _log.exception("View.async_update: merge failed")

            # Track AP max count
            try:
                cur_aps = int(self.state.get("aps", 0))
                if cur_aps > self._max_aps_seen:
                    self._max_aps_seen = cur_aps
                self.state["aps_max_seen"] = self._max_aps_seen
            except Exception:
                pass

            # Handle recent captures
            try:
                self._handle_recent_captures(self.state.get("recent_captures", []))
            except Exception:
                _log.exception("View.async_update: _handle_recent_captures failed")

    # ------------------------------------------------------------------
    def _handle_recent_captures(self, captures: List[Dict[str, Any]]):
        """Play reactions + update chatter when MonitoringAgent pushes events. Synchronous."""
        if not captures:
            return

        new_msgs = []
        for cap in captures[-5:]:
            if not isinstance(cap, dict):
                continue
            msg = cap.get("message")
            if msg and msg not in self._last_announced_captures:
                new_msgs.append(cap)
                self._last_announced_captures.append(msg)

        if len(self._last_announced_captures) > 30:
            self._last_announced_captures = self._last_announced_captures[-30:]

        for cap in new_msgs:
            try:
                formatted = self.voice.format_chatter_entry(cap)
                if formatted:
                    self._chatter_lines.append(formatted)
                    
                    msg = cap.get("message", "")
                    _log.info(f"[UI] New capture event: {msg}")
                    mood = self._current_mood
                    voice_line = self.voice.get_event_line(msg, mood) or msg
                    ts = datetime.now().strftime("%H:%M:%S")
                    self._chatter_lines.append(f"[{ts}] {voice_line}")
                    
                    # React visually
                    if "pmkid" in msg.lower():
                        self.state["face"] = self.voice.get_face_for_mood("happy")
                    elif "handshake" in msg.lower():
                        self.state["face"] = self.voice.get_face_for_mood("curious")
                    else:
                        self.state["face"] = self.voice.get_face_for_mood(mood)
                        
                    base_cool = self.voice.get_chatter_interval(mood)
                    cooldown_dur = min(30.0, max(15.0, base_cool * 0.3))
                    self._event_cooldown_expiry = time.time() + cooldown_dur
            except Exception:
                _log.debug("View._handle_recent_captures failed", exc_info=True)

    # ------------------------------------------------------------------
    async def update_mood(self, new_mood, reason: str = "automata"):
        """Update UI to reflect the current mood. Thread-safe."""
        mood_name = getattr(new_mood, "name", str(new_mood)).lower()
        
        current_time = time.time()
        if current_time - self._last_mood_update < self._mood_debounce_interval:
            _log.debug(f"Mood change debounced: {self._current_mood} -> {mood_name} (too soon)")
            return
            
        with self._state_lock:
            _log.info(f"🎭 View.update_mood: Updating mood to {mood_name} (reason={reason})")

            try:
                self._current_mood = mood_name
                self._last_mood_update = current_time

                self.state["agent_mood"] = mood_name
                self.state["face"] = self.voice.get_face_for_mood(mood_name)
                text_message = self.voice.get_mood_line(mood_name) or "..."
                
                ts = datetime.now().strftime("%H:%M:%S")
                self._chatter_lines.append(f"[{ts}] {text_message}")
                
                self._current_chatter_msg = text_message
                self._last_chatter_change = current_time
                self._chatter_hold = self.voice.get_chatter_interval(mood_name)
                self._event_cooldown_expiry = 0.0
                
                _log.info(f"✅ Mood update completed: {mood_name}")
            except Exception:
                _log.exception("View.update_mood failed")

    async def start(self):
        """Start display."""
        if self._running:
            return

        self._running = True
        _log.info("View starting")
        if self.display and hasattr(self.display, 'start'):
            self.display.start()

    # ------------------------------------------------------------------
    async def on_starting(self):
        """Display startup banner or boot animation."""
        with self._state_lock:
            try:
                self.state["status"] = "Initializing Kaiagotchi..."
                self.state["face"] = self.voice.get_face_for_mood("neutral")
                ts = datetime.now().strftime("%H:%M:%S")
                self._chatter_lines.append(f"[{ts}] Initializing Kaiagotchi...")
            except Exception:
                _log.debug("View.on_starting failed", exc_info=True)

    async def stop(self):
        """Stop display."""
        self._running = False
        if self.display and hasattr(self.display, 'stop'):
            self.display.stop()
        _log.info("View stopped gracefully")

    async def on_shutdown(self):
        """Alias for stop to support legacy scripts."""
        await self.stop()