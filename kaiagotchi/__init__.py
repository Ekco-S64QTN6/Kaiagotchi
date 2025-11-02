# Minimal package metadata — must NOT import legacy packages during build
__version__ = "0.1.0"
__all__ = ["__version__", "name", "set_name", "uptime", "mem_usage", "main", "Agent"] # FIX 1: Corrected syntax and included 'Agent'

import re
import time
import logging
import argparse
import sys
from typing import Optional, Dict, Any

_logger = logging.getLogger(__name__)

# FIX 2: Import the Agent class from the .agent sub-package
from .agent import Agent

_name: Optional[str] = None

def set_name(new_name: str) -> None:
    """Set the agent name with simple validation."""
    global _name
    if new_name is None:
        raise ValueError("name cannot be None")
    new_name = str(new_name).strip()
    if new_name == "":
        raise ValueError("name cannot be empty")
    if not re.match(r"^[a-zA-Z0-9\-]{2,25}$", new_name):
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

def main() -> int:
    """
    Minimal entry point used by [project.scripts] in pyproject.toml.
    Keep this light — do NOT import heavy subsystems at module import time.
    """
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

    # Lazy import example for runtime-only modules (do not import during build)
    # from .log_config import setup_logging  # import inside runtime flow if needed

    _logger.info("kaiagotchi starting (version %s, name=%s)", __version__, name())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())