"""The HUD-in-a-window launcher: loopback-only, health-gated, clean teardown.

The window itself needs WebKitGTK and a display, so these cover the parts that
run anywhere: origin locking, the health wait that gates the window on the
backend's web server, and backend teardown that never shells out to sudo when
the backend is already gone.
"""
from __future__ import annotations

import http.server
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).resolve().parent.parent / "kaiagotchi" / "ui" / "web"
sys.path.insert(0, str(WEB_DIR))

import app_window  # noqa: E402
import hud  # noqa: E402


@pytest.mark.parametrize("url,home,ok", [
    ("http://127.0.0.1:8080/x", "http://127.0.0.1:8080/", True),
    ("http://127.0.0.1:8080/", "http://127.0.0.1:9999/", False),
    ("http://evil.example/", "http://127.0.0.1:8080/", False),
    ("https://127.0.0.1:8080/", "http://127.0.0.1:8080/", False),
])
def test_same_origin(url, home, ok):
    assert app_window.same_origin(url, home) is ok


def test_available_returns_a_bool():
    assert isinstance(app_window.available(), bool)


def test_main_refuses_non_loopback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app_window", "--url", "http://10.0.0.5/"])
    assert app_window._main() == 2
    assert "loopback" in capsys.readouterr().err


def _serve_once(body: bytes) -> tuple[http.server.HTTPServer, int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


@pytest.mark.parametrize("body", [
    b'<html><head><title>Cyber-Deck</title></head><body><div id="app-container"></div></body></html>',
    b'<html><head><title>Kaiagotchi HUD Login</title></head><body>Login</body></html>',
])
def test_wait_healthy_accepts_kaiagotchi_dashboard_or_login(body):
    srv, port = _serve_once(body)
    try:
        assert hud.wait_healthy(f"http://127.0.0.1:{port}/", timeout=5) is True
    finally:
        srv.shutdown()


def test_wait_healthy_rejects_unrelated_200_test_page():
    body = (
        b"<html><body><h1>KAIAGOTCHI // CYBER-DECK</h1>"
        b"<p>HUD-in-a-window launcher test (--no-backend)</p></body></html>"
    )
    srv, port = _serve_once(body)
    try:
        assert hud.wait_healthy(f"http://127.0.0.1:{port}/", timeout=0.5) is False
    finally:
        srv.shutdown()


def test_wait_healthy_rejects_dead_backend_even_if_port_answers():
    srv, port = _serve_once(b'<html><body><div id="app-container"></div></body></html>')
    class ExitedBackend:
        def poll(self):
            return 1
    try:
        assert hud.wait_healthy(
            f"http://127.0.0.1:{port}/", timeout=5, backend=ExitedBackend()
        ) is False
    finally:
        srv.shutdown()


def test_wait_healthy_false_on_dead_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    assert hud.wait_healthy(f"http://127.0.0.1:{dead}/", timeout=1.5) is False


def test_stop_backend_is_a_noop_when_already_exited(monkeypatch):
    called = []
    monkeypatch.setattr(hud.subprocess, "run", lambda *a, **k: called.append(a))
    proc = subprocess.Popen(["true"])
    proc.wait()
    hud.stop_backend(proc)
    assert called == []  # never signals a backend that is already gone


def test_venv_python_prefers_project_venv():
    p = hud.venv_python()
    assert p.endswith("python3") or p == sys.executable


def test_start_backend_forwards_only_explicit_app_environment(monkeypatch):
    commands = []
    popen_calls = []
    monkeypatch.setenv("KAIAGOTCHI_INTERFACE", "wlan3")
    monkeypatch.setenv("KAIA_CONFIG", "/etc/kaiagotchi/config.toml")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-cross-sudo")
    monkeypatch.setattr(hud.subprocess, "run", lambda cmd, **kwargs: commands.append((cmd, kwargs)))
    monkeypatch.setattr(hud.subprocess, "Popen", lambda cmd, **kwargs: popen_calls.append((cmd, kwargs)) or object())
    monkeypatch.setattr(hud, "venv_python", lambda: "/repo/venv/bin/python3")

    hud.start_backend(["--no-web"])

    assert commands == [(["sudo", "-v"], {"check": True})]
    cmd, kwargs = popen_calls[0]
    assert cmd[:5] == [
        "sudo", "env", "KAIAGOTCHI_INTERFACE=wlan3",
        "KAIA_CONFIG=/etc/kaiagotchi/config.toml", "/repo/venv/bin/python3",
    ]
    assert "UNRELATED_SECRET" not in " ".join(cmd)
    assert kwargs["stdin"] is hud.subprocess.DEVNULL
