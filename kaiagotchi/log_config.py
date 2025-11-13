# kaiagotchi/log_config.py
"""
Centralized logging configuration for Kaiagotchi.

Goals:
 - All logs, prints, and warnings (including Pydantic serialization warnings)
   are captured and written to logs/kaiagotchi.log.
 - No output from libraries or warnings contaminates the terminal UI.
 - The terminal UI uses sys.__stdout__ (untouched) for display.
"""

import os
import sys
import logging
import warnings
from pathlib import Path

# ---------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------
# Allow runtime log level control via environment variable
# Default to INFO to reduce noisy debug output; enable DEBUG via KAIA_LOG_LEVEL=DEBUG
LOG_LEVEL_NAME = os.getenv("KAIA_LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.WARNING)

# ---------------------------------------------------------------------
# Preemptive global suppression of Pydantic warnings (before import)
# ---------------------------------------------------------------------
os.environ["PYTHONWARNINGS"] = (
    "ignore::UserWarning:pydantic,"
    "ignore:PydanticSerializationUnexpectedValue"
)

# ---------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "kaiagotchi.log"


def setup_logging(config=None, debug_mode: bool = False):
    """Configure project-wide logging with optional debug mode."""
    # Allow debug mode to override the default LOG_LEVEL
    level = logging.DEBUG if debug_mode else LOG_LEVEL

    # Clear any existing handlers
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers[:]:
            root.removeHandler(handler)

    if debug_mode:
        logging.debug(f"Debug mode enabled, logging at DEBUG level")
    else:
        logging.debug(f"Using log level from KAIA_LOG_LEVEL={LOG_LEVEL_NAME}")

    # ----------------------------
    # File handler (sole output)
    # ----------------------------
    # Use rotating handler to prevent huge logs
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        LOG_FILE,
        mode="a",
        maxBytes=5_242_880,  # 5MB
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)

    # Remove all previous handlers (avoid duplicates)
    for h in list(root.handlers):
        root.removeHandler(h)

    # Attach only the file handler
    root.addHandler(file_handler)

    # -----------------------------------------------------------------
    # Redirect stdout/stderr to loggers
    # -----------------------------------------------------------------
    class _StreamToLogger:
        """Redirects writes to a logger instead of console."""

        def __init__(self, logger, level=logging.INFO):
            self.logger = logger
            self.level = level
            self._buffer = ""

        def write(self, buf):
            if not buf:
                return
            self._buffer += buf
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    try:
                        self.logger.log(self.level, line.strip())
                    except Exception:
                        pass

        def flush(self):
            if self._buffer:
                try:
                    self.logger.log(self.level, self._buffer.strip())
                except Exception:
                    pass
                self._buffer = ""

    # Keep original stdout/stderr for UI (do not replace these)
    sys.__stdout__ = getattr(sys, "__stdout__", sys.stdout)
    sys.__stderr__ = getattr(sys, "__stderr__", sys.stderr)

    # Capture all normal prints/logs
    stdout_logger = logging.getLogger("kaiagotchi.captured.stdout")
    stderr_logger = logging.getLogger("kaiagotchi.captured.stderr")

    for logger in (stdout_logger, stderr_logger):
        logger.propagate = False
        logger.addHandler(file_handler)
        logger.setLevel(logging.DEBUG)

    sys.stdout = _StreamToLogger(stdout_logger, logging.INFO)
    sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR)

    # -----------------------------------------------------------------
    # Capture Python warnings -> logging
    # -----------------------------------------------------------------
    logging.captureWarnings(True)

    # Redirect warnings.showwarning
    def _showwarning_to_logger(message, category, filename, lineno, file=None, line=None):
        try:
            logging.getLogger("py.warnings").warning(
                f"{category.__name__}: {message} (in {filename}:{lineno})"
            )
        except Exception:
            pass

    warnings.showwarning = _showwarning_to_logger

    # Filter pydantic-related noise
    warnings.filterwarnings("ignore", category=UserWarning, module=r"pydantic\..*")
    warnings.filterwarnings("ignore", message=r"PydanticSerializationUnexpectedValue")

    # Route py.warnings logger to file only
    py_warn_logger = logging.getLogger("py.warnings")
    for h in list(py_warn_logger.handlers):
        py_warn_logger.removeHandler(h)
    py_warn_logger.addHandler(file_handler)
    py_warn_logger.setLevel(logging.WARNING)
    py_warn_logger.propagate = False

    # -----------------------------------------------------------------
    # Aggressively silence pydantic and other StreamHandlers
    # -----------------------------------------------------------------
    try:
        import pydantic

        pydantic_logger = logging.getLogger("pydantic")
        pydantic_logger.setLevel(logging.CRITICAL)
        pydantic_logger.disabled = True
        if hasattr(pydantic, "main") and hasattr(pydantic.main, "_logger"):
            pydantic.main._logger = None
    except Exception:
        pass

    # Monkeypatch StreamHandler.emit so all handlers write to file
    _orig_emit = logging.StreamHandler.emit

    def _emit_to_file(self, record):
        try:
            file_handler.emit(record)
        except Exception:
            try:
                _orig_emit(self, record)
            except Exception:
                pass

    logging.StreamHandler.emit = _emit_to_file  # type: ignore

    # -----------------------------------------------------------------
    # Nuclear option: block direct writes to stderr from C extensions
    # -----------------------------------------------------------------
    real_stderr_write = sys.__stderr__.write

    def _patched_stderr_write(msg):
        if "PydanticSerializationUnexpectedValue" in str(msg):
            return
        try:
            real_stderr_write(msg)
        except Exception:
            pass

    sys.__stderr__.write = _patched_stderr_write

    # -----------------------------------------------------------------
    logger = logging.getLogger("kaiagotchi")
    logger.info(f"Logging initialized. Writing to {LOG_FILE}")
    return logger


# Initialize immediately so logging is active early
setup_logging()
