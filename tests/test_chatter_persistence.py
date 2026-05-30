import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from kaiagotchi.agent.agent import Agent
from kaiagotchi.data.system_types import SystemState, GlobalSystemState

@pytest.mark.asyncio
async def test_thought_persistence():
    """Verify thoughts are persisted in system state and not overwritten."""
    # Setup
    config = {
        "personality": {"default_mood": "neutral"},
        "ui": {"fps": 60}
    }
    mock_view = MagicMock()
    mock_view.async_update = AsyncMock()
    
    # Create Agent
    agent = Agent(config, view=mock_view)
    agent.system_state = SystemState() # Reset state
    
    # 1. Generate a thought via Automata
    # We need to mock the voice to return a predictable string
    agent.automata._voice.get_mood_line = MagicMock(return_value="I am thinking")
    
    await agent.automata.generate_thought()
    
    # Verify thought is in system state
    captures = agent.system_state.recent_captures
    assert len(captures) == 1
    assert "💭 I am thinking" in captures[0]["message"]
    assert captures[0]["type"] == "thought"
    
    # 2. Simulate network update (which usually overwrites if not careful)
    # Create a dummy network capture
    net_capture = {"timestamp": "12:00:00", "message": "New AP found"}
    
    # Manually trigger what MonitoringAgent does: append to list in lock
    async with agent.state_lock:
        current = agent.system_state.recent_captures
        current.append(net_capture)
        agent.system_state.recent_captures = current
        
    # Verify BOTH exist
    captures = agent.system_state.recent_captures
    assert len(captures) == 2
    assert "💭 I am thinking" in captures[0]["message"]
    assert "New AP found" in captures[1]["message"]

@pytest.mark.asyncio
async def test_automata_callback_integration():
    """Verify Automata correctly uses the callback provided by Agent."""
    mock_callback = AsyncMock()
    from kaiagotchi.core.automata import Automata
    
    mock_view = MagicMock()
    automata = Automata({}, mock_view, on_thought=mock_callback)
    automata._voice.get_mood_line = MagicMock(return_value="Callback test")
    
    await automata.generate_thought()
    
    mock_callback.assert_called_once()
    args = mock_callback.call_args[0]
    assert "💭 Callback test" in args[0]
