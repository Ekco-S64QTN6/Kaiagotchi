from kaiagotchi.ui.terminal_display import TerminalDisplay


def test_terminal_display_reads_nested_ui_limits_and_custom_faces():
    previous = TerminalDisplay._instance
    TerminalDisplay._instance = None
    try:
        display = TerminalDisplay({
            "ui": {
                "max_visible_aps": 4,
                "max_visible_stations": 3,
                "max_visible_chatter": 2,
                "faces": {
                    "happy": "(custom-happy)",
                    "neutral": "(custom-neutral)",
                },
            }
        })

        assert display._max_visible_aps == 4
        assert display._max_visible_stations == 3
        assert display._max_visible_chatter == 2
        assert display._get_face({"mood": "happy"}) == "(custom-happy)"
        assert display._get_face({"mood": "neutral"}) == "(custom-neutral)"
    finally:
        TerminalDisplay._instance = previous


def test_face_overrides_ignore_invalid_values():
    from kaiagotchi.ui.faces import NEUTRAL, get_face

    assert get_face("neutral", overrides={"neutral": ""}) == NEUTRAL
    assert get_face("neutral", overrides={"neutral": 42}) == NEUTRAL
