from __future__ import annotations
import asyncio
import atexit
import logging
import sys
import time
import shutil
import re
from typing import Any, Dict, Optional, List
from datetime import datetime
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

        self._max_visible_aps = int(self._config.get("max_visible_aps", 15))
        self._max_visible_stations = int(self._config.get("max_visible_stations", 10))
        self._max_visible_chatter = int(self._config.get("max_visible_chatter", 6))

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
            except Exception:
                _LOG.exception("draw failed")

    def render(self, state: Dict[str, Any]):
        if not self._enabled:
            return
        try:
            now = time.time()
            
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
        except Exception:
            _LOG.exception("render failed")

    def update_table(self, aps: List[Dict[str, Any]], stations: Optional[List[Dict[str, Any]]] = None):
        try:
            aps_sorted = sorted(
                aps or [],
                key=lambda a: (self._parse_last_seen(a.get("last_seen", "")), int(a.get("power", -9999))),
                reverse=True,
            )
        except Exception:
            aps_sorted = aps or []
        try:
            stations_sorted = sorted(
                stations or [],
                key=lambda s: int(s.get("packets", -1)),
                reverse=True,
            )
        except Exception:
            stations_sorted = stations or []
        self._ap_table = aps_sorted[: self._max_visible_aps]
        self._stations = stations_sorted[: self._max_visible_stations]
        try:
            if self._last_state:
                self.render(self._last_state.copy())
        except Exception:
            _LOG.exception("update_table failed")

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

    def _make_line(self, text: str = "", width: Optional[int] = None) -> str:
        """Create a line padded to the specified width."""
        if width is None:
            cols, _ = self._term_size()
            width = max(60, cols - 2)
        return self._pad(text or "", width, align="left")

    # ---- State change detection ----
    def _state_changed(self, prev: Dict[str, Any], new: Dict[str, Any]) -> bool:
        """
        Return True if the new state differs in important fields that affect UI.
        """
        if not prev:
            return True
        
        # DEBUG: Log mood changes to see what's happening
        prev_mood = prev.get("agent_mood")
        new_mood = new.get("agent_mood")
        if prev_mood != new_mood:
            _LOG.debug(f"Mood change detected: {prev_mood} -> {new_mood}")
            return True
        
        if (prev.get("face") != new.get("face") or 
            prev.get("status") != new.get("status")):
            return True
        
        if (prev.get("aps", 0) != new.get("aps", 0) or
            prev.get("aps_max_seen", 0) != new.get("aps_max_seen", 0)):
            return True
        
        prev_chatter = prev.get("chatter_log") or []
        new_chatter = new.get("chatter_log") or []
        if len(prev_chatter) != len(new_chatter):
            return True
        
        if len(prev.get("aps_list", [])) != len(new.get("aps_list", [])):
            return True
        if len(prev.get("stations_list", [])) != len(new.get("stations_list", [])):
            return True
        
        if time.time() - self._last_draw_time > 10.0:
            return True
            
        return False

    # ---- Timestamp handling ----
    def _parse_last_seen(self, s: str) -> float:
        """Robust timestamp parsing for multiple formats."""
        if not s or s == "--":
            return 0.0
            
        s = str(s).strip()
        
        # Handle relative time (HH:MM:SS)
        if ":" in s and "-" not in s and "T" not in s:
            try:
                parts = s.split(":")
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    now = datetime.now()
                    dt = now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
                    if dt > now:
                        dt = dt.replace(day=dt.day - 1)
                    return dt.timestamp()
            except Exception:
                pass
        
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
                    now = datetime.now()
                    dt = dt.replace(year=now.year, month=now.month, day=now.day)
                return dt.timestamp()
            except ValueError:
                continue
                
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
        except Exception:
            return default

    def _get_face(self, state: Dict[str, Any]) -> str:
        """Get face from state, ensuring it's not hardcoded."""
        face = state.get("face")
        if face:
            return face
        mood = state.get("agent_mood") or state.get("mood")
        if isinstance(mood, str):
            return faces.get_face(mood)
        if hasattr(mood, "name"):
            return faces.get_face(mood.name)
        # DEBUG: Log if we're falling back to neutral
        _LOG.debug(f"Falling back to neutral face for mood: {mood}")
        return faces.get_face("neutral")

    # ---- Renderers ----
    def _render_header(self, state: Dict[str, Any]):
        try:
            cols, _ = self._term_size()
            inner = max(60, cols - 2)
            
            # Get dynamic face and mood - ensure they're not hardcoded
            face = self._get_face(state)
            face_colored = f"{BOX_PINK}{face}{RESET}"
            
            # Get mood from state, handle both "NEUTRAL" and "neutral" formats
            mood = state.get("agent_mood") or state.get("mood") or "neutral"
            mood_str = getattr(mood, "name", str(mood)).lower() if mood else "neutral"
            mood_text = mood_str.capitalize()  # "neutral" -> "Neutral"
            
            status_msg = (state.get("status") or "").strip() or "Monitoring signals..."
            aps_val = state.get("aps", "--")
            aps_max_val = state.get("aps_max_seen")
            aps_str = str(aps_val)
            if aps_max_val and aps_max_val != aps_val:
                aps_str = f"{aps_val} ({aps_max_val})"
            pwnd = state.get("pwnd", "0")
            mode = state.get("mode", "") or ""
            uptime = state.get("uptime", "--:--:--")

            top = f"{BOX_GREEN}┌" + "─" * inner + "┐" + RESET
            bot = f"{BOX_GREEN}└" + "─" * inner + "┘" + RESET

            # LEFT-ALIGNED face and status (original position)
            face_status = f"  {face_colored}  < {status_msg} >"
            
            # Info line - left aligned
            info = (
                f"  {CYAN}APs:{RESET} {aps_str} "
                f"{CYAN}PWND:{RESET} {pwnd} "
                f"{CYAN}MOOD:{RESET} {mood_text} "
                f"{CYAN}MODE:{RESET} {mode} "
                f"{CYAN}Uptime:{RESET} {uptime}"
            )
            
            # Ensure info fits
            info_plain = self._strip_ansi(info)
            if len(info_plain) > (inner - 2):
                info = (
                    f"  {CYAN}APs:{RESET} {aps_str} "
                    f"{CYAN}MOOD:{RESET} {mood_text} "
                    f"{CYAN}MODE:{RESET} {mode}"
                )
                info_plain = self._strip_ansi(info)
                if len(info_plain) > (inner - 2):
                    info = info_plain[:(inner - 2)]

            self._out.write("\033[H")
            self._out.write(top + "\n")
            self._out.write(f"{BOX_GREEN}│{RESET} {self._make_line(face_status, inner - 2)} {BOX_GREEN}│{RESET}\n")
            self._out.write(f"{BOX_GREEN}│{RESET} {self._make_line(info, inner - 2)} {BOX_GREEN}│{RESET}\n")
            self._out.write(bot + "\n")
            self._out.flush()
        except Exception:
            _LOG.exception("_render_header failed")

    def _render_tables(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]):
        try:
            cols, term_rows = self._term_size()
            inner = max(60, cols - 2)

            header_rows = 4
            reserved_chatter = 1
            remaining = max(3, term_rows - header_rows - reserved_chatter)

            ap_budget = min(self._max_visible_aps, max(1, remaining // 2))
            sta_budget = min(self._max_visible_stations, max(1, remaining - ap_budget))

            ap_draw = min(len(aps or []), ap_budget)
            sta_draw = min(len(stations or []), sta_budget)

            # AP Table - YELLOW BOX
            top_ap = f"{BOX_YELLOW}┌" + "─" * inner + "┐" + RESET
            bot_ap = f"{BOX_YELLOW}└" + "─" * inner + "┘" + RESET

            fixed_ap_cols = (
                COL_BSSID + 2
                + COL_CH + 2
                + COL_PWR + 3
                + COL_AES + 2
                + COL_BEACON + 2
                + COL_FIRST + 2
                + COL_LAST + 2
            )
            essid_width = max(8, inner - fixed_ap_cols - 2)

            # CENTERED headers for AP table
            head_ap = (
                f"{BOLD}{YELLOW}"
                f"{self._pad('BSSID', COL_BSSID, 'center')}  "
                f"{self._pad('Channel', COL_CH, 'center')}  "
                f"{self._pad('Power', COL_PWR, 'center')}   "
                f"{self._pad('Encryption', COL_AES, 'center')}  "  # Fixed full "Encryption"
                f"{self._pad('Beacons', COL_BEACON, 'center')}  "
                f"{self._pad('First Seen', COL_FIRST, 'center')}  "
                f"{self._pad('Last Seen', COL_LAST, 'center')}  "
                f"{self._pad('ESSID', essid_width, 'left')}"
                f"{RESET}"
            )

            header_line = f"{BOX_YELLOW}│{RESET} {self._make_line(head_ap, inner - 2)} {BOX_YELLOW}│{RESET}"
            ap_rows_out: List[str] = []

            for ap in (aps or [])[:ap_draw]:
                bssid = self._pad(str(ap.get("bssid", "")), COL_BSSID, "left")
                ch = self._pad(str(ap.get("channel", "--")), COL_CH, "center")
                pwr_val = ap.get("power", "--")
                try:
                    pval = int(pwr_val)
                    pcolor = GREEN if pval >= -50 else YELLOW if pval >= -70 else RED
                except Exception:
                    pcolor = GRAY
                    
                enc = (ap.get("privacy", "--") or "--").upper()
                enc_color = (
                    RED if "WEP" in enc else
                    GREEN if "WPA3" in enc or "WPA2" in enc else
                    YELLOW if "WPA" in enc else
                    GRAY if "OPEN" in enc or "OPN" in enc else CYAN
                )
                # CENTERED beacons count
                beacons = self._pad(str(ap.get("beacons", "--")), COL_BEACON, "center")

                first_raw = ap.get("first_seen", "--")
                last_raw = ap.get("last_seen", "--")
                first_ts = self._parse_last_seen(first_raw)
                last_ts = self._parse_last_seen(last_raw)
                
                first_display = self._format_timestamp(first_ts, "--")
                last_display = self._format_timestamp(last_ts, "--")
                
                if last_ts and first_ts and (last_ts - first_ts) <= 2.0:
                    last_display = "new"

                first_seen = self._pad(first_display, COL_FIRST, "center")
                last_seen = self._pad(last_display, COL_LAST, "center")
                essid = self._pad(str(ap.get("essid", "")), essid_width, "left")

                # CENTERED power and encryption
                pwr_text = f"{pcolor}{self._pad(str(pwr_val), COL_PWR, 'center')}{RESET}"
                enc_text = f"{enc_color}{self._pad(enc, COL_AES, 'center')}{RESET}"  # Centered WPA2 etc.

                row = (
                    f"{bssid}  "
                    f"{CYAN}{ch}{RESET}  "
                    f"{pwr_text}   "
                    f"{enc_text}  "
                    f"{beacons}  "
                    f"{first_seen}  "
                    f"{last_seen}  "
                    f"{essid}"
                )
                ap_rows_out.append(f"{BOX_YELLOW}│{RESET} {self._make_line(row, inner - 2)} {BOX_YELLOW}│{RESET}")

            if not ap_rows_out:
                ap_rows_out.append(f"{BOX_YELLOW}│{RESET} {self._make_line('No Access Points detected', inner - 2)} {BOX_YELLOW}│{RESET}")

            # Station Table - CYAN BOX
            top_sta = f"{BOX_CYAN}┌" + "─" * inner + "┐" + RESET
            bot_sta = f"{BOX_CYAN}└" + "─" * inner + "┘" + RESET

            fixed_sta_cols = (
                COL_STA_MAC + 2
                + COL_STA_PWR + 2
                + COL_STA_PKT + 2
                + COL_STA_BSSID + 2
            )
            probed_width = max(8, inner - fixed_sta_cols - 2)

            head_sta = (
                f"{BOLD}{CYAN}"
                f"{self._pad('Station MAC', COL_STA_MAC, 'center')}  "
                f"{self._pad('Power', COL_STA_PWR, 'center')}  "
                f"{self._pad('Packets', COL_STA_PKT, 'center')}  "  # Centered header
                f"{self._pad('BSSID', COL_STA_BSSID, 'center')}  "
                f"{self._pad('Probed', probed_width, 'left')}"
                f"{RESET}"
            )
            header_sta = f"{BOX_CYAN}│{RESET} {self._make_line(head_sta, inner - 2)} {BOX_CYAN}│{RESET}"
            sta_rows_out: List[str] = []

            for s in (stations or [])[:sta_draw]:
                mac = self._pad(str(s.get("station_mac", "")), COL_STA_MAC, "left")
                pwr_val = s.get("power", "--")
                pkts = s.get("packets", "--")
                bssid = self._pad(str(s.get("bssid", "--")), COL_STA_BSSID, "left")
                probed = self._pad(str(s.get("essids", "")), probed_width, "left")
                
                try:
                    pval = int(pwr_val)
                    pcolor = GREEN if pval >= -50 else YELLOW if pval >= -70 else RED
                except Exception:
                    pcolor = GRAY

                # CENTERED power and packets
                pwr_text = f"{pcolor}{self._pad(str(pwr_val), COL_STA_PWR, 'center')}{RESET}"
                pkts_text = self._pad(str(pkts), COL_STA_PKT, 'center')  # Centered packet numbers

                line = (
                    f"{mac}  "
                    f"{pwr_text}  "
                    f"{pkts_text}  "
                    f"{bssid}  "
                    f"{probed}"
                )
                sta_rows_out.append(f"{BOX_CYAN}│{RESET} {self._make_line(line, inner - 2)} {BOX_CYAN}│{RESET}")

            if not sta_rows_out:
                sta_rows_out.append(f"{BOX_CYAN}│{RESET} {self._make_line('No Stations detected', inner - 2)} {BOX_CYAN}│{RESET}")

            # Output blocks
            self._out.write(top_ap + "\n")
            self._out.write(header_line + "\n")
            for r in ap_rows_out:
                self._out.write(r + "\n")
            self._out.write(bot_ap + "\n")

            self._out.write(top_sta + "\n")
            self._out.write(header_sta + "\n")
            for r in sta_rows_out:
                self._out.write(r + "\n")
            self._out.write(bot_sta + "\n")
            self._out.flush()
        except Exception:
            _LOG.exception("_render_tables failed")

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

            header_used = 4
            ap_used = 3 + min(len(self._ap_table), self._max_visible_aps)
            sta_used = 3 + min(len(self._stations), self._max_visible_stations)
            used = header_used + ap_used + sta_used
            remaining = max(1, term_rows - used - 1)

            actual_messages = len(lines)
            visible_count = min(self._max_visible_chatter, max(1, min(remaining, max(1, actual_messages))))

            top = f"{BOX_PINK}┌" + "─" * inner + "┐" + RESET
            bot = f"{BOX_PINK}└" + "─" * inner + "┘" + RESET
            header_title = f"{BOLD}{PINK}System Chatter{RESET}"
            header_line = f"{BOX_PINK}│{RESET} {self._make_line(header_title, inner - 2)} {BOX_PINK}│{RESET}"

            chatter_rows: List[str] = []
            recent = lines[-visible_count:] if lines else []
            pad = max(0, visible_count - len(recent))

            for _ in range(pad):
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line('', inner - 2)} {BOX_PINK}│{RESET}")

            for raw_line in recent:
                key = self._strip_ansi(raw_line)
                color = self._message_colors.get(key) or CHATTER_PALETTE[hash(key) % len(CHATTER_PALETTE)]
                self._message_colors[key] = color
                rendered = f"{color}{raw_line}{RESET}"
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line(rendered, inner - 2)} {BOX_PINK}│{RESET}")

            if not chatter_rows:
                chatter_rows.append(f"{BOX_PINK}│{RESET} {self._make_line('Awaiting events...', inner - 2)} {BOX_PINK}│{RESET}")

            self._out.write(top + "\n")
            self._out.write(header_line + "\n")
            for r in chatter_rows:
                self._out.write(r + "\n")
            self._out.write(bot + "\n")
            self._out.flush()
        except Exception:
            _LOG.debug("_render_chatter_box failed", exc_info=True)

    def force_redraw(self):
        try:
            self.clear()
            self._render_header(self._last_state or {})
            self._render_tables(self._ap_table, self._stations)
            self._render_chatter_box(self._last_state or {})
        except Exception:
            _LOG.exception("force_redraw failed")