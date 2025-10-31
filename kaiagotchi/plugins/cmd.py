import os
import logging
import glob
import re
import shutil
import socket
import tempfile
import subprocess
from fnmatch import fnmatch
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

# Safe imports with error handling
try:
    from ..utils import download_file, unzip, save_config, parse_version, md5
    from . import default_path
except ImportError as e:
    logging.error("Failed to import required modules: %s", e)
    raise

SAVE_DIR = '/usr/local/share/kaiagotchi/available-plugins/'
DEFAULT_INSTALL_PATH = '/usr/local/share/kaiagotchi/installed-plugins/'

class PluginManagerError(Exception):
    """Base exception for plugin manager errors."""
    pass

class NetworkError(PluginManagerError):
    """Raised when network operations fail."""
    pass

class PluginNotFoundError(PluginManagerError):
    """Raised when a plugin is not found."""
    pass

def _ensure_directory(path: str) -> bool:
    """Ensure directory exists with proper permissions."""
    try:
        os.makedirs(path, mode=0o755, exist_ok=True)
        return True
    except OSError as e:
        logging.error("Failed to create directory %s: %s", path, e)
        return False

def _get_editor() -> str:
    """Get the system editor with fallbacks."""
    editor = os.environ.get('EDITOR')
    if not editor:
        # Try common editors in order of preference
        for candidate in ['vim', 'nano', 'vi', 'emacs']:
            if shutil.which(candidate):
                editor = candidate
                break
        else:
            editor = 'vi'  # Final fallback
    return editor

def add_parsers(subparsers):
    """Add the plugins subcommand to argparse."""
    parser_plugins = subparsers.add_parser('plugins', 
                                         help='Manage kaiagotchi plugins')
    plugin_subparsers = parser_plugins.add_subparsers(dest='plugincmd', 
                                                    required=True,
                                                    help='Plugin commands')

    # Search command
    parser_search = plugin_subparsers.add_parser('search', 
                                               help='Search for plugins')
    parser_search.add_argument('pattern', type=str, 
                             help="Search expression (wildcards allowed)")

    # List command
    parser_list = plugin_subparsers.add_parser('list', 
                                             help='List available plugins')
    parser_list.add_argument('-i', '--installed', action='store_true',
                           help='List installed plugins')

    # Update command
    plugin_subparsers.add_parser('update', 
                               help='Update plugin database')

    # Upgrade command
    parser_upgrade = plugin_subparsers.add_parser('upgrade',
                                                help='Upgrade plugins')
    parser_upgrade.add_argument('pattern', type=str, nargs='?', default='*',
                              help="Filter expression (wildcards allowed)")

    # Enable command
    parser_enable = plugin_subparsers.add_parser('enable',
                                               help='Enable a plugin')
    parser_enable.add_argument('name', type=str,
                             help='Name of the plugin')

    # Disable command
    parser_disable = plugin_subparsers.add_parser('disable',
                                                help='Disable a plugin')
    parser_disable.add_argument('name', type=str,
                              help='Name of the plugin')

    # Install command
    parser_install = plugin_subparsers.add_parser('install',
                                                help='Install a plugin')
    parser_install.add_argument('name', type=str,
                              help='Name of the plugin')

    # Uninstall command
    parser_uninstall = plugin_subparsers.add_parser('uninstall',
                                                  help='Uninstall a plugin')
    parser_uninstall.add_argument('name', type=str,
                                help='Name of the plugin')

    # Edit command
    parser_edit = plugin_subparsers.add_parser('edit',
                                             help='Edit plugin options')
    parser_edit.add_argument('name', type=str,
                           help='Name of the plugin')

    return subparsers

def used_plugin_cmd(args) -> bool:
    """Check if plugins subcommand was used."""
    return hasattr(args, 'plugincmd') and args.plugincmd is not None

