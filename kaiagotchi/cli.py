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
    from kaiagotchi.agent.agent import Agent  # fallback legacy agent
except Exception:
    Agent = None

# Project logger
logger = logging.getLogger("kaiagotchi.cli")


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

        # Prefer Manager if it exists (wires AI subsystems and orchestrates lifecycle)
        if Manager is not None:
            logger.info("Manager found — booting via core.manager.Manager")
            try:
                mgr = Manager(config=config, view=view, system_state=system_state, state_lock=state_lock)
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
            except Exception as e:
                logger.exception("Manager failed to boot; falling back to Agent start", exc_info=e)
                mgr = None

        # If Manager wasn't used, fall back to legacy Agent
        if mgr is None:
            if Agent is None:
                raise RuntimeError("No Manager or Agent implementation available to start Kaiagotchi")
            logger.info("No Manager available — starting legacy Agent directly")
            agent = Agent(config=config, view=view, system_state=system_state, state_lock=state_lock)
            await agent.start()

        # If Manager exists and provides a run loop or awaitable, block until it finishes
        if mgr is not None and hasattr(mgr, "run_forever") and asyncio.iscoroutinefunction(getattr(mgr, "run_forever")):
            await mgr.run_forever()

        # If Agent exists and provides a run loop method, await it (legacy)
        if agent is not None and hasattr(agent, "run_forever") and asyncio.iscoroutinefunction(getattr(agent, "run_forever")):
            await agent.run_forever()

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
        # Clean shutdown for Manager/Agent/View
        try:
            # If manager has a stop/shutdown coroutine, await it
            if mgr is not None:
                stop_fn = getattr(mgr, "stop", None) or getattr(mgr, "shutdown", None)
                if stop_fn:
                    if asyncio.iscoroutinefunction(stop_fn):
                        await stop_fn()
                    else:
                        await asyncio.get_running_loop().run_in_executor(None, stop_fn)
                logger.info("Manager stopped/cleanup complete.")

            # If agent has stop, call/await it
            if agent is not None:
                stop_fn = getattr(agent, "stop", None) or getattr(agent, "shutdown", None)
                if stop_fn:
                    if asyncio.iscoroutinefunction(stop_fn):
                        await stop_fn()
                    else:
                        await asyncio.get_running_loop().run_in_executor(None, stop_fn)
                logger.info("Agent stopped/cleanup complete.")

            # View shutdown: prefer coroutine await if available
            if view is not None:
                try:
                    vs = getattr(view, "stop", None) or getattr(view, "on_shutdown", None)
                    if vs:
                        if asyncio.iscoroutinefunction(vs):
                            await vs()
                        else:
                            # run sync stop in executor to avoid blocking loop
                            await asyncio.get_running_loop().run_in_executor(None, vs)
                    logger.info("View shutdown executed cleanly.")
                except Exception:
                    logger.exception("Error during View shutdown", exc_info=True)
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
