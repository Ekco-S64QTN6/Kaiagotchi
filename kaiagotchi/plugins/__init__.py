import os
import queue
import glob
import threading
import importlib
import importlib.util
import logging
import time
from typing import Dict, Any, Optional, Callable, List, Set
from dataclasses import dataclass

# Safe imports with fallbacks
try:
    import prctl
    PRCTL_AVAILABLE = True
except ImportError:
    prctl = None
    PRCTL_AVAILABLE = False
    logging.debug("prctl not available, thread naming disabled")

default_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "default")
loaded: Dict[str, Any] = {}
database: Dict[str, str] = {}
locks: Dict[str, threading.Lock] = {}
exitFlag = 0
plugin_event_queues: Dict[str, 'PluginEventQueue'] = {}
plugin_thread_workers: Dict[str, threading.Thread] = {}

@dataclass
class PluginConfig:
    """Configuration for a plugin."""
    enabled: bool = False
    options: Dict[str, Any] = None

    def __post_init__(self):
        if self.options is None:
            self.options = {}

class PluginError(Exception):
    """Base exception for plugin-related errors."""
    pass

class PluginLoadError(PluginError):
    """Raised when a plugin fails to load."""
    pass

class PluginEventError(PluginError):
    """Raised when a plugin event fails."""
    pass

def _safe_thread_name(name: str) -> str:
    """Set thread name safely with prctl fallback."""
    if PRCTL_AVAILABLE and prctl:
        try:
            prctl.set_name(name[:15])  # Linux thread name limit
        except Exception:
            pass  # Silently continue if thread naming fails
    return name

def run_once(pqueue: 'PluginEventQueue', event_name: str, *args, **kwargs) -> None:
    """Run a plugin event once in a separate thread."""
    try:
        _safe_thread_name(f"R1_{pqueue.plugin_name}_{event_name}")
        pqueue.process_event(event_name, *args, **kwargs)
        logging.debug("Thread for %s %s exiting", pqueue.plugin_name, event_name)
    except Exception as e:
        logging.exception("Thread for %s, %s, %s, %s", 
                         pqueue.plugin_name, event_name, repr(args), repr(kwargs))

class PluginEventQueue(threading.Thread):
    """Thread-safe event queue for plugin event processing."""
    
    def __init__(self, plugin_name: str):
        try:
            super().__init__(daemon=True)
            self.plugin_name = plugin_name
            self.work_queue: queue.Queue = queue.Queue()
            self.queue_lock = threading.Lock()
            self.load_handler: Optional[threading.Thread] = None
            self.keep_going = True
            self._stop_event = threading.Event()
            logging.debug("PLUGIN EVENT QUEUE FOR %s starting", plugin_name)
            self.start()
        except Exception as e:
            logging.exception("Failed to create PluginEventQueue: %s", e)
            raise PluginEventError(f"Failed to create event queue for {plugin_name}") from e

    def __del__(self):
        """Ensure proper cleanup."""
        self.stop()

    def stop(self) -> None:
        """Stop the event queue gracefully."""
        self.keep_going = False
        self._stop_event.set()
        if self.load_handler and self.load_handler.is_alive():
            self.load_handler.join(timeout=5.0)

    def add_work(self, event_name: str, *args, **kwargs) -> bool:
        """Add work to the queue in a thread-safe manner."""
        if not self.keep_going:
            return False

        if event_name == "loaded":
            return self._handle_loaded_event(event_name, *args, **kwargs)
        else:
            self.work_queue.put([event_name, args, kwargs])
            return True

    def _handle_loaded_event(self, event_name: str, *args, **kwargs) -> bool:
        """Handle loaded event in separate thread."""
        try:
            cb_name = f'on_{event_name}'
            callback = getattr(loaded[self.plugin_name], cb_name, None)
            if callback and callable(callback):
                self.load_handler = threading.Thread(
                    target=run_once,
                    args=(self, event_name, *args),
                    kwargs=kwargs,
                    daemon=True,
                    name=f"PluginLoad_{self.plugin_name}"
                )
                self.load_handler.start()
                return True
            return False
        except Exception as e:
            logging.exception("Failed to handle loaded event for %s: %s", self.plugin_name, e)
            return False

    def run(self) -> None:
        """Main event processing loop."""
        logging.debug("Worker thread starting for %s", self.plugin_name)
        _safe_thread_name(f"PLG {self.plugin_name}")
        self.process_events()
        logging.info("Worker thread exiting for %s", self.plugin_name)

    def process_event(self, event_name: str, *args, **kwargs) -> None:
        """Process a single event."""
        cb_name = f'on_{event_name}'
        try:
            plugin = loaded.get(self.plugin_name)
            if not plugin:
                logging.warning("Plugin %s not found for event %s", self.plugin_name, event_name)
                return
                
            callback = getattr(plugin, cb_name, None)
            logging.debug("%s.%s: %s", self.plugin_name, event_name, repr(args))
            
            if callback and callable(callback):
                callback(*args, **kwargs)
        except Exception as e:
            logging.exception("Error processing event %s for plugin %s: %s", 
                            event_name, self.plugin_name, e)

    def process_events(self) -> None:
        """Process events from the queue."""
        global exitFlag
        
        while not exitFlag and self.keep_going and not self._stop_event.is_set():
            try:
                data = self.work_queue.get(timeout=2.0)
                if data is None:  # Sentinel value for shutdown
                    break
                    
                event_name, args, kwargs = data
                self.process_event(event_name, *args, **kwargs)
                self.work_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logging.exception("Error in event processing loop for %s: %s", 
                                self.plugin_name, e)

