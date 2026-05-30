from threading import Lock
import logging

log = logging.getLogger(__name__)


class State:
    """Thread-safe container for Kaiagotchi's UI elements."""

    def __init__(self, initial_state=None):
        # Avoid mutable default argument issues
        self._state = dict(initial_state) if isinstance(initial_state, dict) else {}

        # Initialize default tracked values - CHANGED: "CALM" to "NEUTRAL"
        self._state.setdefault("agent_mood", "NEUTRAL")
        self._state.setdefault("reward_value", 0.0)
        self._state.setdefault("face", "(・_・)")
        self._state.setdefault("status", "Booting up...")
        self._state.setdefault("channel", "--")
        self._state.setdefault("mode", "INIT")
        self._state.setdefault("aps", 0)

        self._lock = Lock()
        self._listeners = {}
        self._changes = {}

    # -------------------------------------------------------------------------
    # Element management
    # -------------------------------------------------------------------------

    def add_element(self, key, elem):
        """Add a new UI element object (with .value attribute)."""
        with self._lock:
            self._state[key] = elem
            self._changes[key] = True
            log.debug(f"State.add_element: added '{key}'")

    def has_element(self, key) -> bool:
        """Check if a UI element exists."""
        with self._lock:
            return key in self._state

    def remove_element(self, key):
        """Remove an element and mark as changed."""
        with self._lock:
            if key in self._state:
                del self._state[key]
                self._changes[key] = True
                log.debug(f"State.remove_element: removed '{key}'")

    # -------------------------------------------------------------------------
    # Listener management
    # -------------------------------------------------------------------------

    def add_listener(self, key, cb):
        """Attach a callback listener for value changes on key."""
        with self._lock:
            self._listeners[key] = cb
            log.debug(f"State.add_listener: registered listener for '{key}'")

    # -------------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------------

    def items(self):
        """Thread-safe iteration over state items."""
        with self._lock:
            return list(self._state.items())

    def get(self, key):
        """Return the current value for a key, or None."""
        with self._lock:
            val = self._state.get(key)
            if hasattr(val, "value"):
                return val.value
            return val

    # -------------------------------------------------------------------------
    # Change tracking
    # -------------------------------------------------------------------------

    def reset(self):
        """Reset the internal change tracker."""
        with self._lock:
            self._changes.clear()
            log.debug("State.reset: cleared change tracker")

    def changes(self, ignore=()):
        """Return list of keys that have changed since last reset."""
        with self._lock:
            return [k for k in self._changes if k not in ignore]

    def has_changes(self) -> bool:
        """Return True if any keys have changed since last reset."""
        with self._lock:
            return len(self._changes) > 0

    # -------------------------------------------------------------------------
    # Core setter
    # -------------------------------------------------------------------------

    def set(self, key, value):
        """
        Set a value for a key. Creates the element if it doesn't exist.
        If the value changes, mark as changed and call listener if any.
        """
        with self._lock:
            # Create new element if it doesn't exist
            if key not in self._state:
                elem = type("UIElement", (), {"value": value})()
                self._state[key] = elem
                self._changes[key] = True
                log.debug(f"State.set: created new key '{key}' -> {value!r}")

                if key in self._listeners and self._listeners[key]:
                    try:
                        self._listeners[key](None, value)
                    except Exception:
                        log.exception(f"Listener for '{key}' raised an error")
                return

            # Existing key: update only if value actually changed
            prev_elem = self._state[key]
            prev_value = prev_elem.value if hasattr(prev_elem, "value") else prev_elem
            if prev_value != value:
                if hasattr(prev_elem, "value"):
                    prev_elem.value = value
                else:
                    self._state[key] = type("UIElement", (), {"value": value})()
                self._changes[key] = True
                log.debug(f"State.set: updated '{key}' {prev_value!r} -> {value!r}")

                if key in self._listeners and self._listeners[key]:
                    try:
                        self._listeners[key](prev_value, value)
                    except Exception:
                        log.exception(f"Listener for '{key}' raised an error")

    # -------------------------------------------------------------------------
    # Convenience setters / getters
    # -------------------------------------------------------------------------

    def set_mood(self, mood: str):
        """Convenience wrapper to set the agent mood."""
        self.set("agent_mood", mood)

    def set_reward(self, value: float):
        """Convenience wrapper to set the numeric reward value."""
        self.set("reward_value", round(float(value), 4))

    def get_mood(self) -> str:
        """Return current agent mood (default NEUTRAL).""" 
        return self.get("agent_mood") or "NEUTRAL"

    def get_reward(self) -> float:
        """Return current reward value (default 0.0)."""
        try:
            return float(self.get("reward_value") or 0.0)
        except Exception:
            return 0.0