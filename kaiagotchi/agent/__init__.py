# kaiagotchi/agent/__init__.py
"""
Agent module for Kaiagotchi - contains the core decision-making and monitoring components.
"""

from .base import KaiagotchiBase
from .decision_engine import DecisionEngine, AgentState
from .monitoring_agent import MonitoringAgent

# FIX: Import the Agent class from the sibling agent.py file so it can be accessed
from .agent import Agent 

# UPDATE: Include 'Agent' in the list of exported names
__all__ = ['Agent', 'KaiagotchiBase', 'DecisionEngine', 'AgentState', 'MonitoringAgent']