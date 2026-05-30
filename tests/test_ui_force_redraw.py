import asyncio
import pytest
from kaiagotchi.ui.terminal_display import TerminalDisplay

@pytest.mark.asyncio
async def test_force_redraw_runs_without_error():
    """Ensure force_redraw() runs without error."""
    td = TerminalDisplay()
    # Mock output
    class MockOut:
        def write(self, x): pass
        def flush(self): pass
    
    td._out = MockOut()
    
    # Set some state
    td._last_state = {
        "network": {"access_points": {}, "current_channel": 1}, 
        "current_system_state": "MONITOR",
        "status": "Testing"
    }
    
    # Should not raise
    td.force_redraw()

@pytest.mark.asyncio
async def test_draw_updates_last_state():
    """Ensure draw() updates _last_state."""
    td = TerminalDisplay()
    class MockOut:
        def write(self, x): pass
        def flush(self): pass
    td._out = MockOut()
    
    dummy = {
        "network": {"access_points": {"a": {}, "b": {}}, "current_channel": 11}, 
        "current_system_state": "MONITOR",
        "status": "Testing",
        "agent_mood": "happy"
    }
    
    await td.draw(dummy)
    
    assert td._last_state.get("agent_mood") == "happy"
    assert td._last_state.get("status") == "Testing"

@pytest.mark.asyncio
async def test_draw_logs_state_change(caplog):
    """Ensure state changes trigger debug logs."""
    import logging
    caplog.set_level(logging.DEBUG, logger="kaiagotchi.ui.terminal_display")
    
    td = TerminalDisplay()
    class MockOut:
        def write(self, x): pass
        def flush(self): pass
    td._out = MockOut()
    
    state1 = {"status": "Old", "agent_mood": "neutral"}
    state2 = {"status": "New", "agent_mood": "happy"}
    
    await td.draw(state1)
    caplog.clear()
    
    await td.draw(state2)
    
    # "Status changed to:" is logged by _update_status
    found = any("Status changed to:" in rec.message for rec in caplog.records)
    assert found, "Expected 'Status changed to:' debug log not found"
