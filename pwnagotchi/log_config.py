import logging
import logging.handlers
import os
import sys

# Constants for robust, size-limited log rotation
MAX_BYTES = 5 * 1024 * 1024  # Limit log file size to 5 MB
BACKUP_COUNT = 3             # Keep 3 rotated backup files

def setup_logging(config, debug_mode: bool = False):
    """
    Initializes and configures the centralized logging system for the Kaia AI application.

    This setup ensures:
    1.  Hierarchical control over log levels (DEBUG/INFO).
    2.  Persistent logging to a file with automatic rotation for stability.
    3.  Real-time output to the console for monitoring.
    4.  Suppression of verbose third-party library logging (e.g., Scapy, Requests).

    :param config: The application's configuration dictionary (must contain log path info).
    :param debug_mode: If True, set the global level to DEBUG; otherwise, set to INFO.
    """

    # Retrieve configuration settings
    log_cfg = config['main']['log']
    log_file = log_cfg.get('path', '/var/log/kaiagotchi/kaiagotchi.log')
    log_level = 'DEBUG' if debug_mode else 'INFO'

    # 1. Establish the root logger and set its level
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.getLevelName(log_level))

    # Clear existing handlers to prevent multiple logging messages upon re-initialization
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 2. Define a precise log format
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s.%(funcName)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # --- Handlers for Output and Persistence ---

    # 3. Console Handler (Standard Error for real-time output)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO) # Console should generally only show INFO+
    root_logger.addHandler(console_handler)

    # 4. Rotating File Handler (for persistent, size-controlled logging)
    log_dir = os.path.dirname(log_file)
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            root_logger.info(f"Created log directory: {log_dir}")
        except OSError as e:
            root_logger.error(f"Failed to create log directory {log_dir}: {e}")
            # Do not proceed with file logging if directory creation fails

    # Use the robust RotatingFileHandler for automatic file size management
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG) # File should capture ALL debug information
        root_logger.addHandler(file_handler)
    except Exception as e:
         root_logger.error(f"Failed to initialize file logging at {log_file}: {e}")


    # 5. Suppress overly verbose third-party loggers for clarity
    if not debug_mode:
        logging.getLogger("scapy").disabled = True
        logging.getLogger("urllib3").propagate = False
        logging.getLogger("requests").addHandler(logging.NullHandler())
        
        # Suppress future warnings from dependencies like Pandas/Tensorflow
        import warnings
        warnings.simplefilter(action='ignore', category=FutureWarning)
        warnings.simplefilter(action='ignore', category=DeprecationWarning)
        
    # Final status message
    root_logger.info("=========================================================================")
    root_logger.info(f"Kaia AI Logging System Initialized | Level: {log_level}")
    root_logger.info(f"Persistent logging active at: {log_file}")
    root_logger.info("=========================================================================")
