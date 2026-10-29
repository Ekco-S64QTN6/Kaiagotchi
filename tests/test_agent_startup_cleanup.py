"""Regression tests for Agent startup cancellation cleanup."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kaiagotchi.agent.agent import Agent


@pytest.mark.asyncio
async def test_cancellation_during_automata_start_cleans_up_monitor_task():
    monitor_started = asyncio.Event()
    monitor_cancelled = asyncio.Event()
    automata_started = asyncio.Event()

    async def blocking_monitor_start():
        monitor_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            monitor_cancelled.set()

    async def blocking_automata_start(_get_state):
        automata_started.set()
        await asyncio.Event().wait()

    agent = Agent.__new__(Agent)
    agent.logger = logging.getLogger("tests.agent-startup-cleanup")
    agent.config = {}
    agent._running = False
    agent._monitor_task = None
    agent._decision_task = None
    agent._update_task = None
    agent.monitoring_agent = SimpleNamespace(
        start=blocking_monitor_start,
        stop=AsyncMock(),
    )
    agent.automata = SimpleNamespace(
        _running=False,
        start=blocking_automata_start,
        stop=AsyncMock(),
    )
    agent.persistent_mood = None
    agent.persistent_network = None
    agent.last_session = SimpleNamespace(save=Mock())
    agent.action_manager = SimpleNamespace(cleanup=AsyncMock())
    agent._view = None

    start_task = asyncio.create_task(agent.start_async())
    try:
        await asyncio.wait_for(monitor_started.wait(), timeout=1.0)
        await asyncio.wait_for(automata_started.wait(), timeout=1.0)
        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(start_task, timeout=2.0)
    finally:
        # Prevent a failed regression from leaking a background test task.
        monitor_task = agent._monitor_task
        if monitor_task is not None and not monitor_task.done():
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)

    assert agent._running is False
    assert agent._monitor_task is not None and agent._monitor_task.cancelled()
    assert monitor_cancelled.is_set()
    agent.automata.stop.assert_awaited_once()
    agent.monitoring_agent.stop.assert_awaited_once()
    agent.action_manager.cleanup.assert_awaited_once()
    agent.last_session.save.assert_called_once_with()
