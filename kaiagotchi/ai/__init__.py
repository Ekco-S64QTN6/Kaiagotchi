# kaiagotchi/ai/__init__.py
"""
AI Subsystems for Kaiagotchi:
- EpochTracker: temporal context
- RewardEngine: reward modeling
"""
from .reward import RewardEngine
from .epoch import EpochTracker

__all__ = ["RewardEngine", "EpochTracker"]
