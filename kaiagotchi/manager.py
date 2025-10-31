# manager.py 
import logging
import os
import sys
import argparse
from typing import Dict, Any

# Import Core Components
try:
    from kaiagotchi.agent.base import KaiagotchiBase
except ImportError:
    from kaiagotchi.agent import Agent as KaiagotchiBase

from kaiagotchi.utils import load_config
from kaiagotchi.security import SecurityManager

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'

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
    
    # Add security-specific arguments
    parser.add_argument(
        '--accept-risks',
        action='store_true',
        help='Skip interactive security warning (use in automated environments)'
    )
    
    parser.add_argument(
        '--skip-security-checks',
        action='store_true',
        help='Skip security environment checks (not recommended)'
    )
    
    args = parser.parse_args()

    # 1. Configuration Loading
    config = load_config(config_path=args.config_path)

    # 2. Security Management
    security_mgr = SecurityManager(config)
    
    # Display security warning (only in interactive mode, unless skipped)
    if not args.accept_risks and sys.stdin.isatty():
        security_mgr.display_security_warning()
    
    # Check environment (unless explicitly skipped)
    if not args.skip_security_checks:
        if not security_mgr.check_environment():
            manager_logger.critical("Security environment checks failed. Exiting.")
            sys.exit(1)
        
        # Validate network interface permissions
        iface = config.get('main', {}).get('iface')
        if iface and not security_mgr.validate_interface_permissions(iface):
            manager_logger.critical(f"Insufficient permissions for interface: {iface}")
            sys.exit(1)
    else:
        manager_logger.warning("Security checks skipped - proceeding with caution")

    # 3. Logging Setup
    log_level = config.get('log', {}).get('level', 'INFO')
    setup_logging(log_level)
    
    # Log startup with security context
    manager_logger.info("Kaiagotchi starting with enhanced security controls")
    
    # 4. Agent Initialization and Start
    command = args.command.lower() 

    if command == 'run':
        manager_logger.info(f"Starting Kaiagotchi agent. Configuration loaded from: {args.config_path}")
        
        try:
            # Instantiate the agent
            agent = KaiagotchiBase(config=config)
            
            # Web UI Initialization
            if config.get('ui', {}).get('enabled', False):
                manager_logger.info("Initializing Web UI Server...")
                # Note: You'll need to implement or import the Server class
                # web_server_instance = Server(agent=agent, config=config)
                pass
                
            # Main Agent Start
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

if __name__ == '__main__':
    main()