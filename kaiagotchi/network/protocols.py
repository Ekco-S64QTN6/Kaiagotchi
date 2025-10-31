from typing import Protocol, Dict, Any, List, Optional, runtime_checkable

@runtime_checkable
class ActionManager(Protocol):
    """Protocol defining the interface for network action managers with enhanced operations."""
    
    async def set_monitor_mode(self, interface: str, timeout: float = 30.0) -> bool:
        """Set interface to monitor mode with timeout support."""
        ...
    
    async def set_managed_mode(self, interface: str, timeout: float = 30.0) -> bool:
        """Set interface to managed mode with timeout support."""
        ...
    
    async def get_interface_info(self, interface: str) -> Dict[str, Any]:
        """Get comprehensive interface information."""
        ...

    async def get_access_points(self, scan_time: int = 10) -> List[Dict[str, Any]]:
        """Scan for wireless access points."""
        ...

    async def cleanup(self) -> None:
        """Cleanup resources and reset interfaces."""
        ...

    async def is_interface_available(self, interface: str) -> bool:
        """Check if interface exists and is available."""
        ...

    async def get_supported_modes(self, interface: str) -> List[str]:
        """Get supported interface modes (monitor, managed, etc.)."""
        ...


@runtime_checkable
class NetworkMonitor(Protocol):
    """Protocol for network monitoring components."""
    
    def start(self) -> None:
        """Start the network monitor."""
        ...
    
    def stop(self) -> None:
        """Stop the network monitor."""
        ...
    
    def get_current_state(self) -> Dict[str, Any]:
        """Get current network state snapshot."""
        ...


@runtime_checkable  
class PacketHandler(Protocol):
    """Protocol for packet capture and analysis."""
    
    async def start_capture(self, interface: str, **kwargs) -> bool:
        """Start packet capture on interface."""
        ...
    
    async def stop_capture(self) -> None:
        """Stop packet capture."""
        ...
    
    async def get_capture_stats(self) -> Dict[str, Any]:
        """Get capture statistics."""
        ...
    
    def is_capturing(self) -> bool:
        """Check if currently capturing packets."""
        ...