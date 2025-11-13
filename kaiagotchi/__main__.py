"""
Kaiagotchi module entrypoint

Allows launching Kaiagotchi directly via:
    python -m kaiagotchi

This safely initializes logging, loads configuration, and
delegates execution to the core Manager bootstrap routine.
"""

import asyncio
import logging
import os
import sys

from kaiagotchi.core.manager import Manager
from kaiagotchi import __version__

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def _setup_logging() -> logging.Logger:
    """Initialize root logging before Kaiagotchi subsystems load."""
    level = getattr(logging, os.environ.get("KAIA_LOGLEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("kaiagotchi.main")
    logger.info(f"Kaiagotchi v{__version__} logging initialized (level={logging.getLevelName(level)})")
    return logger


# ---------------------------------------------------------------------------
# Main async entrypoint
# ---------------------------------------------------------------------------
async def _run_main() -> int:
    """Asynchronous bootstrap-and-run wrapper."""
    logger = _setup_logging()
    config_path = os.environ.get("KAIA_CONFIG", "/etc/kaiagotchi/config.toml")

    logger.info(f"Kaiagotchi v{__version__} starting...")
    logger.debug(f"Using configuration: {config_path}")

    try:
        exit_code = await Manager.bootstrap_and_run(config_path=config_path)
        logger.info("Kaiagotchi shut down cleanly.")
        return exit_code
    except KeyboardInterrupt:
        logger.info("Kaiagotchi interrupted by user (Ctrl+C).")
        return 0
    except Exception:
        logger.exception("Fatal error during Kaiagotchi runtime.")
        return 1


# ---------------------------------------------------------------------------
# CLI-compatible entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    """CLI wrapper for `python -m kaiagotchi` or console_scripts entrypoint."""
    try:
        sys.exit(asyncio.run(_run_main()))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
