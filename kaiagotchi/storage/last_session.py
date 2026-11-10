"""Private, atomic persistence for the most recent Kaiagotchi session."""

import logging
import os
import stat
from typing import Any

from .file_io import atomically_save_data, load_data


class LastSession:
    """Load and save last-session metadata inside an owner-only directory."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.session_dir = os.path.expanduser("~/.kaiagotchi")
        self.session_file = os.path.join(self.session_dir, "last_session.json")
        self.data: dict[str, Any] = {}
        self._storage_ready = False

        descriptor: int | None = None
        try:
            os.makedirs(self.session_dir, exist_ok=True)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self.session_dir, flags)
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("session storage path is not a directory")
            os.fchmod(descriptor, 0o700)
            self._storage_ready = True
        except OSError as exc:
            self.logger.error(
                "Could not securely open session directory %s: %s",
                self.session_dir,
                exc,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load JSON only from a regular session file, never a symlink target."""
        if not self._storage_ready:
            self.data = {}
            return

        value = load_data(self.session_file, default={})
        self.data = value if isinstance(value, dict) else {}

    # ------------------------------------------------------------------
    def save(self) -> None:
        """Atomically save the session using the shared private-file contract."""
        if not self._storage_ready:
            self.logger.error("Session storage is unavailable; refusing to save.")
            return

        if atomically_save_data(self.session_file, self.data, fmt="json"):
            self.logger.info("Session data saved to %s", self.session_file)
        else:
            self.logger.error("Failed to save session data to %s", self.session_file)

    # ------------------------------------------------------------------
    def get(self, key: str, default=None):
        """Get a value from the session data dictionary."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a single key/value pair in session data."""
        self.data[key] = value

    def update(self, updates: dict[str, Any]) -> None:
        """Update multiple key/value pairs in session data."""
        self.data.update(updates)
