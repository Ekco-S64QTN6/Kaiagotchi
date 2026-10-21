from unittest.mock import AsyncMock, MagicMock

import pytest

from kaiagotchi.agent.agent import Agent
from kaiagotchi.data.system_types import SystemState


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

    # Inject the same state object used by MonitoringAgent.
    agent = Agent(config, view=mock_view, system_state=SystemState())

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


def test_system_state_declares_runtime_fields_and_dumps_them():
    """Runtime telemetry is typed model state, not hidden Pydantic extras."""
    state = SystemState()
    expected = {
        "mood", "aps", "aps_max_seen", "mode", "status", "substatus", "uptime",
        "aps_list", "stations_list", "recent_captures", "chatter_log",
    }
    dumped = state.model_dump()
    assert expected <= dumped.keys()
    assert state.recent_captures == []
    assert state.chatter_log == []
    assert state.mood == "neutral"


def test_agent_restores_persisted_mood_to_system_state(monkeypatch):
    """Restored mood is visible to downstream state snapshots after startup."""
    class StoredMood:
        def get_last_mood(self):
            return "happy"

        def get_last_reward(self):
            return 0.5

    monkeypatch.setattr("kaiagotchi.agent.agent.PersistentMood", StoredMood)
    mock_view = MagicMock()
    mock_view.async_update = AsyncMock()
    agent = Agent(
        {"personality": {"default_mood": "neutral"}, "ui": {"fps": 2}},
        view=mock_view,
        system_state=SystemState(),
    )
    assert agent.system_state.mood == "happy"
    assert agent.automata.current_mood.value == "happy"



def test_channel_hopping_uses_monitoring_adapter(monkeypatch):
    """A configured wlan0 must not override the capture dongle's wlan1."""
    monkeypatch.delenv("KAIAGOTCHI_INTERFACE", raising=False)
    config = {
        "main": {"iface": "wlan0"},
        "personality": {"channels": [1, 6, 11]},
        "ui": {"fps": 2},
    }
    agent = Agent(config, view=MagicMock(), system_state=SystemState())

    assert agent.monitoring_agent.interface == "wlan1"
    assert agent.action_manager._interface == "wlan1"
    assert agent.action_manager._monitor_interface == "wlan1"