def handle_cmd(args, config: Dict[str, Any]) -> int:
    """Handle plugin commands."""
    cmd_handlers = {
        'update': update,
        'search': lambda a, c: list_plugins(a, c, a.pattern),
        'install': install,
        'uninstall': uninstall,
        'list': list_plugins,
        'enable': enable,
        'disable': disable,
        'upgrade': lambda a, c: upgrade(a, c, a.pattern),
        'edit': edit,
    }
    
    handler = cmd_handlers.get(args.plugincmd)
    if not handler:
        logging.error("Unknown plugin command: %s", args.plugincmd)
        return 1
    
    try:
        return handler(args, config)
    except Exception as e:
        logging.error("Error executing plugin command %s: %s", args.plugincmd, e)
        return 1

def edit(args, config: Dict[str, Any]) -> int:
    """Edit plugin configuration."""
    plugin = args.name
    
    if plugin not in config.get('main', {}).get('plugins', {}):
        logging.error("Plugin %s not found in configuration", plugin)
        return 1

    editor = _get_editor()
    
    # Create temporary configuration file
    plugin_config = {
        'main': {
            'plugins': {
                plugin: config['main']['plugins'][plugin]
            }
        }
    }

    try:
        import tomlkit
        
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.toml', 
                                       prefix=f'kaiagotchi_{plugin}_', delete=False) as tmp:
            # Write current config
            tmp.write(tomlkit.dumps(plugin_config))
            tmp.flush()
            
            # Launch editor
            result = subprocess.run([editor, tmp.name])
            if result.returncode != 0:
                logging.error("Editor exited with code %d", result.returncode)
                os.unlink(tmp.name)  # Clean up temp file
                return result.returncode
            
            # Read back changes
            tmp.seek(0)
            try:
                new_config = tomlkit.load(tmp)
                config['main']['plugins'][plugin] = new_config['main']['plugins'][plugin]
            except Exception as e:
                logging.error("Invalid TOML configuration: %s", e)
                os.unlink(tmp.name)  # Clean up temp file
                return 1
            
            os.unlink(tmp.name)  # Clean up temp file
        
        # Save configuration
        save_config(config, getattr(args, 'user_config', None))
        logging.info("Updated configuration for plugin %s", plugin)
        return 0
        
    except ImportError:
        logging.error("tomlkit required for editing configuration")
        return 1
    except Exception as e:
        logging.error("Failed to edit plugin configuration: %s", e)
        return 1

def enable(args, config: Dict[str, Any]) -> int:
    """Enable a plugin."""
    plugin = args.name
    
    if 'main' not in config:
        config['main'] = {}
    if 'plugins' not in config['main']:
        config['main']['plugins'] = {}
    
    if plugin not in config['main']['plugins']:
        config['main']['plugins'][plugin] = {}
    
    config['main']['plugins'][plugin]['enabled'] = True
    
    try:
        save_config(config, getattr(args, 'user_config', None))
        logging.info("Enabled plugin: %s", plugin)
        return 0
    except Exception as e:
        logging.error("Failed to enable plugin %s: %s", plugin, e)
        return 1

def disable(args, config: Dict[str, Any]) -> int:
    """Disable a plugin."""
    plugin = args.name
    
    if 'main' not in config:
        config['main'] = {}
    if 'plugins' not in config['main']:
        config['main']['plugins'] = {}
    
    if plugin not in config['main']['plugins']:
        config['main']['plugins'][plugin] = {}
    
    config['main']['plugins'][plugin]['enabled'] = False
    
    try:
        save_config(config, getattr(args, 'user_config', None))
        logging.info("Disabled plugin: %s", plugin)
        return 0
    except Exception as e:
        logging.error("Failed to disable plugin %s: %s", plugin, e)
        return 1

