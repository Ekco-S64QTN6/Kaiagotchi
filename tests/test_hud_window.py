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
    backend = subprocess.Popen(["false"])
    backend.wait()
    try:
        assert hud.wait_healthy(
            f"http://127.0.0.1:{port}/", timeout=5, backend=backend
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

    hud.start_backend(["--manual"])

    assert commands == [(["sudo", "-v"], {"check": True})]

    cmd, kwargs = popen_calls[0]
    assert cmd[:6] == [
        "sudo", "-n", "env", "KAIAGOTCHI_INTERFACE=wlan3",
        "KAIA_CONFIG=/etc/kaiagotchi/config.toml", "/repo/venv/bin/python3",
    ]
    assert cmd[6:11] == [
        "-m", "kaiagotchi.cli", "--debug", "--web", "--no-tui",
    ]
    assert cmd[-1] == "--manual"
    assert "UNRELATED_SECRET" not in " ".join(cmd)
    assert kwargs["stdin"] is hud.subprocess.DEVNULL
    assert kwargs["process_group"] == 0
    assert "start_new_session" not in kwargs



def test_select_loopback_port_uses_preferred_port_when_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        preferred = reservation.getsockname()[1]
    assert hud.select_loopback_port(preferred) == preferred


def test_select_loopback_port_falls_back_when_preferred_is_occupied():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        occupied = blocker.getsockname()[1]
        chosen = hud.select_loopback_port(occupied)
        assert chosen != occupied
        assert hud.loopback_port_available(chosen)


def test_main_uses_an_available_port_when_default_is_occupied(monkeypatch, capsys):
    class FakeBackend:
        def poll(self):
            return None

    class FakeWindow:
        def wait(self):
            return 0

        def terminate(self):
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        occupied = blocker.getsockname()[1]
        monkeypatch.setattr(hud, "DEFAULT_PORT", occupied)
        monkeypatch.setattr(hud, "DEFAULT_URL", f"http://127.0.0.1:{occupied}/")

        backend_calls = []
        window_calls = []
        monkeypatch.setattr(hud.app_window, "available", lambda: True)
        monkeypatch.setattr(
            hud, "start_backend",
            lambda args: backend_calls.append(args) or FakeBackend(),
        )
        monkeypatch.setattr(hud, "wait_healthy", lambda url, backend=None: window_calls.append(url) or True)
        monkeypatch.setattr(hud.app_window, "launch", lambda url, size: FakeWindow())
        monkeypatch.setattr(hud, "stop_backend", lambda proc: None)

        assert hud.main([]) == 0

    assert len(window_calls) == 1
    selected_url = window_calls[0]
    selected_port = int(selected_url.rsplit(":", 1)[1].rstrip("/"))
    assert selected_port != occupied
    assert backend_calls[0][-4:] == ["--host", "127.0.0.1", "--port", str(selected_port)]
    assert f"using available loopback port {selected_port}" in capsys.readouterr().err


def test_main_rejects_an_explicit_port_that_is_already_in_use(monkeypatch, capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        occupied = blocker.getsockname()[1]
        monkeypatch.setattr(hud.app_window, "available", lambda: True)
        monkeypatch.setattr(hud, "start_backend", lambda _args: pytest.fail("must not start backend"))
        assert hud.main(["--port", str(occupied)]) == 1
    assert "already in use" in capsys.readouterr().err


def _launched_url(monkeypatch, argv):
    launched = []

    class FakeWindow:
        def wait(self):
            return 0

        def terminate(self):
            pass

    monkeypatch.setattr(hud.app_window, "available", lambda: True)
    monkeypatch.setattr(hud, "wait_healthy", lambda url, backend=None: True)
    monkeypatch.setattr(hud.app_window, "launch", lambda url, size: launched.append(url) or FakeWindow())
    rc = hud.main(["--no-backend", *argv])
    return rc, launched


@pytest.mark.parametrize("argv,face", [
    ([], None),                      # the page's own default: t2
    (["--face", "k59"], "k59"),
    (["--t1"], "t1"),
    (["--random"], "random"),
])
def test_portrait_flags_select_the_face(monkeypatch, argv, face):
    rc, launched = _launched_url(monkeypatch, argv)
    assert rc == 0
    assert (f"face={face}" in launched[0]) if face else ("face=" not in launched[0])


def test_an_unknown_portrait_is_refused(monkeypatch, capsys):
    rc, launched = _launched_url(monkeypatch, ["--face", "nobody"])
    assert rc == 2 and not launched
    assert "--face must be one of" in capsys.readouterr().err


def test_the_page_defaults_to_the_t2_portrait():
    js = (WEB_DIR / "static" / "js" / "operative.js").read_text()
    assert ".get('face') || 't2'" in js


class _Proc:
    def __init__(self, code):
        self.code, self.returncode, self.terminated = code, None, False

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("w", timeout)
        self.returncode = self.code
        return self.code

    def terminate(self):
        self.terminated = True


def _launch_with(monkeypatch, codes):
    started = []

    def popen(argv, stdin=None, env=None):
        started.append(env or {})
        return _Proc(codes[len(started) - 1])

    monkeypatch.setattr(app_window, "available", lambda: True)
    monkeypatch.setattr(app_window.subprocess, "Popen", popen)
    monkeypatch.delenv(app_window.SOFTWARE_ENV, raising=False)
    return app_window.launch("http://127.0.0.1:8080/"), started


def test_the_window_renders_on_the_gpu_first(monkeypatch):
    window, started = _launch_with(monkeypatch, [None])          # still running: kept
    assert len(started) == 1 and app_window.SOFTWARE_ENV not in started[0]
    assert window.code is None


def test_a_window_that_dies_at_once_reopens_with_software_rendering(monkeypatch, capsys):
    window, started = _launch_with(monkeypatch, [1, None])
    assert len(started) == 2
    assert app_window.SOFTWARE_ENV not in started[0]
    assert started[1][app_window.SOFTWARE_ENV] == "1"
    assert "software rendering" in capsys.readouterr().err


def test_a_window_closed_normally_is_not_reopened(monkeypatch):
    window, started = _launch_with(monkeypatch, [0])
    assert len(started) == 1
