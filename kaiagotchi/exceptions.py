class KaiagotchiError(Exception):
    """Base exception for all Kaiagotchi errors."""
    pass

class NetworkError(KaiagotchiError):
    """Raised when network operations fail."""
    pass

class ConfigError(KaiagotchiError):
    """Raised when configuration is invalid."""
    pass