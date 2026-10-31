from __future__ import annotations

import asyncio
import threading
from pathlib import Path
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

    web_servers = []
    event_loop_thread_id = threading.get_ident()

    class FakeWebServer:
        def __init__(self, *_args, **_kwargs):
            self.stop_thread_id = None
            web_servers.append(self)

        def start(self):
            return None

        def stop(self):
            self.stop_thread_id = threading.get_ident()

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
        no_web=False,
        web=None,
        port=None,
        host=None,
    )
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", FakeSplash)
    monkeypatch.setattr(cli, "WebServer", FakeWebServer)
    monkeypatch.setattr(cli, "Manager", FailingManager)
    monkeypatch.setattr(cli, "_shutdown_event", asyncio.Event())
    # Avoid replacing pytest's own process signal handlers during this test.
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    assert await cli.run_agent() == 1
    assert len(web_servers) == 1
    assert web_servers[0].stop_thread_id is not None
    assert web_servers[0].stop_thread_id != event_loop_thread_id



@pytest.mark.asyncio
async def test_cli_observes_manager_bootstrap_failure_before_splash_finishes(monkeypatch):
    class FakeView:
        def __init__(self, _config):
            self.suppress_output = False
            self.display = None

        def get_snapshot_dict(self):
            return {}

        async def stop(self):
            return None

    class BlockingSplash:
        def __init__(self):
            self.cancelled = False

        async def show(self, duration=0):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    class FailingManager:
        def __init__(self, **_kwargs):
            pass

        async def bootstrap(self):
            raise RuntimeError("bootstrap failed immediately")

    args = SimpleNamespace(
        debug=False,
        config="test-config.toml",
        manual=False,
        no_web=True,
        web=None,
        port=None,
        host=None,
        tui=False,
    )
    splash = BlockingSplash()
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", lambda: splash)
    monkeypatch.setattr(cli, "WebServer", None)
    monkeypatch.setattr(cli, "Manager", FailingManager)
    monkeypatch.setattr(cli, "Agent", None)
    monkeypatch.setattr(cli, "_shutdown_event", asyncio.Event())

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    # The old implementation waited for the 15-second splash before noticing
    # that bootstrap had already failed. This bound makes the regression test
    # fail instead of hanging if startup stops observing manager_task.
    exit_code = await asyncio.wait_for(cli.run_agent(), timeout=1.0)

    assert exit_code == 1
    assert splash.cancelled is True


@pytest.mark.asyncio
async def test_cli_legacy_agent_is_not_cancelled_when_splash_finishes(monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()
    cancelled = asyncio.Event()

    class FakeView:
        def __init__(self, _config):
            self.suppress_output = False
            self.display = None

        def get_snapshot_dict(self):
            return {}

        async def stop(self):
            return None

    class InstantSplash:
        async def show(self, duration=0):
            return None

    class BlockingAgent:
        def __init__(self, **_kwargs):
            pass

        async def start(self):
            started.set()
            try:
                await cli._shutdown_event.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def stop(self):
            stopped.set()

    args = SimpleNamespace(
        debug=False,
        config="test-config.toml",
        manual=False,
        no_web=True,
        web=None,
        port=None,
        host=None,
        tui=True,
    )
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", InstantSplash)
    monkeypatch.setattr(cli, "WebServer", None)
    monkeypatch.setattr(cli, "Manager", None)
    monkeypatch.setattr(cli, "Agent", BlockingAgent)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    runner = asyncio.create_task(cli.run_agent())
    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.sleep(0.05)

    assert not runner.done(), "Agent should keep running after the splash finishes"
    assert not cancelled.is_set()

    cli._shutdown_event.set()
    assert await asyncio.wait_for(runner, timeout=1.0) == 0
    assert stopped.is_set()
    assert not cancelled.is_set()


@pytest.mark.asyncio
async def test_cli_legacy_agent_start_failure_is_observed_before_splash_finishes(monkeypatch):
    class FakeView:
        def __init__(self, _config):
            self.suppress_output = False
            self.display = None

        def get_snapshot_dict(self):
            return {}

        async def stop(self):
            return None

    class BlockingSplash:
        def __init__(self):
            self.cancelled = False

        async def show(self, duration=0):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    class FailingAgent:
        def __init__(self, **_kwargs):
            pass

        async def start(self):
            raise RuntimeError("agent startup failed immediately")

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
        tui=True,
    )
    splash = BlockingSplash()
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", lambda: splash)
    monkeypatch.setattr(cli, "WebServer", None)
    monkeypatch.setattr(cli, "Manager", None)
    monkeypatch.setattr(cli, "Agent", FailingAgent)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    exit_code = await asyncio.wait_for(cli.run_agent(), timeout=1.0)

    assert exit_code == 1
    assert splash.cancelled is True


