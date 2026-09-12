# kaiagotchi/agent/__init__.py
"""
Agent layer for Kaiagotchi.
Includes:
- MonitoringAgent for live airodump-ng streaming
- kaiagotchiBase for shared logic
"""
from .base import kaiagotchiBase
from .monitoring_agent import MonitoringAgent

__all__ = ["MonitoringAgent", "kaiagotchiBase"]
