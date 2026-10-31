import asyncio

import pytest

from kaiagotchi.agent.decision_engine import AgentState, DecisionEngine


@pytest.mark.asyncio
async def test_transition_to_without_view_updates_state_and_emits_event():
    engine = DecisionEngine()
    events = []
    engine.events.on("state_changed", events.append)

    result = await engine._transition_to(AgentState.RECON_SCAN, "test transition")
    await asyncio.sleep(0)

    assert result is AgentState.RECON_SCAN
    assert engine.current_state is AgentState.RECON_SCAN
    assert events == [
        {
            "old_state": "INITIALIZING",
            "new_state": "RECON_SCAN",
            "reason": "test transition",
            "timestamp": engine._last_state_change,
        }
    ]


@pytest.mark.asyncio
async def test_transition_to_calls_attached_view_redraw():
    engine = DecisionEngine()
    redraw_calls = []

    class FakeView:
        def force_redraw(self):
            redraw_calls.append("redrawn")

    engine.set_view(FakeView())

    await engine._transition_to(AgentState.TARGETING, "target selected")

    assert redraw_calls == ["redrawn"]


@pytest.mark.asyncio
async def test_transition_to_awaits_async_view_redraw():
    engine = DecisionEngine()
    redraw_calls = []

    class FakeView:
        async def force_redraw(self):
            redraw_calls.append("redrawn")

    engine.set_view(FakeView())

    await engine._transition_to(AgentState.MAINTENANCE, "maintenance")

    assert redraw_calls == ["redrawn"]