class Plugin:
    """Base class for all plugins."""
    
    def __init__(self):
        self.options: Dict[str, Any] = {}
        self._initialized = False

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Automatically register plugin subclasses."""
        super().__init_subclass__(**kwargs)
        global loaded, locks

        plugin_name = cls.__module__.split('.')[-1]  # Get just the module name
        try:
            plugin_instance = cls()
            logging.debug("Loaded plugin %s as %s", plugin_name, plugin_instance)
            loaded[plugin_name] = plugin_instance
            plugin_instance._initialized = True

            # Initialize locks for all event handlers
            for attr_name in dir(plugin_instance):
                if attr_name.startswith('on_'):
                    cb = getattr(plugin_instance, attr_name, None)
                    if cb is not None and callable(cb):
                        lock_key = f"{plugin_name}::{attr_name}"
                        locks[lock_key] = threading.Lock()
                        
        except Exception as e:
            logging.exception("Failed to initialize plugin %s: %s", plugin_name, e)
            raise PluginLoadError(f"Plugin {plugin_name} initialization failed") from e

def toggle_plugin(name: str, enable: bool = True) -> bool:
    """
    Load or unload a plugin.
    
    Returns:
        bool: True if changed, otherwise False
    """
    global loaded, database

    try:
        # Import here to avoid circular imports
        from .. import config as kaiagotchi_config
        from ..ui import view
        from ..utils import save_config

        config = kaiagotchi_config.CONFIG
        
        if not config:
            logging.error("No configuration available")
            return False

        # Ensure plugin entry exists in config
        if 'main' not in config or 'plugins' not in config['main']:
            config['main'] = config.get('main', {})
            config['main']['plugins'] = config['main'].get('plugins', {})
            
        if name not in config['main']['plugins']:
            config['main']['plugins'][name] = {}

        config['main']['plugins'][name]['enabled'] = enable

        if not enable and name in loaded:
            # Unload plugin
            return _unload_plugin(name, config, view)
        elif enable and name in database and name not in loaded:
            # Load plugin
            return _load_plugin(name, config, view)
            
        return False
        
    except ImportError as e:
        logging.error("Failed to import required modules: %s", e)
        return False
    except Exception as e:
        logging.exception("Error toggling plugin %s: %s", name, e)
        return False

def _unload_plugin(name: str, config: Dict[str, Any], view: Any) -> bool:
    """Unload a plugin and clean up resources."""
    try:
        plugin = loaded[name]
        
        # Call unload handler if exists
        if hasattr(plugin, 'on_unload') and callable(plugin.on_unload):
            plugin.on_unload(view.ROOT)
        
        # Clean up event queue
        if name in plugin_event_queues:
            plugin_event_queues[name].stop()
            del plugin_event_queues[name]
        
        # Remove from loaded plugins
        del loaded[name]
        
        # Save config
        from ..utils import save_config
        cfg_path = config.get("paths", {}).get("config_file", "/etc/kaiagotchi/config.toml")
        save_config(config, cfg_path)
        
        logging.info("Unloaded plugin: %s", name)
        return True
        
    except Exception as e:
        logging.exception("Error unloading plugin %s: %s", name, e)
        return False

def _load_plugin(name: str, config: Dict[str, Any], view: Any) -> bool:
    """Load a plugin and initialize it."""
    try:
        if not load_from_file(database[name]):
            return False
            
        if name in loaded and name in config['main']['plugins']:
            loaded[name].options = config['main']['plugins'][name]
        
        # Initialize plugin
        one(name, 'loaded')
        time.sleep(1)  # Reduced from 3 seconds for better responsiveness
        
        if config:
            one(name, 'config_changed', config)
            
        one(name, 'ui_setup', view.ROOT)
        
        if hasattr(view.ROOT, '_agent'):
            one(name, 'ready', view.ROOT._agent)
        
        # Save config
        from ..utils import save_config
        cfg_path = config.get("paths", {}).get("config_file", "/etc/kaiagotchi/config.toml")
        save_config(config, cfg_path)
        
        logging.info("Loaded plugin: %s", name)
        return True
        
    except Exception as e:
        logging.exception("Error loading plugin %s: %s", name, e)
        return False

def on(event_name: str, *args, **kwargs) -> None:
    """Send event to all loaded plugins."""
    global loaded, plugin_event_queues
    
    for plugin_name in list(loaded.keys()):  # Use list to avoid modification during iteration
        one(plugin_name, event_name, *args, **kwargs)

def one(plugin_name: str, event_name: str, *args, **kwargs) -> None:
    """Send event to a specific plugin."""
    global loaded, plugin_event_queues
    
    if plugin_name not in loaded:
        logging.debug("Plugin %s not loaded, skipping event %s", plugin_name, event_name)
        return
        
    plugin = loaded[plugin_name]
    cb_name = f'on_{event_name}'
    callback = getattr(plugin, cb_name, None)
    
    if callback is None or not callable(callback):
        return
        
    # Ensure event queue exists
    if plugin_name not in plugin_event_queues:
        plugin_event_queues[plugin_name] = PluginEventQueue(plugin_name)
    
    # Add work to queue
    if not plugin_event_queues[plugin_name].add_work(event_name, *args, **kwargs):
        logging.warning("Failed to add work for plugin %s, event %s", plugin_name, event_name)

def load_from_file(filename: str) -> bool:
    """Load a plugin from a file."""
    try:
        plugin_name = os.path.basename(filename).replace(".py", "")
        logging.debug("Loading plugin from %s", filename)
        
        spec = importlib.util.spec_from_file_location(plugin_name, filename)
        if spec is None or spec.loader is None:
            logging.error("Failed to create spec for %s", filename)
            return False
            
        instance = importlib.util.module_from_spec(spec)
        
        # Add plugin to sys.modules so it can be imported
        import sys
        sys.modules[plugin_name] = instance
        
        spec.loader.exec_module(instance)
        
        # Create event queue if needed
        if plugin_name not in plugin_event_queues:
            plugin_event_queues[plugin_name] = PluginEventQueue(plugin_name)
            
        return True
        
    except Exception as e:
        logging.exception("Failed to load plugin from %s: %s", filename, e)
        return False

def load_from_path(path: str, enabled: Set[str] = None) -> Dict[str, Any]:
    """Load plugins from a directory path."""
    global loaded, database
    
    if enabled is None:
        enabled = set()
        
    logging.debug("Loading plugins from %s - enabled: %s", path, enabled)
    
    if not os.path.exists(path):
        logging.warning("Plugin path does not exist: %s", path)
        return loaded
        
    for filename in glob.glob(os.path.join(path, "*.py")):
        if os.path.isdir(filename):
            continue
            
        plugin_name = os.path.basename(filename).replace(".py", "")
        database[plugin_name] = filename
        
        if plugin_name in enabled:
            try:
                if not load_from_file(filename):
                    logging.warning("Failed to load plugin: %s", plugin_name)
            except Exception as e:
                logging.warning("Error while loading %s: %s", filename, e)
                logging.debug("Detailed error:", exc_info=True)

    return loaded

def load(config: Dict[str, Any]) -> None:
    """Load all plugins based on configuration."""
    try:
        if 'main' not in config or 'plugins' not in config['main']:
            logging.warning("No plugin configuration found")
            return
            
        enabled = {
            name for name, options in config['main']['plugins'].items()
            if options.get('enabled', False)
        }

        # Load default plugins
        load_from_path(default_path, enabled=enabled)

        # Load custom plugins
        custom_path = config['main'].get('custom_plugins')
        if custom_path and os.path.exists(custom_path):
            load_from_path(custom_path, enabled=enabled)

        # Propagate options to loaded plugins
        for name, plugin in loaded.items():
            if name in config['main']['plugins']:
                plugin.options = config['main']['plugins'][name]
            else:
                plugin.options = {}

        # Initialize plugins
        on('loaded')
        on('config_changed', config)
        
        logging.info("Loaded %d plugins: %s", len(loaded), list(loaded.keys()))
        
    except Exception as e:
        logging.exception("Error loading plugins: %s", e)

def shutdown() -> None:
    """Shutdown all plugins and clean up resources."""
    global exitFlag, plugin_event_queues
    
    logging.info("Shutting down plugin system...")
    exitFlag = 1
    
    # Stop all event queues
    for plugin_name, queue in list(plugin_event_queues.items()):
        try:
            queue.stop()
            queue.join(timeout=5.0)
        except Exception as e:
            logging.warning("Error stopping queue for %s: %s", plugin_name, e)
    
    plugin_event_queues.clear()
    
    # Call unload on all plugins
    for plugin_name, plugin in list(loaded.items()):
        try:
            if hasattr(plugin, 'on_unload') and callable(plugin.on_unload):
                plugin.on_unload(None)
        except Exception as e:
            logging.warning("Error unloading plugin %s: %s", plugin_name, e)
    
    loaded.clear()
    logging.info("Plugin system shutdown complete")

# Safe plugin runner functions
def _plugin_runner(plugin_callable: Callable, *args, **kwargs) -> None:
    """Safely run a plugin callable with error handling."""
    try:
        plugin_callable(*args, **kwargs)
    except Exception:
        logging.exception("Plugin crashed: %s", 
                         getattr(plugin_callable, "__name__", repr(plugin_callable)))

def start_plugin_in_thread(plugin_callable: Callable, *args, **kwargs) -> threading.Thread:
    """Start a plugin callable in a separate thread."""
    thread = threading.Thread(
        target=_plugin_runner,
        args=(plugin_callable,) + args,
        kwargs=kwargs,
        daemon=True,
        name=f"PluginThread_{getattr(plugin_callable, '__name__', 'unknown')}"
    )
    thread.start()
    return thread

# Safe config saving
def save_config_safe(config: Dict[str, Any], save_func: Callable) -> bool:
    """Safely save configuration with error handling."""
    cfg_path = config.get("paths", {}).get("config_file", "/etc/kaiagotchi/config.toml")
    try:
        save_func(config, cfg_path)
        return True
    except Exception:
        logging.exception("Failed to save config to %s", cfg_path)
        return False