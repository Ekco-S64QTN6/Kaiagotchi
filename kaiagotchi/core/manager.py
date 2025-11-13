from __future__ import annotations
import asyncio, logging, os, sys
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from kaiagotchi.ui.view import View
    from kaiagotchi.data.system_types import SystemState

try:
    from kaiagotchi.config.config import load_config
except Exception:
    def load_config(path: str) -> Dict[str, Any]:
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
    from kaiagotchi.ai.epoch import EpochTracker
except Exception:
    EpochTracker = None

try:
    from kaiagotchi.ai.reward import RewardEngine
except Exception:
    RewardEngine = None

try:
    from kaiagotchi.core.automata import Automata
except Exception:
    Automata = None

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
    NetworkStateClass = SystemMetricsClass = SessionMetricsClass = GlobalSystemStateClass = SystemStateClass = None

logger = logging.getLogger("kaiagotchi.core.manager")


class Manager:
    """Manager orchestrates the Kaiagotchi runtime."""

    def __init__(self, *, config: Optional[Dict[str, Any]] = None, view: Optional[Any] = None,
                 system_state: Optional[Any] = None, state_lock: Optional[asyncio.Lock] = None):
        self.config = config or {}
        self.view = view
        self.agent = None
        self.monitoring_agent = None
        self.system_state = system_state
        self._state_lock = state_lock or asyncio.Lock()
        self._epoch = None
        self._reward_engine = None
        self._automata = None
        self._ticker = None
        self._run_event = None
        self._bootstrap_done = False
        self._started = False

    async def bootstrap(self) -> None:
        """Prepare configuration, logging, and all subsystems."""
        logger.info("Manager: bootstrap starting")

        if not self.config:
            config_path = os.environ.get("KAIA_CONFIG", "/etc/kaiagotchi/config.toml")
            try:
                self.config = load_config(config_path)
                logger.info(f"Manager: loaded config from {config_path}")
            except Exception:
                logger.warning("Manager: failed to load config; using defaults")
                self.config = {}

        logging.getLogger().setLevel(
            getattr(logging, self.config.get("log", {}).get("level", "INFO").upper(), logging.INFO)
        )

        # ---------- SINGLE VIEW INIT ----------
        if self.view is None and ViewClass:
            try:
                self.view = ViewClass(self.config)
                logger.info("Manager: View initialized (primary display)")
            except Exception:
                logger.exception("Manager: failed to initialize View")
                self.view = None

        # ---------- STATE INIT ----------
        if self.system_state is None and SystemStateClass:
            try:
                net = NetworkStateClass(access_points={}, interfaces={}, last_scan_time=0.0)
                metrics = SystemMetricsClass(cpu_usage=0.0, memory_usage=0.0, disk_free_gb=0.0, uptime_seconds=0.0)
                session = SessionMetricsClass(duration_seconds=0.0, handshakes_secured=0)
                gss = GlobalSystemStateClass.BOOTING
                self.system_state = SystemStateClass(
                    current_system_state=gss,
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

        # ---------- AGENT ----------
        if Agent:
            try:
                self.agent = Agent(
                    config=self.config,
                    view=self.view,  # ✅ shared view
                    system_state=self.system_state,
                    state_lock=self._state_lock,
                )
                logger.info("Manager: Agent initialized (linked to shared View)")
            except Exception:
                logger.exception("Manager: Agent initialization failed")

        # ---------- AI SUBSYSTEMS ----------
        if EpochTracker:
            try:
                self._epoch = EpochTracker(self.config)
                logger.info("Manager: EpochTracker initialized")
            except Exception:
                logger.exception("Manager: EpochTracker init failed")

        if RewardEngine:
            try:
                self._reward_engine = RewardEngine(self.config)
                logger.info("Manager: RewardEngine initialized")
            except Exception:
                logger.exception("Manager: RewardEngine init failed")

        if Automata:
            try:
                self._automata = Automata(self.config, self.view, reward_engine=self._reward_engine)
                logger.info("Manager: Automata initialized and linked")
            except Exception:
                logger.exception("Manager: Automata init failed")

        # Attach AI subsystems to agent
        if self.agent:
            for k, v in {
                "epoch_tracker": self._epoch,
                "reward_engine": self._reward_engine,
                "automata": self._automata,
            }.items():
                try:
                    setattr(self.agent, k, v)
                except Exception:
                    logger.debug(f"Manager: attach {k} failed")

        self._bootstrap_done = True
        logger.info("Manager: bootstrap complete")

    async def start(self) -> None:
        """Start the subsystems (ensuring single display)."""
        if not self._bootstrap_done:
            await self.bootstrap()
        if self._started:
            return

        logger.info("Manager: starting subsystems")

        # Start View first
        if self.view:
            try:
                await self.view.start()
                await self.view.on_starting()
                logger.info("Manager: View started")
            except Exception:
                logger.exception("Manager: view.start() failed")

        # Start Agent second
        if self.agent:
            try:
                await self.agent.start()
                logger.info("Manager: Agent started")
            except Exception:
                logger.exception("Manager: agent.start() failed")

        # Start Ticker third
        if SystemTicker and self.system_state:
            try:
                self._ticker = SystemTicker(system_state=self.system_state, interval=2.0)
                await self._ticker.start()
                logger.info("Manager: SystemTicker started")
            except Exception:
                logger.exception("Manager: ticker start failed")

        # Delay MonitoringAgent until initial Agent/UI settle
        await asyncio.sleep(2.0)
        try:
            from kaiagotchi.agent.monitoring_agent import MonitoringAgent
            logger.info("Manager: initializing MonitoringAgent (shared View)")
            self.monitoring_agent = MonitoringAgent(
                config=self.config,
                system_state=self.system_state,
                state_lock=self._state_lock,
                view=self.view,  # ✅ use same view
            )
            self.monitoring_agent.automata = self._automata
            self.monitoring_agent.reward_engine = self._reward_engine
            self.monitoring_agent.epoch_tracker = self._epoch
            await self.monitoring_agent.start()
            logger.info("Manager: MonitoringAgent started (shared View)")
        except Exception as e:
            logger.exception(f"Manager: failed to start MonitoringAgent: {e}")

        self._run_event = asyncio.Event()
        self._started = True
        logger.info("Manager: all subsystems started")

    async def stop(self) -> None:
        """Stop everything safely."""
        logger.info("Manager: stopping subsystems")
        self._started = False

        async def safe_stop(obj: Any, *methods: str):
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
                        logger.debug(f"Manager: {name}() failed", exc_info=True)

        for obj, methods in [
            (self.monitoring_agent, ("stop",)),
            (self.agent, ("stop", "shutdown")),
            (self.view, ("stop", "on_shutdown")),
            (self._ticker, ("stop",)),
            (self._epoch, ("stop",)),
            (self._reward_engine, ("stop",)),
            (self._automata, ("stop",)),
        ]:
            if obj:
                await safe_stop(obj, *methods)

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
