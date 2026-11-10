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
- Non-loopback binds require token authentication; browser sessions use an
  HttpOnly, SameSite=Strict cookie for both HTTP telemetry and WebSockets.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import math
import os
import random
import re
import secrets
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psutil
from aiohttp import WSMsgType, web

_LOG = logging.getLogger("kaiagotchi.ui.web.server")
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _is_same_origin_request(request: web.Request, allowed_hosts: set[str] | None = None) -> bool:
    """Reject browser WebSocket requests initiated by a different origin.

    WebSocket clients outside a browser may omit Origin; browser clients always
    send it. For browser requests require the origin scheme/host/port to match
    the current request, preventing a hostile website from reading the
    unauthenticated local telemetry socket.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return True

    try:
        parsed = urlsplit(origin)
        current = urlsplit(f"{request.scheme}://{request.host}")
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return False

        scheme = parsed.scheme.lower()
        current_scheme = current.scheme.lower()
        if scheme != current_scheme:
            return False

        origin_host = (parsed.hostname or "").casefold().rstrip(".")
        if not origin_host:
            return False
        # Host/Origin equality by itself is vulnerable to DNS rebinding: a
        # hostile hostname can resolve to loopback and match its own Origin.
        if allowed_hosts is not None and origin_host not in allowed_hosts:
            return False

        origin_port = parsed.port or (443 if scheme == "https" else 80)
        current_port = current.port or (443 if current_scheme == "https" else 80)
        return (
            parsed.hostname is not None
            and current.hostname is not None
            and parsed.hostname.casefold() == current.hostname.casefold()
            and origin_port == current_port
        )
    except (ValueError, TypeError):
        return False


def _bind_host_is_loopback(host: str) -> bool:
    """Return whether a configured bind host is unambiguously loopback-only."""
    normalized = host.strip().strip("[]").rstrip(".").casefold()
    if normalized == "localhost":
        return True
    try:
        address = ipaddress.ip_address(normalized.split("%", 1)[0])
    except ValueError:
        # A hostname other than the literal localhost may resolve to a LAN IP.
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def _log_listener_started(host: str, port: int, authenticated: bool = False) -> None:
    """Log the bind address and explain the trust boundary for LAN listeners."""
    normalized_host = host.strip().lower()
    if not _bind_host_is_loopback(host):
        wildcard_bind = normalized_host in {"", "0.0.0.0", "::", "[::]"}
        if authenticated:
            if wildcard_bind:
                _LOG.warning(
                    "Cyber-Deck HUD is bound to all network interfaces (%s:%d) "
                    "with token authentication. HTTP is not encrypted; use a "
                    "TLS reverse proxy or a trusted private network.",
                    host or "*",
                    port,
                )
            else:
                _LOG.warning(
                    "Cyber-Deck HUD is bound to a non-loopback address (%s:%d) "
                    "with token authentication. HTTP is not encrypted; use a "
                    "trusted private network or VPN.",
                    host,
                    port,
                )
        elif wildcard_bind:
            _LOG.warning(
                "Cyber-Deck HUD is bound to all network interfaces (%s:%d). "
                "The telemetry UI has no authentication; expose it only on a trusted network.",
                host or "*",
                port,
            )
        else:
            _LOG.warning(
                "Cyber-Deck HUD is bound to a non-loopback address (%s:%d) without "
                "authentication; expose it only on a trusted network.",
                host,
                port,
            )
        return

    # IPv6 URLs require brackets around the literal address.
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    suffix = " (token authentication enabled)" if authenticated else ""
    _LOG.info("Cyber-Deck HUD live at http://%s:%d%s", display_host, port, suffix)


_LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kaiagotchi HUD Login</title>
  <style>
    body { background:#080d12; color:#d8e6ef; font:16px system-ui,sans-serif;
           display:grid; min-height:100vh; place-items:center; margin:0; }
    main { width:min(92vw,24rem); border:1px solid #24515e; padding:2rem;
           background:#101b23; box-sizing:border-box; }
    h1 { color:#00f0ff; font-size:1.25rem; }
    label { display:block; margin:1rem 0 .4rem; }
    input,button { box-sizing:border-box; width:100%; padding:.8rem; }
    input { background:#080d12; border:1px solid #42606c; color:inherit; }
    button { margin-top:1rem; background:#00d6d6; border:0; font-weight:700; }
    .error { color:#ff8b82; }
  </style>
</head>
<body>
  <main>
    <h1>Kaiagotchi Cyber-Deck</h1>
    <p>Enter the web HUD access token configured by the operator.</p>
    <p class="error" role="alert">__ERROR__</p>
    <form method="post" action="/login">
      <label for="token">Access token</label>
      <input id="token" name="token" type="password" autocomplete="current-password"
             required autofocus>
      <button type="submit">Unlock dashboard</button>
    </form>
  </main>
</body>
</html>"""


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

    Non-loopback binds require a long `web.auth_token` or `KAIA_WEB_AUTH_TOKEN`.
    The built-in HTTP server does not encrypt traffic; use only on a trusted
    private network or over a VPN.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        state_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self._config = config or {}
        web_cfg = self._config.get("web", {})
        if not isinstance(web_cfg, Mapping):
            web_cfg = {}
        # The dashboard exposes live SSIDs, station MACs, and runtime telemetry.
        # Non-loopback listeners must have a long token before the socket is opened.
        self._host = str(web_cfg.get("host", "127.0.0.1"))
        self._port = int(web_cfg.get("port", 8080))
        self._hz = float(web_cfg.get("update_hz", 10.0))  # 10 Hz broadcast
        configured_token = os.environ.get("KAIA_WEB_AUTH_TOKEN") or web_cfg.get("auth_token", "")
        self._auth_token = str(configured_token).strip()
        self._auth_enabled = bool(self._auth_token)
        if self._auth_enabled and len(self._auth_token) < 24:
            raise ValueError(
                "Web HUD auth tokens must contain at least 24 characters; "
                "use a randomly generated secret."
            )
        if not _bind_host_is_loopback(self._host) and not self._auth_enabled:
            raise ValueError(
                "Non-loopback Web HUD binds require web.auth_token or "
                "KAIA_WEB_AUTH_TOKEN; do not expose telemetry without authentication."
            )
        self._auth_cookie_name = "kaiagotchi_hud_session"
        self._session_ttl = 12 * 60 * 60
        self._sessions: dict[str, float] = {}
        self._state_provider = state_provider

        # Keep the authenticating session attached to each long-lived socket.
        # HTTP middleware only runs at the WebSocket handshake; every later
        # message and broadcast must enforce expiry/revocation independently.
        self._clients: dict[web.WebSocketResponse, str | None] = {}
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
        self._stop_event.clear()
        self._started = True
        self._thread = threading.Thread(
            target=self._run_server_thread,
            name="kaiagotchi-web",
            daemon=True,
        )
        self._thread.start()
        _LOG.info("WebServer thread started on %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Signal the server loop to stop; its finally block owns cleanup."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                _LOG.warning("WebServer thread did not stop within 5 seconds")
                return
        self._started = False
        _LOG.info("WebServer stopped")

    def _allowed_origin_hosts(self) -> set[str]:
        """Return hostnames/IPs that identify this machine, never arbitrary DNS names."""
        allowed = {"localhost"}
        for name in (socket.gethostname(), socket.getfqdn()):
            normalized = name.casefold().rstrip(".")
            if normalized:
                allowed.add(normalized)

        configured = self._host.strip("[]").casefold().rstrip(".")
        if configured not in {"", "0.0.0.0", "::"}:
            allowed.add(configured)

        try:
            for addresses in psutil.net_if_addrs().values():
                for address in addresses:
                    if address.family in {socket.AF_INET, socket.AF_INET6}:
                        allowed.add(address.address.split("%", 1)[0].casefold())
        except Exception:
            _LOG.debug("Could not enumerate local interface addresses for Origin checks", exc_info=True)
        return allowed

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
                if self._loop and not self._loop.is_closed():
                    self._loop.close()
            except Exception:
                _LOG.debug("Error closing WebServer loop", exc_info=True)
            self._started = False

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

    @web.middleware
    async def _auth_middleware(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        """Require a live browser session for the dashboard and telemetry routes."""
        if not self._auth_enabled or request.path == "/login" or request.path.startswith("/static/"):
            return await handler(request)

        self._prune_expired_sessions()
        session = request.cookies.get(self._auth_cookie_name)
        if self._session_is_active(session):
            return await handler(request)

        if request.path == "/ws" or request.path.startswith("/api/"):
            raise web.HTTPUnauthorized(
                text="Authenticate at /login before accessing Cyber-Deck telemetry.",
                headers={"Cache-Control": "no-store"},
            )
        raise web.HTTPFound("/login")

    def _prune_expired_sessions(self) -> None:
        """Remove expired browser sessions from the in-memory session table."""
        now = time.time()
        for session, expires_at in tuple(self._sessions.items()):
            if expires_at <= now:
                self._sessions.pop(session, None)

    def _session_is_active(self, session: str | None) -> bool:
        """Check whether a browser session is still authorized.

        Loopback mode intentionally has no authentication and therefore no
        session token. On an authenticated listener, missing, revoked, and
        expired session IDs are all rejected.
        """
        if not self._auth_enabled:
            return True
        if not session:
            return False
        expires_at = self._sessions.get(session)
        if expires_at is None or expires_at <= time.time():
            self._sessions.pop(session, None)
            return False
        return True

    def _create_app(self) -> web.Application:
        """Build the HTTP/WebSocket app with its auth boundary and static routes."""
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/login", self._handle_login)
        app.router.add_post("/login", self._handle_login)
        app.router.add_post("/logout", self._handle_logout)
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/api/state", self._handle_api_state)

        # Static code/assets contain no telemetry; data endpoints remain protected.
        if _STATIC_DIR.exists():
            app.router.add_static("/static/", path=str(_STATIC_DIR), name="static")
        return app

    async def _serve(self) -> None:
        """Build and run the aiohttp application."""
        app = self._create_app()
        self._runner = web.AppRunner(app)
        broadcast_task: asyncio.Task[None] | None = None
        try:
            # Keep setup/start inside the cleanup scope too: bind failures can
            # happen after AppRunner.setup() has already allocated resources.
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()

            _log_listener_started(self._host, self._port, authenticated=self._auth_enabled)

            broadcast_task = asyncio.create_task(self._broadcast_loop())
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            if broadcast_task is not None:
                broadcast_task.cancel()
                await asyncio.gather(broadcast_task, return_exceptions=True)
            # This is the sole cleanup owner. stop() only sets the event and
            # joins this thread, avoiding concurrent AppRunner/WebSocket closes.
            await self._cleanup()

    # ── Request Handlers ──────────────────────────────────────

    def _login_page(self, error: bool = False, status: int = 200) -> web.Response:
        """Render the small no-store login form without exposing the configured token."""
        page = _LOGIN_PAGE.replace(
            "__ERROR__",
            "Access token was not accepted." if error else "",
        )
        return web.Response(
            text=page,
            status=status,
            content_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    async def _handle_login(self, request: web.Request) -> web.StreamResponse:
        """Authenticate the configured token and issue a short-lived HttpOnly session."""
        if not self._auth_enabled:
            raise web.HTTPNotFound()

        if request.method == "GET":
            return self._login_page()

        if not _is_same_origin_request(request, self._allowed_origin_hosts()):
            raise web.HTTPForbidden(text="Cross-origin login is not allowed")

        try:
            form = await request.post()
            supplied = form.get("token", "")
        except (ValueError, TypeError):
            return web.Response(status=400, text="Invalid login request")

        if (
            not isinstance(supplied, str)
            or len(supplied) > 512
            or not hmac.compare_digest(supplied.encode("utf-8"), self._auth_token.encode("utf-8"))
        ):
            return self._login_page(error=True, status=401)

        # Bound session growth and expire old browser sessions on each request.
        self._prune_expired_sessions()
        now = time.time()
        if len(self._sessions) >= 128:
            oldest = min(self._sessions.items(), key=lambda item: item[1])[0]
            self._sessions.pop(oldest, None)

        session = secrets.token_urlsafe(32)
        self._sessions[session] = now + self._session_ttl
        response = web.Response(status=302, headers={"Location": "/"})
        response.set_cookie(
            self._auth_cookie_name,
            session,
            max_age=self._session_ttl,
            httponly=True,
            samesite="Strict",
            secure=request.secure,
            path="/",
        )
        return response

    async def _handle_logout(self, request: web.Request) -> web.StreamResponse:
        """Revoke the current browser session and clear its cookie."""
        if self._auth_enabled and not _is_same_origin_request(
            request, self._allowed_origin_hosts()
        ):
            raise web.HTTPForbidden(text="Cross-origin logout is not allowed")

        session = request.cookies.get(self._auth_cookie_name, "")
        self._sessions.pop(session, None)

        # Revoking a cookie must also revoke sockets established with it.
        for websocket, websocket_session in tuple(self._clients.items()):
            if session and websocket_session == session:
                try:
                    await websocket.close(code=1008, message=b"Session revoked")
                except Exception:
                    _LOG.debug("Could not close revoked WebSocket session", exc_info=True)

        response = web.Response(status=302, headers={"Location": "/login"})
        response.del_cookie(self._auth_cookie_name, path="/")
        return response

    async def _handle_index(self, request: web.Request) -> web.StreamResponse:
        """Serve index.html after the auth middleware has checked the browser session."""
        index_file = _STATIC_DIR / "index.html"
        if index_file.is_file():
            response = web.FileResponse(index_file)
            if self._auth_enabled:
                response.headers["Cache-Control"] = "no-store"
            return response
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
        """Handle WebSocket telemetry connections under the browser session lifetime."""
        if not _is_same_origin_request(request, self._allowed_origin_hosts()):
            raise web.HTTPForbidden(text="Cross-origin WebSocket access is not allowed")

        session = (
            request.cookies.get(self._auth_cookie_name)
            if self._auth_enabled
            else None
        )
        if not self._session_is_active(session):
            raise web.HTTPUnauthorized(text="Web HUD session is no longer active")

        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)

        # The session may be revoked while the handshake is being prepared.
        if not self._session_is_active(session):
            await ws.close(code=1008, message=b"Session expired")
            return ws

        self._clients[ws] = session
        remote = request.remote
        _LOG.info("Cyber-Deck client connected: %s (total: %d)", remote, len(self._clients))

        try:
            if not self._session_is_active(session):
                await ws.close(code=1008, message=b"Session expired")
                return ws

            # Send immediate initial state only while this socket's session is active.
            init_state = self._get_latest_snapshot()
            await ws.send_str(json.dumps(init_state, default=str))

            async for msg in ws:
                if not self._session_is_active(session):
                    await ws.close(code=1008, message=b"Session expired")
                    break

                if msg.type == WSMsgType.TEXT:
                    try:
                        cmd = json.loads(msg.data)
                        action = cmd.get("action")
                        if action == "ping":
                            await ws.send_str(json.dumps({"action": "pong", "ts": time.time()}))
                        elif action == "request_state":
                            # Re-check immediately before sending sensitive state.
                            if not self._session_is_active(session):
                                await ws.close(code=1008, message=b"Session expired")
                                break
                            state = self._get_latest_snapshot()
                            await ws.send_str(json.dumps(state, default=str))
                    except Exception:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    _LOG.debug("WebSocket error with %s: %s", remote, ws.exception())
        finally:
            self._clients.pop(ws, None)
            _LOG.info("Cyber-Deck client disconnected: %s (remaining: %d)", remote, len(self._clients))

        return ws

    # ── Data Pipeline ─────────────────────────────────────────

    def _get_latest_snapshot(self) -> dict[str, Any]:
        """Fetch live state; use simulated data only when no provider was supplied."""
        if self._state_provider is None:
            return _generate_mock_snapshot()

        try:
            snap = self._state_provider()
            if not isinstance(snap, dict):
                raise TypeError(
                    f"state provider must return a dict, got {type(snap).__name__}"
                )
            # An empty dict is a valid startup/empty state. Do not replace it
            # with fictional APs or stations just because it contains no keys.
            return self._serialize_snapshot(snap)
        except Exception:
            _LOG.warning("Live state provider failed; publishing an empty snapshot", exc_info=True)
            return self._serialize_snapshot({})

    async def _broadcast_loop(self) -> None:
        """Continuously broadcast state snapshots to all connected clients."""
        interval = 1.0 / max(1.0, min(30.0, self._hz))
        while not self._stop_event.is_set():
            if self._clients:
                try:
                    payload = self._get_latest_snapshot()
                    message = json.dumps(payload, default=str)

                    dead: set[web.WebSocketResponse] = set()
                    for ws, session in tuple(self._clients.items()):
                        if ws.closed:
                            dead.add(ws)
                            continue
                        if not self._session_is_active(session):
                            try:
                                await ws.close(code=1008, message=b"Session expired")
                            except Exception:
                                _LOG.debug("Could not close expired WebSocket session", exc_info=True)
                            dead.add(ws)
                            continue
                        try:
                            await ws.send_str(message)
                        except Exception:
                            dead.add(ws)
                    for ws in dead:
                        self._clients.pop(ws, None)
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

        network_snapshot = snap.get("network")
        net = network_snapshot if isinstance(network_snapshot, dict) else {}
        channel = _to_int(snap.get("channel")) or _to_int(net.get("current_channel"))
        on_channel = [a["pwr"] for a in aps if a["ch"] == channel and a["pwr"] is not None]
        all_power = [a["pwr"] for a in aps if a["pwr"] is not None]
        # Prefer the agent's measured signal (per-frame RadioTap). Fall back to the
        # strongest AP on the current channel, then to the strongest AP seen at all,
        # so the RSSI history is populated even while the radio hops channels.
        explicit_rssi = _dbm(snap.get("current_rssi"))
        current_rssi = (
            explicit_rssi if explicit_rssi is not None
            else max(on_channel) if on_channel
            else max(all_power) if all_power
            else None
        )

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
            "current_rssi": current_rssi,
            "packet_breakdown": breakdown if isinstance(breakdown, dict) else None,
            "packet_rate": snap.get("packet_rate"),
            "total_packets": totals if isinstance(totals, dict) else None,
            "aps": aps,
            "stations": stations,
            "chatter": chatter[-50:],
            "startup_ready": bool(snap.get("startup_ready", True)),
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
