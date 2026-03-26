"""Configuration for AgentWatch SDK."""

from dataclasses import dataclass, field
from typing import Optional

# Pricing per million tokens (as of March 2026)
MODEL_PRICING = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    # OpenAI (for future multi-model support)
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    # Google (for future multi-model support)
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
}


@dataclass
class AgentWatchConfig:
    """Configuration for the AgentWatch monitoring client."""

    # Where to send telemetry
    backend_url: str = "http://localhost:8100"

    # Project identification
    project_id: str = "default"
    environment: str = "development"

    # Agent identification
    agent_name: str = "default-agent"
    agent_version: str = "0.1.0"

    # Cost alerting
    cost_alert_threshold_hourly: float = 5.00  # USD
    cost_alert_threshold_daily: float = 50.00  # USD

    # Hallucination detection
    enable_hallucination_detection: bool = True
    hallucination_confidence_threshold: float = 0.7

    # Security monitoring
    enable_security_monitoring: bool = True
    enable_pii_detection: bool = True

    # Behavioral drift
    enable_drift_detection: bool = True
    drift_window_size: int = 100  # Number of recent events to analyze

    # Batching
    batch_size: int = 10
    flush_interval_seconds: float = 5.0

    # Local fallback
    local_log_path: Optional[str] = None  # If set, also logs to local JSON file

    # Sampling (1.0 = log everything)
    sampling_rate: float = 1.0

    # Custom tags applied to all events
    tags: dict = field(default_factory=dict)
