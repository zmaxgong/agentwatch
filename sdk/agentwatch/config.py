"""Configuration for AgentWatch SDK."""

from dataclasses import dataclass, field
from typing import Optional

from .pricing import get_model_pricing


# Pricing per million tokens - fetched from provider APIs with fallback to hardcoded
def _get_pricing():
    """Lazy-load pricing to avoid circular imports and allow caching."""
    return get_model_pricing()

# This is evaluated once on first access - MODEL_PRICING is a function that returns current pricing
MODEL_PRICING = _get_pricing()


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