def upgrade(args, config: Dict[str, Any], pattern: str = '*') -> int:
    """Upgrade plugins matching pattern."""
    try:
        available = _get_available()
        installed = _get_installed(config)
        
        upgraded = 0
        
        for plugin, filename in installed.items():
            if not fnmatch(plugin, pattern) or plugin not in available:
                continue

            available_version = _extract_version(available[plugin])
            installed_version = _extract_version(filename)

            if not available_version or not installed_version:
                continue
                
            if available_version <= installed_version:
                continue

            logging.info('Upgrading %s from %s to %s', 
                        plugin, '.'.join(installed_version), '.'.join(available_version))
            
            try:
                # Backup existing plugin
                backup_file = f"{filename}.bak"
                shutil.copy2(filename, backup_file)
                
                # Install new version
                shutil.copy2(available[plugin], filename)
                
                # Handle configuration files
                for conf_src in glob.glob(available[plugin].replace('.py', '.y?ml')):
                    conf_dst = os.path.join(os.path.dirname(filename), os.path.basename(conf_src))
                    if os.path.exists(conf_dst) and md5(conf_dst) != md5(conf_src):
                        shutil.copy2(conf_dst, f"{conf_dst}.bak")
                    shutil.copy2(conf_src, conf_dst)
                
                upgraded += 1
                logging.info('Successfully upgraded %s', plugin)
                
            except Exception as e:
                logging.error('Failed to upgrade %s: %s', plugin, e)
                # Restore backup if exists
                if os.path.exists(backup_file):
                    shutil.copy2(backup_file, filename)

        if upgraded == 0:
            logging.info('No plugins to upgrade')
        
        return 0
    except Exception as e:
        logging.error("Error during plugin upgrade: %s", e)
        return 1

def list_plugins(args, config: Dict[str, Any], pattern: str = '*') -> int:
    """List available and installed plugins."""
    try:
        available = _get_available()
        installed = _get_installed(config)
        
        available_and_installed = set(available.keys()) | set(installed.keys())
        available_not_installed = set(available.keys()) - set(installed.keys())
        
        max_len_list = available_and_installed if args.installed else available_not_installed
        if not max_len_list:
            print('No plugins found. Try: sudo kaiagotchi plugins update')
            return 1
            
        max_len = max(map(len, max_len_list))
        
        # Format string with columns
        line_fmt = "| {name:<%d} | {version:^8} | {enabled:^8} | {status:<14} | {author:<20} |" % max_len
        header = line_fmt.format(
            name="Plugin", version="Version", enabled="Active", 
            status="Status", author="Author"
        )
        separator = '-' * len(header)
        
        print(separator)
        print(header)
        print(separator)
        
        found = False
        
        if args.installed:
            for plugin, filename in sorted(installed.items()):
                if not fnmatch(plugin, pattern):
                    continue
                found = True
                
                installed_version = _extract_version(filename)
                available_version = _extract_version(available.get(plugin))
                
                status = "installed"
                if installed_version and available_version and available_version > installed_version:
                    status = "update available"
                
                enabled = 'yes' if (
                    plugin in config.get('main', {}).get('plugins', {}) and
                    config['main']['plugins'][plugin].get('enabled', False)
                ) else 'no'
                
                print(line_fmt.format(
                    name=plugin,
                    version='.'.join(installed_version) if installed_version else 'unknown',
                    enabled=enabled,
                    status=status,
                    author=_extract_author(filename)
                ))
        
        for plugin in sorted(available_not_installed):
            if not fnmatch(plugin, pattern):
                continue
            found = True
            
            available_version = _extract_version(available[plugin])
            print(line_fmt.format(
                name=plugin,
                version='.'.join(available_version) if available_version else 'unknown',
                enabled='-',
                status='available',
                author=_extract_author(available[plugin])
            ))
        
        print(separator)
        
        if not found:
            print('No plugins matching pattern. Try: sudo kaiagotchi plugins update')
            return 1
            
        return 0
    except Exception as e:
        logging.error("Error listing plugins: %s", e)
        return 1

def _extract_version(filename: str) -> Optional[List[str]]:
    """Extract version from plugin file."""
    try:
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        match = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return parse_version(match.group(1))
    except Exception as e:
        logging.debug("Failed to extract version from %s: %s", filename, e)
    
    return None