@pytest.mark.asyncio
async def test_cli_does_not_start_legacy_agent_after_manager_bootstrap_failure(monkeypatch):
    stopped = asyncio.Event()
    legacy_agent_constructed = False

    class FakeView:
        def __init__(self, _config):
            self.suppress_output = False
            self.display = None

        def get_snapshot_dict(self):
            return {}

        async def stop(self):
            return None

    class InstantSplash:
        async def show(self, duration=0):
            return None

    class FailingManager:
        def __init__(self, **_kwargs):
            pass

        async def bootstrap(self):
            raise RuntimeError("simulated partial bootstrap failure")

        async def stop(self):
            stopped.set()

    class LegacyAgent:
        def __init__(self, **_kwargs):
            nonlocal legacy_agent_constructed
            legacy_agent_constructed = True

        async def start(self):
            raise AssertionError("legacy fallback must not run")

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
        tui=True,
    )
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "setup_logging", lambda _debug=False: None)
    monkeypatch.setattr(cli, "load_config", lambda _path: {"log": {"level": "INFO"}})
    monkeypatch.setattr(cli, "View", FakeView)
    monkeypatch.setattr(cli, "SplashScreen", InstantSplash)
    monkeypatch.setattr(cli, "WebServer", None)
    monkeypatch.setattr(cli, "Manager", FailingManager)
    monkeypatch.setattr(cli, "Agent", LegacyAgent)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_args, **_kwargs: None)

    assert await cli.run_agent() == 1
    assert not legacy_agent_constructed
    assert stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked_stage",
    ["view.start", "view.on_starting", "ticker.start", "agent.start"],
)
async def test_manager_cancellation_during_startup_stops_started_components(
    monkeypatch, blocked_stage
):
    entered_blocking_stage = asyncio.Event()
    agent_stopped = asyncio.Event()
    blocking_stage_cancelled = asyncio.Event()

    async def block_startup(stage):
        if blocked_stage == stage:
            entered_blocking_stage.set()
            try:
                await asyncio.Event().wait()
            finally:
                blocking_stage_cancelled.set()

    class FakeView:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            await block_startup("view.start")

        async def on_starting(self):
            await block_startup("view.on_starting")

        async def stop(self):
            self.stop_calls += 1

    ticker_instances = []

    class FakeTicker:
        def __init__(self, **_kwargs):
            self.stop_calls = 0
            ticker_instances.append(self)

        async def start(self):
            await block_startup("ticker.start")

        async def stop(self):
            self.stop_calls += 1

    class FakeAgent:
        async def start(self):
            await block_startup("agent.start")

        async def stop(self):
            agent_stopped.set()

    view = FakeView()
    manager = Manager(
        config={"log": {"level": "INFO"}},
        view=view,
        system_state={"status": "booting"},
    )
    manager.agent = FakeAgent()
    manager._bootstrap_done = True
    monkeypatch.setattr(manager_module, "SystemTicker", FakeTicker)

    start_task = asyncio.create_task(manager.start())
    await asyncio.wait_for(entered_blocking_stage.wait(), timeout=1.0)
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(start_task, timeout=2.0)

    assert blocking_stage_cancelled.is_set()
    assert view.stop_calls == 1
    assert agent_stopped.is_set()
    if blocked_stage in {"ticker.start", "agent.start"}:
        assert len(ticker_instances) == 1
        assert ticker_instances[0].stop_calls == 1
    else:
        assert ticker_instances == []


@pytest.mark.asyncio
async def test_manager_defers_repeated_cancellation_until_startup_cleanup_finishes(
    monkeypatch,
):
    startup_blocked = asyncio.Event()
    view_stop_started = asyncio.Event()
    agent_stop_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_finished = []

    class BlockingView:
        async def start(self):
            startup_blocked.set()
            await asyncio.Event().wait()

        async def on_starting(self):
            return None

        async def stop(self):
            view_stop_started.set()
            await allow_cleanup.wait()
            cleanup_finished.append("view")

    class BlockingAgent:
        async def start(self):
            return None

        async def stop(self):
            agent_stop_started.set()
            await allow_cleanup.wait()
            cleanup_finished.append("agent")

    manager = Manager(
        config={"log": {"level": "INFO"}},
        view=BlockingView(),
        system_state={},
    )
    manager.agent = BlockingAgent()
    manager._bootstrap_done = True
    monkeypatch.setattr(manager_module, "SystemTicker", None)

    start_task = asyncio.create_task(manager.start())
    await asyncio.wait_for(startup_blocked.wait(), timeout=1.0)
    start_task.cancel()
    await asyncio.wait_for(agent_stop_started.wait(), timeout=1.0)
    await asyncio.wait_for(view_stop_started.wait(), timeout=1.0)

    start_task.cancel()
    await asyncio.sleep(0)
    assert cleanup_finished == []

    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(start_task, timeout=2.0)

    assert set(cleanup_finished) == {"agent", "view"}



@pytest.mark.asyncio
async def test_manager_loads_config_with_path_argument(monkeypatch):
    received_paths = []

    def fake_load_config(path=None):
        received_paths.append(path)
        return {"log": {"level": "INFO"}, "loaded_from_path": True}

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

    config_path = "/tmp/kaiagotchi-manager-test.toml"
    monkeypatch.setenv("KAIA_CONFIG", config_path)
    monkeypatch.setattr(manager_module, "load_config", fake_load_config)
    monkeypatch.setattr(manager_module, "Agent", FakeAgent)

    manager = Manager(view=object(), system_state={})
    await manager.bootstrap()

    assert received_paths == [Path(config_path)]
    assert manager.config["loaded_from_path"] is True
    assert isinstance(manager.agent, FakeAgent)


@pytest.mark.asyncio
async def test_manager_awaits_awaitable_returned_by_sync_stop_wrapper():
    stopped = []

    async def async_stop():
        await asyncio.sleep(0)
        stopped.append("stopped")

    class WrappedStopAgent:
        def stop(self):
            return async_stop()

    manager = Manager(config={}, system_state={})
    manager.agent = WrappedStopAgent()

    await manager.stop()

    assert stopped == ["stopped"]
