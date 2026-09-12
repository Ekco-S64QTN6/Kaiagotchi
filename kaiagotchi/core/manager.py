from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kaiagotchi.ui.view import View  # noqa: F401

try:
    from kaiagotchi.config.config import load_config
except Exception:
    def load_config(path: str | None = None) -> dict[str, Any]:
        return {}

try:
    from kaiagotchi.agent.agent import Agent
except Exception:
    Agent = None

try:
    from kaiagotchi.ui.view import View as ViewClass
except Exception:
    ViewClass = None

try:
    from kaiagotchi.core.system import SystemTicker
except Exception:
    SystemTicker = None

try:
    import kaiagotchi.data.system_types as st
    NetworkStateClass = getattr(st, "NetworkState", None)
    SystemMetricsClass = getattr(st, "SystemMetrics", None)
    SessionMetricsClass = getattr(st, "SessionMetrics", None)
    GlobalSystemStateClass = getattr(st, "GlobalSystemState", None)
    SystemStateClass = getattr(st, "SystemState", None)
except Exception:
    NetworkStateClass = SystemMetricsClass = SessionMetricsClass = None
    GlobalSystemStateClass = SystemStateClass = None

logger = logging.getLogger("kaiagotchi.core.manager")


class Manager:
    """Thin orchestrator around the :class:`Agent`.

    The Agent owns all AI subsystems (epoch tracker, reward engine, automata),
    the monitoring agent, and persistence. The Manager's job is to build the
    shared View and SystemState, hand them to the Agent, run a lightweight
    metrics ticker, and coordinate startup/shutdown. It deliberately does *not*
    duplicate the Agent's subsystems.
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        view: Any | None = None,
        system_state: Any | None = None,
        state_lock: asyncio.Lock | None = None,
    ):
        self.config = config or {}
        self.view = view
        self.agent = None
        self.system_state = system_state
        self._state_lock = state_lock or asyncio.Lock()
        self._ticker = None
        self._run_event: asyncio.Event | None = None
        self._bootstrap_done = False
        self._started = False
        self._stopping = False

    async def bootstrap(self) -> None:
        """Prepare configuration, the shared View, SystemState, and the Agent."""
        logger.info("Manager: bootstrap starting")

        if not self.config:
            config_path = os.environ.get("KAIA_CONFIG", "/etc/kaiagotchi/config.toml")
            try:
                self.config = load_config(config_path)
                logger.info("Manager: loaded config from %s", config_path)
            except Exception:
                logger.warning("Manager: failed to load config; using defaults")
                self.config = {}

        logging.getLogger().setLevel(
            getattr(logging, self.config.get("log", {}).get("level", "INFO").upper(), logging.INFO)
        )

        # ---------- SINGLE SHARED VIEW ----------
        if self.view is None and ViewClass:
            try:
                self.view = ViewClass(self.config)
                logger.info("Manager: View initialized (primary display)")
            except Exception:
                logger.exception("Manager: failed to initialize View")
                self.view = None

        # ---------- SHARED SYSTEM STATE ----------
        if self.system_state is None and SystemStateClass:
            try:
                net = NetworkStateClass(access_points={}, interfaces={}, last_scan_time=0.0)
                metrics = SystemMetricsClass(
                    cpu_usage=0.0, memory_usage=0.0, disk_free_gb=0.0, uptime_seconds=0.0
                )
                session = SessionMetricsClass(duration_seconds=0.0, handshakes_secured=0)
                self.system_state = SystemStateClass(
                    current_system_state=GlobalSystemStateClass.BOOTING,
                    config_hash="manager_boot",
                    network=net,
                    metrics=metrics,
                    agents={},
                    session_metrics=session,
                )
                logger.info("Manager: default SystemState created")
            except Exception:
                logger.warning("Manager: minimal SystemState fallback")
                self.system_state = {}

        # ---------- AGENT (owns AI subsystems + monitoring) ----------
        if Agent:
            try:
                self.agent = Agent(
                    config=self.config,
                    view=self.view,
                    system_state=self.system_state,
                    state_lock=self._state_lock,
                )
                logger.info("Manager: Agent initialized (shares View and SystemState)")
            except Exception:
                logger.exception("Manager: Agent initialization failed")

        self._bootstrap_done = True
        logger.info("Manager: bootstrap complete")

    async def start(self) -> None:
        """Start the View, metrics ticker, and Agent."""
        if not self._bootstrap_done:
            await self.bootstrap()
        if self._started or self._stopping:
            return

        logger.info("Manager: starting subsystems")

        # View first so the display is live before the agent pushes updates.
        if self.view:
            try:
                await self.view.start()
                await self.view.on_starting()
                logger.info("Manager: View started")
            except Exception:
                logger.exception("Manager: view.start() failed")

        # Lightweight metrics ticker (spawns its own background task).
        if SystemTicker and self.system_state:
            try:
                self._ticker = SystemTicker(system_state=self.system_state, interval=2.0)
                await self._ticker.start()
                logger.info("Manager: SystemTicker started")
            except Exception:
                logger.exception("Manager: ticker start failed")

        self._run_event = asyncio.Event()
        self._started = True
        self._stopping = False

        # The Agent runs its own monitoring / decision / UI loops and blocks
        # until shutdown, so start it last.
        if self.agent:
            try:
                await self.agent.start()
                logger.info("Manager: Agent finished")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Manager: agent.start() failed")

    async def stop(self) -> None:
        """Stop the Agent, ticker, and View safely."""
        if self._stopping:
            logger.debug("Manager: already stopping, skipping duplicate stop")
            return

        logger.info("Manager: stopping subsystems")
        self._stopping = True
        self._started = False

        async def safe_stop(obj: Any, *methods: str) -> None:
            for name in methods:
                fn = getattr(obj, name, None)
                if fn:
                    try:
                        if asyncio.iscoroutinefunction(fn):
                            await fn()
                        else:
                            await asyncio.get_running_loop().run_in_executor(None, fn)
                        return
                    except Exception:
                        logger.debug("Manager: %s() failed", name, exc_info=True)

        stop_tasks = []
        if self.agent:
            stop_tasks.append(safe_stop(self.agent, "stop", "shutdown"))
        if self._ticker:
            stop_tasks.append(safe_stop(self._ticker, "stop"))
        if self.view:
            stop_tasks.append(safe_stop(self.view, "stop", "on_shutdown"))

        if stop_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*stop_tasks, return_exceptions=True), timeout=15.0
                )
                logger.info("Manager: all subsystems stopped")
            except TimeoutError:
                logger.warning("Manager: some subsystems took too long to stop")
            except Exception as e:
                logger.error("Manager: error during subsystem shutdown: %s", e)

        if self._run_event:
            self._run_event.set()

        logger.info("Manager: stopped")

    async def run_forever(self) -> None:
        """Run until stopped."""
        if not self._started:
            await self.start()
        self._run_event = self._run_event or asyncio.Event()
        logger.info("Manager: entering run_forever loop")
        try:
            await self._run_event.wait()
        except asyncio.CancelledError:
            logger.info("Manager: run_forever cancelled")
        finally:
            logger.info("Manager: exiting run_forever")
