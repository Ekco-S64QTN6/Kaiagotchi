import logging
import json
import threading
import time
from typing import Dict, Any

# We must import from the 'kaiagotchi' namespace as per the project structure
# Corrected imports for utilities and file I/O:
from kaiagotchi.utils import get_state_path
from kaiagotchi.storage.file_io import atomically_save_data, load_data

# Configure logging for the agent base module
agent_logger = logging.getLogger('agent.base')

# Define the base state dictionary structure for initial load
DEFAULT_STATE = {
    'name': 'Kaiagotchi',
    'face': '^_^',
    'uptime': 0,
    'last_seen': 0,
    'total_handshakes': 0,
    'session_handshakes': 0,
    'status': 'Loading...'
}

class KaiagotchiBase:
    """
    The base class for the Kaiagotchi agent.
    
    This class handles core agent identity, persistent state loading/saving,
    and defines the fundamental lifecycle methods for the agent.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initializes the agent with configuration and loads state.
        
        Args:
            config: The application configuration dictionary.
        """
        self.config = config
        # Use the name from config, default to 'Kaiagotchi'
        self.name = config.get('main', {}).get('name', 'Kaiagotchi')
        self.base_dir = config.get('main', {}).get('base_dir', '/var/lib/kaiagotchi')
        
        # Determine state file path using the utility function from kaiagotchi.utils
        self.state_file_path = get_state_path(self.config, 'agent_state.json')
        agent_logger.info(f"Agent state file path: {self.state_file_path}")
        
        # Load or initialize state
        self._state = self._load_state()
        
        # Simple agent loop management
        self._running = False
        self._stop_event = threading.Event()

    def _load_state(self) -> Dict[str, Any]:
        """
        Attempts to load persistent state from disk using kaiagotchi.storage.file_io.
        
        If the file doesn't exist or is corrupted, returns the default state.
        """
        # load_data is imported from kaiagotchi.storage.file_io
        loaded_state = load_data(self.state_file_path, default=DEFAULT_STATE)
        
        # The agent's name should always be governed by the config
        loaded_state['name'] = self.name
        
        agent_logger.info(f"Agent state loaded. Current face: {loaded_state.get('face')}")
        return loaded_state

    def save_state(self) -> bool:
        """
        Saves the current agent state atomically to disk using kaiagotchi.storage.file_io.
        """
        # Update last_seen timestamp before saving (necessary for accurate status reporting)
        self.set('last_seen', int(time.time()))
        
        # atomically_save_data is imported from kaiagotchi.storage.file_io
        success = atomically_save_data(self.state_file_path, self._state)
        if success:
            agent_logger.debug("Agent state saved successfully.")
        else:
            agent_logger.error("Failed to save agent state atomically.")
        return success

    # --- State Accessors ---
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Gets a value from the agent's state.
        """
        return self._state.get(key, default)

    def set(self, key: str, value: Any):
        """
        Sets a value in the agent's state.
        """
        self._state[key] = value

    # --- Agent Lifecycle Methods (to be implemented/overridden) ---

    def on_loaded(self):
        """
        Called once when the agent is loaded and initialized. 
        This is the main entry point for post-setup tasks.
        """
        agent_logger.info(f"Agent '{self.name}' is loaded and ready.")
        pass

    def run(self):
        """
        The main agent loop. This method should block or be run in a separate thread.
        """
        self._running = True
        agent_logger.info("Agent main loop started.")
        while not self._stop_event.is_set():
            # Placeholder for core agent logic (scanning, decision making, etc.)
            
            # Update uptime and status for demonstration
            # Increment uptime by the loop pause time (5 seconds)
            self.set('uptime', self.get('uptime', 0) + 5)
            self.set('status', f"Running for {self.get('uptime')} seconds...")
            
            # Save the state every 5 seconds
            self.save_state()
            self._stop_event.wait(timeout=5) # Pause execution
            
        agent_logger.info("Agent main loop stopped.")

    def stop(self):
        """
        Signals the agent's main loop to stop gracefully.
        """
        if self._running:
            agent_logger.info("Stopping agent...")
            self._stop_event.set()
            self._running = False
            self.save_state()
            agent_logger.info("Agent stopped.")
            
    # --- Other Core Methods ---
    
    def on_handshake_capture(self, capture_data: Dict[str, Any]):
        """
        Called when a new, unique handshake (or PMKID) is successfully captured.
        
        Args:
            capture_data: Dictionary containing details about the capture.
        """
        self.set('total_handshakes', self.get('total_handshakes', 0) + 1)
        self.set('session_handshakes', self.get('session_handshakes', 0) + 1)
        agent_logger.info(f"Handshake captured! Total: {self.get('total_handshakes')}")
        pass