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
from pathlib import Path

# ensure local log directory exists
local_logs = Path(__file__).resolve().parent.parent / "logs"
local_logs.mkdir(exist_ok=True, parents=True)

import argparse
import asyncio
import logging
import os
import sys
import signal
from typing import Optional

# Put package root on path (so "kaiagotchi" imports resolve when run from repo root)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Core imports
from kaiagotchi.config.config import load_config
from kaiagotchi.ui.view import View
from kaiagotchi.data.system_types import (
    SystemState,
    SystemMetrics,
    SessionMetrics,
    NetworkState,
    GlobalSystemState,
)

# Optional imports (Manager preferred)
Manager = None
Agent = None
try:
    from kaiagotchi.core.manager import Manager  # preferred orchestrator
except Exception:
    Manager = None

try:
    from kaiagotchi.agent.agent import Agent
    from kaiagotchi.ui.splash import SplashScreen
    from kaiagotchi.ui.terminal_display import TerminalDisplay
except Exception:
    Agent = None

# Project logger
logger = logging.getLogger("kaiagotchi.cli")

# Global flag for shutdown
_shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    _shutdown_event.set()


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
    # helper flags (handled below in __main__)
    parser.add_argument("--smoke-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diag-ui", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def setup_logging(debug: bool = False) -> None:
    """Configure logging to separate debug from UI output."""
    # Try log directories in order of preference until we find one we can write to
    log_dirs = [
        str(local_logs),
        os.path.expanduser("~/kaiagotchi/logs"),
        "/var/log/kaiagotchi"
    ]

    log_dir: Optional[str] = None
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
            except (IOError, OSError):
                continue
        except (IOError, OSError):
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
    args = parse_arguments()
    setup_logging(args.debug)

    logger.info("Starting Kaiagotchi...")

    view: Optional[View] = None
    mgr = None
    agent = None

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    def handle_signal():
        logger.info("Signal received, initiating shutdown...")
        _shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows support or non-main thread
            signal.signal(sig, lambda s, f: handle_signal())

    try:
        # Load configuration
        config = load_config(args.config)
        logger.info(f"Configuration loaded from {args.config}")

        # Manual override if requested
        if args.manual:
            config.setdefault("main", {})["mode"] = "manual"
            logger.info("Manual mode enabled via CLI")

        # Shared system state
        system_state = SystemState(
            current_system_state=GlobalSystemState.BOOTING,
            config_hash="cli_config_hash",
            network=NetworkState(access_points={}, interfaces={}, last_scan_time=0.0),
            metrics=SystemMetrics(cpu_usage=0.0, memory_usage=0.0, disk_free_gb=0.0, uptime_seconds=0.0),
            agents={},
            session_metrics=SessionMetrics(duration_seconds=0.0, handshakes_secured=0),
        )
        state_lock = asyncio.Lock()

        # Initialize View (do not call start_rotation here; Manager/Agent will control lifecycle)
        view = View(config)
        view.suppress_output = True  # Suppress output during splash

        # Show splash screen (after View init so it clears screen first)
        splash = None
        try:
            splash = SplashScreen()
            # Don't await here, we'll do it in parallel with startup
        except Exception as e:
            logger.warning(f"Failed to init splash screen: {e}")

        # Prefer Manager if it exists (wires AI subsystems and orchestrates lifecycle)
        if Manager is not None:
            logger.info("Manager found — booting via core.manager.Manager")
            try:
                mgr = Manager(config=config, view=view, system_state=system_state, state_lock=state_lock)
                
                # Define startup task
                async def start_manager():
                    # Manager should expose an async 'start' or 'bootstrap' method; attempt both
                    if hasattr(mgr, "bootstrap") and asyncio.iscoroutinefunction(getattr(mgr, "bootstrap")):
                        await mgr.bootstrap()
                    elif hasattr(mgr, "start") and asyncio.iscoroutinefunction(getattr(mgr, "start")):
                        await mgr.start()
                    else:
                        # If manager.start is sync, run it in executor
                        start_fn = getattr(mgr, "start", None)
                        if start_fn:
                            await asyncio.get_running_loop().run_in_executor(None, start_fn)
                    logger.info("Manager booted successfully.")

                # Run splash and manager startup concurrently
                # We want splash to run for at least 15s, but manager can start in background
                splash_task = asyncio.create_task(splash.show(duration=15.0))
                manager_task = asyncio.create_task(start_manager())
                shutdown_wait = asyncio.create_task(_shutdown_event.wait())
                
                # Wait for splash OR shutdown
                done, pending = await asyncio.wait(
                    [splash_task, shutdown_wait],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                if shutdown_wait in done:
                    logger.info("Shutdown requested during splash/startup")
                    splash_task.cancel()
                    manager_task.cancel()
                    return 0

                # If splash finished, check manager status
                if manager_task.done():
                    try:
                        await manager_task
                    except Exception as e:
                        logger.error(f"Manager startup failed: {e}")
                        raise e
                
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
                logger.exception("Manager failed to boot; falling back to Agent start", exc_info=e)
                mgr = None

        # If Manager wasn't used, fall back to legacy Agent
        # ------------------------------------------------------------------
        # 2. Fallback: Run Agent directly if Manager is missing
        # ------------------------------------------------------------------
        if mgr is None:
            if Agent is None:
                raise RuntimeError("No Manager or Agent implementation available to start Kaiagotchi")
            logger.info("No Manager available — starting legacy Agent directly")
            
            try:
                # Create agent
                agent = Agent(
                    config=config,
                    system_state=system_state,
                    state_lock=state_lock
                )
                
                # Register signal handlers for clean shutdown
                loop = asyncio.get_running_loop()
                
                def handle_signal():
                    _log.info("Signal received, initiating shutdown...")
                    asyncio.create_task(shutdown(agent))

                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, handle_signal)
                    except NotImplementedError:
                        pass # Windows support

                # Start agent in background while splash runs
                agent_start_task = asyncio.create_task(agent.start())
                shutdown_wait = asyncio.create_task(_shutdown_event.wait())
                
                if splash:
                    splash_task = asyncio.create_task(splash.show(duration=15.0))
                    done, pending = await asyncio.wait(
                        [splash_task, shutdown_wait],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    if shutdown_wait in done:
                         splash_task.cancel()
                         agent_start_task.cancel()
                         return 0
                else:
                    # If splash failed to init, just wait a bit or proceed
                    done, pending = await asyncio.wait(
                        [asyncio.create_task(asyncio.sleep(1.0)), shutdown_wait],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    if shutdown_wait in done:
                        agent_start_task.cancel()
                        return 0
                
                    if shutdown_wait in done:
                        agent_start_task.cancel()
                        return 0
                
                # Re-register signal handlers (Rich Progress might have restored defaults)
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, handle_signal)
                    except NotImplementedError:
                        signal.signal(sig, lambda s, f: handle_signal())

                # Enable view output
                view.suppress_output = False
                
                # Now wait for agent task (which runs forever)
                # But we need to handle signals, so we wait on the shutdown event
                # shutdown_wait is already created/used, let's recreate or reuse?
                # It might have completed if we are here? No, if we are here, splash completed first.
                # So shutdown_wait is still pending.
                
                done, pending = await asyncio.wait(
                    [agent_start_task, shutdown_wait],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                if agent_start_task in done:
                    # Agent exited on its own
                    try:
                        await agent_start_task
                    except Exception as e:
                        logger.error(f"Agent task failed: {e}")
                        
                if shutdown_task in done:
                    logger.info("Shutdown event triggered")
                    
                # Cancel pending
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            except asyncio.CancelledError:
                _log.info("Main task cancelled")
            except Exception as e:
                _log.exception(f"Fatal error in agent: {e}")
            finally:
                await shutdown(agent)
                
            return 0 # Agent path returns 0 on successful completion/shutdown

        # ------------------------------------------------------------------
        # 3. Run Manager (Preferred)
        # ------------------------------------------------------------------
        # Create a task for the main run loop
        main_task = None
        if mgr is not None and hasattr(mgr, "run_forever") and asyncio.iscoroutinefunction(getattr(mgr, "run_forever")):
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
            
            if main_task in done:
                try:
                    await main_task
                except Exception as e:
                    logger.error(f"Manager task failed: {e}")

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

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
        # Clean shutdown for Manager/Agent/View with proper timeout
        try:
            # Give shutdown process time to complete
            shutdown_timeout = 10.0  # Increased timeout for proper PCAP archiving
            
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
                    except asyncio.TimeoutError:
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
                    except asyncio.TimeoutError:
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
                except asyncio.TimeoutError:
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


def run() -> int:
    """Main CLI entrypoint wrapper that runs the async runner."""
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
                await v.show_startup_sequence()
                dummy = {"network": {"access_points": {"a": {}, "b": {}, "c": {}}, "current_channel": 6},
                         "current_system_state": "MONITORING"}
                for _ in range(5):
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