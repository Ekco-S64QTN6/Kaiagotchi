# exceptions.py - Enhanced version
class KaiagotchiError(Exception):
    """Base exception for all Kaiagotchi errors."""
    pass

class NetworkError(KaiagotchiError):
    """Raised when network operations fail."""
    pass

class ConfigError(KaiagotchiError):
    """Raised when configuration is invalid."""
    pass

class SecurityError(KaiagotchiError):
    """Raised when security checks fail."""
    pass

class HardwareError(KaiagotchiError):
    """Raised when hardware operations fail."""
    pass

class ConfigValidationError(KaiagotchiError):
    """Raised when configuration validation fails."""
    pass