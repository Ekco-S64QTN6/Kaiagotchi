"""Legacy import-compatibility shims for the unsupported Bettercap backend.

Kaiagotchi currently uses its passive airodump-ng capture implementation.
These names remain importable for older integrations, but they do not manage
or launch a Bettercap process. Calling start() fails explicitly.
"""

from typing import Any

_UNSUPPORTED_BACKEND = (
    "The Bettercap backend is not supported by Kaiagotchi. "
    "Use the built-in passive airodump-ng capture path instead."
)


class BettercapIntegration:
    """Legacy compatibility name; no Bettercap process lifecycle is available."""

    def __init__(self, config: Any):
        self.config = config

    def start(self) -> None:
        """Fail explicitly rather than claiming an unsupported backend started."""
        raise NotImplementedError(_UNSUPPORTED_BACKEND)

    def stop(self) -> None:
        """Remain safe to call when no Bettercap process was started."""
        return None


class Client:
    """Legacy plugin-import compatibility name for the unsupported backend."""

    def __init__(self, config: Any):
        self.config = config

    def start(self) -> None:
        """Fail explicitly rather than claiming an unsupported client started."""
        raise NotImplementedError(_UNSUPPORTED_BACKEND)

    def stop(self) -> None:
        """Remain safe to call when no Bettercap process was started."""
        return None


__all__ = ["BettercapIntegration", "Client"]
