"""Regression tests for WebSocket Origin validation."""

from types import SimpleNamespace

import pytest
from aiohttp import web

from kaiagotchi.ui.web.server import WebServer, _is_same_origin_request


def test_websocket_origin_validation_allows_same_origin_and_non_browser_clients():
    same_origin = SimpleNamespace(
        headers={"Origin": "http://127.0.0.1:8080"},
        scheme="http",
        host="127.0.0.1:8080",
    )
    no_origin = SimpleNamespace(headers={}, scheme="http", host="127.0.0.1:8080")

    assert _is_same_origin_request(same_origin)
    assert _is_same_origin_request(no_origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://evil.example:8080",
        "null",
        "javascript://127.0.0.1:8080",
        "http://127.0.0.1:9999",
    ],
)
def test_websocket_origin_validation_rejects_foreign_origins(origin):
    request = SimpleNamespace(
        headers={"Origin": origin},
        scheme="http",
        host="127.0.0.1:8080",
    )
    assert not _is_same_origin_request(request)


@pytest.mark.asyncio
async def test_websocket_handler_rejects_cross_origin_before_upgrade():
    server = WebServer()
    request = SimpleNamespace(
        headers={"Origin": "https://evil.example"},
        scheme="http",
        host="127.0.0.1:8080",
    )

    with pytest.raises(web.HTTPForbidden):
        await server._handle_ws(request)


def test_websocket_origin_validation_rejects_matching_but_untrusted_dns_host():
    request = SimpleNamespace(
        headers={"Origin": "http://rebind.attacker.example:8080"},
        scheme="http",
        host="rebind.attacker.example:8080",
    )
    assert not _is_same_origin_request(
        request,
        allowed_hosts={"localhost", "127.0.0.1", "::1"},
    )
