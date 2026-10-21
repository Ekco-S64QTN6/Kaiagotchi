from types import SimpleNamespace

from kaiagotchi.cli import _web_enabled


def test_tui_flag_forces_terminal_only_even_when_config_enables_web():
    args = SimpleNamespace(tui=True, no_web=False, web=None)
    assert _web_enabled(args, {"web": {"enabled": True}}) is False


def test_tui_flag_wins_over_explicit_web_flag():
    args = SimpleNamespace(tui=True, no_web=False, web=True)
    assert _web_enabled(args, {"web": {"enabled": True}}) is False


def test_no_web_flag_disables_web_and_explicit_web_can_enable_configured_off():
    assert _web_enabled(
        SimpleNamespace(tui=False, no_web=True, web=None),
        {"web": {"enabled": True}},
    ) is False
    assert _web_enabled(
        SimpleNamespace(tui=False, no_web=False, web=True),
        {"web": {"enabled": False}},
    ) is True


def test_web_mode_defaults_to_config_when_no_mode_flag_is_set():
    args = SimpleNamespace(tui=False, no_web=False, web=None)
    assert _web_enabled(args, {"web": {"enabled": False}}) is False
    assert _web_enabled(args, {"web": {"enabled": True}}) is True
    assert _web_enabled(args, {}) is True


def test_malformed_web_config_falls_back_to_enabled():
    args = SimpleNamespace(tui=False, no_web=False, web=None)
    assert _web_enabled(args, {"web": "not-a-table"}) is True
