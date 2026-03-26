"""Core AgentWatch client for collecting and shipping telemetry."""

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import MODEL_PRICING, AgentWatchConfig
from .detectors import DriftDetector, HallucinationDetector, SecurityDetector
from .events import (
    AlertSeverity,
    CostBreakdown,
    Event,
    EventType,
    SecurityFlag,
    TokenUsage,
)

logger = logging.getLogger("agentwatch")


class AgentWatch:
    """
    Main telemetry client for AgentWatch.

    Usage:
        aw = AgentWatch(AgentWatchConfig(project_id="my-project"))
        aw.start_session()

        # Record events manually
        aw.record_llm_call(model="claude-sonnet-4-6", ...)

        # Or use the wrapper for automatic monitoring
        from agentwatch import MonitoredClient
        client = MonitoredClient(aw)
    """

    def __init__(self, config: Optional[AgentWatchConfig] = None):
        self.config = config or AgentWatchConfig()
        self._session_id = ""
        self._events: List[Event] = []
        self._buffer: List[Dict] = []
        self._lock = threading.Lock()
        self._flush_timer: Optional[threading.Timer] = None
        self._running = False

        # Detectors
        self._security = SecurityDetector(enable_pii=self.config.enable_pii_detection)
        self._hallucination = HallucinationDetector()
        self._drift = DriftDetector(window_size=self.config.drift_window_size)

        # Cumulative cost tracking
        self._hourly_cost = 0.0
        self._daily_cost = 0.0
        self._total_cost = 0.0
        self._hour_start = time.time()
        self._day_start = time.time()

        # Stats
        self._request_count = 0
        self._error_count = 0
        self._total_tokens = 0

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start a new monitoring session."""
        self._session_id = session_id or str(uuid.uuid4())
        self._running = True

        event = self._make_event(EventType.SESSION_START)
        self._emit(event)

        self._schedule_flush()
        logger.info(f"AgentWatch session started: {self._session_id}")
        return self._session_id

    def end_session(self):
        """End the current monitoring session."""
        event = self._make_event(
            EventType.SESSION_END,
            metadata={
                "total_cost": self._total_cost,
                "total_requests": self._request_count,
                "total_errors": self._error_count,
                "total_tokens": self._total_tokens,
            },
        )
        self._emit(event)
        self._flush()
        self._running = False
        if self._flush_timer:
            self._flush_timer.cancel()
        logger.info(f"AgentWatch session ended: {self._session_id}")

    def record_llm_call(
        self,
        provider: str,
        model: str,
        messages: List[Dict],
        response_text: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        stop_reason: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        error: Optional[str] = None,
        trace_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Event:
        """Record a complete LLM call with all analysis."""
        self._request_count += 1

        # Build token usage
        tokens = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        self._total_tokens += tokens.total_tokens

        # Calculate cost
        cost = self._calculate_cost(model, tokens)
        self._track_cost(cost.total_cost)

        # Security analysis
        security_flags: List[SecurityFlag] = []
        if self.config.enable_security_monitoring:
            # Scan the last user message
            user_messages = [m for m in messages if m.get("role") == "user"]
            if user_messages:
                last_input = str(user_messages[-1].get("content", ""))
                security_flags.extend(self._security.scan_input(last_input))
            security_flags.extend(self._security.scan_output(response_text))

        # Hallucination analysis
        hallucination_score = None
        confidence_score = None
        refusal_detected = False
        if self.config.enable_hallucination_detection:
            prompt_text = str(messages[-1].get("content", "")) if messages else ""
            hallucination_score, confidence_score, refusal_detected = self._hallucination.analyze(
                prompt_text, response_text
            )

        # Drift analysis
        drift_score = None
        if self.config.enable_drift_detection:
            num_tools = len(tool_calls) if tool_calls else 0
            drift_score = self._drift.record(
                response_length=len(response_text),
                refusal=refusal_detected,
                tool_calls=num_tools,
                latency_ms=latency_ms,
            )

        # Sanitize messages (remove full content, keep structure)
        sanitized_messages = self._sanitize_messages(messages)

        # Build event
        event = self._make_event(
            EventType.LLM_RESPONSE,
            provider=provider,
            model=model,
            messages=sanitized_messages,
            response_text=response_text[:500],  # Truncate for storage
            tokens=tokens,
            cost=cost,
            latency_ms=latency_ms,
            stop_reason=stop_reason,
            hallucination_score=hallucination_score,
            confidence_score=confidence_score,
            refusal_detected=refusal_detected,
            security_flags=security_flags,
            drift_score=drift_score,
            trace_id=trace_id or str(uuid.uuid4()),
            metadata=metadata or {},
        )

        # Handle errors
        if error:
            event.error_type = "llm_error"
            event.error_message = error
            self._error_count += 1

        self._emit(event)

        # Generate alerts if needed
        self._check_alerts(event)

        return event

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: Dict,
        tool_output: Optional[str] = None,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Event:
        """Record a tool/function call."""
        event = self._make_event(
            EventType.TOOL_CALL,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output[:500] if tool_output else None,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )
        if error:
            event.error_type = "tool_error"
            event.error_message = error
            self._error_count += 1
        self._emit(event)
        return event

    def record_custom(
        self,
        name: str,
        data: Dict[str, Any],
        tags: Optional[Dict[str, str]] = None,
    ) -> Event:
        """Record a custom event."""
        event = self._make_event(
            EventType.CUSTOM,
            metadata={"custom_name": name, **data},
            tags=tags or {},
        )
        self._emit(event)
        return event

    # --- Internal methods ---

    def _make_event(self, event_type: EventType, **kwargs) -> Event:
        """Create a new event with standard fields populated."""
        return Event(
            event_type=event_type,
            project_id=self.config.project_id,
            agent_name=self.config.agent_name,
            agent_version=self.config.agent_version,
            environment=self.config.environment,
            session_id=self._session_id,
            **kwargs,
        )

    def _calculate_cost(self, model: str, tokens: TokenUsage) -> CostBreakdown:
        """Calculate the cost of an LLM call."""
        pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
        input_cost = (tokens.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (tokens.output_tokens / 1_000_000) * pricing["output"]
        return CostBreakdown(
            input_cost=round(input_cost, 6),
            output_cost=round(output_cost, 6),
            total_cost=round(input_cost + output_cost, 6),
        )

    def _track_cost(self, cost: float):
        """Track cumulative costs and reset hourly/daily windows."""
        now = time.time()
        if now - self._hour_start > 3600:
            self._hourly_cost = 0.0
            self._hour_start = now
        if now - self._day_start > 86400:
            self._daily_cost = 0.0
            self._day_start = now

        self._hourly_cost += cost
        self._daily_cost += cost
        self._total_cost += cost

    def _check_alerts(self, event: Event):
        """Generate alerts based on thresholds."""
        # Cost alerts
        if self._hourly_cost > self.config.cost_alert_threshold_hourly:
            self._emit(
                self._make_event(
                    EventType.COST_ALERT,
                    metadata={
                        "alert": "hourly_cost_exceeded",
                        "threshold": self.config.cost_alert_threshold_hourly,
                        "current": self._hourly_cost,
                        "severity": AlertSeverity.WARNING.value,
                    },
                )
            )

        if self._daily_cost > self.config.cost_alert_threshold_daily:
            self._emit(
                self._make_event(
                    EventType.COST_ALERT,
                    metadata={
                        "alert": "daily_cost_exceeded",
                        "threshold": self.config.cost_alert_threshold_daily,
                        "current": self._daily_cost,
                        "severity": AlertSeverity.CRITICAL.value,
                    },
                )
            )

        # Security alerts
        if event.security_flags:
            critical_flags = [
                f for f in event.security_flags if f.severity == AlertSeverity.CRITICAL
            ]
            if critical_flags:
                self._emit(
                    self._make_event(
                        EventType.SECURITY_ALERT,
                        security_flags=critical_flags,
                        metadata={"severity": "critical"},
                    )
                )

        # Hallucination alerts
        if (
            event.hallucination_score is not None
            and event.hallucination_score > self.config.hallucination_confidence_threshold
        ):
            self._emit(
                self._make_event(
                    EventType.HALLUCINATION_DETECTED,
                    hallucination_score=event.hallucination_score,
                    metadata={"model": event.model, "trace_id": event.trace_id},
                )
            )

        # Drift alerts
        if event.drift_score is not None and event.drift_score > 0.5:
            self._emit(
                self._make_event(
                    EventType.DRIFT_DETECTED,
                    drift_score=event.drift_score,
                    metadata={"model": event.model},
                )
            )

    def _sanitize_messages(self, messages: List[Dict]) -> List[Dict]:
        """Sanitize messages for storage — keep structure, truncate content."""
        sanitized = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                truncated = content[:200] + "..." if len(content) > 200 else content
            else:
                truncated = "[complex content]"
            sanitized.append(
                {
                    "role": msg.get("role", "unknown"),
                    "content_length": len(str(content)),
                    "content_preview": truncated,
                }
            )
        return sanitized

    def _emit(self, event: Event):
        """Add event to buffer."""
        with self._lock:
            self._events.append(event)
            self._buffer.append(event.to_dict())

        # Write to local log if configured
        if self.config.local_log_path:
            self._write_local(event)

        if len(self._buffer) >= self.config.batch_size:
            self._flush()

    def _flush(self):
        """Flush buffered events to the backend."""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer.copy()
            self._buffer.clear()

        try:
            import urllib.request

            data = json.dumps({"events": batch}).encode()
            req = urllib.request.Request(
                f"{self.config.backend_url}/api/v1/events",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to flush events to backend: {e}")
            # Re-buffer on failure
            with self._lock:
                self._buffer.extend(batch)

    def _schedule_flush(self):
        """Schedule periodic flush."""
        if not self._running:
            return
        self._flush()
        self._flush_timer = threading.Timer(
            self.config.flush_interval_seconds, self._schedule_flush
        )
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _write_local(self, event: Event):
        """Write event to local JSON log file."""
        path = Path(self.config.local_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    @property
    def stats(self) -> Dict[str, Any]:
        """Get current session statistics."""
        return {
            "session_id": self._session_id,
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "total_tokens": self._total_tokens,
            "total_cost": round(self._total_cost, 4),
            "hourly_cost": round(self._hourly_cost, 4),
            "daily_cost": round(self._daily_cost, 4),
            "events_buffered": len(self._buffer),
            "events_total": len(self._events),
        }
