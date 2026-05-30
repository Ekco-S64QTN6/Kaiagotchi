import logging
from kaiagotchi.ui.terminal_display import TerminalDisplay

logger = logging.getLogger("kaiagotchi.ui.display")


class Display:
    """
    Provides a unified display abstraction layer for Kaiagotchi.
    Delegates to the active UI backend (e.g., TerminalDisplay).
    """

    def __init__(self, config):
        self.config = config
        ui_cfg = config.get("ui", {}).get("display", {})
        self._enabled = ui_cfg.get("enabled", True)
        self._rotation = ui_cfg.get("rotation", 0)
        self._implementation = TerminalDisplay(config)
        self._agent = None
        logger.debug("Display abstraction initialized (Terminal mode).")

        self.init_display()

    # ------------------------------------------------------
    # Initialization
    # ------------------------------------------------------
    def init_display(self):
        """Initialize the display implementation."""
        if not self._enabled:
            logger.warning("Display is disabled in configuration.")
            return

        try:
            if hasattr(self._implementation, "initialize"):
                self._implementation.initialize()
                logger.info("Terminal display initialized successfully.")
        except Exception as e:
            logger.error(f"Display initialization failed: {e}")

    # ------------------------------------------------------
    # Rendering and Control
    # ------------------------------------------------------
    def render(self, view_data):
        """Render view data using the active display implementation."""
        if not self._enabled:
            logger.debug("Skipping render: Display disabled.")
            return

        try:
            self._implementation.render(view_data)
        except Exception as e:
            logger.error(f"Error rendering display frame: {e}")

    def clear(self):
        """Clear the display."""
        if hasattr(self._implementation, "clear"):
            try:
                self._implementation.clear()
            except Exception as e:
                logger.warning(f"Error clearing display: {e}")

    # ------------------------------------------------------
    # Agent Binding
    # ------------------------------------------------------
    def set_agent(self, agent):
        """Bind the agent for context-aware display updates."""
        self._agent = agent
        if hasattr(self._implementation, "set_agent"):
            try:
                self._implementation.set_agent(agent)
            except Exception as e:
                logger.warning(f"Display agent binding failed: {e}")

    # ------------------------------------------------------
    # Capability flags
    # ------------------------------------------------------
    def is_dummy_display(self):
        """Return True for non-physical (terminal) display."""
        return True

    def is_waveshare_any(self):
        """No Waveshare hardware in terminal mode."""
        return False
