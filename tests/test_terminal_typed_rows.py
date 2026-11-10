from __future__ import annotations

import threading

import kaiagotchi.ui.terminal_display as terminal_module
from kaiagotchi.data.system_types import AccessPoint
from kaiagotchi.ui.terminal_display import TerminalDisplay


class RecordingScreen:
    def __init__(self, height: int = 30, width: int = 120):
        self.height = height
        self.width = width
        self.writes: list[tuple[int, int, str]] = []

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def addnstr(self, y: int, x: int, value: str, count: int, _attr: int) -> None:
        self.writes.append((y, x, value[:count]))


def _display() -> TerminalDisplay:
    return object.__new__(TerminalDisplay)


def test_ap_rows_render_boolean_privacy_and_string_fields(monkeypatch):
    monkeypatch.setattr(terminal_module.curses, "color_pair", lambda pair: pair)
    display = _display()
    screen = RecordingScreen()
    secured = AccessPoint(
        bssid="02:11:22:33:44:55",
        ssid="Typed secured AP",
        privacy=True,
    ).model_dump()
    open_ap = AccessPoint(
        bssid="02:11:22:33:44:66",
        ssid="Typed open AP",
        privacy=False,
    ).model_dump()
    text_ap = {
        "bssid": "02:11:22:33:44:77",
        "essid": "Legacy AP",
        "privacy": "WPA2",
        "channel": "6",
        "power": "-42",
    }

    display._draw_ap_rows(screen, 0, 0, 100, 10, [None, secured, open_ap, text_ap])

    rendered = "\n".join(value for _y, _x, value in screen.writes)
    assert "Secured" in rendered
    assert "Open" in rendered
    assert "WPA2" in rendered
    assert "Typed secured AP" in rendered
    assert "Typed open AP" in rendered
    assert "Legacy AP" in rendered


def test_ap_and_station_rows_render_null_and_non_string_fields_without_error(monkeypatch):
    monkeypatch.setattr(terminal_module.curses, "color_pair", lambda pair: pair)
    display = _display()
    screen = RecordingScreen()

    display._draw_ap_rows(
        screen,
        0,
        0,
        100,
        10,
        [
            None,
            {
                "bssid": None,
                "channel": None,
                "power": "not-a-number",
                "privacy": None,
                "essid": 12345,
            },
        ],
    )
    display._draw_sta_rows(
        screen,
        5,
        0,
        100,
        10,
        [
            "malformed-row",
            {
                "station_mac": None,
                "power": "unknown",
                "packets": None,
                "bssid": 12345,
            },
        ],
    )

    rendered = "\n".join(value for _y, _x, value in screen.writes)
    assert "12345" in rendered
    assert "unassociated" not in rendered
    assert "0      12345" in rendered


def test_take_snapshot_filters_malformed_ap_and_station_rows_before_sorting():
    display = _display()
    display._state_provider = None
    display._lock = threading.Lock()
    display._snapshot = {
        "aps_list": [
            None,
            {"bssid": "weak", "power": "-80"},
            "bad row",
            {"bssid": "strong", "power": "-30"},
        ],
        "stations_list": [
            None,
            {"station_mac": "11:22:33:44:55:66", "power": "-60", "packets": 5},
            "bad row",
        ],
    }
    display._ap_table = []
    display._stations = []
    display._max_visible_aps = 10
    display._max_visible_stations = 10
    display._current_status = "Monitoring signals..."

    snapshot = display._take_snapshot()

    assert [ap["bssid"] for ap in snapshot["_aps"]] == ["strong", "weak"]
    assert [station["station_mac"] for station in snapshot["_stas"]] == [
        "11:22:33:44:55:66"
    ]
