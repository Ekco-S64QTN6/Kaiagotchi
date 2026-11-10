from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import kaiagotchi.agent.agent
    import kaiagotchi.core.system
    import kaiagotchi.data.system_types
    import kaiagotchi.ui.view

try:
    from kaiagotchi.config.config import load_config
except Exception:
    def load_config(system_path: Path | None = None) -> dict[Any, Any]:
        return {}

Agent: type[kaiagotchi.agent.agent.Agent] | None = None
try:
    from kaiagotchi.agent.agent import Agent as _Agent
except Exception:
    pass
else:
    Agent = _Agent

ViewClass: type[kaiagotchi.ui.view.View] | None = None
try:
    from kaiagotchi.ui.view import View as _View
except Exception:
    pass
else:
    ViewClass = _View

SystemTicker: type[kaiagotchi.core.system.SystemTicker] | None = None
try:
    from kaiagotchi.core.system import SystemTicker as _SystemTicker
except Exception:
    pass
else:
    SystemTicker = _SystemTicker

GlobalSystemStateClass: type[kaiagotchi.data.system_types.GlobalSystemState] | None = None
SystemStateClass: type[kaiagotchi.data.system_types.SystemState] | None = None
try:
    from kaiagotchi.data.system_types import GlobalSystemState as _GlobalSystemState
    from kaiagotchi.data.system_types import SystemState as _SystemState
except Exception:
    pass
else:
    GlobalSystemStateClass = _GlobalSystemState
    SystemStateClass = _SystemState

logger = logging.getLogger("kaiagotchi.core.manager")

