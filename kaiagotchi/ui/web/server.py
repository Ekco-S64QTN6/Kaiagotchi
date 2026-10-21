"""
Kaiagotchi Web UI Server — Async aiohttp HTTP + WebSocket bridge.

Serves the Cyber-Deck HUD frontend and streams real-time telemetry
from the Kaiagotchi core engine via WebSocket at configurable Hz.

Architecture:
- Runs as a daemon thread alongside Kaiagotchi's engine (or standalone for UI dev).
- Consumes View.get_snapshot_dict() data pipeline.
- Broadcasts JSON state snapshots to all connected browser clients.
- Serves static assets from kaiagotchi/ui/web/static/.
- Port defaults to 8080, configurable via config.toml [web] section.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

_LOG = logging.getLogger("kaiagotchi.ui.web.server")
_STATIC_DIR = Path(__file__).resolve().parent / "static"


_MOCK_APS = [
    ("EC:1A:59:2B:3C:4D", "Cyberdyne_Guest", 11, -44, "WPA2"),
    ("88:9F:12:45:67:89", "NovaCorp_Office", 6, -51, "WPA3"),
    ("70:5A:3B:7C:9D:1E", "Downtown_FreeWiFi", 1, -58, "WPA2"),
    ("A4:B8:7F:22:11:33", "Hotel_Nexus_5G", 36, -63, "WPA2"),
    ("3C:5E:7A:9B:BD:1F", "IoT_Sensors", 11, -67, "WPA3"),
    ("D8:3A:7C:1E:2B:4F", "Legacy_Device_Ntwk", 1, -74, "WPA2"),
    ("00:1A:2B:3C:4D:5E", "HomeNet_5G", 44, -79, "WPA3"),
    ("02:11:22:33:44:55", "CoffeeShop", 6, -84, "WPA2"),
    ("04:6F:8A:1B:2C:3D", "Linksys_2G", 11, -88, "WPA2"),
]

_MOCK_STATIONS = [
    ("10:9A:BC:DE:F0:12", -38, 11, "12K/8K", "CONNECTED"),
    ("02:11:22:33:44:55", -51, 6, "4K/2K", "CONNECTED"),
    ("04:6F:8A:1B:2C:3D", -63, 1, "1K/872", "CONNECTED"),
    ("08:12:34:56:78:9A", -72, 36, "512/341", "HANDSHAKE"),
    ("0C:4D:6E:8F:90:AB", -81, 44, "212/164", "PROBING"),
    ("12:34:56:78:9A:BC", -91, 157, "98/77", "DISCONNECTED"),
]

# Passive-observation phrasing only.
_MOCK_LINES = [
    ("info", "Scan cycle complete ({aps} APs)"),
    ("info", "New AP observed: CoffeeShop (CH 6)"),
    ("warn", "Signal fluctuation on CH 11 (-42 -> -58)"),
    ("info", "Probe request burst observed"),
    ("auth", "Re-association observed: 04:6F:8A:1B:2C:3D"),
    ("info", "Monitoring mode active"),
    ("info", "Beacon interval drift on NovaCorp_Office"),
    ("sync", "Channel survey synced"),
]

_MOCK_MOODS = ["awake", "neutral", "curious", "happy", "confident", "bored", "sleepy",
               "sad", "frustrated", "angry", "broken", "debug", "neutral"]


class _MockFeed:
    """Stateful simulated telemetry for UI development (no radio required)."""

    def __init__(self) -> None:
        self.start = time.time()
        self.last = self.start
        self.totals = [0.0, 0.0]
        self.chatter: list[dict[str, str]] = []
        self.next_line = 0.0
        self.line_idx = 0
        self.pwnd = 2

    def _say(self, kind: str, text: str) -> None:
        self.chatter.append({"time": time.strftime("%H:%M:%S"), "type": kind, "text": text})
        del self.chatter[:-40]

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        el = now - self.start
        dt, self.last = now - self.last, now

        if el >= self.next_line:
            kind, text = _MOCK_LINES[self.line_idx % len(_MOCK_LINES)]
            self._say(kind, text.format(aps=len(_MOCK_APS)))
            self.line_idx += 1
            self.next_line = el + random.uniform(3.0, 6.0)
        if int(el) > 0 and int(el) % 50 == 0 and int(el) // 50 + 2 != self.pwnd:
            self.pwnd = int(el) // 50 + 2
            self._say("eapol", "Handshake captured (passive): 08:12:34:56:78:9A")

        aps = []
        for i, (bssid, ssid, ch, pwr, enc) in enumerate(_MOCK_APS):
            jitter = math.sin(el * (0.4 + i * 0.07) + i) * 3 + random.uniform(-1, 1)
            aps.append({"bssid": bssid, "ssid": ssid, "ch": ch, "pwr": int(pwr + jitter), "enc": enc})

        t = el * 1.3
        rssi = -50 + math.sin(t) * 9 + math.sin(t * 2.7) * 4 + random.uniform(-2, 2)
        rates = {
            "probe_req": {"rx": int(310 + 90 * math.sin(t * 0.7) + random.uniform(-25, 25)), "tx": int(12 + random.uniform(0, 6))},
            "beacon": {"rx": int(430 + 30 * math.sin(t * 0.3) + random.uniform(-10, 10)), "tx": 0},
            "auth": {"rx": int(24 + 10 * math.sin(t * 1.1) + random.uniform(0, 6)), "tx": int(random.uniform(0, 4))},
            "eapol": {"rx": int(max(0.0, 2 + 2 * math.sin(t * 0.5))), "tx": 0},
        }
        rx = sum(r["rx"] for r in rates.values())
        tx = sum(r["tx"] for r in rates.values())
        self.totals[0] += rx * dt
        self.totals[1] += tx * dt

        mood = _MOCK_MOODS[int(el // 18) % len(_MOCK_MOODS)]
        hh, rem = divmod(int(el), 3600)
        return {
            "timestamp": now,
            "uptime": f"{hh:02d}:{rem // 60:02d}:{rem % 60:02d}",
            "status": self.chatter[-1]["text"] if self.chatter else "Monitoring signals...",
            "mood": mood,
            "mode": "MONITORING",
            "aps_count": len(aps),
            "aps_total": 15,
            "pwnd_count": self.pwnd,
            "current_channel": 11,
            "current_rssi": round(rssi, 1),
            "packet_breakdown": rates,
            "packet_rate": rx + tx,
            "total_packets": {"rx": int(self.totals[0]), "tx": int(self.totals[1])},
            "aps": aps,
            "stations": [
                {"mac": m, "pwr": p, "ch": c, "tx_rx": tr, "status": st}
                for m, p, c, tr, st in _MOCK_STATIONS
            ],
            "chatter": list(self.chatter),
        }


_MOCK = _MockFeed()


def _generate_mock_snapshot() -> dict[str, Any]:
    """Simulated cyber-deck telemetry for standalone preview."""
    return _MOCK.snapshot()


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _dbm(value: Any) -> int | None:
    """airodump power as int dBm; -1 / 0 / junk mean 'not reported'."""
    n = _to_int(value)
    return n if n is not None and n < -1 else None


class WebServer:
    """Async aiohttp HTTP + WebSocket server for the Cyber-Deck HUD.

    Usage:
        server = WebServer(config, state_provider=view.get_snapshot_dict)
        server.start()  # launches in a daemon thread
        ...
        server.stop()
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        state_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self._config = config or {}
        web_cfg = self._config.get("web", {})
        # The dashboard exposes live SSIDs, station MACs, and runtime telemetry.
        # Keep it local unless the operator explicitly configures a LAN bind.
        self._host = str(web_cfg.get("host", "127.0.0.1"))
        self._port = int(web_cfg.get("port", 8080))
        self._hz = float(web_cfg.get("update_hz", 10.0))  # 10 Hz broadcast
        self._state_provider = state_provider

        self._clients: set[web.WebSocketResponse] = set()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        _LOG.info(
            "WebServer initialized (host=%s, port=%d, hz=%.1f)",
            self._host, self._port, self._hz,
        )

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Launch the server in a background daemon thread."""
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._run_server_thread,
            name="kaiagotchi-web",
            daemon=True,
        )
        self._thread.start()
        _LOG.info("WebServer thread started on %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Signal the server to shut down cleanly."""
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._started = False
        _LOG.info("WebServer stopped")

    def set_state_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        """Set or update the state provider callback."""
        self._state_provider = provider

    # ── Server Thread ─────────────────────────────────────────

    def _run_server_thread(self) -> None:
        """Entry point for the server daemon thread."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._serve())
        except Exception:
            _LOG.exception("WebServer thread encountered fatal error")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _cleanup(self) -> None:
        """Close active websockets and server runner."""
        for ws in list(self._clients):
            try:
                await ws.close(code=1000, message=b"Server shutdown")
            except Exception:
                pass
        self._clients.clear()

        if self._runner:
            await self._runner.cleanup()

    async def _serve(self) -> None:
        """Build and run the aiohttp application."""
        app = web.Application()

        # Routes
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/api/state", self._handle_api_state)

        # Serve static assets
        if _STATIC_DIR.exists():
            app.router.add_static("/static/", path=str(_STATIC_DIR), name="static")

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        _LOG.info(
            "Cyber-Deck HUD live at http://%s:%d",
            "localhost" if self._host == "0.0.0.0" else self._host,
            self._port,
        )

        # Start broadcast loop
        broadcast_task = asyncio.create_task(self._broadcast_loop())

        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
            await self._cleanup()

    # ── Request Handlers ──────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve index.html."""
        index_file = _STATIC_DIR / "index.html"
        if index_file.is_file():
            return web.FileResponse(index_file)
        return web.Response(
            text="<h1>Kaiagotchi Cyber-Deck HUD</h1><p>index.html not found in static directory.</p>",
            content_type="text/html",
            status=404,
        )

    async def _handle_api_state(self, request: web.Request) -> web.Response:
        """Return current snapshot JSON."""
        snap = self._get_latest_snapshot()
        return web.json_response(snap)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket telemetry connections."""
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)

        self._clients.add(ws)
        remote = request.remote
        _LOG.info("Cyber-Deck client connected: %s (total: %d)", remote, len(self._clients))

        # Send immediate initial state
        try:
            init_state = self._get_latest_snapshot()
            await ws.send_str(json.dumps(init_state, default=str))
        except Exception:
            pass

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        cmd = json.loads(msg.data)
                        action = cmd.get("action")
                        if action == "ping":
                            await ws.send_str(json.dumps({"action": "pong", "ts": time.time()}))
                        elif action == "request_state":
                            st = self._get_latest_snapshot()
                            await ws.send_str(json.dumps(st, default=str))
                    except Exception:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    _LOG.debug("WebSocket error with %s: %s", remote, ws.exception())
        finally:
            self._clients.discard(ws)
            _LOG.info("Cyber-Deck client disconnected: %s (remaining: %d)", remote, len(self._clients))

        return ws

    # ── Data Pipeline ─────────────────────────────────────────

    def _get_latest_snapshot(self) -> dict[str, Any]:
        """Fetch snapshot from state provider, or generate simulated data if none."""
        if self._state_provider:
            try:
                snap = self._state_provider()
                if snap:
                    return self._serialize_snapshot(snap)
            except Exception:
                _LOG.debug("State provider error", exc_info=True)

        return _generate_mock_snapshot()

    async def _broadcast_loop(self) -> None:
        """Continuously broadcast state snapshots to all connected clients."""
        interval = 1.0 / max(1.0, min(30.0, self._hz))
        while not self._stop_event.is_set():
            if self._clients:
                try:
                    payload = self._get_latest_snapshot()
                    message = json.dumps(payload, default=str)

                    dead = set()
                    for ws in list(self._clients):
                        if ws.closed:
                            dead.add(ws)
                            continue
                        try:
                            await ws.send_str(message)
                        except Exception:
                            dead.add(ws)
                    self._clients -= dead
                except Exception:
                    _LOG.debug("Broadcast error", exc_info=True)

            await asyncio.sleep(interval)

    def _serialize_snapshot(self, snap: dict[str, Any]) -> dict[str, Any]:
        """Transform the View snapshot into the wire payload.

        Only real values are emitted: anything the engine does not measure
        (per-type packet rates, totals) is sent as null so the UI shows '--'.
        """
        aps = []
        for ap in snap.get("aps_list") or []:
            if not isinstance(ap, dict):
                continue
            aps.append({
                "bssid": ap.get("bssid", ""),
                "ssid": ap.get("essid") or ap.get("ssid") or "<Hidden>",
                "ch": _to_int(ap.get("channel")),
                "pwr": _dbm(ap.get("power")),
                "enc": (ap.get("privacy") or ap.get("enc") or "--").strip(),
                "beacons": _to_int(ap.get("beacons")) or 0,
            })

        stations = []
        for sta in snap.get("stations_list") or []:
            if not isinstance(sta, dict):
                continue
            bssid = str(sta.get("bssid", ""))
            pkts = _to_int(sta.get("packets")) or 0
            stations.append({
                "mac": sta.get("station_mac") or sta.get("mac", ""),
                "bssid": bssid,
                "pwr": _dbm(sta.get("power")),
                "ch": _to_int(sta.get("channel")),
                "tx_rx": str(pkts) if pkts else "-",
                "status": "PROBING" if "not associated" in bssid.lower() else "CONNECTED",
            })

        chatter = []
        for entry in snap.get("chatter_log") or []:
            if isinstance(entry, dict):
                chatter.append({"time": entry.get("timestamp", ""), "type": entry.get("type", "info"),
                                "text": entry.get("message", "")})
            elif isinstance(entry, str):
                m = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$", entry)
                chatter.append({"time": m.group(1) if m else "", "type": "info", "text": m.group(2) if m else entry})

        net = snap.get("network") if isinstance(snap.get("network"), dict) else {}
        channel = _to_int(snap.get("channel")) or _to_int(net.get("current_channel"))
        on_channel = [a["pwr"] for a in aps if a["ch"] == channel and a["pwr"] is not None]

        mood = snap.get("agent_mood") or snap.get("mood") or "neutral"
        mood = str(getattr(mood, "value", mood)).lower()

        breakdown = snap.get("packet_breakdown")
        totals = snap.get("total_packets")
        return {
            "timestamp": time.time(),
            "uptime": snap.get("uptime", "00:00:00"),
            "status": snap.get("status", "Monitoring signals..."),
            "mood": mood,
            "mode": snap.get("mode", "MONITORING"),
            "aps_count": len(aps),
            "aps_total": snap.get("aps_max_seen", len(aps)),
            "pwnd_count": _to_int(snap.get("pwnd_count")) or 0,
            "current_channel": channel,
            "current_rssi": max(on_channel) if on_channel else None,
            "packet_breakdown": breakdown if isinstance(breakdown, dict) else None,
            "packet_rate": snap.get("packet_rate"),
            "total_packets": totals if isinstance(totals, dict) else None,
            "aps": aps,
            "stations": stations,
            "chatter": chatter[-50:],
        }


def main():
    """Run WebServer standalone for frontend development & live preview."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    srv = WebServer()
    srv.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
