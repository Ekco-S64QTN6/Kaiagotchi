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


def _serve_once() -> tuple[http.server.HTTPServer, int]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_wait_healthy_true_when_served():
    srv, port = _serve_once()
    try:
        assert hud.wait_healthy(f"http://127.0.0.1:{port}/", timeout=5) is True
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
