import os
import json
import logging
import tempfile
import glob
import stat
from typing import Any, Dict

file_io_logger = logging.getLogger("file_io")


def atomically_save_data(filepath: str, data: Dict[str, Any], fmt: str = "json") -> bool:
    """
    Atomically saves data to a file, preserving ownership and permissions.
    Prevents corruption and permission flips between runs as root/non-root.

    Steps:
    - Write to a temp file in the same directory.
    - Replace target atomically with os.replace().
    - Reapply prior file's ownership/permissions if it existed.
    - If new file, set owner to current user and mode 600.
    """
    if fmt.lower() != "json":
        file_io_logger.error(f"Unsupported format '{fmt}' for atomic save.")
        return False

    file_io_logger.debug(f"Attempting atomic save to: {filepath}")

    # Ensure the parent directory exists
    dir_path = os.path.dirname(filepath)
    if dir_path and not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            file_io_logger.error(f"Could not create directory {dir_path}: {e}")
            return False

    # Preserve existing file metadata if present
    existing_mode = 0o600
    existing_uid = os.getuid()
    existing_gid = os.getgid()

    if os.path.exists(filepath):
        try:
            st = os.stat(filepath)
            existing_mode = stat.S_IMODE(st.st_mode)
            existing_uid = st.st_uid
            existing_gid = st.st_gid
        except Exception as e:
            file_io_logger.debug(f"Could not stat existing file {filepath}: {e}")

    temp_file_name = None
    try:
        # Write to a temporary file first
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=dir_path, encoding="utf-8"
        ) as tmp_fp:
            json.dump(data, tmp_fp, indent=4)
            temp_file_name = tmp_fp.name

        # Atomically replace original
        os.replace(temp_file_name, filepath)

        # Reapply ownership + permissions
        try:
            os.chmod(filepath, existing_mode)
        except Exception as e:
            file_io_logger.debug(f"chmod({filepath}, {oct(existing_mode)}) failed: {e}")

        try:
            os.chown(filepath, existing_uid, existing_gid)
        except PermissionError:
            # Non-root user can’t chown root-owned files
            pass
        except Exception as e:
            file_io_logger.debug(f"chown({filepath}, {existing_uid}, {existing_gid}) failed: {e}")

        file_io_logger.info(f"Successfully saved data to {filepath} atomically.")
        return True

    except Exception as e:
        file_io_logger.error(f"Error during atomic save to {filepath}: {e}", exc_info=True)
        if temp_file_name and os.path.exists(temp_file_name):
            os.remove(temp_file_name)
        return False


def load_data(filepath: str, default: Any = None) -> Any:
    """
    Loads data from JSON, handling permission and decoding errors safely.
    """
    if not os.path.exists(filepath):
        file_io_logger.debug(f"File not found: {filepath}. Returning default value.")
        return default

    file_io_logger.debug(f"Loading data from: {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            file_io_logger.info(f"Successfully loaded data from {filepath}")
            return data
    except PermissionError as e:
        file_io_logger.error(
            f"Permission denied when reading {filepath}: {e}. "
            "Try adjusting ownership or running as the same user who created the file."
        )
        return default
    except json.JSONDecodeError:
        file_io_logger.error(f"File {filepath} is corrupted (Invalid JSON).")
        return default
    except Exception as e:
        file_io_logger.error(f"Error reading file {filepath}: {e}")
        return default


def total_unique_handshakes(path: str) -> int:
    """
    Count .pcap files in a directory — used for handshake tracking.
    """
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))


# Example usage for local testing
if __name__ == "__main__":
    file_io_logger.setLevel(logging.DEBUG)

    # 1. Test Save/Load
    test_data = {"status": "ok", "count": 5, "items": [1, 2, 3]}
    test_path = "/tmp/kaiagotchi_test_save.json"

    print(f"--- Testing Save to {test_path} ---")
    atomically_save_data(test_path, test_data)

    print(f"\n--- Testing Load from {test_path} ---")
    loaded = load_data(test_path, default={})
    print(f"Loaded Data: {loaded}")

    # Cleanup
    if os.path.exists(test_path):
        os.remove(test_path)

    # 2. Test Handshake Count
    print(f"\n--- Testing Handshake Count ---")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(
        f"Handshakes in current directory ({current_dir}): "
        f"{total_unique_handshakes(current_dir)}"
    )
