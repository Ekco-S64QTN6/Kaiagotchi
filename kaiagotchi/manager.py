import logging
import os
import sys
import argparse
import threading # Required for the new UI import
from typing import Dict, Any

# --- Import Core Components ---

# 1. FIX: Import KaiagotchiBase from the correct, final location (agent/base.py)
from kaiagotchi.agent.base import KaiagotchiBase

# 2. NEW: Import the Server class from your existing UI file.
from kaiagotchi.ui.web import Server

# 3. Import utility functions from your existing utils.py file
from kaiagotchi.utils import load_config


# --- Global Configuration Constants (These were duplicated in your old manager.py and utils.py) ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
# ---

# Set up the logger for this specific module
manager_logger = logging.getLogger('manager')


def setup_logging(level_name: str):
    """
    Sets up basic application-wide logging based on the configured level.
    """
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    
    # Configure the root logger
    logging.basicConfig(
        level=numeric_level,
        format='[%(levelname)s] (%(name)s) %(message)s'
    )
    manager_logger.info(f"Logging initialized at level: {level_name.upper()}")


def main():
    """
    The main execution function for the Kaiagotchi application.
    """
    parser = argparse.ArgumentParser(
        description='Kaiagotchi Agent Management Utility.',
        epilog='Use the "run" command to start the main agent loop.'
    )
    
    parser.add_argument(
        '-c', '--config-path',
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help=f'Path to the configuration file (default: {DEFAULT_CONFIG_PATH}).'
    )
    
    parser.add_argument(
        'command',
        nargs='?', 
        default='run',
        help='The command to execute (e.g., run, status). Default is "run".'
    )
    
    args = parser.parse_args()

    # 1. Configuration Loading (using imported function)
    config = load_config(config_path=args.config_path)

    # 2. Logging Setup
    log_level = config.get('log', {}).get('level', 'INFO')
    setup_logging(log_level)
    
    # 3. Agent Initialization and Start
    command = args.command.lower() 

    if command == 'run':
        manager_logger.info(f"Starting Kaiagotchi agent. Configuration loaded from: {args.config_path}")
        
        try:
            # Instantiate the agent
            agent = KaiagotchiBase(config=config)
            
            # --- Web UI Initialization ---
            if config.get('ui', {}).get('enabled', False):
                manager_logger.info("Initializing Web UI Server...")
                
                # CORRECTED: Instantiate the Server class from your ui/web.py.
                # The Server.__init__ method handles the threading internally,
                # as shown in the code you provided.
                web_server_instance = Server(agent=agent, config=config)
                
            # --- Main Agent Start ---
            # The agent.run() call is designed to block until it's stopped 
            agent.run() 
            
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            manager_logger.info("Termination signal received (Ctrl+C). Stopping agent gracefully.")
            if 'agent' in locals():
                agent.stop()
        except Exception as e:
            manager_logger.critical(f"A fatal error occurred during agent execution: {e}", exc_info=True)
            sys.exit(1)
            
    else:
        manager_logger.warning(f"Command '{command}' not yet implemented. Use 'run'.")