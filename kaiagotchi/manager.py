import logging
import sys
import argparse
import signal
import time
from typing import Dict, Any, Optional

# Internal imports from the kaiagotchi package
from kaiagotchi.utils import load_config
# We import the agent base class we just created
from kaiagotchi.agent.base import KaiagotchiBase

# Define the log level mapping for configuration
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

# --- Manager Logger Configuration ---
manager_logger = logging.getLogger('manager')
# The initial log level is set low so we can see all setup messages before
# the main configuration takes effect.
manager_logger.setLevel(logging.DEBUG)


class Manager:
    """
    The main application manager for Kaiagotchi.
    
    Responsible for loading configuration, setting up logging, initializing
    the core agent, and managing the main application lifecycle (start/stop).
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Loads configuration and prepares the system for startup.
        """
        manager_logger.info("Initializing Kaiagotchi Manager...")
        
        # 1. Load Configuration
        # This calls the function we defined in kaiagotchi/utils.py
        self.config = load_config(config_path)
        manager_logger.info("Configuration loaded.")
        
        # 2. Setup Logging based on loaded configuration
        self._setup_logging()

        # 3. Initialize Agent
        # The agent type could be configurable later, but for now we use the base class
        self.agent: KaiagotchiBase = KaiagotchiBase(self.config)
        manager_logger.info(f"Agent '{self.agent.name}' initialized.")

        # 4. State Management and Cleanup Handlers
        # Allows for graceful shutdown on signals (like Ctrl+C)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        
        manager_logger.info("Manager initialization complete.")

    def _setup_logging(self):
        """
        Configures the application's logging infrastructure based on the config.
        Sets up console and file logging with appropriate formats and levels.
        """
        log_config = self.config.get('log', {})
        log_level_str = log_config.get('level', 'INFO').upper()
        log_level = LOG_LEVEL_MAP.get(log_level_str, logging.INFO)
        
        # 1. Root Logger Setup
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        
        # Clear existing handlers to prevent duplicate logs (common during re-init)
        if root_logger.hasHandlers():
            root_logger.handlers.clear()

        # Define a consistent format
        log_format = logging.Formatter(
            '%(asctime)s | %(name)-10s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 2. Console Handler (for real-time output)
        if log_config.get('console', True):
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(log_format)
            root_logger.addHandler(console_handler)
            manager_logger.debug("Console logging enabled.")

        # 3. File Handler (for persistent logs)
        log_filepath = log_config.get('file', '/var/log/kaiagotchi/kaiagotchi.log')
        if log_filepath:
            try:
                # Ensure log directory exists
                import os
                log_dir = os.path.dirname(log_filepath)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)
                
                file_handler = logging.FileHandler(log_filepath, mode='a')
                file_handler.setFormatter(log_format)
                root_logger.addHandler(file_handler)
                manager_logger.debug(f"File logging enabled at: {log_filepath}")
            except Exception as e:
                manager_logger.error(f"Failed to set up file logging at {log_filepath}: {e}")
                # Log to console if file logging fails

    def _handle_signal(self, signum, frame):
        """
        Signal handler for clean shutdown.
        """
        manager_logger.warning(f"Received signal {signum}. Initiating shutdown...")
        self.stop()
        sys.exit(0)

    def start(self):
        """
        Starts the core application loop.
        """
        manager_logger.info(f"Starting Kaiagotchi agent '{self.agent.name}'...")
        
        # 1. Call agent's loaded hook
        self.agent.on_loaded()
        
        # 2. Start the agent's main run loop (this method is blocking)
        try:
            self.agent.run()
        except Exception as e:
            manager_logger.critical(f"Agent terminated unexpectedly: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        """
        Stops the core application and performs cleanup.
        """
        manager_logger.info("Manager performing shutdown and cleanup...")
        self.agent.stop() # Signal the agent to stop its internal loop
        
        # Placeholder for other cleanup actions (e.g., stopping UI server, cleaning up interfaces)
        manager_logger.info("Cleanup complete. Application terminated.")


# --- Main Execution Block ---

def main():
    """
    Parses command-line arguments and starts the Manager.
    """
    parser = argparse.ArgumentParser(
        description="Kaiagotchi - An autonomous technical counterpart for Wi-Fi security research.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Optional argument to specify a custom config file
    parser.add_argument(
        '-c', '--config',
        help="Specify a custom configuration file path (e.g., /home/user/my-config.toml)",
        default=None,
        type=str
    )
    
    # Optional argument to display version (you need to implement a function to get version later)
    parser.add_argument(
        '-V', '--version',
        action='store_true',
        help="Display the version number and exit."
    )
    
    args = parser.parse_args()
    
    if args.version:
        # Placeholder for version logic (will be implemented in kaiagotchi.utils later)
        print("Kaiagotchi Version: 1.0.0 (Alpha)") 
        sys.exit(0)
    
    # Initialize and start the Manager
    try:
        manager = Manager(config_path=args.config)
        manager.start()
    except Exception as e:
        manager_logger.critical(f"Fatal error during Manager startup: {e}", exc_info=True)
        sys.exit(1)