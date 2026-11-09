from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import CookieJar, web
from aiohttp.client_exceptions import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from kaiagotchi.ui.web.server import WebServer

TOKEN = "kaiagotchi-test-token-" + ("x" * 32)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost"])
def test_loopback_bind_remains_available_without_authentication(host):
    server = WebServer({"web": {"host": host}})
    assert server._auth_enabled is False


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.25", "kaiagotchi.local"])
def test_non_loopback_bind_requires_a_token(host):
    with pytest.raises(ValueError, match="Non-loopback Web HUD binds require"):
        WebServer({"web": {"host": host}})


@pytest.mark.parametrize("host", ["192.168.1.25", "10.0.0.12", "0.0.0.0", "::"])
def test_non_loopback_bind_accepts_long_configured_token(host):
    server = WebServer({"web": {"host": host, "auth_token": TOKEN}})
    assert server._auth_enabled is True
    assert server._auth_token == TOKEN


def test_short_auth_token_is_rejected_even_on_loopback():
    with pytest.raises(ValueError, match="at least 24 characters"):
        WebServer({"web": {"host": "127.0.0.1", "auth_token": "too-short"}})


def test_environment_token_overrides_configured_token(monkeypatch):
    environment_token = "environment-token-" + ("z" * 32)
    monkeypatch.setenv("KAIA_WEB_AUTH_TOKEN", environment_token)
    server = WebServer({
        "web": {
            "host": "0.0.0.0",
            "auth_token": TOKEN,
        }
    })
    assert server._auth_token == environment_token


@pytest.mark.asyncio
async def test_lan_auth_protects_index_api_and_websocket_and_supports_browser_login():
    server = WebServer(
        {
            "web": {
                "host": "0.0.0.0",
                "auth_token": TOKEN,
            }
        },
        state_provider=lambda: {},
    )
    test_server = TestServer(server._create_app())
    client = TestClient(
        test_server,
        cookie_jar=CookieJar(unsafe=True),
    )
    await client.start_server()
    try:
        index = await client.get("/", allow_redirects=False)
        assert index.status == 302
        assert index.headers["Location"] == "/login"

        state = await client.get("/api/state")
        assert state.status == 401

        with pytest.raises(WSServerHandshakeError) as websocket_error:
            await client.ws_connect("/ws")
        assert websocket_error.value.status == 401

        login_page = await client.get("/login")
        assert login_page.status == 200
        assert 'name="token"' in await login_page.text()
        assert TOKEN not in await login_page.text()
        assert login_page.headers["Cache-Control"] == "no-store"

        rejected = await client.post(
            "/login",
            data={"token": "not-the-token"},
            allow_redirects=False,
        )
        assert rejected.status == 401
        assert TOKEN not in await rejected.text()

        accepted = await client.post(
            "/login",
            data={"token": TOKEN},
            allow_redirects=False,
        )
        assert accepted.status == 302
        assert accepted.headers["Location"] == "/"

        cookie = client.session.cookie_jar.filter_cookies(client.make_url("/"))[
            "kaiagotchi_hud_session"
        ]
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "Strict"

        index = await client.get("/")
        assert index.status == 200

        state = await client.get("/api/state")
        assert state.status == 200
        assert (await state.json())["aps"] == []

        websocket = await client.ws_connect("/ws")
        initial_state = await websocket.receive_json(timeout=2)
        assert initial_state["aps"] == []
        await websocket.close()

        logout = await client.post("/logout", allow_redirects=False)
        assert logout.status == 302
        assert logout.headers["Location"] == "/login"

        state_after_logout = await client.get("/api/state")
        assert state_after_logout.status == 401
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_auth_disabled_on_loopback_preserves_existing_http_and_websocket_flow():
    server = WebServer(state_provider=lambda: {})
    client = TestClient(TestServer(server._create_app()))
    await client.start_server()
    try:
        index = await client.get("/")
        assert index.status == 200

        state = await client.get("/api/state")
        assert state.status == 200
        assert (await state.json())["aps"] == []

        websocket = await client.ws_connect("/ws")
        initial_state = await websocket.receive_json(timeout=2)
        assert initial_state["aps"] == []
        await websocket.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_login_rejects_a_foreign_origin():
    server = WebServer({"web": {"host": "0.0.0.0", "auth_token": TOKEN}})
    request = SimpleNamespace(
        method="POST",
        headers={"Origin": "https://evil.example"},
        scheme="http",
        host="127.0.0.1:8080",
        path="/login",
    )

    with pytest.raises(web.HTTPForbidden, match="Cross-origin login"):
        await server._handle_login(request)
