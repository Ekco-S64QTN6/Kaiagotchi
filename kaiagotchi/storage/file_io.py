import glob
import json
import logging
import os
import stat
import tempfile
from typing import Any

file_io_logger = logging.getLogger("file_io")


def atomically_save_data(filepath: str, data: dict[str, Any], fmt: str = "json") -> bool:
    """
    Atomically saves data to a file, preserving ownership and permissions.
    Prevents corruption and permission flips between runs as root/non-root.

    Steps:
    - Write the complete JSON document to a temporary file in the target directory.
    - Flush and fsync the file contents before it can replace the current state.
    - Apply the prior file's ownership/permissions (or private 0600 defaults).
    - Replace the target atomically, then fsync the parent directory entry.

    File and directory synchronization improve crash durability; atomic replace
    alone guarantees visibility, not persistence across sudden power loss.
    """
    if fmt.lower() != "json":
        file_io_logger.error(f"Unsupported format '{fmt}' for atomic save.")
        return False

    file_io_logger.debug(f"Attempting atomic save to: {filepath}")

    # Use the current directory for relative paths such as "state.json".
    dir_path = os.path.dirname(filepath) or "."
    try:
        os.makedirs(dir_path, exist_ok=True)
    except OSError as exc:
        file_io_logger.error("Could not create directory %s: %s", dir_path, exc)
        return False

    # Preserve existing file metadata if present. New files remain private.
    existing_mode = 0o600
    existing_uid = os.getuid()
    existing_gid = os.getgid()

    try:
        # lstat is deliberate: a symlink target is not the metadata source for
        # the new state file. os.replace() will replace the link itself.
        existing_stat = os.lstat(filepath)
    except FileNotFoundError:
        existing_stat = None
    except OSError as exc:
        file_io_logger.debug("Could not lstat existing file %s: %s", filepath, exc)
        existing_stat = None

    if existing_stat is not None and stat.S_ISREG(existing_stat.st_mode):
        existing_mode = stat.S_IMODE(existing_stat.st_mode)
        existing_uid = existing_stat.st_uid
        existing_gid = existing_stat.st_gid
    elif existing_stat is not None:
        file_io_logger.warning(
            "Replacing non-regular state path %s with a private regular file",
            filepath,
        )

    temp_file_name: str | None = None
    replaced = False
    try:
        # Keep the temporary file on the target filesystem so os.replace()
        # remains atomic. Capture its name before serialization can fail.
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, dir=dir_path, encoding="utf-8"
        ) as tmp_fp:
            temp_file_name = tmp_fp.name
            json.dump(data, tmp_fp, indent=4)
            tmp_fp.flush()

            # Set metadata before publishing the new inode. chown may clear
            # set-id bits, so permissions are applied afterwards.
            try:
                os.fchown(tmp_fp.fileno(), existing_uid, existing_gid)
            except PermissionError:
                # An unprivileged process cannot take ownership of a prior
                # root-owned file; retain the temporary file's current owner.
                pass
            except OSError as exc:
                file_io_logger.debug(
                    "fchown(%s, %d, %d) failed: %s",
                    temp_file_name,
                    existing_uid,
                    existing_gid,
                    exc,
                )

            try:
                os.fchmod(tmp_fp.fileno(), existing_mode)
            except OSError as exc:
                # NamedTemporaryFile starts at 0600, so failures are private.
                file_io_logger.debug(
                    "fchmod(%s, %s) failed: %s",
                    temp_file_name,
                    oct(existing_mode),
                    exc,
                )

            # The file's contents and metadata must reach stable storage before
            # a directory entry can point at this inode.
            os.fsync(tmp_fp.fileno())

        os.replace(temp_file_name, filepath)
        replaced = True
        temp_file_name = None

        # Persist the rename itself. Opening the directory also works for
        # relative target paths because dir_path is normalized above.
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(dir_path, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        file_io_logger.info("Successfully saved data to %s atomically and durably.", filepath)
        return True

    except Exception as exc:
        if replaced:
            file_io_logger.error(
                "State file %s was replaced, but durability could not be confirmed: %s",
                filepath,
                exc,
                exc_info=True,
            )
        else:
            file_io_logger.error(
                "Error during atomic save to %s: %s", filepath, exc, exc_info=True
            )
        if temp_file_name and os.path.exists(temp_file_name):
            try:
                os.remove(temp_file_name)
            except OSError:
                file_io_logger.warning("Could not remove temporary state file %s", temp_file_name)
        return False


def load_data(filepath: str, default: Any = None) -> Any:
    """Load JSON only from a regular file, without following symlinks."""
    file_io_logger.debug("Loading data from: %s", filepath)
    descriptor: int | None = None
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(filepath, flags)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            file_io_logger.warning(
                "Refusing to load non-regular state path %s", filepath
            )
            return default

        state_file = os.fdopen(descriptor, "r", encoding="utf-8")
        descriptor = None
        with state_file as fp:
            data = json.load(fp)
        file_io_logger.info("Successfully loaded data from %s", filepath)
        return data
    except FileNotFoundError:
        file_io_logger.debug("File not found: %s. Returning default value.", filepath)
        return default
    except PermissionError as exc:
        file_io_logger.error(
            "Permission denied when reading %s: %s. "
            "Try adjusting ownership or running as the same user who created the file.",
            filepath,
            exc,
        )
        return default
    except json.JSONDecodeError:
        file_io_logger.error("File %s is corrupted (Invalid JSON).", filepath)
        return default
    except OSError as exc:
        file_io_logger.warning(
            "Could not safely open state file %s without following links: %s",
            filepath,
            exc,
        )
        return default
    except Exception as exc:
        file_io_logger.error("Error reading file %s: %s", filepath, exc)
        return default
    finally:
        if descriptor is not None:
            os.close(descriptor)


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
    print("\n--- Testing Handshake Count ---")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(
        f"Handshakes in current directory ({current_dir}): "
        f"{total_unique_handshakes(current_dir)}"
    )
