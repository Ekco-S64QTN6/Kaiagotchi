"""
Google Drive authentication command-line interface for Kaiagotchi.
Handles secure OAuth2 authentication and token management.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import argparse

# Import with fallback for optional dependency
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2 import auth as pydrive2_auth
    PYDRIVE_AVAILABLE = True
except ImportError:
    PYDRIVE_AVAILABLE = False
    logging.warning("PyDrive2 not available - Google Drive features disabled")

# Security imports
import stat
import getpass


class GoogleAuthManager:
    """Secure Google Drive authentication manager."""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".kaiagotchi" / "google"
        self.credentials_file = self.config_dir / "credentials.json"
        self.settings_file = self.config_dir / "settings.yaml"
        self.secrets_file = self.config_dir / "client_secrets.json"
        self.logger = logging.getLogger('kaiagotchi.google.auth')
        
        # Ensure secure directory structure
        self._setup_secure_directories()
    
    def _setup_secure_directories(self) -> None:
        """Create secure configuration directories with proper permissions."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            
            # Set secure permissions on existing files
            for file_path in [self.credentials_file, self.settings_file, self.secrets_file]:
                if file_path.exists():
                    file_path.chmod(0o600)
                    
        except Exception as e:
            self.logger.error(f"Failed to setup secure directories: {e}")
            raise
    
    def _check_prerequisites(self) -> bool:
        """Check if required files and dependencies are available."""
        if not PYDRIVE_AVAILABLE:
            self.logger.error("PyDrive2 is not installed. Install with: pip install pydrive2")
            return False
            
        if not self.secrets_file.exists():
            self.logger.error(f"client_secrets.json not found at {self.secrets_file}")
            self.logger.info("Download from: https://console.developers.google.com/apis/credentials")
            return False
            
        if not self.settings_file.exists():
            self._create_default_settings()
            
        return True
    
    def _create_default_settings(self) -> None:
        """Create default settings file for Google Auth."""
        settings_content = """\
client_config_backend: file
client_config_file: {secrets_file}

save_credentials: true
save_credentials_backend: file
save_credentials_file: {creds_file}

get_refresh_token: true

oauth_scope:
  - https://www.googleapis.com/auth/drive.file
  - https://www.googleapis.com/auth/drive.metadata
""".format(
    secrets_file=str(self.secrets_file),
    creds_file=str(self.credentials_file)
)
        
        with open(self.settings_file, 'w') as f:
            f.write(settings_content)
        self.settings_file.chmod(0o600)
    
    def authenticate(self) -> bool:
        """Perform OAuth2 authentication flow."""
        if not self._check_prerequisites():
            return False
        
        try:
            # Display security warning
            self._display_security_warning()
            
            # Initialize Google Auth
            gauth = GoogleAuth(settings_file=str(self.settings_file))
            
            # Get authentication URL
            auth_url = gauth.GetAuthUrl()
            print(f"\n🔐 Please open this URL in your browser:\n\n{auth_url}\n")
            
            # Get authorization code
            auth_code = input("📋 Paste the authorization code from the browser: ").strip()
            
            if not auth_code:
                self.logger.error("No authorization code provided")
                return False
            
            # Exchange code for tokens
            gauth.Auth(auth_code)
            gauth.SaveCredentialsFile(str(self.credentials_file))
            
            # Secure the credentials file
            self.credentials_file.chmod(0o600)
            
            print("✅ Successfully authenticated with Google Drive!")
            return True
            
        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False
    
    def refresh_token(self) -> bool:
        """Refresh OAuth2 access token."""
        if not self._check_prerequisites():
            return False
        
        try:
            gauth = GoogleAuth(settings_file=str(self.settings_file))
            gauth.LoadCredentialsFile(str(self.credentials_file))
            
            if gauth.access_token_expired:
                if gauth.credentials:
                    gauth.Refresh()
                    gauth.SaveCredentialsFile(str(self.credentials_file))
                    self.credentials_file.chmod(0o600)
                    print("✅ Successfully refreshed access token")
                    return True
                else:
                    print("❌ No valid credentials found. Please run 'kaiagotchi google login' first.")
                    return False
            else:
                print("✅ Token is still valid, no refresh needed")
                return True
                
        except pydrive2_auth.RefreshError:
            print("🔄 Refresh token expired, re-authentication required")
            return self.authenticate()
        except pydrive2_auth.InvalidCredentialsError:
            print("❌ Invalid credentials, re-authentication required")
            return self.authenticate()
        except Exception as e:
            self.logger.error(f"Token refresh failed: {e}")
            return False
    
    def _display_security_warning(self) -> None:
        """Display security and privacy warning."""
        warning = """
⚠️  GOOGLE DRIVE AUTHENTICATION - SECURITY NOTICE

By completing authentication, you grant Kaiagotchi access to:
• Create and manage files in your Google Drive
• Access metadata about your files
• Store handshake files and session data

SECURITY NOTES:
• Credentials are stored locally with secure permissions
• Only files created by Kaiagotchi will be accessed
• You can revoke access anytime via Google Account settings
• No personal data beyond handshake files is accessed

Do you want to continue? [y/N]: """
        
        response = input(warning).strip().lower()
        if response not in ('y', 'yes'):
            print("Authentication cancelled.")
            sys.exit(0)


