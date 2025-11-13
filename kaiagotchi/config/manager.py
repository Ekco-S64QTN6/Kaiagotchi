import logging
import pathlib
import os
import sys
from typing import Dict, Any, Optional
import tomlkit

# Security imports for file operations
import stat
import grp
import pwd

# --- Global Configuration Constants ---
DEFAULT_CONFIG_PATH = '/etc/kaiagotchi/config.toml'
DEFAULT_BASE_DIR = '/var/lib/kaiagotchi'
DEFAULT_STATE_FILENAME = 'state.json'
CONFIG_FILE_PERMISSIONS = 0o600  # Secure: rw-------
# ---

utils_logger = logging.getLogger('utils')


def _secure_file_permissions(file_path: str) -> bool:
    """
    Secure configuration file permissions to prevent unauthorized access.
    
    Args:
        file_path: Path to the file to secure
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if os.path.exists(file_path):
            # Set permissions to owner read/write only
            os.chmod(file_path, CONFIG_FILE_PERMISSIONS)
            
            # If running as root, set ownership to root
            if os.geteuid() == 0:
                os.chown(file_path, 0, 0)  # root:root
                
            utils_logger.debug(f"Secured permissions for {file_path}")
            return True
    except Exception as e:
        utils_logger.warning(f"Could not secure permissions for {file_path}: {e}")
    
    return False


def validate_config_structure(config: Dict[str, Any]) -> bool:
    """
    Validate the basic structure and required fields of the configuration.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check required main section
        if 'main' not in config:
            utils_logger.error("Configuration missing required 'main' section")
            return False
            
        main_config = config['main']
        
        # Validate name
        if 'name' not in main_config:
            utils_logger.error("Configuration missing required 'main.name' field")
            return False
            
        # Validate base directory path
        base_dir = main_config.get('base_dir', DEFAULT_BASE_DIR)
        if not isinstance(base_dir, str) or not base_dir.strip():
            utils_logger.error("Invalid base_dir configuration")
            return False
            
        # Validate personality settings if present
        if 'personality' in config:
            personality = config['personality']
            required_personality_fields = ['sad_num_epochs', 'bored_num_epochs']
            for field in required_personality_fields:
                if field not in personality:
                    utils_logger.warning(f"Missing recommended personality field: {field}")
                    
        utils_logger.debug("Configuration structure validation passed")
        return True
        
    except Exception as e:
        utils_logger.error(f"Configuration validation failed: {e}")
        return False


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Loads application configuration from a TOML file with security enhancements.

    If the config file does not exist, it loads an empty or default configuration.

    Args:
        config_path: The path to the TOML configuration file.

    Returns:
        A dictionary containing the application configuration.
    """
    # Base/Default Configuration with enhanced defaults
    config: Dict[str, Any] = {
        'main': {
            'name': 'kaiagotchi',
            'base_dir': DEFAULT_BASE_DIR,
            'plugin_dirs': ['/etc/kaiagotchi/plugins'],
            'secure_mode': True,
        },
        'personality': {
            'sad_num_epochs': 10,
            'bored_num_epochs': 5,
            'bond_encounters_factor': 10.0,
        },
        'ui': {
            'enabled': True,
            'web': {
                'enabled': True,
                'host': '0.0.0.0',
                'port': 8080,
                'authentication': True
            }
        },
        'log': {
            'level': 'INFO',
            'file': '/var/log/kaiagotchi/kaiagotchi.log',
            'max_size': '10MB',
            'backup_count': 3
        },
        'security': {
            'mask_sensitive_data': True,
            'validate_plugins': True,
            'require_authentication': True
        }
    }
    
    # 1. Check if config file exists
    if not os.path.exists(config_path):
        utils_logger.warning(f"Configuration file not found at {config_path}. Using default configuration.")
        # Create directory structure for default config location
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        return config

    # 2. Secure file permissions before reading
    _secure_file_permissions(config_path)

    # 3. Read and parse the TOML file
    try:
        with open(config_path, 'r', encoding='utf-8') as fp:
            config_content = fp.read()
            loaded_config = tomlkit.parse(config_content)
        
        # Deep merge configuration instead of simple update
        def deep_merge(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
            """Recursively merge two dictionaries."""
            for key, value in update.items():
                if (key in base and 
                    isinstance(base[key], dict) and 
                    isinstance(value, dict)):
                    base[key] = deep_merge(base[key], value)
                else:
                    base[key] = value
            return base
        
        # Perform deep merge
        config = deep_merge(config, loaded_config)
        
        # 4. Validate configuration structure
        if not validate_config_structure(config):
            utils_logger.warning("Configuration validation failed, using default configuration")
            return load_config()  # Return fresh default config
            
        utils_logger.info(f"Configuration loaded successfully from {config_path}")

    except PermissionError as e:
        utils_logger.error(f"Permission denied accessing configuration file {config_path}: {e}")
        utils_logger.warning("Falling back to default configuration.")
        
    except Exception as e:
        utils_logger.error(f"Error loading or parsing configuration from {config_path}: {e}", exc_info=True)
        utils_logger.warning("Falling back to default configuration.")

    return config


def save_config(config: Dict[str, Any], config_path: str = DEFAULT_CONFIG_PATH) -> bool:
    """
    Save configuration to a TOML file with security measures.
    
    Args:
        config: Configuration dictionary to save
        config_path: Path where to save the configuration
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        # Convert dictionary to TOML
        toml_content = tomlkit.dumps(config)
        
        # Write to temporary file first (atomic write)
        temp_path = f"{config_path}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as fp:
            fp.write(toml_content)
        
        # Replace original file atomically
        os.replace(temp_path, config_path)
        
        # Secure file permissions
        _secure_file_permissions(config_path)
        
        utils_logger.info(f"Configuration saved successfully to {config_path}")
        return True
        
    except Exception as e:
        utils_logger.error(f"Error saving configuration to {config_path}: {e}")
        # Clean up temporary file if it exists
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def get_state_path(config: Dict[str, Any], filename: str = DEFAULT_STATE_FILENAME) -> str:
    """
    Determines the full path for a persistent state file based on the application config.

    The path is constructed as: <base_dir>/<filename>

    Args:
        config: The application configuration dictionary.
        filename: The specific name of the state file (e.g., 'state.json', 'log.txt').

    Returns:
        The absolute path to the state file.
    """
    # Extract base directory from config, falling back to default if missing
    base_dir = config.get('main', {}).get('base_dir', DEFAULT_BASE_DIR)
    
    # Ensure the directory exists with secure permissions
    try:
        path = pathlib.Path(base_dir)
        path.mkdir(parents=True, exist_ok=True)
        
        # Set secure permissions for the directory
        if os.geteuid() == 0:  # Running as root
            os.chmod(str(path), 0o700)  # drwx------
            os.chown(str(path), 0, 0)   # root:root
            
    except Exception as e:
        utils_logger.error(f"Could not create or secure directory {base_dir}: {e}")
        # Fallback to a safe temporary directory
        base_dir = '/tmp/kaiagotchi'
        pathlib.Path(base_dir).mkdir(parents=True, exist_ok=True)
    
    state_path = str(pathlib.Path(base_dir) / filename)
    utils_logger.debug(f"State path generated: {state_path}")
    return state_path


def mask_sensitive_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a safe version of config for logging by masking sensitive data.
    
    Args:
        config: Original configuration dictionary
        
    Returns:
        Configuration with sensitive fields masked
    """
    masked_config = config.copy()
    sensitive_keys = ['password', 'secret', 'key', 'token', 'auth']
    
    def mask_recursive(obj):
        if isinstance(obj, dict):
            return {k: mask_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [mask_recursive(item) for item in obj]
        else:
            return obj
    
    for section in masked_config:
        if isinstance(masked_config[section], dict):
            for key in list(masked_config[section].keys()):
                if any(sensitive in key.lower() for sensitive in sensitive_keys):
                    masked_config[section][key] = '***MASKED***'
    
    return masked_config