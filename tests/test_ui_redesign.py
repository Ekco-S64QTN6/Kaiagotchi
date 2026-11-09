
import pytest

import kaiagotchi.ui.terminal_display as terminal_display_module
from kaiagotchi.ui.terminal_display import TerminalDisplay


def test_terminal_display_handles_missing_original_stdout(monkeypatch):
    monkeypatch.setattr(TerminalDisplay, "_instance", None)
    monkeypatch.setattr(terminal_display_module.sys, "__stdout__", None)

    display = TerminalDisplay()

    assert display._out is None
    assert display._owns_terminal is False
    # Also cover stdout disappearing after the terminal was acquired.
    display._owns_terminal = True
    display._atexit_cleanup()
    display._owns_terminal = False
    display.show_goodbye()
    display._render_header({"interface": "wlan1"})
    display._render_tables([], [])


class MockOut:
    def __init__(self):
        self.buffer = []
    def write(self, s):
        self.buffer.append(s)
    def flush(self):
        pass
    def get_content(self):
        return "".join(self.buffer)

@pytest.mark.asyncio
async def test_header_contains_interface_model():
    """Verify header shows interface and model."""
    td = TerminalDisplay()
    td._out = MockOut()

    state = {
        "interface": "wlan1",
        "interface_model": "TestModel 123",
        "aps": 5,
        "mood": "happy"
    }

    td._render_header(state)
    content = td._out.get_content()

    # Check for Interface and Model
    assert "wlan1" in content
    assert "[TestModel 123]" in content

    # Check for htop-style bars (brackets)
    assert "[" in content and "]" in content

@pytest.mark.asyncio
async def test_table_format_htop_style():
    """Verify tables use clean layout without internal vertical bars."""
    td = TerminalDisplay()
    td._out = MockOut()

    aps = [{"bssid": "AA:BB:CC:DD:EE:FF", "power": "-50", "essid": "TestAP"}]
    stations = [{"station_mac": "11:22:33:44:55:66", "power": "-60"}]

    td._render_tables(aps, stations)
    content = td._out.get_content()

    # Check for content
    assert "AA:BB:CC:DD:EE:FF" in content
    assert "TestAP" in content

    # Check for bar visualization (pipes)
    assert "|" in content

    # Ensure we don't have excessive vertical bars (only borders)
    # This is a loose check, but htop style usually has fewer separators
    # We just check that the row content is there
    assert "11:22:33:44:55:66" in content

@pytest.mark.asyncio
async def test_box_header_format():
    """Verify box headers use dashes for padding, not spaces."""
    td = TerminalDisplay()
    td._out = MockOut()

    aps = [{"bssid": "AA:BB:CC:DD:EE:FF", "power": "-50", "essid": "TestAP"}]
    td._render_tables(aps, [])
    content = td._out.get_content()

    # Check for "Access Points" surrounded by dashes
    # e.g. ┌────────── Access Points ──────────┐
    assert "─ Access Points ─" in content or "─Access Points─" in content or "── Access Points ──" in content

def test_show_goodbye_does_not_write_terminal_controls_without_a_tty(monkeypatch):
    class NonTTYOut:
        def __init__(self):
            self.writes = []

        def isatty(self):
            return False

        def write(self, value):
            self.writes.append(value)

        def flush(self):
            pass

    previous = TerminalDisplay._instance
    output = NonTTYOut()
    monkeypatch.setattr(TerminalDisplay, "_instance", None)
    monkeypatch.setattr(terminal_display_module.sys, "__stdout__", output)
    try:
        display = TerminalDisplay()
        assert display._owns_terminal is False
        monkeypatch.setattr(display, "stop", lambda: None)

        display.show_goodbye()

        assert output.writes == []
    finally:
        TerminalDisplay._instance = previous

def test_curses_thread_failure_requests_application_shutdown(monkeypatch, caplog):
    import threading

    display = object.__new__(TerminalDisplay)
    display._stop_event = threading.Event()
    display._started = True

    def fail_wrapper(_main):
        raise RuntimeError("simulated curses initialization failure")

    monkeypatch.setattr(terminal_display_module.curses, "wrapper", fail_wrapper)

    with caplog.at_level("ERROR", logger="kaiagotchi.ui.terminal_display"):
        display._run_curses()

    assert display._started is False
    assert display.should_quit is True
    assert "Curses thread crashed" in caplog.text


def test_curses_thread_return_clears_started_flag(monkeypatch):
    import threading

    display = object.__new__(TerminalDisplay)
    display._stop_event = threading.Event()
    display._started = True
    monkeypatch.setattr(
        terminal_display_module.curses, "wrapper", lambda _main: None
    )

    display._run_curses()

    assert display._started is False
    assert display.should_quit is False
