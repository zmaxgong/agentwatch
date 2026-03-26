"""
AgentWatch SDK - Observability for AI Agents
Monitor cost, performance, hallucinations, and behavioral drift.
"""

from .client import AgentWatch
from .wrapper import MonitoredClient
from .events import Event, EventType
from .config import AgentWatchConfig

__version__ = "0.1.0"
__all__ = ["AgentWatch", "MonitoredClient", "Event", "EventType", "AgentWatchConfig"]
