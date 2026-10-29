from unittest.mock import AsyncMock, MagicMock

import pytest

from kaiagotchi.core.automata import AgentMood, Automata
from kaiagotchi.data.system_types import AgentMood as SystemAgentMood
from kaiagotchi.ui.voice.voice import Voice


@pytest.mark.asyncio
async def test_generate_thought_injects_to_view():
    """Ensure generate_thought calls view.async_update with a thought."""
    # Mock dependencies
    mock_view = MagicMock()
    mock_view.async_update = AsyncMock()

    automata = Automata(config={}, view=mock_view)

    # Force a mood
    automata._current_mood = AgentMood.HAPPY

    # Call generate_thought
    await automata.generate_thought()

    # Verify view was updated
    assert mock_view.async_update.called
    call_args = mock_view.async_update.call_args[0][0]
    assert "recent_captures" in call_args
    assert len(call_args["recent_captures"]) == 1
    event = call_args["recent_captures"][0]
    assert event["type"] == "thought"
    assert "💭" in event["message"]

@pytest.mark.asyncio
async def test_tick_calls_generate_thought(monkeypatch):
    """Ensure tick occasionally calls generate_thought."""
    mock_view = MagicMock()
    mock_view.async_update = AsyncMock()
    automata = Automata(config={}, view=mock_view)

    # Mock random to always trigger thought (return 0.0 < 0.1)
    import random
    monkeypatch.setattr(random, "random", lambda: 0.0)

    # Mock generate_thought to track calls
    automata.generate_thought = AsyncMock()

    await automata.tick({})

    assert automata.generate_thought.called


def test_automata_uses_the_shared_system_mood_enum():
    assert AgentMood is SystemAgentMood


def test_voice_recognizes_automata_mood_for_thoughts(monkeypatch):
    """Automata moods should select matching voice lines, not neutral fallbacks."""
    voice = Voice()
    monkeypatch.setattr(
        "kaiagotchi.ui.voice.voice.random.choice",
        lambda choices: choices[0],
    )

    assert voice.get_mood_line(AgentMood.HAPPY) == Voice.VOICE_LINES["happy"][0]
    assert (
        voice.get_mood_line(AgentMood.CONFIDENT)
        == Voice.VOICE_LINES["confident"][0]
    )
