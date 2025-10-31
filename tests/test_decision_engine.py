# filepath: tests/test_decision_engine.py
import pytest
import asyncio
from unittest.mock import AsyncMock
from kaiagotchi.agent.decision_engine import DecisionEngine, AgentState
from kaiagotchi.agent.base import KaiagotchiBase

@pytest.mark.asyncio
async def test_state_transitions(mock_action_manager):
    engine = DecisionEngine(config={})
    assert engine.current_state == AgentState.INITIALIZING
    
    state = {"network": {"interface_count": 1}}
    new_state = engine.process_state(state, mock_action_manager)
    assert new_state == AgentState.RECON_SCAN

@pytest.mark.asyncio
async def test_concurrent_state_updates():
    agent = KaiagotchiBase(config={})
    updates = []
    
    async def updater():
        for i in range(100):
            agent.update_state({"counter": i})
            updates.append(i)
            await asyncio.sleep(0)
    
    tasks = [asyncio.create_task(updater()) for _ in range(10)]
    await asyncio.gather(*tasks)
    
    assert len(updates) == 1000
    assert isinstance(agent.state.get("counter"), int)

@pytest.mark.asyncio
async def test_agent_cleanup(mock_action_manager):
    agent = KaiagotchiBase(config={})
    agent.action_manager = mock_action_manager
    
    task = asyncio.create_task(agent.start())
    await asyncio.sleep(0.1)
    
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    mock_action_manager.cleanup.assert_called_once()
