#!/usr/bin/env python3
"""KAIAGOTCHI HUD: the Cyber-Deck dashboard as a desktop application.

The same split as the Kaia Sentinel HUD: the privileged capture backend runs as
root (it needs CAP_NET_ADMIN for monitor mode), while this launcher and the
window run as the login user and only read the loopback HUD the backend serves.
Nothing here needs the user's display to cross into root, and nothing root needs
the user's Wayland session.

    ./kaiagotchi-hud                 # start backend + open the HUD window
    ./kaiagotchi-hud --no-backend    # just open the window against a backend already running

Run this module with the *system* Python (``/usr/bin/python3``): app_window
needs GObject introspection and WebKitGTK, which the project venv lacks. The
backend is still started with the project venv.
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "kaiagotchi", "ui", "web"))
import app_window  # noqa: E402  (standalone module, no project imports)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/"


def venv_python() -> str:
    cand = os.path.join(ROOT, "venv", "bin", "python3")
    return cand if os.path.exists(cand) else sys.executable


def loopback_port_available(port: int, host: str = DEFAULT_HOST) -> bool:
    """Check whether a loopback TCP port can be bound right now."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
        return True
    except OSError:
        return False


def select_loopback_port(preferred: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> int:
    """Use the preferred port when free, otherwise ask the OS for a free one.

    The Cyber-Deck default is 8080, but a stale test/development server must
    never be mistaken for Kaiagotchi's backend. Choosing an ephemeral loopback
    port lets the real backend start without killing or taking over that
    unrelated listener.
    """
    if loopback_port_available(preferred, host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def wait_healthy(
    url: str, timeout: float = 45.0, backend: subprocess.Popen | None = None
) -> bool:
    """Wait for Kaiagotchi's real dashboard, not an unrelated HTTP 200 on port 8080.

    A stale development server can own the default port and return a placeholder
    page. The previous status-only probe treated that as healthy and opened it
    even when the backend started by this launcher had failed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Do not let an older listener make a dead child process look healthy.
        if backend is not None and backend.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200 and r.headers.get_content_type() == "text/html":
                    page = r.read(128 * 1024)
                    if (
                        b'id="app-container"' in page
                        or b"<title>Kaiagotchi HUD Login</title>" in page
                    ):
                        return True
        except OSError:
            pass
        time.sleep(0.4)
    return False


def start_backend(extra_args: list[str] | None = None) -> subprocess.Popen:
    """Start root capture in a separate process group while retaining this TTY.

    ``sudo -v`` authenticates on the launcher's controlling terminal. Do not
    start the sudo child in a new session: with tty-scoped sudo timestamps that
    can detach it from the terminal and make the second sudo invocation unable
    to reuse the authentication just obtained.
    """
    subprocess.run(["sudo", "-v"], check=True)
    # Match run_kaiagotchi.sh: carry only the explicit Kaiagotchi selectors
    # through sudo. In particular, KAIAGOTCHI_INTERFACE remains an override.
    app_env = [
        f"{name}={os.environ[name]}"
        for name in ("KAIAGOTCHI_INTERFACE", "KAIA_CONFIG")
        if name in os.environ
    ]
    # Authentication was just refreshed above. Never prompt from the
    # detached backend's stdin; preserve the terminal session so sudo's
    # terminal-scoped timestamp remains valid, but isolate its process group.
    cmd = [
        "sudo", "-n", "env", *app_env, venv_python(), "-m", "kaiagotchi.cli",
        "--debug", "--web", "--no-tui", *(extra_args or []),
    ]
    return subprocess.Popen(
        cmd, cwd=ROOT, process_group=0, stdin=subprocess.DEVNULL
    )


def stop_backend(proc: subprocess.Popen) -> None:
    """Terminate the root backend's process group. The child is setuid root, so
    the user signals it through sudo, escalating to SIGKILL if it lingers."""
    if proc.poll() is not None:
        return
    pgid = proc.pid
    for sig, wait in ((signal.SIGTERM, 12.0), (signal.SIGKILL, 5.0)):
        subprocess.run(["sudo", "kill", f"-{sig.value}", f"-{pgid}"],
                       stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\\n\\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL, help="loopback HUD URL (default %(default)s)")
    ap.add_argument("--port", type=int, default=None, help="backend port (default: 8080, or an available port if busy)")
    ap.add_argument("--host", default=None, help="loopback bind host (default 127.0.0.1)")
    ap.add_argument("--no-backend", action="store_true",
                    help="do not start the capture backend; attach to one already running")
    ap.add_argument("--size", default="1280x800")
    args, passthrough = ap.parse_known_args(argv)

    if not app_window.available():
        print("This machine cannot open a WebKitGTK window: install webkit2gtk-4.1 and "
              "python-gobject (pacman -S webkit2gtk-4.1 python-gobject).", file=sys.stderr)
        return 2

    parsed_url = urlsplit(args.url)
    host = args.host or parsed_url.hostname or DEFAULT_HOST
    if parsed_url.scheme != "http" or host not in (DEFAULT_HOST, "localhost"):
        print("the desktop HUD only supports an HTTP loopback URL", file=sys.stderr)
        return 2
    if args.port is not None and not 1 <= args.port <= 65535:
        print("--port must be between 1 and 65535", file=sys.stderr)
        return 2

    configured_port = parsed_url.port or DEFAULT_PORT
    port = args.port or configured_port
    if not args.no_backend:
        if args.port is not None:
            if not loopback_port_available(port, DEFAULT_HOST):
                print(f"requested HUD port {port} is already in use", file=sys.stderr)
                return 1
        else:
            selected = select_loopback_port(port, DEFAULT_HOST)
            if selected != port:
                print(
                    f"HUD port {port} is already in use; using available loopback port {selected}",
                    file=sys.stderr,
                )
            port = selected

    # Normalize the bind host to the numeric loopback address. That avoids
    # localhost resolving to a different address family than the probe socket.
    host = DEFAULT_HOST
    path = parsed_url.path or "/"
    url = urlunsplit(("http", f"{host}:{port}", path, parsed_url.query, ""))

    backend: subprocess.Popen | None = None
    try:
        if not args.no_backend:
            backend_args = [*passthrough, "--host", host, "--port", str(port)]
            backend = start_backend(backend_args)
        if not wait_healthy(url, backend=backend):
            print(f"the HUD did not come up at {url}; the backend may have failed to start "
                  "(run ./run_kaiagotchi.sh --no-window on its own to see why).", file=sys.stderr)
            return 1
        window = app_window.launch(url, size=args.size)
        if window is None:
            return 2
        signal.signal(signal.SIGTERM, lambda *a: window.terminate())
        signal.signal(signal.SIGINT, lambda *a: window.terminate())
        return window.wait() or 0
    finally:
        if backend is not None:
            stop_backend(backend)


if __name__ == "__main__":
    sys.exit(main())
