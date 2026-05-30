# kaiagotchi/agent/__init__.py
"""
Agent layer for Kaiagotchi.
Includes:
- MonitoringAgent for live airodump-ng streaming
- kaiagotchiBase for shared logic
"""
from .monitoring_agent import MonitoringAgent
from .base import kaiagotchiBase

__all__ = ["MonitoringAgent", "kaiagotchiBase"]
