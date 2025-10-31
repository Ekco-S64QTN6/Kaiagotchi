import os
import json
import logging
import tempfile
import glob # New import for total_unique_handshakes
from typing import Any, Dict

file_io_logger = logging.getLogger('file_io')


def atomically_save_data(filepath: str, data: Dict[str, Any], fmt: str = 'json') -> bool:
    """
    Saves data to a file in an atomic manner using a temporary file.
    This prevents data corruption if the process is interrupted during the write operation.

    The temporary file is written first, then it is atomically renamed to the
    final destination filepath.

    Args:
        filepath: The full path to the final destination file.
        data: The dictionary or object to save.
        fmt: The format to use ('json' only supported currently).

    Returns:
        True if the save was successful, False otherwise.
    """
    if fmt.lower() != 'json':
        file_io_logger.error(f"Unsupported format '{fmt}' for atomic save.")
        return False

    file_io_logger.debug(f"Attempting atomic save to: {filepath}")
    
    # 1. Ensure the directory exists
    dir_path = os.path.dirname(filepath)
    if dir_path and not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError as e:
            file_io_logger.error(f"Could not create directory {dir_path}: {e}")
            return False

    # 2. Use a temporary file in the same directory for atomic rename
    temp_file_name = None
    try:
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=dir_path, encoding='utf-8') as tmp_fp:
            json.dump(data, tmp_fp, indent=4)
            temp_file_name = tmp_fp.name
        
        # 3. Atomically rename the temporary file to the final destination
        os.rename(temp_file_name, filepath)
        file_io_logger.info(f"Successfully saved data to {filepath} atomically.")
        return True
    
    except Exception as e:
        file_io_logger.error(f"Error during atomic save to {filepath}: {e}", exc_info=True)
        # Clean up the temporary file if it was created but rename failed
        if temp_file_name and os.path.exists(temp_file_name):
            os.remove(temp_file_name)
        return False


def load_data(filepath: str, default: Any = None) -> Any:
    """
    Loads data from a file assumed to be in JSON format.

    Handles file-not-found, JSON decoding errors, and other I/O errors gracefully.

    Args:
        filepath: The full path to the file.
        default: The value to return if the file does not exist or is corrupted.

    Returns:
        The loaded data (usually a dictionary) or the default value.
    """
    if not os.path.exists(filepath):
        file_io_logger.debug(f"File not found: {filepath}. Returning default value.")
        return default

    file_io_logger.debug(f"Loading data from: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            file_io_logger.info(f"Successfully loaded data from {filepath}")
            return data
    except json.JSONDecodeError:
        file_io_logger.error(f"File {filepath} is corrupted (Invalid JSON).")
        return default
    except Exception as e:
        file_io_logger.error(f"Error reading file {filepath}: {e}")
        return default


def total_unique_handshakes(path: str) -> int:
    """
    Returns the count of unique handshakes (files ending in .pcap) in a directory.

    This function is a file system utility, scanning a path for capture files.

    Args:
        path: The directory path to scan.

    Returns:
        The total number of .pcap files found.
    """
    expr = os.path.join(path, "*.pcap")
    return len(glob.glob(expr))


# Example usage (for testing the module locally)
if __name__ == '__main__':
    file_io_logger.setLevel(logging.DEBUG)
    
    # 1. Test Save/Load
    test_data = {'status': 'ok', 'count': 5, 'items': [1, 2, 3]}
    test_path = '/tmp/kaiagotchi_test_save.json'
    
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
    # Get the directory of the current file for a realistic test path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # The count should likely be 0 unless tested in a capture directory
    print(f"Handshakes in current directory ({current_dir}): {total_unique_handshakes(current_dir)}")
