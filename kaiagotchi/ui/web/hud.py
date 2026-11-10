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
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "kaiagotchi", "ui", "web"))
import app_window  # noqa: E402  (standalone module, no project imports)

DEFAULT_URL = "http://127.0.0.1:8080/"


def venv_python() -> str:
    cand = os.path.join(ROOT, "venv", "bin", "python3")
    return cand if os.path.exists(cand) else sys.executable


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
    """Start the root capture backend in its own session so the whole tree can
    be signalled on exit. ``sudo -v`` first, so any password prompt happens in
    the terminal before the window takes over."""
    subprocess.run(["sudo", "-v"], check=True)
    # Match run_kaiagotchi.sh: carry only the explicit Kaiagotchi selectors
    # through sudo. In particular, KAIAGOTCHI_INTERFACE remains an override.
    app_env = [
        f"{name}={os.environ[name]}"
        for name in ("KAIAGOTCHI_INTERFACE", "KAIA_CONFIG")
        if name in os.environ
    ]
    cmd = ["sudo", "env", *app_env, venv_python(), "-m", "kaiagotchi.cli",
           "--debug", *(extra_args or [])]
    return subprocess.Popen(cmd, cwd=ROOT, start_new_session=True, stdin=subprocess.DEVNULL)


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
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL, help="loopback HUD URL (default %(default)s)")
    ap.add_argument("--no-backend", action="store_true",
                    help="do not start the capture backend; attach to one already running")
    ap.add_argument("--size", default="1280x800")
    args, passthrough = ap.parse_known_args(argv)

    if not app_window.available():
        print("This machine cannot open a WebKitGTK window: install webkit2gtk-4.1 and "
              "python-gobject (pacman -S webkit2gtk-4.1 python-gobject).", file=sys.stderr)
        return 2

    backend: subprocess.Popen | None = None
    try:
        if not args.no_backend:
            backend = start_backend(passthrough)
        if not wait_healthy(args.url, backend=backend):
            print(f"the HUD did not come up at {args.url}; the backend may have failed to start "
                  "(run ./run_kaiagotchi.sh on its own to see why).", file=sys.stderr)
            return 1
        window = app_window.launch(args.url, size=args.size)
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