def _extract_author(filename: str) -> str:
    """Extract author from plugin file."""
    try:
        with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        match = re.search(r'__author__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
        if match:
            return match.group(1)
    except Exception:
        pass
    
    return 'unknown'

def _get_available() -> Dict[str, str]:
    """Get available plugins."""
    available = {}
    if os.path.exists(SAVE_DIR):
        for filename in glob.glob(os.path.join(SAVE_DIR, "*.py")):
            plugin_name = os.path.basename(filename).replace(".py", "")
            available[plugin_name] = filename
    return available

def _get_installed(config: Dict[str, Any]) -> Dict[str, str]:
    """Get installed plugins."""
    installed = {}
    search_dirs = [
        default_path,
        config.get('main', {}).get('custom_plugins')
    ]
    
    for search_dir in search_dirs:
        if search_dir and os.path.exists(search_dir):
            for filename in glob.glob(os.path.join(search_dir, "*.py")):
                plugin_name = os.path.basename(filename).replace(".py", "")
                installed[plugin_name] = filename
                
    return installed

def uninstall(args, config: Dict[str, Any]) -> int:
    """Uninstall a plugin."""
    try:
        plugin_name = args.name
        installed = _get_installed(config)
        
        if plugin_name not in installed:
            logging.error('Plugin %s is not installed.', plugin_name)
            return 1
        
        os.remove(installed[plugin_name])
        
        # Remove configuration if exists
        if plugin_name in config.get('main', {}).get('plugins', {}):
            del config['main']['plugins'][plugin_name]
            save_config(config, getattr(args, 'user_config', None))
        
        logging.info('Uninstalled plugin: %s', plugin_name)
        return 0
    except Exception as e:
        logging.error('Failed to uninstall %s: %s', plugin_name, e)
        return 1

def install(args, config: Dict[str, Any]) -> int:
    """Install a plugin."""
    try:
        plugin_name = args.name
        available = _get_available()
        installed = _get_installed(config)
        
        if plugin_name not in available:
            logging.error('Plugin %s not found.', plugin_name)
            return 1
        
        if plugin_name in installed:
            logging.error('Plugin %s already installed.', plugin_name)
            return 1
        
        # Determine install path
        install_path = config.get('main', {}).get('custom_plugins', DEFAULT_INSTALL_PATH)
        if not _ensure_directory(install_path):
            return 1
        
        # Install plugin file
        src_file = available[plugin_name]
        dst_file = os.path.join(install_path, os.path.basename(src_file))
        shutil.copy2(src_file, dst_file)
        
        # Install configuration files
        for conf_src in glob.glob(src_file.replace('.py', '.y?ml')):
            conf_dst = os.path.join(install_path, os.path.basename(conf_src))
            if os.path.exists(conf_dst):
                # Backup existing config
                backup_dst = f"{conf_dst}.bak"
                shutil.copy2(conf_dst, backup_dst)
                logging.info('Backed up existing config: %s', os.path.basename(conf_src))
            
            shutil.copy2(conf_src, conf_dst)
        
        logging.info('Installed plugin: %s', plugin_name)
        return 0
        
    except Exception as e:
        logging.error('Failed to install %s: %s', plugin_name, e)
        return 1

def _check_internet() -> bool:
    """Check internet connectivity."""
    try:
        # Try DNS resolution first
        socket.gethostbyname('google.com')
        return True
    except Exception:
        return False

def update(config: Dict[str, Any]) -> int:
    """Update plugin database."""
    try:
        if not _check_internet():
            logging.error("No internet connection. Please check network connectivity.")
            print("No internet connection detected.")
            return 1
        
        urls = config.get('main', {}).get('custom_plugin_repos', [])
        if not urls:
            logging.error('No plugin repositories configured.')
            return 1
        
        if not _ensure_directory(SAVE_DIR):
            return 1
        
        success_count = 0
        for idx, repo_url in enumerate(urls):
            dest_file = os.path.join(SAVE_DIR, f'plugins{idx}.zip')
            
            logging.info('Downloading plugins from %s', repo_url)
            
            try:
                # Download plugin archive
                if not download_file(repo_url, dest_file):
                    logging.error('Failed to download from %s', repo_url)
                    continue
                
                # Extract plugins
                if not unzip(dest_file, SAVE_DIR, strip_dirs=1):
                    logging.error('Failed to extract plugins from %s', dest_file)
                    continue
                
                success_count += 1
                logging.info('Successfully updated plugins from %s', repo_url)
                
            except Exception as e:
                logging.error('Failed to update from %s: %s', repo_url, e)
                continue
        
        if success_count > 0:
            logging.info('Plugin database updated successfully from %d repositories', success_count)
            return 0
        else:
            logging.error('Failed to update from any repository')
            return 1
            
    except Exception as e:
        logging.error("Error during plugin update: %s", e)
        return 1