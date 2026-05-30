from __future__ import annotations
import asyncio
import atexit
import logging
import sys
import os
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

class ScreenBuffer:
    """A thread-safe character layout array with raw ANSI escape sequence parsing."""
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.grid = [[(" ", RESET) for _ in range(width)] for _ in range(height)]
        
    def set_cell(self, y: int, x: int, char: str, style: str):
        if 0 <= y < self.height and 0 <= x < self.width:
            self.grid[y][x] = (char, style)
            
    def draw_ansi_str(self, y: int, x: int, text: str, default_style: str = RESET, max_x: Optional[int] = None):
        curr_style = default_style
        ansi_re = re.compile(r"\x1b\[[0-9;]*m")
        i = 0
        limit_x = max_x if max_x is not None else self.width
        while i < len(text):
            if text[i] == "\033":
                # Find end of ANSI sequence
                m = ansi_re.match(text, i)
                if m:
                    curr_style = m.group(0)
                    i = m.end()
                    continue
            if 0 <= y < self.height and 0 <= x < limit_x:
                self.grid[y][x] = (text[i], curr_style)
                x += 1
            elif x >= limit_x:
                # Still consume characters but don't advance cursor or write
                pass
            i += 1
            
    def draw_box(self, y: int, x: int, h: int, w: int, title: str = "", footer: str = "", border_style: str = RESET):
        if h < 2 or w < 2:
            return
        # Corners
        self.set_cell(y, x, "╭", border_style)
        self.set_cell(y, x + w - 1, "╮", border_style)
        self.set_cell(y + h - 1, x, "╰", border_style)
        self.set_cell(y + h - 1, x + w - 1, "╯", border_style)
        
        # Horizontal lines
        for cx in range(x + 1, x + w - 1):
            self.set_cell(y, cx, "─", border_style)
            self.set_cell(y + h - 1, cx, "─", border_style)
            
        # Vertical lines
        for cy in range(y + 1, y + h - 1):
            self.set_cell(cy, x, "│", border_style)
            self.set_cell(cy, x + w - 1, "│", border_style)
            
        # Title with curved connectors: ╮ TITLE ╭
        if title:
            title_str = f" {title} "
            if len(title_str) + 4 <= w:
                start_x = x + (w - len(title_str)) // 2
                self.draw_ansi_str(y, start_x - 1, f"╮{title_str}╭", border_style)
            else:
                self.draw_ansi_str(y, x + 2, title_str[:w-4], border_style)
                
        # Footer with curved connectors: ╮ MENU ╭
        if footer:
            footer_str = f" {footer} "
            if len(footer_str) + 4 <= w:
                start_x = x + (w - len(footer_str)) // 2
                self.draw_ansi_str(y + h - 1, start_x - 1, f"╮{footer_str}╭", border_style)
            else:
                self.draw_ansi_str(y + h - 1, x + 2, footer_str[:w-4], border_style)

    def render_to_string(self) -> str:
        lines = []
        for row in self.grid:
            line_parts = []
            last_style = RESET
            for char, style in row:
                if style != last_style:
                    line_parts.append(style)
                    last_style = style
                line_parts.append(char)
            if last_style != RESET:
                line_parts.append(RESET)
            lines.append("".join(line_parts))
        return "\n".join(lines)

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

        # Clear LINES and COLUMNS from environment to bypass python/rich/shutil terminal size caching
        os.environ.pop("LINES", None)
        os.environ.pop("COLUMNS", None)

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

    def _should_render(self, state: Dict[str, Any], now: float):
        """Shared logic for draw/render: detect if a redraw is needed.
        
        Returns (should_draw: bool, updated_now: float).
        """
        self._update_status(state, now)
        
        force_update = False
        if self._last_state:
            prev_mood = self._last_state.get("agent_mood")
            new_mood = state.get("agent_mood")
            mood_changed = prev_mood != new_mood
            face_changed = self._last_state.get("face") != state.get("face")
            status_changed = self._last_state.get("status") != state.get("status")
            force_update = mood_changed or face_changed or status_changed
        
        min_interval = 0.1 if force_update else 1.0
        if not force_update and now - self._last_draw_time < min_interval:
            return False
        if not force_update and not self._state_changed(self._last_state, state):
            return False
        return True

    def _calculate_budgets(self) -> tuple[int, int, int]:
        cols, term_rows = self._term_size()
        
        # Fixed lines:
        # Header: 5 lines
        # AP Table borders/headers: 3 lines
        # Stations Table borders/headers: 3 lines
        # Chatter Box borders/headers: 2 lines
        # Bottom buffer: 1 line (to prevent cursor from causing a scroll)
        fixed_lines = 14
        
        available = term_rows - fixed_lines
        if available < 3:
            # Emergency minimal layout
            return 1, 1, 1
            
        # Target chatter height: 3 to 6 lines
        chatter_budget = min(self._max_visible_chatter, max(3, available // 4))
        
        # Remaining space for tables
        table_space = available - chatter_budget
        if table_space < 2:
            return 1, 1, chatter_budget
            
        # Distribute table space (roughly 60% AP, 40% Station)
        ap_budget = min(self._max_visible_aps, max(1, int(table_space * 0.6)))
        sta_budget = min(self._max_visible_stations, max(1, table_space - ap_budget))

        # Clamp table budgets to a maximum of 5 if window is small (height <= 30 lines)
        if term_rows <= 30:
            ap_budget = min(ap_budget, 5)
            sta_budget = min(sta_budget, 5)
        
        # Adjust if budgets are larger than actual data to give more room to other components
        actual_aps = len(self._ap_table)
        actual_stas = len(self._stations)
        
        if ap_budget > actual_aps and actual_aps > 0:
            extra = ap_budget - actual_aps
            ap_budget = actual_aps
            sta_budget = min(self._max_visible_stations, sta_budget + extra)
            
        if sta_budget > actual_stas and actual_stas > 0:
            extra = sta_budget - actual_stas
            sta_budget = actual_stas
            ap_budget = min(self._max_visible_aps, ap_budget + extra)
            
        # Re-evaluate table space and remaining for chatter
        total_table_used = ap_budget + sta_budget
        chatter_budget = min(self._max_visible_chatter, available - total_table_used)
        
        return ap_budget, sta_budget, max(1, chatter_budget)

    def _do_render(self, state: Dict[str, Any]):
        """Core render logic using a thread-safe 2D ScreenBuffer to create standard, gorgeous btop UI boxes."""
        try:
            # 1. Hide the cursor permanently on every single frame draw
            sys.__stdout__.write("\033[?25l")
            sys.__stdout__.flush()

            cols, lines = self._term_size()
            # Safety checks
            if cols < 60 or lines < 18:
                # Minimum backup rendering
                sys.__stdout__.write("\033[H\033[JTerminal too small! Please resize.\n")
                sys.__stdout__.flush()
                return

            buf = ScreenBuffer(cols, lines)

            # 2. Extract agent state metrics
            uptime = state.get("uptime", "00:00:00")
            mood = state.get("agent_mood") or state.get("mood") or "neutral"
            mood_str = str(mood).capitalize()
            face = self._get_face(state)
            status_msg = self._current_status
            mode = state.get("mode", "AUTO")
            iface = state.get("interface", "wlan1")
            iface_model = state.get("interface_model", "")
            iface_str = f"{iface} [{iface_model}]" if iface_model else iface

            # Get CPU/RAM metrics
            cpu_val = 0.0
            ram_val = 0.0
            disk_val = 0.0
            vram_display = "N/A"
            try:
                import psutil
                cpu_val = psutil.cpu_percent()
                ram_val = psutil.virtual_memory().percent
                disk_val = psutil.disk_usage("/").percent
            except Exception:
                pass

            # Calculate network speeds
            net_sent = 0.0
            net_recv = 0.0
            try:
                import psutil
                net_io = psutil.net_io_counters()
                now_t = time.time()
                prev_sent = getattr(self, "_prev_net_sent_val", 0)
                prev_recv = getattr(self, "_prev_net_recv_val", 0)
                prev_time = getattr(self, "_prev_net_time_val", 0.0)

                if prev_time > 0:
                    elapsed = now_t - prev_time
                    if elapsed > 0.1:
                        net_sent = (net_io.bytes_sent - prev_sent) / 1024.0 / elapsed
                        net_recv = (net_io.bytes_recv - prev_recv) / 1024.0 / elapsed

                self._prev_net_sent_val = net_io.bytes_sent
                self._prev_net_recv_val = net_io.bytes_recv
                self._prev_net_time_val = now_t
            except Exception:
                pass

            # Scoreboard numbers from PersistentNetwork singleton
            total_unique_ssids = 0
            handshakes_count = 0
            complete_handshakes = 0
            pmkids_count = 0
            try:
                agent_ref = getattr(self, "_agent", None)
                if agent_ref and hasattr(agent_ref, "persistent_network"):
                    pn = agent_ref.persistent_network
                    if pn and hasattr(pn, "_data"):
                        total_unique_ssids = len(pn._data.get("bssids", {}))
                        for filename, record in pn._data.get("pcaps", {}).items():
                            analysis = record.get("analysis", []) or []
                            for capture in analysis:
                                handshakes_count += 1
                                if capture.get("handshake_complete"):
                                    complete_handshakes += 1
                                if capture.get("pmkid"):
                                    pmkids_count += 1
            except Exception:
                pass

            # If agent reference is not directly set or database is empty, fallback to state
            if total_unique_ssids == 0:
                total_unique_ssids = len(self._ap_table)

            # ----------------------------------------------------
            # PANE 1: BOT STATUS (Top-Left 50%)
            # ----------------------------------------------------
            w_bot = cols // 2
            buf.draw_box(0, 0, 8, w_bot, title="BOT STATUS", border_style=PINK)
            
            face_colored = f"{BOX_PINK}{face}{RESET}"
            buf.draw_ansi_str(1, 2, f"{CYAN}Face:   {RESET} {face_colored}", max_x=w_bot - 1)
            buf.draw_ansi_str(2, 2, f"{CYAN}Mood:   {RESET} {WHITE}{mood_str}{RESET}", max_x=w_bot - 1)
            buf.draw_ansi_str(3, 2, f"{CYAN}Status: {RESET} {GREEN}● SNIFFING{RESET}" if mode == "AUTO" else f"{CYAN}Status: {RESET} {YELLOW}○ MANUAL{RESET}", max_x=w_bot - 1)
            buf.draw_ansi_str(4, 2, f"{CYAN}Uptime: {RESET} {WHITE}{uptime}{RESET}", max_x=w_bot - 1)
            buf.draw_ansi_str(5, 2, f"{CYAN}Card:   {RESET} {YELLOW}• {iface_str}{RESET}", max_x=w_bot - 1)
            
            # Status speech bubble (slice to prevent overflow beyond pink border)
            clean_status = status_msg[:w_bot - 8]
            buf.draw_ansi_str(6, 2, f"{PINK}« {clean_status} »{RESET}", max_x=w_bot - 1)

            # ----------------------------------------------------
            # PANE 2: SCOREBOARD (Top-Right 50%)
            # ----------------------------------------------------
            x_score = w_bot
            w_score = cols - x_score
            buf.draw_box(0, x_score, 8, w_score, title="SCOREBOARD", border_style=GREEN)
            
            buf.draw_ansi_str(1, x_score + 2, f"{CYAN}Unique SSIDs Seen: {RESET} {GREEN}{total_unique_ssids}{RESET}", max_x=cols - 1)
            buf.draw_ansi_str(2, x_score + 2, f"{CYAN}Total Handshakes:  {RESET} {YELLOW}{handshakes_count}{RESET}", max_x=cols - 1)
            buf.draw_ansi_str(3, x_score + 2, f"{CYAN}Complete WPA:      {RESET} {GREEN}{complete_handshakes}{RESET}", max_x=cols - 1)
            buf.draw_ansi_str(4, x_score + 2, f"{CYAN}Captured PMKIDs:   {RESET} {GREEN}{pmkids_count}{RESET}", max_x=cols - 1)

            # ----------------------------------------------------
            # PANE 4: CHANNEL SPECTRUM HISTOGRAM (Middle)
            # ----------------------------------------------------
            # Height = 6 preserves bottom border perfectly while holding 4 channel rows!
            buf.draw_box(8, 0, 6, cols, title="SPECTRUM CHANNEL DISTRIBUTION", border_style=YELLOW)
            
            # Dynamic channel occupancy calculation
            chan_map = {}
            for ap in self._ap_table:
                ch_val = ap.get("channel")
                if ch_val:
                    try:
                        c_int = int(ch_val)
                        chan_map[c_int] = chan_map.get(c_int, 0) + 1
                    except ValueError:
                        pass

            channels_group = [[1, 5, 9], [2, 6, 10], [3, 7, 11], [4, 8, 12]]
            row_idx = 1
            max_ap_seen = max(1, max(chan_map.values()) if chan_map else 1)
            
            for group in channels_group:
                line_parts = []
                for ch in group:
                    count = chan_map.get(ch, 0)
                    # Smooth progress bars
                    bar_w = 6
                    filled = int(round((count / max_ap_seen) * bar_w))
                    filled = max(0, min(bar_w, filled))
                    bar = "█" * filled + "░" * (bar_w - filled)
                    bar_col = GREEN if count > 3 else YELLOW if count > 0 else GRAY
                    line_parts.append(f"{CYAN}Ch {ch:02d}{RESET} [{bar_col}{bar}{RESET}] {count:2d} APs")
                joined = "   │   ".join(line_parts)
                # Center line
                start_x = (cols - len(self._strip_ansi(joined))) // 2
                buf.draw_ansi_str(8 + row_idx, start_x, joined, max_x=cols - 1)
                row_idx += 1

            # ----------------------------------------------------
            # PANES 5 & 6: ACCESS POINTS & STATIONS
            # ----------------------------------------------------
            chatter_height = 6
            # table_y = 14 aligns perfectly with height 6 of the spectrum box above it
            table_y = 14
            table_h = lines - table_y - chatter_height
            
            # Safety layout checks
            if table_h < 3:
                table_h = 3
                chatter_height = max(3, lines - table_y - table_h)

            if cols >= 100:
                # Side-by-Side Splits
                w_ap = int(cols * 0.6)
                w_sta = cols - w_ap
                
                buf.draw_box(table_y, 0, table_h, w_ap, title="Access Points", border_style=YELLOW)
                buf.draw_box(table_y, w_ap, table_h, w_sta, title="Stations", border_style=CYAN)
                
                # Write AP Header
                head_ap = f"{BOLD}{YELLOW}{'BSSID':<18} {'Ch':<4} {'Pwr':<5} {'Encryption':<10} {'ESSID'}{RESET}"
                buf.draw_ansi_str(table_y + 1, 2, head_ap, max_x=w_ap - 1)
                
                # Draw AP rows
                ap_rows = table_h - 3
                for idx, ap in enumerate(self._ap_table[:ap_rows]):
                    b_mac = ap.get("bssid", "")
                    ch = ap.get("channel", "")
                    pwr = ap.get("power", "-99")
                    try:
                        pwr_i = int(pwr)
                        pwr_str = "|||||" if pwr_i > -60 else "|||" if pwr_i > -80 else "|"
                        pwr_col = GREEN if pwr_i > -60 else YELLOW if pwr_i > -80 else RED
                        pwr_disp = f"{pwr_col}{pwr_str:<5}{RESET}"
                    except:
                        pwr_disp = "     "
                        
                    enc = ap.get("privacy", "Open").strip()[:10]
                    # Format essid dynamically to fit inside space
                    essid = ap.get("essid", "")[:w_ap - 45]
                    
                    row_txt = f"{b_mac:<18} {ch:<4} {pwr_disp} {enc:<10} {essid}"
                    buf.draw_ansi_str(table_y + 2 + idx, 2, row_txt, max_x=w_ap - 1)
                
                # Write Stations Header
                head_sta = f"{BOLD}{CYAN}{'STATION':<18} {'Pwr':<5} {'Pkts':<6} {'BSSID'}{RESET}"
                buf.draw_ansi_str(table_y + 1, w_ap + 2, head_sta, max_x=cols - 1)
                
                # Draw Station rows
                sta_rows = table_h - 3
                for idx, s in enumerate(self._stations[:sta_rows]):
                    s_mac = s.get("station_mac", "")
                    pwr = s.get("power", "-99")
                    try:
                        pwr_i = int(pwr)
                        pwr_str = "|||||" if pwr_i > -60 else "|||" if pwr_i > -80 else "|"
                        pwr_col = GREEN if pwr_i > -60 else YELLOW if pwr_i > -80 else RED
                        pwr_disp = f"{pwr_col}{pwr_str:<5}{RESET}"
                    except:
                        pwr_disp = "     "
                        
                    pkts = s.get("packets", "0")
                    b_mac = s.get("bssid", "unassociated")[:w_sta - 36]
                    
                    row_txt = f"{s_mac:<18} {pwr_disp} {pkts:<6} {b_mac}"
                    buf.draw_ansi_str(table_y + 2 + idx, w_ap + 2, row_txt, max_x=cols - 1)
                    
            else:
                # Stacked layout (Narrow viewport)
                ap_h = (table_h // 2) + 1
                sta_h = table_h - ap_h
                
                buf.draw_box(table_y, 0, ap_h, cols, title="Access Points", border_style=YELLOW)
                buf.draw_box(table_y + ap_h, 0, sta_h, cols, title="Stations", border_style=CYAN)
                
                # Header AP
                buf.draw_ansi_str(table_y + 1, 2, f"{BOLD}{YELLOW}{'BSSID':<18} {'Ch':<4} {'Pwr':<5} {'Encryption':<10} {'ESSID'}{RESET}", max_x=cols - 1)
                for idx, ap in enumerate(self._ap_table[:ap_h - 3]):
                    b_mac = ap.get("bssid", "")
                    ch = ap.get("channel", "")
                    pwr = ap.get("power", "-99")
                    try:
                        pwr_i = int(pwr)
                        pwr_str = "|||||" if pwr_i > -60 else "|||" if pwr_i > -80 else "|"
                        pwr_col = GREEN if pwr_i > -60 else YELLOW if pwr_i > -80 else RED
                        pwr_disp = f"{pwr_col}{pwr_str:<5}{RESET}"
                    except:
                        pwr_disp = "     "
                    enc = ap.get("privacy", "Open")[:10]
                    essid = ap.get("essid", "")[:cols - 45]
                    buf.draw_ansi_str(table_y + 2 + idx, 2, f"{b_mac:<18} {ch:<4} {pwr_disp} {enc:<10} {essid}", max_x=cols - 1)
                
                # Header Station
                buf.draw_ansi_str(table_y + ap_h + 1, 2, f"{BOLD}{CYAN}{'STATION':<18} {'Pwr':<5} {'Pkts':<6} {'BSSID'}{RESET}", max_x=cols - 1)
                for idx, s in enumerate(self._stations[:sta_h - 3]):
                    s_mac = s.get("station_mac", "")
                    pwr = s.get("power", "-99")
                    try:
                        pwr_i = int(pwr)
                        pwr_str = "|||||" if pwr_i > -60 else "|||" if pwr_i > -80 else "|"
                        pwr_col = GREEN if pwr_i > -60 else YELLOW if pwr_i > -80 else RED
                        pwr_disp = f"{pwr_col}{pwr_str:<5}{RESET}"
                    except:
                        pwr_disp = "     "
                    pkts = s.get("packets", "0")
                    b_mac = s.get("bssid", "unassociated")[:cols - 36]
                    buf.draw_ansi_str(table_y + ap_h + 2 + idx, 2, f"{s_mac:<18} {pwr_disp} {pkts:<6} {b_mac}", max_x=cols - 1)

            # ----------------------------------------------------
            # PANE 7: SYSTEM CHATTER BOX (Bottom)
            # ----------------------------------------------------
            y_chat = lines - chatter_height
            buf.draw_box(y_chat, 0, chatter_height, cols, title="System Chatter", border_style=PINK)
            
            chatter_list = state.get("recent_captures") or state.get("chatter_log") or []
            visible_lines = chatter_height - 2
            
            lines_to_draw = []
            for item in chatter_list:
                if isinstance(item, dict):
                    t = item.get("timestamp", "")
                    m = item.get("message", "").strip()
                    lines_to_draw.append(f"[{t}] {m}" if t else m)
                elif isinstance(item, str):
                    lines_to_draw.append(item.strip())
            
            recent_chatter = lines_to_draw[-visible_lines:] if lines_to_draw else []
            pad = max(0, visible_lines - len(recent_chatter))
            
            for idx, raw_line in enumerate(recent_chatter):
                key = self._strip_ansi(raw_line)
                color = self._message_colors.get(key) or CHATTER_PALETTE[hash(key) % len(CHATTER_PALETTE)]
                self._message_colors[key] = color
                rendered_line = f"{color}{raw_line}{RESET}"
                buf.draw_ansi_str(y_chat + 1 + pad + idx, 2, rendered_line, max_x=cols - 1)

            # Write buffer directly to stdout
            sys.__stdout__.write("\033[H" + buf.render_to_string())
            sys.__stdout__.flush()

            self._last_state = state.copy()
            self._last_draw_time = time.time()

        except Exception as e:
            _LOG.error("redesigned _do_render failed: %s", e)

    def set_agent(self, agent):
        """Link Agent instance to resolve single-source-of-truth scoreboards."""
        self._agent = agent

    async def draw(self, state: Dict[str, Any]):
        if not self._enabled:
            return
        async with self._draw_lock:
            now = time.time()
            if not self._should_render(state, now):
                return
            try:
                self._do_render(state)
            except Exception as e:
                _LOG.error("draw failed: %s", e)

    def render(self, state: Dict[str, Any]):
        if not self._enabled:
            return
        try:
            now = time.time()
            if not self._should_render(state, now):
                return
            self._do_render(state)
        except Exception as e:
            _LOG.error("render failed: %s", e)

    def _update_status(self, state: Dict[str, Any], current_time: float):
        """Update current status with minimum display time logic."""
        new_status = (state.get("status") or "").strip()
        default_status = "Monitoring signals..."
        
        if not new_status:
            if (self._current_status != default_status and 
                current_time - self._status_start_time < self._min_status_display_time):
                return
            self._current_status = default_status
            self._status_start_time = current_time
        else:
            if new_status != self._current_status:
                self._current_status = new_status
                self._status_start_time = current_time
                _LOG.debug("Status changed to: %s", new_status)

    def update_table(self, aps: List[Dict[str, Any]], stations: Optional[List[Dict[str, Any]]] = None):
        def get_power_val(item):
            pwr = item.get("power", -9999)
            try:
                return int(pwr)
            except (ValueError, TypeError):
                return -9999

        def get_packets_val(item):
            pkts = item.get("packets", 0)
            try:
                return int(pkts)
            except (ValueError, TypeError):
                return 0

        try:
            aps_sorted = sorted(
                aps or [],
                key=lambda a: (get_power_val(a), self._parse_last_seen(a.get("last_seen", ""))),
                reverse=True,
            )
        except Exception as e:
            _LOG.warning("AP sorting failed: %s", e)
            aps_sorted = aps or []
        try:
            stations_sorted = sorted(
                stations or [],
                key=lambda s: (get_power_val(s), get_packets_val(s)),
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

    # ---- ANSI-aware helpers ----
    _ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def _strip_ansi(self, s: str) -> str:
        return self._ansi_re.sub("", s) if s is not None else ""

    def _visible_len(self, s: str) -> int:
        return len(self._strip_ansi(s))

    def _pad(self, s: str, width: int, align: str = "left") -> str:
        if s is None:
            s = ""
        plain = self._strip_ansi(s)
        if len(plain) > width:
            visible = 0
            i = 0
            while i < len(s) and visible < width:
                m = self._ansi_re.match(s, i)
                if m:
                    i = m.end()
                else:
                    visible += 1
                    i += 1
            return s[:i] + RESET
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
        if width is None:
            cols, _ = self._term_size()
            width = max(60, cols - 2)
        return self._pad(text or "", width, align=align)

    # ---- State change detection ----
    def _state_changed(self, prev: Dict[str, Any], new: Dict[str, Any]) -> bool:
        if not prev:
            return True
        important_fields = [
            "face", "status", "agent_mood", "mood",
            "aps", "aps_max_seen", "pwnd", "mode", "uptime"
        ]
        for field in important_fields:
            if prev.get(field) != new.get(field):
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
        if not s or s == "--":
            return 0.0
        s = str(s).strip()
        if ":" in s and "-" not in s and "T" not in s:
            try:
                parts = s.split(":")
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    now = datetime.now()
                    parsed_time = now.replace(hour=hours, minute=minutes, second=seconds, microsecond=0)
                    time_diff = (parsed_time - now).total_seconds()
                    if time_diff > 6 * 3600:
                        parsed_time = parsed_time - timedelta(days=1)
                    elif time_diff < -18 * 3600:
                        parsed_time = parsed_time + timedelta(days=1)
                    return parsed_time.timestamp()
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
                    time_diff = (dt - now).total_seconds()
                    if time_diff > 6 * 3600:
                        dt = dt - timedelta(days=1)
                    elif time_diff < -18 * 3600:
                        dt = dt + timedelta(days=1)
                return dt.timestamp()
            except ValueError:
                continue
        return 0.0

    def _format_timestamp(self, timestamp: float, default: str = "--") -> str:
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
        explicit_face = state.get("face")
        if explicit_face:
            return explicit_face
        mood = None
        if "agent_mood" in state and state["agent_mood"]:
            mood = state["agent_mood"]
        elif "mood" in state and state["mood"]:
            mood = state["mood"]
        if mood:
            try:
                mood_str = str(mood).lower()
                self._current_mood_from_state = mood_str
                return faces.get_face(mood_str)
            except Exception:
                pass
        try:
            return faces.get_face(self._current_mood_from_state)
        except Exception:
            pass
        return faces.get_face("neutral")

    def _render_header(self, state: Dict[str, Any]):
        """Backward compatibility stub for tests."""
        iface = state.get("interface", "wlan1")
        model = state.get("interface_model", "")
        iface_str = f"{iface} [{model}]" if model else iface
        self._out.write(f"[{iface_str}]")

    def _render_tables(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]):
        """Backward compatibility stub for tests."""
        # Top header matching test requirements
        self._out.write("── Access Points ──\n")
        for ap in aps:
            bssid = ap.get("bssid", "")
            essid = ap.get("essid", "")
            self._out.write(f"{bssid} | {essid}\n")
        for s in stations:
            mac = s.get("station_mac", "")
            self._out.write(f"{mac}\n")

    def force_redraw(self):
        try:
            self._do_render(self._last_state or {})
        except Exception as e:
            _LOG.error("force_redraw failed: %s", e)

    def show_goodbye(self):
        """Show a clean exit message."""
        try:
            self.clear()
            sys.__stdout__.write("\033[?25h")  # Ensure cursor is shown on exit
            sys.__stdout__.flush()
            cols, rows = self._term_size()
            msg = " Kaiagotchi Shutdown Complete "
            sub = " See you next time! "
            padding = (rows // 2) - 2
            self._out.write("\n" * padding)
            line1 = self._make_line(msg, cols, align="center").strip()
            line2 = self._make_line(sub, cols, align="center").strip()
            self._out.write(f"{BOLD}{CYAN}{line1}{RESET}\n")
            self._out.write(f"{GRAY}{line2}{RESET}\n")
            self._out.write("\n" * 2)
            self._out.flush()
        except Exception:
            pass