from __future__ import annotations
import asyncio
import curses
import logging
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from kaiagotchi.ui import faces

_LOG = logging.getLogger("kaiagotchi.ui.terminal_display")

# curses color pair IDs
_CP_GREEN, _CP_YELLOW, _CP_RED = 1, 2, 3
_CP_CYAN, _CP_MAGENTA, _CP_WHITE, _CP_GRAY = 4, 5, 6, 7


class TerminalDisplay:
    """Curses-based btop-style terminal dashboard for Kaiagotchi.

    Architecture:
    - A background daemon thread runs curses.wrapper(_curses_main)
    - View pushes state via render() which updates a thread-safe snapshot
    - The curses thread draws at ~4 fps from the snapshot
    - Q key sets stop_event, propagated to cli for clean shutdown
    """

    _instance: Optional[TerminalDisplay] = None

    def __new__(cls, *a, **kw):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._config = config or {}
        self._enabled = True
        self._start_time = time.time()

        # Thread-safe state shared between async View and curses thread
        self._state_provider = None
        self._snapshot: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._ap_table: List[Dict[str, Any]] = []
        self._stations: List[Dict[str, Any]] = []

        # Curses thread management
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False

        # Display limits
        self._max_visible_aps = int(self._config.get("max_visible_aps", 15))
        self._max_visible_stations = int(self._config.get("max_visible_stations", 10))
        self._max_visible_chatter = int(self._config.get("max_visible_chatter", 6))

        # Status tracking
        self._current_status = "Monitoring signals..."
        self._status_start_time = 0.0
        self._min_status_display_time = 3.0
        self._current_mood_from_state = "neutral"
        self._agent = None
        self._last_state: Dict[str, Any] = {}
        self._last_draw_time = 0.0

        # Backward-compat stdout handle (for test stubs and splash)
        self._out = sys.__stdout__

        # Enter alt screen for splash (curses.wrapper will manage its own later)
        try:
            self._out.write("\033[?1049h\033[?25l")
            self._out.flush()
        except Exception:
            pass
        import atexit
        atexit.register(self._atexit_cleanup)
        _LOG.debug("TerminalDisplay initialized (curses backend)")

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self):
        """Launch the curses rendering thread."""
        if self._started or self._stop_event.is_set():
            return
        self._started = True
        self._thread = threading.Thread(target=self._run_curses, name="curses-display", daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the curses thread to exit and wait."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._started = False

    @property
    def should_quit(self) -> bool:
        return self._stop_event.is_set()

    def _atexit_cleanup(self):
        try:
            sys.__stdout__.write("\033[?25h\033[?1049l")
            sys.__stdout__.flush()
        except Exception:
            pass

    def _run_curses(self):
        try:
            curses.wrapper(self._curses_main)
        except Exception:
            _LOG.exception("Curses thread crashed")

    def _curses_main(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(250)
        self._init_colors()

        while not self._stop_event.is_set():
            try:
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    self._stop_event.set()
                    break

                snap = self._take_snapshot()
                self._draw_frame(stdscr, snap)
            except curses.error:
                pass
            except Exception:
                _LOG.debug("Curses frame error", exc_info=True)

    def _take_snapshot(self) -> Dict[str, Any]:
        """Fetch the latest state snapshot from the registered state provider or local fallback."""
        if self._state_provider:
            try:
                snap = self._state_provider()
            except Exception:
                _LOG.debug("Failed to call state provider", exc_info=True)
                snap = {}
        else:
            with self._lock:
                snap = dict(self._snapshot)

        # Ensure _aps and _stas are present (sorted & limited)
        if "_aps" not in snap:
            aps = snap.get("aps_list")
            if aps is not None:
                def pwr(item):
                    try:
                        return int(item.get("power", -9999))
                    except (ValueError, TypeError):
                        return -9999
                try:
                    a = sorted(aps, key=lambda a: (pwr(a), self._parse_last_seen(a.get("last_seen", ""))), reverse=True)
                except Exception:
                    a = aps
                snap["_aps"] = a[:self._max_visible_aps]
            else:
                with self._lock:
                    snap["_aps"] = list(self._ap_table)

        if "_stas" not in snap:
            stas = snap.get("stations_list")
            if stas is not None:
                def pwr(item):
                    try:
                        return int(item.get("power", -9999))
                    except (ValueError, TypeError):
                        return -9999
                try:
                    s = sorted(stas, key=lambda s: (pwr(s), int(s.get("packets", 0) or 0)), reverse=True)
                except Exception:
                    s = stas
                snap["_stas"] = s[:self._max_visible_stations]
            else:
                with self._lock:
                    snap["_stas"] = list(self._stations)

        if "_status" not in snap:
            snap["_status"] = snap.get("status") or self._current_status

        return snap

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        for pid, fg in [(_CP_GREEN, curses.COLOR_GREEN), (_CP_YELLOW, curses.COLOR_YELLOW),
                        (_CP_RED, curses.COLOR_RED), (_CP_CYAN, curses.COLOR_CYAN),
                        (_CP_MAGENTA, curses.COLOR_MAGENTA), (_CP_WHITE, curses.COLOR_WHITE)]:
            curses.init_pair(pid, fg, -1)
        try:
            curses.init_pair(_CP_GRAY, 8, -1)
        except curses.error:
            curses.init_pair(_CP_GRAY, curses.COLOR_WHITE, -1)

    # ── Drawing primitives ────────────────────────────────────

    def _put(self, scr, y, x, text, attr=0):
        h, w = scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        try:
            scr.addnstr(y, x, text, max(0, w - x), attr)
        except curses.error:
            pass

    def _box(self, scr, y, x, h, w, title="", attr=0):
        if h < 2 or w < 2:
            return
        self._put(scr, y, x, "╭" + "─" * (w - 2) + "╮", attr)
        self._put(scr, y + h - 1, x, "╰" + "─" * (w - 2) + "╯", attr)
        for cy in range(y + 1, y + h - 1):
            self._put(scr, cy, x, "│", attr)
            self._put(scr, cy, x + w - 1, "│", attr)
        if title:
            t = f" {title} "
            tx = x + max(1, (w - len(t) - 2) // 2)
            self._put(scr, y, tx, f"╮{t}╭", attr)

    # ── Frame renderer ────────────────────────────────────────

    def _draw_frame(self, scr, snap: Dict[str, Any]):
        scr.erase()
        H, W = scr.getmaxyx()
        if W < 60 or H < 18:
            self._put(scr, 0, 0, "Terminal too small! Please resize.", curses.A_BOLD)
            scr.refresh()
            return

        cp = curses.color_pair
        B = curses.A_BOLD
        uptime = snap.get("uptime", "00:00:00")
        mood = str(snap.get("agent_mood") or snap.get("mood") or "neutral").capitalize()
        face = self._get_face(snap)
        status = snap.get("_status", self._current_status)
        mode = snap.get("mode", "AUTO")
        iface = snap.get("interface", "wlan1")
        im = snap.get("interface_model", "")
        iface_str = f"{iface} [{im}]" if im else iface
        aps = snap.get("_aps", [])
        stas = snap.get("_stas", [])

        # ── PANE 1: BOT STATUS (top-left 50%) ──
        wb = W // 2
        self._box(scr, 0, 0, 8, wb, "BOT STATUS", cp(_CP_MAGENTA))
        labels = [("Face:", face, _CP_MAGENTA), ("Mood:", mood, _CP_WHITE),
                  ("Uptime:", uptime, _CP_WHITE), ("Card:", f"• {iface_str}", _CP_YELLOW)]
        for i, (lbl, val, c) in enumerate(labels, 1):
            if i == 3:  # Status row before Uptime
                slab = "● SNIFFING" if mode == "AUTO" else "○ MANUAL"
                sc = _CP_GREEN if mode == "AUTO" else _CP_YELLOW
                self._put(scr, 3, 2, f"Status:  ", cp(_CP_CYAN))
                self._put(scr, 3, 11, slab, cp(sc))
                self._put(scr, i + 1, 2, f"{lbl:<9}", cp(_CP_CYAN))
                self._put(scr, i + 1, 11, val, cp(c))
            elif i >= 4:
                self._put(scr, i + 1, 2, f"{lbl:<9}", cp(_CP_CYAN))
                self._put(scr, i + 1, 11, val, cp(c))
            else:
                self._put(scr, i, 2, f"{lbl:<9}", cp(_CP_CYAN))
                self._put(scr, i, 11, val, cp(c))
        self._put(scr, 6, 2, f"« {status[:wb - 8]} »", cp(_CP_MAGENTA))

        # ── PANE 2: SCOREBOARD (top-right 50%) ──
        xs = wb
        ws = W - xs
        self._box(scr, 0, xs, 8, ws, "SCOREBOARD", cp(_CP_GREEN))
        ssids, hs, comp, pmk = self._get_scoreboard(snap)
        for i, (lbl, val, c) in enumerate([
            ("Unique SSIDs Seen:", ssids, _CP_GREEN), ("Total Handshakes:", hs, _CP_YELLOW),
            ("Complete WPA:", comp, _CP_GREEN), ("Captured PMKIDs:", pmk, _CP_GREEN),
        ], 1):
            self._put(scr, i, xs + 2, f"{lbl:<20}", cp(_CP_CYAN))
            self._put(scr, i, xs + 22, str(val), cp(c) | B)

        # ── PANE 3: SPECTRUM (full width, 6 rows) ──
        self._box(scr, 8, 0, 6, W, "SPECTRUM CHANNEL DISTRIBUTION", cp(_CP_YELLOW))
        self._draw_spectrum(scr, 9, W, aps)

        # ── PANES 4+5: AP + STATION TABLES ──
        chat_h = 6
        ty = 14
        th = max(3, H - ty - chat_h)

        if W >= 100:
            wap = int(W * 0.6)
            wst = W - wap
            self._box(scr, ty, 0, th, wap, "Access Points", cp(_CP_YELLOW))
            self._box(scr, ty, wap, th, wst, "Stations", cp(_CP_CYAN))
            self._draw_ap_rows(scr, ty + 1, 2, wap - 2, th - 3, aps)
            self._draw_sta_rows(scr, ty + 1, wap + 2, wst - 2, th - 3, stas)
        else:
            ah = th // 2 + 1
            sh = th - ah
            self._box(scr, ty, 0, ah, W, "Access Points", cp(_CP_YELLOW))
            self._box(scr, ty + ah, 0, sh, W, "Stations", cp(_CP_CYAN))
            self._draw_ap_rows(scr, ty + 1, 2, W - 2, ah - 3, aps)
            self._draw_sta_rows(scr, ty + ah + 1, 2, W - 2, sh - 3, stas)

        # ── PANE 6: SYSTEM CHATTER ──
        yc = H - chat_h
        self._box(scr, yc, 0, chat_h, W, "System Chatter", cp(_CP_MAGENTA))
        self._draw_chatter(scr, yc + 1, W, chat_h - 2, snap)

        scr.refresh()

    # ── Sub-pane renderers ────────────────────────────────────

    def _draw_spectrum(self, scr, y0, W, aps):
        cp = curses.color_pair
        ch_map: Dict[int, int] = {}
        for ap in aps:
            try:
                ch_map[int(ap["channel"])] = ch_map.get(int(ap["channel"]), 0) + 1
            except (KeyError, ValueError, TypeError):
                pass
        mx = max(ch_map.values()) if ch_map else 1
        for row, grp in enumerate([[1, 5, 9], [2, 6, 10], [3, 7, 11], [4, 8, 12]]):
            parts = []
            for ch in grp:
                cnt = ch_map.get(ch, 0)
                f = min(6, int(round(cnt / max(1, mx) * 6)))
                parts.append(f"Ch {ch:02d} [{'█' * f}{'░' * (6 - f)}] {cnt:2d} APs")
            line = "   │   ".join(parts)
            self._put(scr, y0 + row, max(2, (W - len(line)) // 2), line, cp(_CP_CYAN))

    def _pwr_display(self, pwr_raw):
        try:
            p = int(pwr_raw)
            s = "|||||" if p > -60 else "|||" if p > -80 else "|"
            c = _CP_GREEN if p > -60 else _CP_YELLOW if p > -80 else _CP_RED
            return f"{s:<5}", c
        except (ValueError, TypeError):
            return "?    ", _CP_GRAY

    def _draw_ap_rows(self, scr, y, x, mw, mr, aps):
        cp = curses.color_pair
        self._put(scr, y, x, f"{'BSSID':<18} {'Ch':<4} {'Pwr':<5} {'Encryption':<10} ESSID",
                  cp(_CP_YELLOW) | curses.A_BOLD)
        for i, ap in enumerate(aps[:mr]):
            ry = y + 1 + i
            b = ap.get("bssid", "")
            ch = ap.get("channel", "")
            ps, pc = self._pwr_display(ap.get("power", "-99"))
            enc = (ap.get("privacy") or "Open").strip()[:10]
            essid = (ap.get("essid") or "")[:max(0, mw - 40)]
            self._put(scr, ry, x, f"{b:<18} {ch:<4} ", cp(_CP_WHITE))
            self._put(scr, ry, x + 23, ps, cp(pc))
            self._put(scr, ry, x + 29, f"{enc:<10} {essid}", cp(_CP_WHITE))

    def _draw_sta_rows(self, scr, y, x, mw, mr, stas):
        cp = curses.color_pair
        self._put(scr, y, x, f"{'STATION':<18} {'Pwr':<5} {'Pkts':<6} BSSID",
                  cp(_CP_CYAN) | curses.A_BOLD)
        for i, s in enumerate(stas[:mr]):
            ry = y + 1 + i
            mac = s.get("station_mac", "")
            ps, pc = self._pwr_display(s.get("power", "-99"))
            pkts = str(s.get("packets", "0"))
            bss = (s.get("bssid") or "unassociated")[:max(0, mw - 32)]
            self._put(scr, ry, x, f"{mac:<18} ", cp(_CP_WHITE))
            self._put(scr, ry, x + 19, ps, cp(pc))
            self._put(scr, ry, x + 25, f"{pkts:<6} {bss}", cp(_CP_WHITE))

    def _draw_chatter(self, scr, y0, W, max_lines, snap):
        cp = curses.color_pair
        palette = [_CP_CYAN, _CP_YELLOW, _CP_GREEN, _CP_RED, _CP_MAGENTA]
        raw = snap.get("recent_captures") or snap.get("chatter_log") or []
        lines = []
        for item in raw:
            if isinstance(item, dict):
                t, m = item.get("timestamp", ""), (item.get("message") or "").strip()
                lines.append(f"[{t}] {m}" if t else m)
            elif isinstance(item, str):
                lines.append(self._strip_ansi(item.strip()))
        vis = lines[-max_lines:] if lines else []
        pad = max(0, max_lines - len(vis))
        for i, ln in enumerate(vis):
            self._put(scr, y0 + pad + i, 2, ln[:W - 4], cp(palette[hash(ln) % len(palette)]))

    # ── Public API (called from View) ─────────────────────────

    def register_state_provider(self, provider_callable):
        self._state_provider = provider_callable

    def render(self, state: Dict[str, Any]):
        """Update the internal snapshot. The curses thread draws from it."""
        if not self._enabled:
            return
        self._update_status(state, time.time())
        with self._lock:
            self._snapshot = dict(state)
            self._snapshot["_status"] = self._current_status
        self._last_state = dict(state)
        self._last_draw_time = time.time()
        if not self._started:
            self.start()

    async def draw(self, state: Dict[str, Any]):
        """Async compatibility wrapper."""
        self.render(state)

    def update_table(self, aps: List[Dict[str, Any]], stations: Optional[List[Dict[str, Any]]] = None):
        def pwr(item):
            try:
                return int(item.get("power", -9999))
            except (ValueError, TypeError):
                return -9999

        try:
            a = sorted(aps or [], key=lambda a: (pwr(a), self._parse_last_seen(a.get("last_seen", ""))), reverse=True)
        except Exception:
            a = aps or []
        try:
            s = sorted(stations or [], key=lambda s: (pwr(s), int(s.get("packets", 0) or 0)), reverse=True)
        except Exception:
            s = stations or []
        with self._lock:
            self._ap_table = a[: self._max_visible_aps]
            self._stations = s[: self._max_visible_stations]

    def set_agent(self, agent):
        self._agent = agent

    def clear(self):
        pass  # curses handles clearing

    def force_redraw(self):
        pass  # curses thread redraws automatically

    def show_goodbye(self):
        self.stop()
        try:
            out = sys.__stdout__
            w, h = shutil.get_terminal_size((80, 24))
            out.write("\033[?25h\033[2J\033[H")
            out.write("\n" * (h // 2 - 2))
            out.write(f"\033[1m\033[38;5;51m{' Kaiagotchi Shutdown Complete ':^{w}}\033[0m\n")
            out.write(f"\033[38;5;245m{' See you next time! ':^{w}}\033[0m\n\n")
            out.flush()
        except Exception:
            pass

    # ── Internal helpers ──────────────────────────────────────

    def _get_scoreboard(self, snap):
        ssids = hs = comp = pmk = 0
        try:
            if self._agent and hasattr(self._agent, "persistent_network"):
                pn = self._agent.persistent_network
                if pn and hasattr(pn, "_data"):
                    ssids = len(pn._data.get("bssids", {}))
                    for r in pn._data.get("pcaps", {}).values():
                        for c in (r.get("analysis") or []):
                            hs += 1
                            if c.get("handshake_complete"):
                                comp += 1
                            if c.get("pmkid"):
                                pmk += 1
        except Exception:
            pass
        return ssids or len(snap.get("_aps", [])), hs, comp, pmk

    def _get_face(self, state: Dict[str, Any]) -> str:
        f = state.get("face")
        if f:
            return f
        mood = state.get("agent_mood") or state.get("mood")
        if mood:
            try:
                ms = str(mood).lower()
                self._current_mood_from_state = ms
                return faces.get_face(ms)
            except Exception:
                pass
        try:
            return faces.get_face(self._current_mood_from_state)
        except Exception:
            return faces.get_face("neutral")

    def _update_status(self, state: Dict[str, Any], now: float):
        new = (state.get("status") or "").strip()
        if not new:
            if (self._current_status != "Monitoring signals..." and
                    now - self._status_start_time < self._min_status_display_time):
                return
            _LOG.debug("Status changed to: Monitoring signals...")
            self._current_status = "Monitoring signals..."
            self._status_start_time = now
        elif new != self._current_status:
            _LOG.debug(f"Status changed to: {new}")
            self._current_status = new
            self._status_start_time = now

    _ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    def _strip_ansi(self, s: str) -> str:
        return self._ansi_re.sub("", s) if s else ""

    def _parse_last_seen(self, s: str) -> float:
        if not s or s == "--":
            return 0.0
        try:
            parts = str(s).strip().split(":")
            if len(parts) == 3 and "-" not in s and "T" not in s:
                h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
                now = datetime.now()
                dt = now.replace(hour=h, minute=m, second=sec, microsecond=0)
                d = (dt - now).total_seconds()
                if d > 21600:
                    dt -= timedelta(days=1)
                elif d < -64800:
                    dt += timedelta(days=1)
                return dt.timestamp()
        except Exception:
            pass
        return 0.0

    # ── Backward compat stubs for tests ──────────────────────

    def _render_header(self, state: Dict[str, Any]):
        iface = state.get("interface", "wlan1")
        model = state.get("interface_model", "")
        self._out.write(f"[{iface} [{model}]]" if model else f"[{iface}]")

    def _render_tables(self, aps: List[Dict[str, Any]], stations: List[Dict[str, Any]]):
        self._out.write("── Access Points ──\n")
        for ap in aps:
            self._out.write(f"{ap.get('bssid', '')} | {ap.get('essid', '')}\n")
        for s in stations:
            self._out.write(f"{s.get('station_mac', '')}\n")

    def _should_render(self, state, now):
        return True  # curses thread handles its own timing