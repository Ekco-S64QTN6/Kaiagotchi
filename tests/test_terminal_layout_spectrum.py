from __future__ import annotations

import curses

import kaiagotchi.ui.terminal_display as terminal_display_module
from kaiagotchi.ui.terminal_display import TerminalDisplay


class RecordingScreen:
    def __init__(self, height: int = 30, width: int = 80) -> None:
        self.height = height
        self.width = width
        self.writes: list[tuple[int, int, str]] = []
        self.refreshed = False
        self.erased = False

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def addnstr(self, y: int, x: int, value: str, count: int, _attr: int) -> None:
        self.writes.append((y, x, value[:count]))

    def refresh(self) -> None:
        self.refreshed = True

    def erase(self) -> None:
        self.erased = True


def test_minimum_tui_height_accounts_for_stacked_and_wide_panes():
    assert TerminalDisplay._minimum_height(60) == 29
    assert TerminalDisplay._minimum_height(99) == 29
    assert TerminalDisplay._minimum_height(100) == 24
    assert TerminalDisplay._minimum_height(160) == 24


def test_frame_requests_resize_before_narrow_layout_can_overlap():
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=28, width=80)

    display._draw_frame(screen, {})

    assert screen.refreshed is True
    assert len(screen.writes) == 1
    assert "60x29" in screen.writes[0][2]


def test_frame_requests_resize_before_wide_layout_can_overlap():
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=23, width=120)

    display._draw_frame(screen, {})

    assert screen.refreshed is True
    assert len(screen.writes) == 1
    assert "60x24" in screen.writes[0][2]


def test_narrow_layout_panes_touch_but_do_not_overlap(monkeypatch):
    monkeypatch.setattr(terminal_display_module.curses, "color_pair", lambda _pair: 0)
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=29, width=80)
    boxes: list[tuple[int, int, int, int, str]] = []

    display._current_status = "Monitoring signals..."
    display._get_face = lambda _snap: "(•‿‿•)"
    display._get_scoreboard = lambda _snap: (0, 0, 0, 0)
    display._put = lambda *_args, **_kwargs: None
    display._box = lambda _scr, y, x, h, w, title="", _attr=0: boxes.append(
        (y, x, h, w, title)
    )
    display._draw_spectrum = lambda *_args: None
    display._draw_ap_rows = lambda *_args: None
    display._draw_sta_rows = lambda *_args: None
    display._draw_chatter = lambda *_args: None

    display._draw_frame(screen, {})

    access_points = next(box for box in boxes if box[4] == "Access Points")
    stations = next(box for box in boxes if box[4] == "Stations")
    chatter = next(box for box in boxes if box[4] == "System Chatter")
    assert access_points[:4] == (14, 0, 5, 80)
    assert stations[:4] == (19, 0, 4, 80)
    assert chatter[:4] == (23, 0, 6, 80)
    assert access_points[0] + access_points[2] == stations[0]
    assert stations[0] + stations[2] == chatter[0]


def test_wide_layout_panes_touch_but_do_not_overlap(monkeypatch):
    monkeypatch.setattr(terminal_display_module.curses, "color_pair", lambda _pair: 0)
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=24, width=120)
    boxes: list[tuple[int, int, int, int, str]] = []

    display._current_status = "Monitoring signals..."
    display._get_face = lambda _snap: "(•‿‿•)"
    display._get_scoreboard = lambda _snap: (0, 0, 0, 0)
    display._put = lambda *_args, **_kwargs: None
    display._box = lambda _scr, y, x, h, w, title="", _attr=0: boxes.append(
        (y, x, h, w, title)
    )
    display._draw_spectrum = lambda *_args: None
    display._draw_ap_rows = lambda *_args: None
    display._draw_sta_rows = lambda *_args: None
    display._draw_chatter = lambda *_args: None

    display._draw_frame(screen, {})

    access_points = next(box for box in boxes if box[4] == "Access Points")
    stations = next(box for box in boxes if box[4] == "Stations")
    chatter = next(box for box in boxes if box[4] == "System Chatter")
    assert access_points[:4] == (14, 0, 4, 72)
    assert stations[:4] == (14, 72, 4, 48)
    assert chatter[:4] == (18, 0, 6, 120)
    assert access_points[0] + access_points[2] == chatter[0]
    assert stations[0] + stations[2] == chatter[0]


def test_spectrum_includes_observed_channels_beyond_2_4_ghz(monkeypatch):
    monkeypatch.setattr(terminal_display_module.curses, "color_pair", lambda _pair: 0)
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=30, width=60)

    display._draw_spectrum(
        screen,
        0,
        60,
        [
            {"channel": 1},
            {"channel": 36},
            {"channel": 149},
            {"channel": 161},
            {"channel": "not-a-channel"},
            None,
            {"channel": True},
        ],
    )

    rendered = "\n".join(value for _y, _x, value in screen.writes)
    assert "Ch   1" in rendered
    assert "Ch  36" in rendered
    assert "Ch 149" in rendered
    assert "Ch 161" in rendered


def test_spectrum_summarizes_channels_beyond_visible_slots(monkeypatch):
    monkeypatch.setattr(terminal_display_module.curses, "color_pair", lambda _pair: 0)
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=30, width=60)
    aps = [{"channel": channel} for channel in [1, 6, 11, 36, 40, 44, 48, 149, 153, 157, 161, 165, 169]]

    display._draw_spectrum(screen, 0, 60, aps)

    rendered = "\n".join(value for _y, _x, value in screen.writes)
    assert "+2 ch / 2 AP" in rendered
    assert "Ch  36" in rendered


def test_empty_spectrum_keeps_the_familiar_2_4_ghz_baseline(monkeypatch):
    monkeypatch.setattr(terminal_display_module.curses, "color_pair", lambda _pair: 0)
    display = object.__new__(TerminalDisplay)
    screen = RecordingScreen(height=30, width=60)

    display._draw_spectrum(screen, 0, 60, [])

    rendered = "\n".join(value for _y, _x, value in screen.writes)
    assert "Ch   1" in rendered
    assert "Ch  12" in rendered
