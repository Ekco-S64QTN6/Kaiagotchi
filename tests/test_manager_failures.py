from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import kaiagotchi.cli as cli
import kaiagotchi.core.manager as manager_module
from kaiagotchi.core.manager import Manager


@pytest.mark.asyncio
async def test_manager_bootstrap_fails_if_agent_is_unavailable(monkeypatch):
    monkeypatch.setattr(manager_module, "Agent", None)
    manager = Manager(
        config={"log": {"level": "INFO"}},
        view=object(),
        system_state={},
    )

    with pytest.raises(RuntimeError, match="Agent implementation is unavailable"):
        await manager.bootstrap()

    assert manager._bootstrap_done is False
    assert manager.agent is None


@pytest.mark.asyncio
async def test_manager_bootstrap_propagates_agent_initialization_failure(monkeypatch):
    class BrokenAgent:
        def __init__(self, **_kwargs):
            raise ValueError("simulated agent initialization failure")

    monkeypatch.setattr(manager_module, "Agent", BrokenAgent)
    manager = Manager(
        config={"log": {"level": "INFO"}},
        view=object(),
        system_state={},
    )

    with pytest.raises(RuntimeError, match="could not initialize the Agent"):
        await manager.bootstrap()

    assert manager._bootstrap_done is False
    assert manager.agent is None


@pytest.mark.asyncio
async def test_manager_propagates_agent_runtime_failure_and_signals_completion():
    class BrokenAgent:
        async def start(self):
            raise ValueError("simulated agent runtime failure")

    manager = Manager(
        config={"log": {"level": "INFO"}},
        system_state={},
    )
    manager.agent = BrokenAgent()
    manager._bootstrap_done = True

    with pytest.raises(RuntimeError, match="Agent runtime failed"):
        await manager.start()

    assert manager._started is False
    assert manager._run_event is not None
    assert manager._run_event.is_set()


@pytest.mark.asyncio
async def test_cli_returns_nonzero_when_manager_runtime_fails(monkeypatch):
    class FakeView:
        def __init__(self, _config):
            self.suppress_output = False
            self.display = None

        def get_snapshot_dict(self):
            return {}

        async def stop(self):
            return None

    class FakeSplash:
        async def show(self, duration=0):
            return None

    class FailingManager:
        def __init__(self, **_kwargs):
            self.agent = None

        async def bootstrap(self):
            return None

        async def run_forever(self):
            raise RuntimeError("simulated manager runtime failure")

        async def stop(self):
            return None

    args = SimpleNamespace(
        debug=False,
        config="test-config.toml",
        manual=False,
        no_web=True,
        web=None,
        port=None,
        host=None,
    )
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", FakeSplash)
    monkeypatch.setattr(cli, "WebServer", None)
    monkeypatch.setattr(cli, "Manager", FailingManager)
    monkeypatch.setattr(cli, "_shutdown_event", asyncio.Event())

    assert await cli.run_agent() == 1
