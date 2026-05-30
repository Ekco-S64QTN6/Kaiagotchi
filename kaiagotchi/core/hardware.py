import os
import logging

_LOG = logging.getLogger("kaiagotchi.core.hardware")

def get_interface_model(interface: str) -> str:
    """
    Attempt to get the hardware model/product name for a network interface.
    Reads from /sys/class/net/{interface}/device/../product
    """
    if not interface or interface == "unknown":
        return "Unknown Device"

    try:
        # Path to the device symlink in sysfs
        sys_path = f"/sys/class/net/{interface}/device"
        
        # For USB devices, product/manufacturer are often in the parent directory
        # of the interface device symlink target.
        # We can try reading 'product' and 'manufacturer' from the device dir
        # and its parent.
        
        paths_to_check = [
            sys_path,           # Direct device
            f"{sys_path}/..",   # Parent (common for USB)
        ]
        
        manufacturer = ""
        product = ""
        
        for path in paths_to_check:
            # Try to find manufacturer
            if not manufacturer:
                try:
                    with open(os.path.join(path, "manufacturer"), "r") as f:
                        manufacturer = f.read().strip()
                except (OSError, IOError):
                    pass
            
            # Try to find product
            if not product:
                try:
                    with open(os.path.join(path, "product"), "r") as f:
                        product = f.read().strip()
                except (OSError, IOError):
                    pass
            
            if manufacturer and product:
                break
        
        if manufacturer and product:
            return f"{manufacturer} {product}"
        elif product:
            return product
        elif manufacturer:
            return f"{manufacturer} Device"
            
    except Exception as e:
        _LOG.debug(f"Failed to get hardware model for {interface}: {e}")
        
    return "Generic Interface"
