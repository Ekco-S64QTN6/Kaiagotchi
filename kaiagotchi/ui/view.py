from __future__ import annotations

import asyncio
import copy
import logging
import random
import time
from typing import Optional, Dict, Any, List

from kaiagotchi.ui.terminal_display import TerminalDisplay
from kaiagotchi.ui.voice import Voice

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
        self._chatter_lines: List[str] = []

        # AP tracking
        self._max_aps_seen: int = 0

        # Mood state management - FIXED: Add proper mood tracking
        self._current_mood = "neutral"
        self._mood_lock = asyncio.Lock()
        self._last_mood_update = 0.0
        self._mood_debounce_interval = 2.0  # Minimum 2 seconds between mood changes

        if not self.display:
            _log.warning("No display provided to View; creating fallback TerminalDisplay.")
            self.display = TerminalDisplay(self._config)

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
    async def async_update(self, state: Dict[str, Any]):
        """Async state update called by Agent. Thread-safe rendering."""
        async with self._update_lock:
            now = time.time()

            # CRITICAL: Extract mood BEFORE any merging to avoid race conditions
            incoming_mood = state.get("agent_mood") or state.get("mood")
            mood_changed = False
            if incoming_mood and incoming_mood != self._current_mood:
                mood_name = getattr(incoming_mood, "name", str(incoming_mood)).lower()
                # Only debounce if we're not in a forced update scenario
                if now - self._last_mood_update >= self._mood_debounce_interval:
                    _log.info(f"🎭 View async_update: Updating mood to {mood_name} from state")
                    self._current_mood = mood_name
                    self._last_mood_update = now
                    mood_changed = True

            # Store current mood before merge to prevent overwrite
            current_mood_before_merge = self._current_mood
            
            # Force update for important changes
            face_changed = (state.get("face") != self.state.get("face"))
            status_changed = (state.get("status") != self.state.get("status"))
            recent_captures_changed = "recent_captures" in state
            
            force_update = mood_changed or face_changed or status_changed or recent_captures_changed

            # Reduce minimum interval for important updates
            self._min_interval = 0.1 if force_update else 1.0

            if not force_update and now - self._last_draw_time < self._min_interval:
                return

            # Deep merge with mood preservation
            try:
                if not isinstance(self.state, dict):
                    self.state = {}
                
                _deep_merge(self.state, state)
                
                # CRITICAL: Ensure mood state is consistent after merge
                # Don't let merged state overwrite our tracked mood
                self.state["agent_mood"] = current_mood_before_merge
                self.state["mood"] = current_mood_before_merge
                    
            except Exception:
                _log.exception("View.async_update: merge failed")

            # Track AP max count (safe coercion)
            try:
                cur_aps = int(self.state.get("aps", 0))
                if cur_aps > self._max_aps_seen:
                    self._max_aps_seen = cur_aps
                self.state["aps_max_seen"] = self._max_aps_seen
            except Exception:
                pass

            # Handle recent captures & chatter
            try:
                await self._handle_recent_captures(self.state.get("recent_captures", []))
                # Ensure chatter log is reflected in state
                self.state["chatter_log"] = list(self._chatter_lines)
            except Exception:
                _log.exception("View.async_update: _handle_recent_captures failed")

            # Normalize state for rendering
            normalized_state = self._ensure_normalized(self.state)

        # Draw/update outside of lock - CRITICAL: Always draw when force_update is True
        if self.display and force_update and not self.suppress_output:
            try:
                # Use render instead of draw for immediate updates
                maybe = self.display.render(normalized_state)
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                _log.exception("View.async_update: display.render failed")

            # Also call update_table if display supports it (pass properly-typed lists)
            try:
                disp_update = getattr(self.display, "update_table", None)
                if callable(disp_update):
                    try:
                        aps = normalized_state.get("aps_list", []) or []
                        stas = normalized_state.get("stations_list", []) or []
                        disp_update(aps, stas)
                    except Exception:
                        _log.exception("View.async_update: display.update_table failed")
            except Exception:
                _log.debug("View.async_update: update_table dispatch failed", exc_info=True)

            # Record last drawn state/time
            self._last_drawn_state = normalized_state.copy()
            self._last_draw_time = now

    # ------------------------------------------------------------------
    async def _handle_recent_captures(self, captures: List[Dict[str, Any]]):
        """Play reactions + update chatter when MonitoringAgent pushes events."""
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
                    if len(self._chatter_lines) > 20:
                        self._chatter_lines = self._chatter_lines[-20:]
            except Exception:
                _log.debug("View._handle_recent_captures: format failed", exc_info=True)

        self.state["chatter_log"] = list(self._chatter_lines)

        # React visually to the newest event(s)
        for cap in new_msgs:
            try:
                msg = cap.get("message", "")
                _log.info(f"[UI] New capture event: {msg}")
                mood = self._current_mood  # Use tracked mood state
                voice_line = self.voice.get_event_line(msg, mood) or msg

                self.state["status"] = voice_line
                self._current_chatter_msg = voice_line
                self._last_chatter_change = time.time()

                base_cool = self.voice.get_chatter_interval(mood)
                self._event_cooldown = min(30.0, max(15.0, base_cool * 0.3))

                # Mood-based faces (unified through Voice)
                if "pmkid" in msg.lower():
                    self.state["face"] = self.voice.get_face_for_mood("happy")
                elif "handshake" in msg.lower():
                    self.state["face"] = self.voice.get_face_for_mood("curious")
                else:
                    self.state["face"] = self.voice.get_face_for_mood(mood)

                # Force immediate update for key events
                if self.display:
                    normalized_state = self._ensure_normalized(self.state)
                    maybe = self.display.render(normalized_state)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    self._last_drawn_state = normalized_state.copy()
                    self._last_draw_time = time.time()
            except Exception:
                _log.debug("View._handle_recent_captures failed", exc_info=True)

    # ------------------------------------------------------------------
    async def update_mood(self, new_mood, reason: str = "automata"):
        """Update UI to reflect the current mood."""
        mood_name = getattr(new_mood, "name", str(new_mood)).lower()
        
        # FIXED: Add debouncing to prevent rapid mood changes
        current_time = time.time()
        if current_time - self._last_mood_update < self._mood_debounce_interval:
            _log.debug(f"Mood change debounced: {self._current_mood} -> {mood_name} (too soon)")
            return
            
        async with self._mood_lock:
            _log.info(f"🎭 View.update_mood: Updating mood to {mood_name} (reason={reason})")

            try:
                # Update tracked mood state
                old_mood = self._current_mood
                self._current_mood = mood_name
                self._last_mood_update = current_time

                # Update state with new mood
                self.state["agent_mood"] = mood_name
                self.state["face"] = self.voice.get_face_for_mood(mood_name)
                text_message = self.voice.get_mood_line(mood_name) or "..."
                self.state["status"] = text_message
                self._current_chatter_msg = text_message
                self._last_chatter_change = time.time()
                self._chatter_hold = self.voice.get_chatter_interval(mood_name)
                self._event_cooldown = 0.0

                # Force immediate render
                normalized_state = self._ensure_normalized(self.state)
                if self.display:
                    # Use render() for immediate update, not draw()
                    maybe = self.display.render(normalized_state)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    self._last_drawn_state = normalized_state.copy()
                    self._last_draw_time = time.time()
                    
                _log.info(f"✅ Mood update completed: {mood_name}")
            except Exception:
                _log.exception("View.update_mood failed")

    # ------------------------------------------------------------------
    async def start(self):
        """Start passive refresh and chatter loops."""
        if self._running:
            return

        self._running = True
        _log.info("View main loop starting")
        self._update_task = asyncio.create_task(self._run_loop())
        self._chatter_task = asyncio.create_task(self._chatter_loop())

    async def _run_loop(self):
        """Passive refresh loop for periodic screen updates."""
        refresh_interval = 3.0  # Reduced for better responsiveness
        while self._running:
            try:
                await asyncio.sleep(refresh_interval)
                # Ensure chatter_log is kept up-to-date
                self.state["chatter_log"] = list(self._chatter_lines)
                normalized_state = self._ensure_normalized(self.state)

                # Check if we need to update (state changed or enough time passed)
                needs_update = (
                    normalized_state != self._last_drawn_state or
                    time.time() - self._last_draw_time > 10.0
                )

                if self.display and needs_update and not self.suppress_output:
                    try:
                        maybe = self.display.render(normalized_state)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    except Exception:
                        _log.exception("View._run_loop: display.render failed")
                    self._last_drawn_state = normalized_state.copy()
                    self._last_draw_time = time.time()
            except asyncio.CancelledError:
                break
            except Exception:
                _log.debug("View._run_loop: refresh failed", exc_info=True)
        _log.debug("View main loop stopped")

    async def _chatter_loop(self):
        """Mood-aware chatter cycle with per-mood intervals and event cooldown."""
        while self._running:
            try:
                mood = self._current_mood  # Use tracked mood state
                now = time.time()

                mood_interval = self.voice.get_chatter_interval(mood)
                base_hold = max(10.0, min(90.0, mood_interval))

                if self._event_cooldown > 0:
                    self._event_cooldown -= 5.0
                else:
                    if (
                        not self._current_chatter_msg
                        or now - self._last_chatter_change > self._chatter_hold
                    ):
                        new_msg = self.voice.get_mood_line(mood) or "..."
                        if new_msg != self._current_chatter_msg:
                            self._current_chatter_msg = new_msg
                            self._last_chatter_change = now
                            self._chatter_hold = random.uniform(base_hold * 0.8, base_hold * 1.2)
                            self.state["status"] = new_msg
                            self.state["face"] = self.voice.get_face_for_mood(mood)
                            
                            # Force update for chatter changes
                            normalized_state = self._ensure_normalized(self.state)
                            if self.display:
                                maybe = self.display.render(normalized_state)
                                if asyncio.iscoroutine(maybe):
                                    await maybe
                                self._last_drawn_state = normalized_state.copy()
                                self._last_draw_time = time.time()

                self.state["status"] = self._current_chatter_msg or "..."
                self.state["chatter_log"] = list(self._chatter_lines)

                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception:
                _log.debug("View._chatter_loop failed", exc_info=True)
        _log.debug("Chatter loop stopped")

    # ------------------------------------------------------------------
    async def on_starting(self):
        """Display startup banner or boot animation."""
        try:
            self.state["status"] = "Initializing Kaiagotchi..."
            self.state["face"] = self.voice.get_face_for_mood("neutral")
            if self.display:
                normalized_state = self._ensure_normalized(self.state)
                maybe = self.display.render(normalized_state)
                if asyncio.iscoroutine(maybe):
                    await maybe
                self._last_drawn_state = normalized_state.copy()
        except Exception:
            _log.debug("View.on_starting failed", exc_info=True)

    async def stop(self):
        """Stop background tasks and clear display."""
        self._running = False
        tasks = [self._update_task, self._chatter_task]
        for t in tasks:
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        _log.info("View stopped gracefully")