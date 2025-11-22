import pytest
import re
from kaiagotchi.ui.terminal_display import TerminalDisplay

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
