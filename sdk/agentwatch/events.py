"""Event types and data structures for AgentWatch telemetry."""

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    """Types of events tracked by AgentWatch."""

    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    COST_ALERT = "cost_alert"
    SECURITY_ALERT = "security_alert"
    HALLUCINATION_DETECTED = "hallucination_detected"
    DRIFT_DETECTED = "drift_detected"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    CUSTOM = "custom"


class AlertSeverity(str, Enum):
    """Severity levels for alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class TokenUsage:
    """Token usage for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class CostBreakdown:
    """Cost breakdown for a single LLM call."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"


@dataclass
class SecurityFlag:
    """A security concern detected in a request or response."""

    flag_type: str  # "prompt_injection", "pii_detected", "jailbreak_attempt", etc.
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str = ""
    evidence: str = ""


@dataclass
class Event:
    """A single telemetry event."""

    event_type: EventType
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Context
    project_id: str = ""
    agent_name: str = ""
    agent_version: str = ""
    environment: str = ""
    session_id: str = ""
    trace_id: str = ""
    parent_event_id: Optional[str] = None

    # LLM-specific
    provider: str = ""  # "anthropic", "openai", "google"
    model: str = ""
    messages: Optional[List[Dict]] = None  # Sanitized message history
    response_text: str = ""
    stop_reason: Optional[str] = None

    # Tool use
    tool_name: Optional[str] = None
    tool_input: Optional[Dict] = None
    tool_output: Optional[str] = None

    # Performance
    latency_ms: float = 0.0
    tokens: Optional[TokenUsage] = None
    cost: Optional[CostBreakdown] = None

    # Quality signals
    hallucination_score: Optional[float] = None  # 0-1, higher = more likely hallucination
    confidence_score: Optional[float] = None
    refusal_detected: bool = False

    # Security
    security_flags: List[SecurityFlag] = field(default_factory=list)

    # Drift
    drift_score: Optional[float] = None  # 0-1, higher = more drift from baseline

    # Error
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Custom
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to a dictionary for serialization."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        if self.tokens:
            d["tokens"] = asdict(self.tokens)
        if self.cost:
            d["cost"] = asdict(self.cost)
        if self.security_flags:
            d["security_flags"] = [
                {**asdict(f), "severity": f.severity.value} for f in self.security_flags
            ]
        # Remove None values for cleaner payloads
        return {k: v for k, v in d.items() if v is not None}
