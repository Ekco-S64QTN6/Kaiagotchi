from typing import Protocol, Dict, Any

class ActionManager(Protocol):
    """Protocol defining the interface for network action managers."""
    
    def set_monitor_mode(self, iface: str, timeout: float = 30.0) -> bool:
        """Set interface to monitor mode."""
        ...
    
    def set_managed_mode(self, iface: str, timeout: float = 30.0) -> bool:
        """Set interface to managed mode."""
        ...
    
    def get_interface_info(self, iface: str) -> Dict[str, Any]:
        """Get current interface information."""
        ...

    def cleanup(self) -> None:
        """Cleanup resources and reset interfaces."""
        ...
