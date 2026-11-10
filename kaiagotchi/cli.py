#!/usr/bin/env python3
# kaiagotchi/cli.py
"""
Kaiagotchi CLI entry point — async startup, display abstraction, and clean shutdown.

Behavior:
- Prefer booting via core.manager.Manager (if present) which wires AI/automata/etc.
- Fallback to Agent startup for legacy behavior.
- Robust logging initialization to a writable logs directory.
- Cleanly awaits view shutdown hooks to avoid "un-awaited coroutine" warnings.
- Provides --smoke-ui and --diag-ui helpers for local testing.
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kaiagotchi.config.config import load_config
from kaiagotchi.data.system_types import GlobalSystemState, SystemState
from kaiagotchi.ui.view import View

if TYPE_CHECKING:
    from kaiagotchi.agent.agent import Agent as AgentType
    from kaiagotchi.core.manager import Manager as ManagerType
    from kaiagotchi.ui.splash import SplashScreen as SplashScreenType
    from kaiagotchi.ui.terminal_display import TerminalDisplay as TerminalDisplayType
    from kaiagotchi.ui.web.server import WebServer as WebServerType
else:
    AgentType = Any
    ManagerType = Any
    SplashScreenType = Any
    TerminalDisplayType = Any
    WebServerType = Any

logger = logging.getLogger("kaiagotchi.cli")

# Preferred local log directory (created lazily in setup_logging()).
local_logs = Path(__file__).resolve().parent.parent / "logs"

# Optional imports (Manager preferred). Keep typed None fallbacks so the
# legacy CLI path remains available when optional subsystems cannot be loaded.
Manager: type[ManagerType] | None = None
try:
    from kaiagotchi.core.manager import Manager as _Manager
except Exception:
    pass
else:
    Manager = _Manager

Agent: type[AgentType] | None = None
SplashScreen: type[SplashScreenType] | None = None
TerminalDisplay: type[TerminalDisplayType] | None = None
WebServer: type[WebServerType] | None = None
try:
    from kaiagotchi.agent.agent import Agent as _Agent
    from kaiagotchi.ui.splash import SplashScreen as _SplashScreen
    from kaiagotchi.ui.terminal_display import TerminalDisplay as _TerminalDisplay
    from kaiagotchi.ui.web.server import WebServer as _WebServer
except Exception as exc:
    logger.error(
        "Failed to import core subsystems (Agent/UI/Splash/Web): %s",
        exc,
        exc_info=True,
    )
else:
    Agent = _Agent
    SplashScreen = _SplashScreen
    TerminalDisplay = _TerminalDisplay
    WebServer = _WebServer

# Global flag for shutdown
_shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    _shutdown_event.set()

async def _await_cleanup_resilient(cleanup: Any) -> None:
    """Finish cleanup before propagating caller cancellation.

    Repeated cancellation can otherwise abort the await of a shielded cleanup
    task. Continue waiting until it reaches a terminal state, then re-raise the
    caller's cancellation so shutdown remains observable to the caller.
    """
    cleanup_task = asyncio.create_task(cleanup)
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
            # Retrieve the child error below, after its task is terminal.
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


# ----------------------------------------------------------
# CLI SETUP
# ----------------------------------------------------------
def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Kaiagotchi - Autonomous Wireless Security Agent")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--config",
        type=str,
        default="/etc/kaiagotchi/config.toml",
        help="Path to configuration file",
    )
    parser.add_argument("--manual", action="store_true", help="Start in manual mode")
    parser.add_argument(
        "--capture-interface",
        "--interface",
        dest="capture_iface",
        help="Dedicated capture adapter (overrides main.capture_iface)",
    )
    parser.add_argument(
        "--reserve-interface",
        dest="reserve_interfaces",
        action="append",
        default=[],
        help="Additional dedicated capture adapter to reserve from NetworkManager (repeatable)",
    )
    parser.add_argument("--web", action="store_true", default=None, help="Enable Cyber-Deck Web UI (default: enabled)")
    parser.add_argument("--no-web", action="store_true", help="Disable Cyber-Deck Web UI")
    parser.add_argument("--tui", action="store_true", help="Force curses TUI mode in terminal")
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Disable the curses display (for web-only or headless operation)",
    )
    parser.add_argument("--port", type=int, default=None, help="Port for Web UI (default: 8080)")
    parser.add_argument("--host", type=str, default=None, help="Host address for Web UI (non-loopback binds require web.auth_token or KAIA_WEB_AUTH_TOKEN)")
    # helper flags (handled below in __main__)
    parser.add_argument("--smoke-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diag-ui", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def _web_enabled(args: Any, config: dict[str, Any]) -> bool:
    """Resolve web-mode flags; --tui explicitly means terminal-only mode."""
    if getattr(args, "tui", False) or getattr(args, "no_web", False):
        return False
    if getattr(args, "web", None):
        return True
    web_config = config.get("web", {})
    return bool(web_config.get("enabled", True)) if isinstance(web_config, dict) else True


def _terminal_display_enabled(args: Any, config: dict[str, Any], web_available: bool = True) -> bool:
    """Select one interactive surface: curses when web is off, never both."""
    return (
        not getattr(args, "no_tui", False)
        and (not _web_enabled(args, config) or not web_available)
    )


def _create_splash_screen() -> Any | None:
    """Create the optional splash screen without blocking headless startup."""
    if SplashScreen is None:
        logger.warning("Splash screen implementation is unavailable")
        return None
    try:
        return SplashScreen()
    except Exception as exc:
        logger.warning("Failed to init splash screen: %s", exc)
        return None


def setup_logging(debug: bool = False) -> None:
    """Configure logging to separate debug from UI output."""
    # Try log directories in order of preference until we find one we can write to
    log_dirs = [
        str(local_logs),
        os.path.expanduser("~/kaiagotchi/logs"),
        "/var/log/kaiagotchi"
    ]

    log_dir: str | None = None
    for d in log_dirs:
        try:
            os.makedirs(d, exist_ok=True)
            # Test write access
            test_file = os.path.join(d, ".write_test")
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.unlink(test_file)
                log_dir = d
                break
            except OSError:
                continue
        except OSError:
            continue

    if not log_dir:
        # If we cannot write anywhere, fallback to current dir (best-effort) but warn
        log_dir = os.getcwd()
        print("WARNING: Could not find preferred writable log directory; using cwd for logs.", file=sys.stderr)

    # Setup log files
    main_log = os.path.join(log_dir, "kaiagotchi.log")

    # Base logging format
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Clear any existing handlers
    for handler in list(root.handlers):
        root.removeHandler(handler)

    try:
        # Main log file - INFO and above
        main_handler = logging.FileHandler(main_log)
        main_handler.setFormatter(logging.Formatter(log_format))
        main_handler.setLevel(logging.INFO)
        root.addHandler(main_handler)

        # Console - WARNING and above only (so UI can control its own output)
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(log_format))
        console.setLevel(logging.WARNING)
        root.addHandler(console)

        # Silence some noisy UI loggers from printing to console repeatedly; keep file handler
        for logger_name in ["kaiagotchi.ui.view", "kaiagotchi.ui.terminal_display"]:
            ui_logger = logging.getLogger(logger_name)
            ui_logger.propagate = False
            ui_logger.handlers = []
            ui_logger.addHandler(main_handler)
            ui_logger.setLevel(logging.DEBUG if debug else logging.INFO)

        logger.info(f"Logging initialized. Writing to {log_dir}")
    except Exception as e:
        print(f"ERROR: Failed to initialize logging: {e}", file=sys.stderr)
        sys.exit(1)


# ----------------------------------------------------------
# CORE EXECUTION
# ----------------------------------------------------------
async def run_agent() -> int:
    """Run the Kaiagotchi agent asynchronously.

    Prefer Manager (if available) to wire all subsystems. Otherwise fall back to Agent.
    Returns process exit code (0 success, non-zero error).
    """
    global _shutdown_event
    # Each invocation gets a fresh event. A previous run's signal must not make
    # a later in-process run exit during startup.
    _shutdown_event = asyncio.Event()

    # Clear LINES and COLUMNS from environment to bypass python/rich/shutil terminal size caching
    os.environ.pop("LINES", None)
    os.environ.pop("COLUMNS", None)

    args = parse_arguments()
    setup_logging(args.debug)

    logger.info("Starting Kaiagotchi...")

    view: View | None = None
    mgr = None
    agent = None
    # Initialized before the try so early configuration/import failures still
    # pass through cleanup without masking the original startup error.
    web_server = None

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    shutdown_requested = 0
    def handle_signal():
        nonlocal shutdown_requested
        shutdown_requested += 1
        if shutdown_requested > 1:
            # Never bypass the monitor's process-group reaping with os._exit().
            # The first signal already requested orderly shutdown; later signals
            # are acknowledged while the bounded cleanup path finishes.
            logger.warning("Additional shutdown signal received; cleanup remains active")
            return
        logger.info("Signal received, initiating shutdown...")
        _shutdown_event.set()
        if view and view.display:
            try:
                view.display.stop()
            except Exception:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows support or non-main thread
            signal.signal(sig, lambda s, f: handle_signal())

    display_monitor_task = None
    try:
        # Load configuration
        config = load_config(args.config)
        logger.info(f"Configuration loaded from {args.config}")

        capture_iface = getattr(args, "capture_iface", None)
        if capture_iface:
            config.setdefault("main", {})["capture_iface"] = capture_iface
        reserve_interfaces = getattr(args, "reserve_interfaces", None) or []
        if reserve_interfaces:
            main_config = config.setdefault("main", {})
            configured = main_config.get("capture_ifaces", [])
            if isinstance(configured, str):
                configured = [configured]
            elif not isinstance(configured, list):
                configured = []
            main_config["capture_ifaces"] = list(
                dict.fromkeys([*configured, *reserve_interfaces])
            )

        # Manual override if requested
        if args.manual:
            config.setdefault("main", {})["mode"] = "manual"
            logger.info("Manual mode enabled via CLI")

        # Shared system state
        system_state = SystemState.minimal(
            current_system_state=GlobalSystemState.BOOTING,
            config_hash="cli_config_hash",
        )
        state_lock = asyncio.Lock()

        # Resolve the interface before constructing View. A web backend must not
        # also create a curses thread in the launcher's terminal.
        web_enabled = _web_enabled(args, config)
        terminal_enabled = _terminal_display_enabled(args, config, WebServer is not None)

        # Initialize View (do not call start_rotation here; Manager/Agent will control lifecycle)
        view = View(config, create_display=terminal_enabled)
        view.suppress_output = True  # Suppress output during terminal splash

        if args.port:
            config.setdefault("web", {})["port"] = args.port
        if args.host:
            config.setdefault("web", {})["host"] = args.host

        if web_enabled and WebServer is not None:
            try:
                web_server = WebServer(config, state_provider=view.get_snapshot_dict)
                web_server.start()
                w_host = config.get("web", {}).get("host", "127.0.0.1")
                w_port = config.get("web", {}).get("port", 8080)
                logger.info("Cyber-Deck Web UI configured at bind address %s:%d", w_host, w_port)
            except Exception as e:
                logger.warning(f"Could not start Cyber-Deck WebServer: {e}")

        async def monitor_display_quit():
            while not _shutdown_event.is_set():
                if view and view.display and getattr(view.display, "should_quit", False):
                    logger.info("Shutdown requested via UI (Q key)")
                    _shutdown_event.set()
                    break
                await asyncio.sleep(0.1)

        display_monitor_task = asyncio.create_task(monitor_display_quit())

        # Only terminal mode owns the terminal splash. Web mode presents its
        # own in-dashboard startup overlay; headless mode stays silent.
        splash = _create_splash_screen() if terminal_enabled else None

        # Prefer Manager if it exists (wires AI subsystems and orchestrates lifecycle)
        if Manager is not None:
            logger.info("Manager found — booting via core.manager.Manager")
            try:
                mgr = Manager(config=config, view=view, system_state=system_state, state_lock=state_lock)

                # Define startup task
                async def start_manager():
                    # Manager should expose an async 'start' or 'bootstrap' method; attempt both
                    if hasattr(mgr, "bootstrap") and asyncio.iscoroutinefunction(mgr.bootstrap):
                        await mgr.bootstrap()
                    elif hasattr(mgr, "start") and asyncio.iscoroutinefunction(mgr.start):
                        await mgr.start()
                    else:
                        # If manager.start is sync, run it in executor
                        start_fn = getattr(mgr, "start", None)
                        if start_fn:
                            await asyncio.get_running_loop().run_in_executor(None, start_fn)
                    logger.info("Manager booted successfully.")

                # Run splash and manager startup concurrently, but observe both:
                # startup failures must not hide behind the splash, and run_forever
                # must not race an unfinished bootstrap/start operation.
                manager_task = asyncio.create_task(start_manager())
                shutdown_wait = asyncio.create_task(_shutdown_event.wait())
                startup_barrier = (
                    asyncio.create_task(splash.show(duration=15.0))
                    if splash
                    else asyncio.create_task(asyncio.sleep(1.0))
                )
                manager_startup_observed = False
                barrier_result_observed = False

                try:
                    while not startup_barrier.done() or not manager_startup_observed:
                        if startup_barrier.done() and not barrier_result_observed:
                            barrier_result_observed = True
                            try:
                                startup_barrier.result()
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                # A visual splash failure must not strand startup.
                                logger.warning("Splash/startup delay failed", exc_info=True)

                        if manager_task.done() and not manager_startup_observed:
                            # Await immediately so an exception is observed as
                            # soon as bootstrap/start fails, not after the splash.
                            await manager_task
                            manager_startup_observed = True
                            continue

                        waiting: list[asyncio.Task[Any]] = [shutdown_wait]
                        if not startup_barrier.done():
                            waiting.append(startup_barrier)
                        if not manager_startup_observed and not manager_task.done():
                            waiting.append(manager_task)

                        done, _pending = await asyncio.wait(
                            waiting,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if shutdown_wait in done:
                            logger.info("Shutdown requested during manager startup")
                            for task in (startup_barrier, manager_task):
                                if not task.done():
                                    task.cancel()
                            await asyncio.gather(
                                startup_barrier, manager_task, return_exceptions=True
                            )
                            return 0

                        if manager_task in done and not manager_startup_observed:
                            await manager_task
                            manager_startup_observed = True

                    # Don't leave a signal waiter behind once startup is complete.
                    if not shutdown_wait.done():
                        shutdown_wait.cancel()
                    try:
                        await shutdown_wait
                    except asyncio.CancelledError:
                        pass

                except BaseException:
                    # Preserve the startup exception while preventing orphaned
                    # splash, manager, or signal-wait tasks.
                    for task in (startup_barrier, manager_task, shutdown_wait):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        startup_barrier, manager_task, shutdown_wait,
                        return_exceptions=True,
                    )
                    raise

                # Re-register signal handlers (Rich Progress might have restored defaults)
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, handle_signal)
                    except NotImplementedError:
                        signal.signal(sig, lambda s, f: handle_signal())

                # Enable view output and force initial draw
                view.suppress_output = False
                # We can trigger a redraw by updating state or just letting the loop catch it
                # But let's force one to be snappy
                if view.display:
                    # Just a dummy update to trigger redraw if needed, or rely on next loop
                    pass

            except Exception as e:
                # Manager bootstrap may already have constructed part of an Agent
                # and started resources. Falling back to a second legacy Agent can
                # duplicate resource owners and hide the original failure.
                logger.exception("Manager failed to boot; refusing legacy fallback", exc_info=e)
                raise RuntimeError("Manager startup failed") from e

        # If Manager wasn't used, fall back to legacy Agent
        # ------------------------------------------------------------------
        # 2. Fallback: Run Agent directly if Manager is missing
        # ------------------------------------------------------------------
        if mgr is None:
            if Agent is None:
                raise RuntimeError("No Manager or Agent implementation available to start Kaiagotchi")
            logger.info("No Manager available — starting legacy Agent directly")

            fallback_exit_code = 0
            try:
                # Create agent — pass the shared view so it doesn't create a
                # second View that overwrites the display's state provider.
                agent = Agent(
                    config=config,
                    view=view,
                    system_state=system_state,
                    state_lock=state_lock
                )

                # Signal handlers (registered once in run_agent) set
                # _shutdown_event; the finally block performs agent teardown.

                # Run legacy Agent startup alongside the splash, but observe the
                # Agent task throughout. A failed start must not be hidden by the
                # full splash delay, and the same shutdown waiter must remain live
                # after the splash ends.
                agent_start_task = asyncio.create_task(agent.start())
                shutdown_wait = asyncio.create_task(_shutdown_event.wait())
                startup_barrier = (
                    asyncio.create_task(splash.show(duration=15.0))
                    if splash
                    else asyncio.create_task(asyncio.sleep(1.0))
                )

                try:
                    while not startup_barrier.done():
                        if shutdown_wait.done():
                            logger.info("Shutdown requested during Agent startup")
                            return 0

                        if agent_start_task.done():
                            # Consume a startup exception immediately rather than
                            # waiting until the splash finishes.
                            await agent_start_task
                            if not _shutdown_event.is_set():
                                logger.error("Agent exited before startup completed")
                                fallback_exit_code = 1
                            return fallback_exit_code

                        legacy_startup_tasks: list[asyncio.Task[Any]] = [
                            startup_barrier,
                            shutdown_wait,
                            agent_start_task,
                        ]
                        done, _pending = await asyncio.wait(
                            legacy_startup_tasks,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if shutdown_wait in done:
                            logger.info("Shutdown requested during Agent startup")
                            return 0

                    try:
                        startup_barrier.result()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.warning("Splash/startup delay failed", exc_info=True)

                    if agent_start_task.done():
                        try:
                            await agent_start_task
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Agent failed during startup")
                            fallback_exit_code = 1
                        else:
                            if not _shutdown_event.is_set():
                                logger.error("Agent exited before the main wait loop")
                                fallback_exit_code = 1
                        return fallback_exit_code

                    # Re-register signal handlers (Rich Progress might have restored defaults)
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        try:
                            loop.add_signal_handler(sig, handle_signal)
                        except NotImplementedError:
                            signal.signal(sig, lambda s, f: handle_signal())

                    view.suppress_output = False

                    done, pending = await asyncio.wait(
                        [agent_start_task, shutdown_wait],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if agent_start_task in done:
                        try:
                            await agent_start_task
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception("Agent task failed")
                            fallback_exit_code = 1

                    if shutdown_wait in done:
                        logger.info("Shutdown event triggered")

                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    return fallback_exit_code

                finally:
                    # Every exit path owns and reaps these tasks. In particular,
                    # never cancel and then reuse shutdown_wait.
                    for task in (startup_barrier, shutdown_wait, agent_start_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        startup_barrier, shutdown_wait, agent_start_task,
                        return_exceptions=True,
                    )

            except asyncio.CancelledError:
                logger.info("Main task cancelled")
            except Exception as e:
                logger.exception(f"Fatal error in agent: {e}")
                fallback_exit_code = 1
            finally:
                if agent:
                    try:
                        await agent.stop()
                    except Exception as stop_err:
                        logger.error(f"Error stopping agent: {stop_err}")

            return fallback_exit_code

        # ------------------------------------------------------------------
        # 3. Run Manager (Preferred)
        # ------------------------------------------------------------------
        # Create a task for the main run loop
        main_task = None
        if mgr is not None and hasattr(mgr, "run_forever") and asyncio.iscoroutinefunction(mgr.run_forever):
            main_task = asyncio.create_task(mgr.run_forever())

        # Wait for either shutdown signal or main task completion
        if main_task:
            # FIXED: Create a task for the shutdown event wait (required in Python 3.13+)
            shutdown_task = asyncio.create_task(_shutdown_event.wait())

            done, pending = await asyncio.wait(
                [main_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            if shutdown_task in done:
                logger.info("Shutdown event triggered")

            manager_exit_code = 0
            if main_task in done:
                try:
                    await main_task
                except Exception:
                    logger.exception("Manager task failed")
                    manager_exit_code = 1

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if manager_exit_code:
                return manager_exit_code

        # Normal exit
        return 0

    except FileNotFoundError:
        logger.error(f"Configuration file not found: {args.config}")
        return 1
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        return 0
    except Exception as e:
        logger.critical(f"Failed to start Kaiagotchi: {e}", exc_info=True)
        return 1

    finally:
        async def _cleanup_runtime() -> None:
            # Clean shutdown for Manager/Agent/View with proper timeout
            try:
                # Cancel display monitor task
                if display_monitor_task and not display_monitor_task.done():
                    display_monitor_task.cancel()
                    try:
                        await display_monitor_task
                    except asyncio.CancelledError:
                        pass

                # Give shutdown process time to complete
                shutdown_timeout = 5.0  # Reduced to 5s max hard timeout

                # Stop WebServer
                if web_server:
                    try:
                        await asyncio.to_thread(web_server.stop)
                        logger.info("WebServer stopped cleanly.")
                    except Exception as ws_err:
                        logger.error(f"Error stopping WebServer: {ws_err}")

                # If manager has a stop/shutdown coroutine, await it
                if mgr is not None:
                    stop_fn = getattr(mgr, "stop", None) or getattr(mgr, "shutdown", None)
                    if stop_fn:
                        try:
                            if asyncio.iscoroutinefunction(stop_fn):
                                await asyncio.wait_for(stop_fn(), timeout=shutdown_timeout)
                            else:
                                await asyncio.wait_for(
                                    asyncio.get_running_loop().run_in_executor(None, stop_fn),
                                    timeout=shutdown_timeout
                                )
                            logger.info("Manager stopped/cleanup complete.")
                        except TimeoutError:
                            logger.warning("Manager shutdown timed out, continuing...")
                        except Exception as e:
                            logger.error(f"Error stopping manager: {e}")

                # If agent has stop, call/await it
                if agent is not None:
                    stop_fn = getattr(agent, "stop", None) or getattr(agent, "shutdown", None)
                    if stop_fn:
                        try:
                            if asyncio.iscoroutinefunction(stop_fn):
                                await asyncio.wait_for(stop_fn(), timeout=shutdown_timeout)
                            else:
                                await asyncio.wait_for(
                                    asyncio.get_running_loop().run_in_executor(None, stop_fn),
                                    timeout=shutdown_timeout
                                )
                            logger.info("Agent stopped/cleanup complete.")
                        except TimeoutError:
                            logger.warning("Agent shutdown timed out, continuing...")
                        except Exception as e:
                            logger.error(f"Error stopping agent: {e}")

                # View shutdown: prefer coroutine await if available
                if view is not None:
                    try:
                        vs = getattr(view, "stop", None) or getattr(view, "on_shutdown", None)
                        if vs:
                            if asyncio.iscoroutinefunction(vs):
                                await asyncio.wait_for(vs(), timeout=5.0)
                            else:
                                # run sync stop in executor to avoid blocking loop
                                await asyncio.wait_for(
                                    asyncio.get_running_loop().run_in_executor(None, vs),
                                    timeout=5.0
                                )
                        logger.info("View shutdown executed cleanly.")
                    except TimeoutError:
                        logger.warning("View shutdown timed out, continuing...")
                    except Exception:
                        logger.exception("Error during View shutdown", exc_info=True)

                # Show goodbye message
                if view is not None and view.display:
                    try:
                        view.display.show_goodbye()
                    except Exception:
                        pass

                # Additional short delay to ensure all cleanup completes
                await asyncio.sleep(0.5)

            except Exception:
                logger.exception("Error during final cleanup", exc_info=True)

        await _await_cleanup_resilient(_cleanup_runtime())

def doctor_main(argv: list[str] | None = None) -> int:
    """Print read-only NetworkManager, kernel, process, and journal diagnostics."""
    parser = argparse.ArgumentParser(
        prog="kaiagotchi doctor",
        description="Diagnose capture-adapter reservation and shutdown state.",
    )
    parser.add_argument(
        "--config",
        default="/etc/kaiagotchi/config.toml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--capture-interface",
        "--interface",
        dest="capture_iface",
        help="Capture adapter override (defaults to configured main.capture_iface)",
    )
    parser.add_argument(
        "--reserve-interface",
        dest="reserve_interfaces",
        action="append",
        default=[],
        help="Additional dedicated adapter to inspect (repeatable)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        if args.capture_iface:
            config.setdefault("main", {})["capture_iface"] = args.capture_iface
        if args.reserve_interfaces:
            main_config = config.setdefault("main", {})
            configured = main_config.get("capture_ifaces", [])
            if isinstance(configured, str):
                configured = [configured]
            elif not isinstance(configured, list):
                configured = []
            main_config["capture_ifaces"] = list(
                dict.fromkeys([*configured, *args.reserve_interfaces])
            )

        from kaiagotchi.network.networkmanager import build_doctor_report

        report = build_doctor_report(config, args.capture_iface)
    except Exception as exc:
        print(f"Kaiagotchi doctor: unable to collect diagnostics: {exc}", file=sys.stderr)
        return 1

    print("Kaiagotchi doctor")
    print(f"NetworkManager reservation: {report['reservation_path']}")
    if report["reservation_error"]:
        print(f"  Read error: {report['reservation_error']}")
    else:
        print(f"  File: {'present' if report['reservation_exists'] else 'MISSING'}")
    selectors = report["config_macs"]
    print(
        "  MAC selectors: "
        + (", ".join(selectors) if selectors else "(none)")
    )

    print("Intended capture adapters:")
    healthy = True
    for item in report["interfaces"]:
        mac = item["mac"] or f"unavailable ({item['mac_error']})"
        reserved = "yes" if item["in_config"] else "NO"
        nm_managed = item["nm_managed"]
        nm_ok = nm_managed == "no"
        healthy = healthy and bool(item["mac"]) and item["in_config"] and nm_ok
        print(
            f"  {item['name']}: MAC={mac}; in config={reserved}; "
            f"NM-MANAGED={nm_managed}; kernel type={item['kernel_type']}"
        )

    uplink = report["uplink"]
    if uplink["name"]:
        print(
            f"Primary/uplink adapter: {uplink['name']}; "
            f"NetworkManager state={uplink['state']}"
        )

    processes = report["airodump_processes"]
    if processes:
        print("airodump-ng processes:")
        for process in processes:
            print(
                f"  PID={process['pid']} PPID={process['ppid']}; "
                f"{process['command']}"
            )
        healthy = False
    else:
        print("airodump-ng processes: none")

    journal = report["journal_scan_rejections"]
    if journal["available"]:
        print(
            "Plasma unmanaged-device scan rejections in current boot: "
            f"{journal['count']}"
        )
        for sample in journal["samples"]:
            print(f"  {sample}")
    else:
        print(
            "Plasma journal scan rejections: unavailable"
            + (f" ({journal.get('error')})" if journal.get("error") else "")
        )

    return 0 if healthy else 1


def run() -> int:
    """Main CLI entrypoint wrapper that runs the async runner or doctor."""
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        return doctor_main(sys.argv[2:])
    try:
        return asyncio.run(run_agent())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        return 0
    except Exception:
        logger.exception("Critical failure in run()", exc_info=True)
        return 2


# ----------------------------------------------------------
# Module CLI helpers: smoke / diag (updated to avoid creating a second TerminalDisplay)
# ----------------------------------------------------------
if __name__ == "__main__":
    # Lightweight smoke UI mode for quick visual checks without full agent startup
    import argparse as _argparse

    p = _argparse.ArgumentParser(add_help=False)
    p.add_argument("--smoke-ui", action="store_true", help="Run UI loop for 10s with dummy state (debug only)")
    p.add_argument("--diag-ui", action="store_true", help="Show current UI debug configuration and exit")
    parsed, _ = p.parse_known_args()

    if parsed.smoke_ui:
        async def smoke_test():
            v = View({})
            try:
                await v.start()
                await v.on_starting()
                dummy = {"network": {"access_points": {"a": {}, "b": {}, "c": {}}, "current_channel": 6},
                         "current_system_state": "MONITORING"}
                for _ in range(5):
                    if v.display:
                        await v.display.draw(dummy)
                    await asyncio.sleep(1.0)
            finally:
                await v.stop()
        try:
            asyncio.run(smoke_test())
        except Exception as e:
            print(f"Smoke UI test failed: {e}", file=sys.stderr)
        sys.exit(0)

    if parsed.diag_ui:
        v = View({})
        debug_env = os.getenv("KAIA_UI_DEBUG", "0")
        print("Kaiagotchi UI Diagnostics:")
        print(f"  KAIA_UI_DEBUG={debug_env}")
        print(f"  TerminalDisplay._ui_debug={getattr(v.display, '_ui_debug', False)}")
        sys.exit(0)

    # Normal run
    sys.exit(run())
