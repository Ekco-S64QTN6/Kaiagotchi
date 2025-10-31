# security.py
import logging
import sys
import os
from typing import Dict, Any

security_logger = logging.getLogger('kaiagotchi.security')

class SecurityManager:
    """Manages security warnings and compliance checks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._warnings_displayed = False
    
    def display_security_warning(self) -> None:
        """Display prominent security and legal warnings."""
        if self._warnings_displayed:
            return
            
        warning_msg = """
        ⚠️  SECURITY AND LEGAL NOTICE ⚠️
        =================================
        
        KAIAGOTCHI WIRELESS SECURITY RESEARCH TOOL
        
        CAPABILITIES:
        • Network monitoring and packet capture
        • Wireless frame injection (deauthentication)
        • Handshake capture and analysis
        • Requires root/administrative privileges
        
        LEGAL CONSIDERATIONS:
        • Use only on networks you own or have explicit permission to test
        • Unauthorized network access may violate laws in your jurisdiction
        • Some operations may violate terms of service
        
        ETHICAL USAGE:
        • For security research and authorized penetration testing only
        • Educational purposes in controlled environments
        • Responsible disclosure of vulnerabilities
        
        By continuing, you acknowledge that:
        1. You have proper authorization for all testing activities
        2. You understand the legal implications in your jurisdiction
        3. You accept full responsibility for your actions
        
        Type 'I UNDERSTAND' to continue: """
        
        print(warning_msg)
        try:
            response = input().strip().upper()
            if response != 'I UNDERSTAND':
                security_logger.critical("User did not accept security terms. Exiting.")
                sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            security_logger.critical("Security warning interrupted. Exiting.")
            sys.exit(1)
            
        self._warnings_displayed = True
        security_logger.info("Security warning acknowledged by user")
    
    def check_environment(self) -> bool:
        """Check if running in appropriate environment."""
        # Check if running as root (required for network operations)
        if os.geteuid() != 0:
            security_logger.error("Root privileges required for network operations")
            return False
            
        # Check for production vs development environment
        if self.config.get('main', {}).get('environment') == 'production':
            security_logger.warning("Running in production environment - extra caution advised")
            
        return True
    
    def validate_interface_permissions(self, interface: str) -> bool:
        """Validate that we have required permissions for network interface."""
        try:
            # Check if interface exists and we can access it
            interface_path = f"/sys/class/net/{interface}"
            if not os.path.exists(interface_path):
                security_logger.error(f"Network interface does not exist: {interface}")
                return False
                
            with open(f"{interface_path}/operstate", "r") as f:
                status = f.read().strip()
                security_logger.debug(f"Interface {interface} status: {status}")
                return True
        except (IOError, OSError, PermissionError) as e:
            security_logger.error(f"Cannot access network interface {interface}: {e}")
            return False