_STOP_TIMEOUT_SECONDS = 15.0


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
        self.agent: kaiagotchi.agent.agent.Agent | None = None
        self.system_state = system_state
        self._state_lock = state_lock or asyncio.Lock()
        self._ticker: kaiagotchi.core.system.SystemTicker | None = None
        self._run_event: asyncio.Event | None = None
        self._bootstrap_done = False
        self._started = False
        self._stopping = False
        self._stop_lock = asyncio.Lock()
        self._stop_tasks: dict[str, asyncio.Task[bool]] = {}
        self._shutdown_complete = False

    async def bootstrap(self) -> None:
        """Prepare configuration, the shared View, SystemState, and the Agent."""
        logger.info("Manager: bootstrap starting")

        if not self.config:
            config_path = os.environ.get("KAIA_CONFIG", "/etc/kaiagotchi/config.toml")
            try:
                self.config = load_config(Path(config_path))
                logger.info("Manager: loaded config from %s", config_path)
            except Exception:
                logger.warning("Manager: failed to load config; using defaults")
                self.config = {}

        logging.getLogger().setLevel(
            getattr(logging, self.config.get("log", {}).get("level", "INFO").upper(), logging.INFO)
        )

        # ---------- SINGLE SHARED VIEW ----------
        if self.view is None and ViewClass is not None:
            try:
                self.view = ViewClass(self.config)
                logger.info("Manager: View initialized (primary display)")
            except Exception:
                logger.exception("Manager: failed to initialize View")
                self.view = None

        # ---------- SHARED SYSTEM STATE ----------
        if self.system_state is None and SystemStateClass is not None:
            try:
                if GlobalSystemStateClass is None:
                    raise RuntimeError("GlobalSystemState implementation is unavailable")
                self.system_state = SystemStateClass.minimal(
                    current_system_state=GlobalSystemStateClass.BOOTING,
                    config_hash="manager_boot",
                )
                logger.info("Manager: default SystemState created")
            except Exception:
                logger.warning("Manager: minimal SystemState fallback")
                self.system_state = {}

        # ---------- AGENT (owns AI subsystems + monitoring) ----------
        if Agent is None:
            raise RuntimeError(
                "Agent implementation is unavailable; Manager cannot start without it"
            )

        try:
            self.agent = Agent(
                config=self.config,
                view=self.view,
                system_state=self.system_state,
                state_lock=self._state_lock,
            )
        except Exception as exc:
            logger.exception("Manager: Agent initialization failed")
            raise RuntimeError("Manager could not initialize the Agent") from exc

        self._bootstrap_done = True
        logger.info("Manager: bootstrap complete")

    async def _cleanup_after_start_failure(self) -> None:
        """Finish bounded component cleanup despite repeated caller cancellation."""
        cleanup_task = asyncio.create_task(self.stop())
        cancellation: asyncio.CancelledError | None = None

        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as exc:
                if cleanup_task.cancelled():
                    break
                if cancellation is None:
                    cancellation = exc
            except Exception:
                # Retrieve and log the child error below after it is terminal.
                break

        cleanup_error: BaseException | None = None
        try:
            await cleanup_task
        except BaseException as exc:
            cleanup_error = exc

        if cancellation is not None:
            raise cancellation
        if cleanup_error is not None:
            raise cleanup_error

    async def start(self) -> None:
        """Start the View, metrics ticker, and Agent."""
        try:
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
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Manager: view.start() failed")

            # Lightweight metrics ticker (spawns its own background task).
            if SystemTicker is not None and self.system_state:
                try:
                    ticker = SystemTicker(system_state=self.system_state, interval=2.0)
                    self._ticker = ticker
                    await ticker.start()
                    logger.info("Manager: SystemTicker started")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Manager: ticker start failed")

            agent = self.agent
            if agent is None:
                raise RuntimeError("Manager has no Agent; bootstrap did not complete")

            self._run_event = asyncio.Event()
            self._started = True
            self._stopping = False

            # The Agent runs its own monitoring / decision / UI loops and blocks
            # until shutdown, so start it last. Do not swallow failures here:
            # callers must know if the core service stopped unexpectedly.
            try:
                await agent.start()
                logger.info("Manager: Agent finished")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Manager: agent.start() failed")
                raise RuntimeError("Manager Agent runtime failed") from exc
            finally:
                self._started = False
                if self._run_event is not None:
                    self._run_event.set()
        except asyncio.CancelledError:
            try:
                await self._cleanup_after_start_failure()
            except asyncio.CancelledError:
                # A second cancellation is deferred until cleanup completes;
                # re-raise the cancellation that interrupted startup.
                pass
            except Exception:
                logger.exception("Manager: cleanup after cancelled startup failed")
            raise
        except Exception:
            try:
                await self._cleanup_after_start_failure()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Manager: cleanup after failed startup failed")
            raise

    async def stop(self) -> None:
        """Stop the Agent, ticker, and View; retain failures for safe retry."""
        async with self._stop_lock:
            if self._shutdown_complete:
                logger.debug("Manager: shutdown is already complete")
                return

            logger.info("Manager: stopping subsystems")
            self._stopping = True
            self._started = False

            async def safe_stop(label: str, obj: Any, *methods: str) -> bool:
                found_method = False
                for name in methods:
                    fn = getattr(obj, name, None)
                    if not callable(fn):
                        continue
                    found_method = True
                    try:
                        if asyncio.iscoroutinefunction(fn):
                            await fn()
                        else:
                            result = await asyncio.get_running_loop().run_in_executor(None, fn)
                            if inspect.isawaitable(result):
                                await result
                        logger.debug("Manager: %s stopped via %s()", label, name)
                        return True
                    except Exception:
                        logger.exception("Manager: %s.%s() failed", label, name)
                # An object with no shutdown hook owns no resource Manager can stop.
                return not found_method

            components = (
                ("agent", self.agent, ("stop", "shutdown")),
                ("ticker", self._ticker, ("stop",)),
                ("view", self.view, ("stop", "on_shutdown")),
            )
            active_tasks: dict[str, asyncio.Task[bool]] = {}

            for label, obj, methods in components:
                if obj is None:
                    continue

                previous = self._stop_tasks.get(label)
                if previous is not None and previous.done():
                    try:
                        previous_succeeded = previous.result()
                    except asyncio.CancelledError:
                        previous_succeeded = False
                    except Exception:
                        logger.exception(
                            "Manager: previous %s shutdown task failed", label
                        )
                        previous_succeeded = False

                    if previous_succeeded:
                        self._stop_tasks.pop(label, None)
                        continue

                    # A failed/cancelled attempt is terminal. Replace it with a
                    # fresh attempt, but never duplicate an in-flight stop task.
                    self._stop_tasks.pop(label, None)
                    previous = None

                if previous is None:
                    previous = asyncio.create_task(
                        safe_stop(label, obj, *methods),
                        name=f"kaiagotchi-manager-stop-{label}",
                    )
                    self._stop_tasks[label] = previous

                active_tasks[label] = previous

            # Wake run_forever callers as soon as shutdown has been requested;
            # component cleanup may still be completing or awaiting a retry.
            if self._run_event is not None:
                self._run_event.set()

            if active_tasks:
                done, pending = await asyncio.wait(
                    set(active_tasks.values()), timeout=_STOP_TIMEOUT_SECONDS
                )
            else:
                done, pending = set(), set()

            failed_labels: list[str] = []
            pending_labels: list[str] = []
            for label, task in active_tasks.items():
                if task in pending:
                    pending_labels.append(label)
                    continue

                try:
                    succeeded = task.result()
                except asyncio.CancelledError:
                    succeeded = False
                except Exception:
                    logger.exception("Manager: %s shutdown task crashed", label)
                    succeeded = False

                if succeeded:
                    self._stop_tasks.pop(label, None)
                else:
                    failed_labels.append(label)

            incomplete = sorted(self._stop_tasks)
            if incomplete:
                details = []
                if failed_labels:
                    details.append("failed: " + ", ".join(sorted(failed_labels)))
                if pending_labels:
                    details.append("still running: " + ", ".join(sorted(pending_labels)))
                logger.warning(
                    "Manager: shutdown incomplete; retryable components: %s%s",
                    ", ".join(incomplete),
                    f" ({'; '.join(details)})" if details else "",
                )
            else:
                self._shutdown_complete = True
                logger.info("Manager: all subsystems stopped")

            logger.info("Manager: stop attempt finished")

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
