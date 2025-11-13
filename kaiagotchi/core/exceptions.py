# exceptions.py - Enhanced version
class kaiagotchiError(Exception):
    """Base exception for all kaiagotchi errors."""
    pass

class NetworkError(kaiagotchiError):
    """Raised when network operations fail."""
    pass

class ConfigError(kaiagotchiError):
    """Raised when configuration is invalid."""
    pass

class SecurityError(kaiagotchiError):
    """Raised when security checks fail."""
    pass

class HardwareError(kaiagotchiError):
    """Raised when hardware operations fail."""
    pass

class ConfigValidationError(kaiagotchiError):
    """Raised when configuration validation fails."""
    pass