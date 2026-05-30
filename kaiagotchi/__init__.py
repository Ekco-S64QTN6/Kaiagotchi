# kaiagotchi/__init__.py
"""
Kaiagotchi - Adaptive Wireless AI Agent

Top-level package metadata and lazy imports for runtime subsystems.
- Provides safe CLI entrypoint (via `main()`).
- Exposes system utilities (uptime, mem_usage, restart, reboot).
- Defers heavy imports (Manager, View, etc.) until runtime to avoid circular deps.
"""

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "name",
    "set_name",
    "uptime",
    "mem_usage",
    "main",
    "Agent",
    "Manager",
    "View",
    "MonitoringAgent",
    "Automata",
    "RewardEngine",
    "EpochTracker",
    "restart",
    "reboot",
]

import re
import time
import logging
import argparse
import sys
from typing import Optional, Dict, Any
from importlib import import_module

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core metadata and system utilities
# ---------------------------------------------------------------------------
_name: Optional[str] = None


def set_name(new_name: str) -> None:
    """Set the agent name with simple validation."""
    global _name
    if new_name is None:
        raise ValueError("name cannot be None")
    new_name = str(new_name).strip()
    if new_name == "":
        raise ValueError("name cannot be empty")
    if not re.match(r"^[a-zA-Z0-9\\-]{2,25}$", new_name):
        raise ValueError("name must be 2-25 chars, letters/digits/hyphen only")
    _name = new_name


def name() -> str:
    """Return the configured name or a default."""
    global _name
    return _name or "kaiagotchi"


def uptime() -> Optional[float]:
    """Return system uptime in seconds, or None if unavailable."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
            first = f.readline().split()[0]
            return float(first)
    except Exception:
        return None


def mem_usage() -> Dict[str, Any]:
    """Return a minimal memory-info dict or empty dict if unavailable."""
    try:
        info = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()
        return info
    except Exception:
        return {}


def restart():
    """Restart the kaiagotchi service (via systemctl)."""
    import subprocess
    subprocess.run(["systemctl", "restart", "kaiagotchi"], check=False)


def reboot():
    """Reboot the system."""
    import subprocess
    subprocess.run(["reboot"], check=False)


# ---------------------------------------------------------------------------
# Lazy import layer — avoids heavy circular imports at package import time
# ---------------------------------------------------------------------------
def __getattr__(name: str):
    """Dynamically expose heavy runtime components only when accessed."""
    mapping = {
        "Manager": "kaiagotchi.core.manager",
        "View": "kaiagotchi.ui.view",
        "MonitoringAgent": "kaiagotchi.agent.monitoring_agent",
        "Automata": "kaiagotchi.core.automata",
        "RewardEngine": "kaiagotchi.ai.reward",
        "EpochTracker": "kaiagotchi.ai.epoch",
        "Agent": "kaiagotchi.agent.agent",
    }

    if name in mapping:
        module = import_module(mapping[name])
        obj = getattr(module, name)
        globals()[name] = obj  # cache for future lookups
        return obj

    raise AttributeError(f"module 'kaiagotchi' has no attribute '{name}'")


# ---------------------------------------------------------------------------
# Minimal CLI entry point (used in pyproject [project.scripts])
# ---------------------------------------------------------------------------
def main() -> int:
    """CLI entrypoint: handles version/name; does not preload runtime subsystems."""
    parser = argparse.ArgumentParser(prog="kaiagotchi")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--name", type=str, help="set agent name at startup")
    args = parser.parse_args()

    if args.version:
        print(f"kaiagotchi {__version__}")
        return 0

    if args.name:
        try:
            set_name(args.name)
        except ValueError as e:
            _logger.error("Invalid name provided: %s", e)
            print(f"Invalid name: {e}", file=sys.stderr)
            return 2

    _logger.info("kaiagotchi starting (version %s, name=%s)", __version__, name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
