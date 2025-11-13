# kaiagotchi/storage/last_session.py
import os
import json
import logging
import tempfile
import stat
from typing import Dict, Any

class LastSession:
    """
    Handles saving and loading of Kaiagotchi's last session data
    in a user-safe and atomic manner.

    Fixes:
    - Prevents permission corruption (always owned by current user)
    - Writes atomically (no partial JSON)
    - Auto-creates ~/.kaiagotchi directory if missing
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.session_dir = os.path.expanduser("~/.kaiagotchi")
        self.session_file = os.path.join(self.session_dir, "last_session.json")
        self.data: Dict[str, Any] = {}

        # Ensure directory exists and is writable by the user
        try:
            os.makedirs(self.session_dir, exist_ok=True)
            os.chmod(self.session_dir, 0o700)
        except Exception as e:
            self.logger.error(f"Could not create or secure session directory {self.session_dir}: {e}")

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load last session data from JSON file."""
        try:
            if os.path.exists(self.session_file):
                with open(self.session_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                self.logger.info(f"Loaded session data from {self.session_file}")
            else:
                self.data = {}
                self.logger.info("No previous session file found — starting fresh.")
        except json.JSONDecodeError:
            self.logger.error(f"Session file {self.session_file} is corrupted. Resetting.")
            self.data = {}
        except PermissionError as e:
            self.logger.error(f"Permission denied when reading {self.session_file}: {e}")
            self.data = {}
        except Exception as e:
            self.logger.error(f"Failed to load session data: {e}")
            self.data = {}

    # ------------------------------------------------------------------
    def save(self) -> None:
        """Atomically save session data to file with preserved permissions."""
        dir_path = os.path.dirname(self.session_file)
        temp_file_name = None

        # Default permissions for new file
        existing_mode = 0o600
        existing_uid = os.getuid()
        existing_gid = os.getgid()

        # Preserve old ownership and mode if file exists
        if os.path.exists(self.session_file):
            try:
                st = os.stat(self.session_file)
                existing_mode = stat.S_IMODE(st.st_mode)
                existing_uid = st.st_uid
                existing_gid = st.st_gid
            except Exception as e:
                self.logger.debug(f"Could not stat {self.session_file}: {e}")

        try:
            # Write to temp file in same directory
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, dir=dir_path, encoding="utf-8"
            ) as tmp_fp:
                json.dump(self.data, tmp_fp, indent=2)
                temp_file_name = tmp_fp.name

            os.replace(temp_file_name, self.session_file)

            # Reapply ownership and permissions
            try:
                os.chmod(self.session_file, existing_mode)
            except Exception as e:
                self.logger.debug(f"chmod({self.session_file}) failed: {e}")

            try:
                os.chown(self.session_file, existing_uid, existing_gid)
            except PermissionError:
                pass
            except Exception as e:
                self.logger.debug(f"chown({self.session_file}) failed: {e}")

            self.logger.info(f"Session data saved to {self.session_file}")
        except Exception as e:
            self.logger.error(f"Failed to save session data atomically: {e}")
            if temp_file_name and os.path.exists(temp_file_name):
                try:
                    os.remove(temp_file_name)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    def get(self, key: str, default=None) -> Any:
        """Get a value from the session data dictionary."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a single key/value pair in session data."""
        self.data[key] = value

    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple key/value pairs in session data."""
        self.data.update(updates)
