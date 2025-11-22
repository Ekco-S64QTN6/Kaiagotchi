from __future__ import annotations
import asyncio
import atexit
import logging
import sys
import time
import shutil
import re
from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
from kaiagotchi.ui import faces

_LOG = logging.getLogger("kaiagotchi.ui.terminal_display")

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[38;5;46m"
YELLOW = "\033[38;5;226m"
RED = "\033[38;5;196m"
CYAN = "\033[38;5;51m"
GRAY = "\033[38;5;245m"
PINK = "\033[38;5;199m"
WHITE = "\033[38;5;255m"

BOX_GREEN = GREEN
BOX_YELLOW = YELLOW
BOX_CYAN = CYAN
BOX_PINK = PINK

# Column widths (visible chars)
COL_BSSID = 17
COL_CH = 7
COL_PWR = 6
COL_AES = 10  # Increased to fit "Encryption"
COL_BEACON = 8
COL_FIRST = 19
COL_LAST = 19

COL_STA_MAC = 17
COL_STA_PWR = 6
COL_STA_PKT = 8  # Increased to center better
COL_STA_BSSID = 17

CHATTER_PALETTE = [CYAN, YELLOW, GREEN, RED, PINK]

class TerminalDisplay:
    _instance: Optional["TerminalDisplay"] = None
    _lock = asyncio.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._out = sys.__stdout__
        self._draw_lock = asyncio.Lock()
        self._enabled = True
        self._start_time = time.time()
        self._last_state: Dict[str, Any] = {}
        self._last_draw_time = 0.0
        self._ap_table: List[Dict[str, Any]] = []
        self._stations: List[Dict[str, Any]] = []
        self._message_colors: Dict[str, str] = {}
        self._config = config or {}
        self._cursor_hidden = False
        self._current_mood_from_state = "neutral"
        
        # Status message tracking
        self._current_status = "Monitoring signals..."
        self._status_start_time = 0.0
        self._min_status_display_time = 3.0  # Minimum seconds to show a status message

        self._max_visible_aps = int(self._config.get("max_visible_aps", 15))
        self._max_visible_stations = int(self._config.get("max_visible_stations", 10))
        self._max_visible_chatter = int(self._config.get("max_visible_chatter", 6))
        self._version = self._config.get("version", "1.0.0")

        try:
            self._out.write("\033[?1049h")
            self._out.flush()
        except Exception:
            pass

        self._hide_cursor()
        atexit.register(self._show_cursor_safe)
        atexit.register(self._leave_alt_buffer_safe)
        _LOG.debug("TerminalDisplay initialized")

    def _leave_alt_buffer_safe(self):
        try:
            sys.__stdout__.write("\033[?1049l")
            sys.__stdout__.flush()
        except Exception:
            pass

    def _hide_cursor(self):
        if not self._cursor_hidden:
            try:
                self._out.write("\033[?25l")
                self._out.flush()
                self._cursor_hidden = True
            except Exception:
                pass

    def _show_cursor_safe(self):
        try:
            sys.__stdout__.write("\033[?25h")
            sys.__stdout__.flush()
        except Exception:
            pass

    def _term_size(self):
        try:
            size = shutil.get_terminal_size(fallback=(80, 24))
            return size.columns, size.lines
        except Exception:
            return 80, 24

    def clear(self):
        try:
            self._out.write("\033[2J\033[H")
            self._out.flush()
        except Exception:
            pass

    async def draw(self, state: Dict[str, Any]):
        if not self._enabled:
            return
        async with self._draw_lock:
            now = time.time()
            
            # Update status with minimum display time logic
            self._update_status(state, now)
            
            # CRITICAL: Allow immediate updates for mood/face/status changes
            force_update = False
            if self._last_state:
                prev_mood = self._last_state.get("agent_mood")
                new_mood = state.get("agent_mood")
                mood_changed = prev_mood != new_mood
                
                face_changed = self._last_state.get("face") != state.get("face")
                status_changed = self._last_state.get("status") != state.get("status")
                
                force_update = mood_changed or face_changed or status_changed
            
            # Reduced minimum interval for mood changes
            min_interval = 0.1 if force_update else 1.0
            
            if not force_update and now - self._last_draw_time < min_interval:
                return
            if not force_update and not self._state_changed(self._last_state, state):
                return
                
            try:
                self.clear()
                self._render_header(state)
                self._render_tables(self._ap_table, self._stations)
                self._render_chatter_box(state)
                self._last_state = state.copy()
                self._last_draw_time = now
            except Exception as e:
                _LOG.error("draw failed: %s", e)
                _LOG.exception("Full draw exception traceback")

    def render(self, state: Dict[str, Any]):
        if not self._enabled:
            return
        try:
            now = time.time()
            
            # Update status with minimum display time logic
            self._update_status(state, now)
            
            # CRITICAL: Allow immediate updates for mood/face/status changes
            force_update = False
            if self._last_state:
                prev_mood = self._last_state.get("agent_mood")
                new_mood = state.get("agent_mood")
                mood_changed = prev_mood != new_mood
                
                face_changed = self._last_state.get("face") != state.get("face")
                status_changed = self._last_state.get("status") != state.get("status")
                
                force_update = mood_changed or face_changed or status_changed
            
            # Reduced minimum interval for mood changes, normal interval for others
            min_interval = 0.1 if force_update else 1.0
            
            if not force_update and now - self._last_draw_time < min_interval:
                return
                
            if not force_update and not self._state_changed(self._last_state, state):
                return
                
            self.clear()
            self._render_header(state)
            self._render_tables(self._ap_table, self._stations)
            self._render_chatter_box(state)
            self._last_state = state.copy()
            self._last_draw_time = now
        except Exception as e:
            _LOG.error("render failed: %s", e)
            _LOG.exception("Full render exception traceback")

    def _update_status(self, state: Dict[str, Any], current_time: float):
        """Update current status with minimum display time logic."""
        new_status = (state.get("status") or "").strip()
        default_status = "Monitoring signals..."
        
        if not new_status:
            # If no status in state, use default but respect minimum display time
            if (self._current_status != default_status and 
                current_time - self._status_start_time < self._min_status_display_time):
                # Keep current status for minimum time
                return
            self._current_status = default_status
            self._status_start_time = current_time
        else:
            # New status from state
            if new_status != self._current_status:
                self._current_status = new_status
                self._status_start_time = current_time
                _LOG.debug("Status changed to: %s", new_status)

    def update_table(self, aps: List[Dict[str, Any]], stations: Optional[List[Dict[str, Any]]] = None):
        try:
            aps_sorted = sorted(
                aps or [],
                key=lambda a: (self._parse_last_seen(a.get("last_seen", "")), int(a.get("power", -9999))),
                reverse=True,
            )
        except Exception as e:
            _LOG.warning("AP sorting failed: %s", e)
            aps_sorted = aps or []
        try:
            stations_sorted = sorted(
                stations or [],
                key=lambda s: int(s.get("packets", -1)),
                reverse=True,
            )
        except Exception as e:
            _LOG.warning("Station sorting failed: %s", e)
            stations_sorted = stations or []
        self._ap_table = aps_sorted[: self._max_visible_aps]
        self._stations = stations_sorted[: self._max_visible_stations]
        try:
            if self._last_state:
                self.render(self._last_state.copy())
        except Exception as e:
            _LOG.error("update_table failed: %s", e)
            _LOG.exception("Full update_table exception traceback")

    # ---- ANSI-aware helpers ----
    _ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def _strip_ansi(self, s: str) -> str:
        return self._ansi_re.sub("", s) if s is not None else ""

    def _visible_len(self, s: str) -> int:
        return len(self._strip_ansi(s))

    def _pad(self, s: str, width: int, align: str = "left") -> str:
        """Pad a string to the specified width, handling ANSI codes correctly."""
        if s is None:
            s = ""
        plain = self._strip_ansi(s)
        if len(plain) > width:
            return plain[:width]
        pad = width - len(plain)
        if align == "left":
            return s + " " * pad
        if align == "right":
            return " " * pad + s
        if align == "center":
            left = pad // 2
            right = pad - left
            return " " * left + s + " " * right
        return s

    def _make_line(self, text: str = "", width: Optional[int] = None, align: str = "left") -> str:
        """Create a line padded to the specified width."""
        if width is None:
            cols, _ = self._term_size()
            width = max(60, cols - 2)
        return self._pad(text or "", width, align=align)

    # ---- State change detection ----
    def _state_changed(self, prev: Dict[str, Any], new: Dict[str, Any]) -> bool:
        """
        Return True if the new state differs in important fields that affect UI.
        Optimized for performance with early returns.
        """
        if not prev:
            return True
        
        # Check high-priority fields first (most likely to change)
        important_fields = [
            "face", "status", "agent_mood", "mood",
            "aps", "aps_max_seen", "pwnd", "mode", "uptime"
        ]
        
        for field in important_fields:
            if prev.get(field) != new.get(field):
                _LOG.debug("State change detected in field '%s': %s -> %s", 
                          field, prev.get(field), new.get(field))
                return True
        
        # Check list lengths (quick check)
        prev_chatter = prev.get("chatter_log") or []
        new_chatter = new.get("chatter_log") or []
        if len(prev_chatter) != len(new_chatter):
            return True
        
        if len(prev.get("aps_list", [])) != len(new.get("aps_list", [])):
            return True
        if len(prev.get("stations_list", [])) != len(new.get("stations_list", [])):
            return True
        
        # Force periodic refresh
        if time.time() - self._last_draw_time > 10.0:
            return True
            
        return False

    # ---- Timestamp handling ----
    def _parse_last_seen(self, s: str) -> float:
        """Robust timestamp parsing for multiple formats with improved midnight handling."""
        if not s or s == "--":
            return 0.0
            
        s = str(s).strip()
        
        # Handle relative time (HH:MM:SS) with robust midnight crossover
        if ":" in s and "-" not in s and "T" not in s:
            try:
                parts = s.split(":")
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    now = datetime.now()
                    parsed_time = now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
                    
                    # Handle midnight crossover: if parsed time is more than 6 hours ahead,
                    # assume it's from the previous day
                    time_diff = (parsed_time - now).total_seconds()
                    if time_diff > 6 * 3600:  # More than 6 hours ahead
                        parsed_time = parsed_time - timedelta(days=1)
                    # If it's more than 18 hours behind, assume it's from the next day
                    # (unlikely but handles edge cases)
                    elif time_diff < -18 * 3600:
                        parsed_time = parsed_time + timedelta(days=1)
                        
                    return parsed_time.timestamp()
            except Exception as e:
                _LOG.debug("Failed to parse relative time '%s': %s", s, e)
        
        # Handle absolute timestamp formats
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f", 
            "%Y-%m-%d %H:%M:%S.%f",
            "%H:%M:%S"
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                if fmt == "%H:%M:%S":
                    # Handle time-only format with midnight crossover
                    now = datetime.now()
                    dt = dt.replace(year=now.year, month=now.month, day=now.day)
                    # Same midnight logic as above
                    time_diff = (dt - now).total_seconds()
                    if time_diff > 6 * 3600:
                        dt = dt - timedelta(days=1)
                    elif time_diff < -18 * 3600:
                        dt = dt + timedelta(days=1)
                return dt.timestamp()
            except ValueError:
                continue
                
        _LOG.debug("Could not parse timestamp '%s' with any format", s)
        return 0.0

    def _format_timestamp(self, timestamp: float, default: str = "--") -> str:
        """Format timestamp for clean display."""
        if not timestamp:
            return default
            
        try:
            dt = datetime.fromtimestamp(timestamp)
            now = datetime.now()
            
            if dt.date() == now.date():
                return dt.strftime("%H:%M:%S")
            else:
                return dt.strftime("%m-%d %H:%M")
        except Exception as e:
            _LOG.debug("Failed to format timestamp %s: %s", timestamp, e)
            return default

    def _get_face(self, state: Dict[str, Any]) -> str:
        """Simplified face resolution with clear priority and better logging."""
        # Priority 1: Explicit face from state
        explicit_face = state.get("face")
        if explicit_face:
            _LOG.debug("Using explicit face: %s", explicit_face)
            return explicit_face
        
        # Priority 2: Mood from state (agent_mood takes precedence)
        mood = None
        mood_source = None
        
        if "agent_mood" in state and state["agent_mood"]:
            mood = state["agent_mood"]
            mood_source = "agent_mood"
        elif "mood" in state and state["mood"]:
            mood = state["mood"]
            mood_source = "mood"
        
        if mood:
            try:
                # Normalize mood string
                mood_str = str(mood).lower()
                self._current_mood_from_state = mood_str
                face_result = faces.get_face(mood_str)
                _LOG.debug("Resolved face from %s '%s': %s", mood_source, mood_str, face_result)
                return face_result
            except Exception as e:
                _LOG.warning("Failed to get face for mood '%s': %s", mood, e)
        
        # Priority 3: Fallback to current tracked mood
        try:
            face_result = faces.get_face(self._current_mood_from_state)
            _LOG.debug("Using fallback face for mood '%s': %s", 
                      self._current_mood_from_state, face_result)
            return face_result
        except Exception as e:
            _LOG.error("Failed to get fallback face for mood '%s': %s", 
                      self._current_mood_from_state, e)
        
        # Final emergency fallback
        _LOG.warning("All face resolution failed, using neutral")
        return faces.get_face("neutral")

    # ---- Renderers ----
    def _render_header(self, state: Dict[str, Any]):
        try:
            # Track current mood
            current_mood = state.get("agent_mood") or state.get("mood") or "neutral"
            self._current_mood_from_state = str(current_mood).lower()
            
            cols, _ = self._term_size()
            inner = max(60, cols - 2)
            
            # Get dynamic face
            face = self._get_face(state)
            face_colored = f"{BOX_PINK}{face}{RESET}"
            
            # Mood text
            mood = state.get("agent_mood") or state.get("mood") or "neutral"
            mood_str = getattr(mood, "name", str(mood)).lower() if mood else "neutral"
            mood_text = mood_str.capitalize()
            
            # Interface info
            iface = state.get("interface", "unknown")
            model = state.get("interface_model", "")
            iface_str = f"{iface}"
            if model:
                iface_str += f" [{model}]"
            
            # Status
            status_msg = self._current_status
            
            # Metrics
            aps_val = state.get("aps", "--")
            pwnd = state.get("pwnd", "0")
            mode = state.get("mode", "AUTO")
            uptime = state.get("uptime", "--:--:--")

            # HTOP-style Header
            # Line 1: Title + Interface (Right aligned)
            title = f"{BOLD}{CYAN}Kaiagotchi{RESET} v{self._version}"
            iface_display = f"{BOLD}{GREEN}{iface_str}{RESET}"
            line1_padding = inner - self._visible_len(title) - self._visible_len(iface_display) - 2
            line1 = f" {title}{' ' * max(1, line1_padding)}{iface_display} "
            
            # Line 2: Face + Status
            line2 = f" {face_colored}  {status_msg}"
            
            # Line 3: Metrics (Bar style)
            # MOOD [|||||     ] Happy
            # APS  [||        ] 12
            
            def make_bar(label, value, color, width=20):
                return f"{CYAN}{label:<5}{RESET} [{color}{value:<{width}}{RESET}]"

            metrics_line = (
                f" {CYAN}MOOD:{RESET} {mood_text:<10} "
                f"{CYAN}MODE:{RESET} {mode:<8} "
                f"{CYAN}APS:{RESET} {str(aps_val):<5} "
                f"{CYAN}PWND:{RESET} {pwnd:<5} "
                f"{CYAN}UPTIME:{RESET} {uptime}"
            )

            top = f"{BOX_GREEN}┌" + "─" * inner + "┐" + RESET
            bot = f"{BOX_GREEN}└" + "─" * inner + "┘" + RESET

            self._out.write("\033[H") # Home
            self._out.write(top + "\n")
            self._out.write(f"{BOX_GREEN}│{RESET}{self._make_line(line1, inner)}{BOX_GREEN}│{RESET}\n")
            self._out.write(f"{BOX_GREEN}│{RESET}{self._make_line(line2, inner)}{BOX_GREEN}│{RESET}\n")
            self._out.write(f"{BOX_GREEN}│{RESET}{self._make_line(metrics_line, inner)}{BOX_GREEN}│{RESET}\n")
            self._out.write(bot + "\n")
            self._out.flush()
        except Exception as e:
            _LOG.error("_render_header failed: %s", e)

    def _render_tables(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]):
        try:
            cols, term_rows = self._term_size()
            inner = max(60, cols - 2)

            header_rows = 5 # Increased for new header
            reserved_chatter = 1
            remaining = max(3, term_rows - header_rows - reserved_chatter)

            ap_budget = min(self._max_visible_aps, max(1, remaining // 2))
            sta_budget = min(self._max_visible_stations, max(1, remaining - ap_budget))

            ap_draw = min(len(aps or []), ap_budget)
            sta_draw = min(len(stations or []), sta_budget)

            # Helper for htop-style bars
            def draw_bar(val, max_val=100, width=5, color=GREEN):
                try:
                    pct = max(0.0, min(1.0, float(val) / float(max_val)))
                    filled = int(pct * width)
                    bar = "|" * filled
                    return f"{color}{bar:<{width}}{RESET}"
                except:
                    return " " * width

            # AP Table
            # Header with background color
            # BSSID | CH | PWR | ENC | ESSID
            
            # Clean layout - no vertical bars
            head_ap = (
                f"{BOLD}{YELLOW}"
                f"{'BSSID':<19} "
                f"{'CH':<4} "
                f"{'PWR':<6} "
                f"{'ENC':<5} "
                f"{'ESSID'}"
                f"{RESET}"
            )
            
            # Fix box header drawing
            title_ap = " Access Points "
            pad_len = inner - len(title_ap)
            left_pad = pad_len // 2
            right_pad = pad_len - left_pad
            header_top = f"{BOX_YELLOW}┌{'─' * left_pad}{title_ap}{'─' * right_pad}┐{RESET}"
            
            self._out.write(header_top + "\n")
            self._out.write(f"{BOX_YELLOW}│{RESET} {self._make_line(head_ap, inner - 2)} {BOX_YELLOW}│{RESET}\n")

            for ap in (aps or [])[:ap_draw]:
                bssid = str(ap.get("bssid", ""))
                ch = str(ap.get("channel", "--"))
                pwr = ap.get("power", "-99")
                try:
                    pwr_int = int(pwr)
                    # Map -100 to -30 range to 0-100 quality
                    qual = max(0, min(100, (pwr_int + 100) * 2))
                    pwr_bar = draw_bar(qual, 100, 5, GREEN if pwr_int > -60 else YELLOW if pwr_int > -80 else RED)
                except:
                    pwr_bar = "     "
                
                enc = (ap.get("privacy", "") or "OPN")[:3].upper()
                essid = str(ap.get("essid", ""))[:30]
                
                row = (
                    f"{bssid:<19} "
                    f"{ch:<4} "
                    f"{pwr_bar} "
                    f"{enc:<5} "
                    f"{essid}"
                )
                self._out.write(f"{BOX_YELLOW}│{RESET} {self._make_line(row, inner - 2)} {BOX_YELLOW}│{RESET}\n")
            
            if not ap_draw:
                 self._out.write(f"{BOX_YELLOW}│{RESET} {self._make_line('No APs', inner - 2)} {BOX_YELLOW}│{RESET}\n")

            self._out.write(f"{BOX_YELLOW}└" + "─" * inner + "┘" + RESET + "\n")

            # Station Table
            head_sta = (
                f"{BOLD}{CYAN}"
                f"{'STATION':<19} "
                f"{'PWR':<6} "
                f"{'PKTS':<6} "
                f"{'BSSID':<19} "
                f"{'PROBED'}"
                f"{RESET}"
            )

            title_sta = " Stations "
            pad_len = inner - len(title_sta)
            left_pad = pad_len // 2
            right_pad = pad_len - left_pad
            header_sta_top = f"{BOX_CYAN}┌{'─' * left_pad}{title_sta}{'─' * right_pad}┐{RESET}"

            self._out.write(header_sta_top + "\n")
            self._out.write(f"{BOX_CYAN}│{RESET} {self._make_line(head_sta, inner - 2)} {BOX_CYAN}│{RESET}\n")

            for s in (stations or [])[:sta_draw]:
                mac = str(s.get("station_mac", ""))
                pwr = s.get("power", "-99")
                try:
                    pwr_int = int(pwr)
                    qual = max(0, min(100, (pwr_int + 100) * 2))
                    pwr_bar = draw_bar(qual, 100, 5, GREEN if pwr_int > -60 else YELLOW if pwr_int > -80 else RED)
                except:
                    pwr_bar = "     "
                
                pkts = str(s.get("packets", "0"))
                bssid = str(s.get("bssid", ""))
                probed = str(s.get("probed_essids", ""))[:20]

                row = (
                    f"{mac:<19} "
                    f"{pwr_bar} "
                    f"{pkts:<6} "
                    f"{bssid:<19} "
                    f"{probed}"
                )
                self._out.write(f"{BOX_CYAN}│{RESET} {self._make_line(row, inner - 2)} {BOX_CYAN}│{RESET}\n")

            if not sta_draw:
                 self._out.write(f"{BOX_CYAN}│{RESET} {self._make_line('No Stations', inner - 2)} {BOX_CYAN}│{RESET}\n")

            self._out.write(f"{BOX_CYAN}└" + "─" * inner + "┘" + RESET + "\n")
            self._out.flush()

        except Exception as e:
            _LOG.error("_render_tables failed: %s", e)

    def _render_chatter_box(self, state: Dict[str, Any]):
        try:
            chatter = state.get("recent_captures") or state.get("chatter_log") or []
            lines: List[str] = []
            for item in chatter:
                if isinstance(item, dict):
                    t = item.get("timestamp", "")
                    m = item.get("message", "").strip()
                    if t and m:
                        lines.append(f"[{t}] {m}")
                    elif m:
                        lines.append(m)
                elif isinstance(item, str):
                    lines.append(item.strip())

            cols, term_rows = self._term_size()
            inner = max(60, cols - 2)

            # Calculate remaining space dynamically
            # Header (5) + AP Table (variable) + Station Table (variable) + Chatter Header (2) + Chatter Footer (1)
            header_rows = 5
            
            # Estimate table heights based on current content (clamped by max settings)
            ap_count = len(self._ap_table)
            sta_count = len(self._stations)
            
            # Tables have header(2) + footer(1) + content
            ap_height = 3 + (1 if ap_count == 0 else ap_count)
            sta_height = 3 + (1 if sta_count == 0 else sta_count)
            
            used_height = header_rows + ap_height + sta_height
            remaining = max(3, term_rows - used_height - 2) # -2 for chatter borders

            actual_messages = len(lines)
            visible_count = min(self._max_visible_chatter, max(1, min(remaining, max(1, actual_messages))))

            title_chat = " System Chatter "
            pad_len = inner - len(title_chat)
            left_pad = pad_len // 2
            right_pad = pad_len - left_pad
            top = f"{BOX_PINK}┌{'─' * left_pad}{title_chat}{'─' * right_pad}┐{RESET}"
            
            bot = f"{BOX_PINK}└" + "─" * inner + "┘" + RESET

            chatter_rows: List[str] = []
            recent = lines[-visible_count:] if lines else []
            
            # Fill from bottom
            pad = max(0, visible_count - len(recent))

            for _ in range(pad):
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line('', inner - 2)} {BOX_PINK}│{RESET}")

            for raw_line in recent:
                key = self._strip_ansi(raw_line)
                color = self._message_colors.get(key) or CHATTER_PALETTE[hash(key) % len(CHATTER_PALETTE)]
                self._message_colors[key] = color
                rendered = f"{color}{raw_line}{RESET}"
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line(rendered, inner - 2)} {BOX_PINK}│{RESET}")

            if not chatter_rows and not pad:
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line('Awaiting events...', inner - 2)} {BOX_PINK}│{RESET}")

            self._out.write(top + "\n")
            for r in chatter_rows:
                self._out.write(r + "\n")
            self._out.write(bot + "\n")
            self._out.flush()
        except Exception as e:
            _LOG.error("_render_chatter_box failed: %s", e)
            _LOG.exception("Full chatter box render exception")

    def force_redraw(self):
        try:
            self.clear()
            self._render_header(self._last_state or {})
            self._render_tables(self._ap_table, self._stations)
            self._render_chatter_box(self._last_state or {})
        except Exception as e:
            _LOG.error("force_redraw failed: %s", e)
            _LOG.exception("Full force_redraw exception")

    def show_goodbye(self):
        """Show a clean exit message."""
        try:
            self.clear()
            cols, rows = self._term_size()
            msg = " Kaiagotchi Shutdown Complete "
            sub = " See you next time! "
            
            # Center vertically
            padding = (rows // 2) - 2
            self._out.write("\n" * padding)
            
            # Center horizontally
            line1 = self._make_line(msg, cols, align="center").strip()
            line2 = self._make_line(sub, cols, align="center").strip()
            
            self._out.write(f"{BOLD}{CYAN}{line1}{RESET}\n")
            self._out.write(f"{GRAY}{line2}{RESET}\n")
            self._out.write("\n" * 2)
            self._out.flush()
        except Exception:
            pass