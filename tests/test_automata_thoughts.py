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



def test_automata_optional_engine_exports_retain_the_real_classes():
    from kaiagotchi.ai.epoch import Epoch
    from kaiagotchi.ai.reward import RewardEngine
    from kaiagotchi.core import automata as automata_module

    assert automata_module.Epoch is Epoch
    assert automata_module.RewardEngine is RewardEngine



def _automata_for_reward_tick(monkeypatch, *, epoch=None, reward=None):
    from kaiagotchi.core import automata as automata_module

    monkeypatch.setattr(automata_module.random, "random", lambda: 1.0)
    automata = Automata(config={}, view=None, reward_engine=reward, epoch_tracker=epoch)
    automata.process_reward = MagicMock()
    automata._maybe_drift = AsyncMock()
    automata.generate_thought = AsyncMock()
    return automata


@pytest.mark.asyncio
async def test_epoch_zero_reward_is_authoritative(monkeypatch):
    epoch = MagicMock()
    epoch.epoch = 0
    epoch.next.side_effect = lambda: setattr(epoch, "epoch", 1)
    epoch.data.return_value = {"reward": 0.0}
    reward_engine = MagicMock()
    automata = _automata_for_reward_tick(
        monkeypatch,
        epoch=epoch,
        reward=reward_engine,
    )

    await automata.tick({"network": {"access_points": {"ap": {}}}})

    automata.process_reward.assert_called_once_with(0.0)
    reward_engine.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_direct_engine_zero_reward_is_not_replaced_by_ap_fallback(monkeypatch):
    reward_engine = MagicMock()
    reward_engine.evaluate.return_value = 0.0
    automata = _automata_for_reward_tick(monkeypatch, reward=reward_engine)

    await automata.tick({"network": {"access_points": {"one": {}, "two": {}}}})

    reward_engine.evaluate.assert_called_once()
    automata.process_reward.assert_called_once_with(0.0)


@pytest.mark.asyncio
async def test_stale_epoch_snapshot_is_ignored_when_epoch_did_not_advance(monkeypatch):
    epoch = MagicMock()
    epoch.epoch = 7
    epoch.next.return_value = None
    epoch.data.return_value = {"reward": 0.8}
    reward_engine = MagicMock()
    reward_engine.evaluate.return_value = 0.25
    automata = _automata_for_reward_tick(
        monkeypatch,
        epoch=epoch,
        reward=reward_engine,
    )

    await automata.tick({"network": {"access_points": {}}})

    epoch.data.assert_not_called()
    reward_engine.evaluate.assert_called_once()
    automata.process_reward.assert_called_once_with(0.25)


@pytest.mark.asyncio
async def test_ap_reward_is_used_only_when_reward_sources_are_unavailable(monkeypatch):
    reward_engine = MagicMock()
    reward_engine.evaluate.return_value = float("nan")
    automata = _automata_for_reward_tick(monkeypatch, reward=reward_engine)

    await automata.tick({"network": {"access_points": {"one": {}, "two": {}, "three": {}}}})

    automata.process_reward.assert_called_once_with(0.03)


def test_reward_coercion_rejects_non_finite_and_boolean_values():
    assert Automata._coerce_reward(0) == 0.0
    assert Automata._coerce_reward(-0.5) == -0.5
    assert Automata._coerce_reward(True) is None
    assert Automata._coerce_reward(float("nan")) is None
    assert Automata._coerce_reward(float("inf")) is None