def add_google_parsers(subparsers: argparse._SubParsersAction) -> None:
    """
    Add Google Drive subcommands to argument parser.
    """
    if not PYDRIVE_AVAILABLE:
        return  # Don't add commands if dependency not available
    
    parser_google = subparsers.add_parser(
        'google', 
        help='Google Drive integration commands'
    )
    google_subparsers = parser_google.add_subparsers(
        dest='googlecmd',
        title='Google commands'
    )
    
    # Login command
    login_parser = google_subparsers.add_parser(
        'login', 
        help='Authenticate with Google Drive'
    )
    login_parser.add_argument(
        '--config-dir',
        help='Custom configuration directory'
    )
    
    # Refresh command
    refresh_parser = google_subparsers.add_parser(
        'refresh', 
        help='Refresh Google Drive authentication token'
    )
    refresh_parser.add_argument(
        '--config-dir',
        help='Custom configuration directory'
    )
    
    # Status command
    status_parser = google_subparsers.add_parser(
        'status', 
        help='Check Google Drive authentication status'
    )
    status_parser.add_argument(
        '--config-dir',
        help='Custom configuration directory'
    )


def is_google_command(args) -> bool:
    """
    Check if Google subcommand was used.
    """
    return hasattr(args, 'googlecmd') and args.googlecmd is not None


def handle_google_command(args, config: Optional[Dict[str, Any]] = None) -> int:
    """
    Handle Google Drive subcommands.
    """
    if not PYDRIVE_AVAILABLE:
        logging.error("Google Drive features require pydrive2. Install with: pip install pydrive2")
        return 1
    
    # Determine config directory
    config_dir = None
    if args.config_dir:
        config_dir = Path(args.config_dir)
    elif config and 'main' in config and 'base_dir' in config['main']:
        config_dir = Path(config['main']['base_dir']) / 'google'
    
    auth_manager = GoogleAuthManager(config_dir)
    
    try:
        if args.googlecmd == 'login':
            success = auth_manager.authenticate()
            return 0 if success else 1
            
        elif args.googlecmd == 'refresh':
            success = auth_manager.refresh_token()
            return 0 if success else 1
            
        elif args.googlecmd == 'status':
            # Implementation for status check
            print("🔍 Google Drive status check not yet implemented")
            return 0
            
        else:
            logging.error(f"Unknown Google command: {args.googlecmd}")
            return 1
            
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        return 1
    except Exception as e:
        logging.error(f"Google command failed: {e}")
        return 1


# Legacy functions for backward compatibility
def add_parsers(subparsers):
    """Legacy function name for backward compatibility."""
    return add_google_parsers(subparsers)


def used_google_cmd(args):
    """Legacy function name for backward compatibility."""
    return is_google_command(args)


def handle_cmd(args):
    """Legacy function name for backward compatibility."""
    return handle_google_command(args)