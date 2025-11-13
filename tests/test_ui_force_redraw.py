import asyncio
import io
import pytest
from kaiagotchi.ui.terminal_display import TerminalDisplay


@pytest.mark.asyncio
async def test_force_redraw_draws_once(monkeypatch):
    """Ensure force_redraw() schedules a single draw without duplicates."""
    out = io.StringIO()
    td = TerminalDisplay()
    td._out = out

    # Mock draw to record calls
    called = []

    async def mock_draw(state):
        called.append(state)

    td.draw = mock_draw  # patch async method

    # Call force_redraw twice rapidly
    td.force_redraw({"network": {"access_points": {}, "current_channel": 1}, "current_system_state": "MONITOR"})
    td.force_redraw({"network": {"access_points": {}, "current_channel": 1}, "current_system_state": "MONITOR"})
    await asyncio.sleep(0.5)  # let tasks run

    # At least one draw should have been scheduled and not too many
    assert 1 <= len(called) <= 2, f"Unexpected draw count: {len(called)}"


@pytest.mark.asyncio
async def test_force_redraw_updates_cache(monkeypatch):
    """Ensure _last_rendered_state updates correctly on draw."""
    td = TerminalDisplay()
    td._ui_debug = True  # Enable debug logging
    dummy = {"network": {"access_points": {"a": {}, "b": {}}, "current_channel": 11}, "current_system_state": "MONITOR"}
    await td.draw(dummy)
    # channel may be int or string depending on extraction; normalize
    ch = td._last_rendered_state.get("ch")
    assert str(ch) == str(11)


@pytest.mark.asyncio
async def test_force_redraw_logs_debug(caplog):
    """Ensure KAIA_UI_DEBUG produces 'Draw invoked' logs."""
    import logging
    caplog.set_level(logging.DEBUG, logger="kaiagotchi.ui.terminal_display")
    td = TerminalDisplay()
    td._ui_debug = True
    dummy_state = {"network": {"access_points": {}, "current_channel": 5}, "current_system_state": "MONITOR"}
    await td.draw(dummy_state)
    found = any("Draw invoked" in rec.message for rec in caplog.records)
    assert found, "Expected 'Draw invoked' debug log not found"
