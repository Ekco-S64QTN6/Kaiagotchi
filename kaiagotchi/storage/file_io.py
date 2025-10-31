import os
import json
import logging
import tempfile
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

    # 2. Write to a temporary file in the same directory
    # Use tempfile.NamedTemporaryFile for automatic cleanup and unique name
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=dir_path, delete=False, encoding='utf-8') as tmp_file:
            # Dump the JSON data
            json.dump(data, tmp_file, indent=4)
            tmp_path = tmp_file.name

        # 3. Atomically rename the temporary file to the final destination
        # os.replace provides atomic move/rename operation on POSIX systems
        os.replace(tmp_path, filepath)
        file_io_logger.info(f"Successfully saved data to {filepath}")
        return True
    
    except Exception as e:
        file_io_logger.error(f"Error during atomic save to {filepath}: {e}", exc_info=True)
        
        # Clean up the temporary file if it still exists after an error
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception as clean_e:
                file_io_logger.warning(f"Failed to clean up temporary file {tmp_path}: {clean_e}")
                
        return False

def load_data(filepath: str, default: Any = None) -> Any:
    """
    Loads data (currently JSON) from a file.

    Args:
        filepath: The full path to the file to load.
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


# Example usage (for testing the module locally)
if __name__ == '__main__':
    file_io_logger.setLevel(logging.DEBUG)
    test_data = {'status': 'ok', 'count': 5, 'items': [1, 2, 3]}
    test_path = '/tmp/kaiagotchi_test_save.json'
    
    print(f"--- Testing Save to {test_path} ---")
    atomically_save_data(test_path, test_data)

    print(f"\n--- Testing Load from {test_path} ---")
    loaded_data = load_data(test_path, default={})
    print(f"Loaded Data: {loaded_data}")
        
    # Clean up (commented out so the user can verify the file if they wish)
    # if os.path.exists(test_path):
    #     os.remove(test_path)
    #     print("\nClean up successful.")
