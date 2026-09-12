# kaiagotchi/ai/__init__.py
"""
AI Subsystems for Kaiagotchi:
- EpochTracker: temporal context
- RewardEngine: reward modeling
"""
from .epoch import Epoch as EpochTracker
from .reward import RewardEngine

__all__ = ["RewardEngine", "EpochTracker"]
