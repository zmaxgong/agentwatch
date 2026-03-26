"""Detection modules for hallucinations, security issues, and behavioral drift."""

import re
from collections import deque
from typing import List, Optional, Tuple

from .events import AlertSeverity, SecurityFlag


class SecurityDetector:
    """Detects security anomalies in LLM inputs and outputs."""

    # Common prompt injection patterns
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?prior\s+(instructions|context)",
        r"you\s+are\s+now\s+(a|an)\s+",
        r"system\s*:\s*you\s+are",
        r"forget\s+(everything|all)\s+(you|that)",
        r"new\s+instructions?\s*:",
        r"override\s+(safety|security|rules)",
        r"jailbreak",
        r"DAN\s+mode",
        r"developer\s+mode\s+enabled",
        r"\[SYSTEM\]",
        r"<<SYS>>",
    ]

    # PII patterns
    PII_PATTERNS = {
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    }

    def __init__(self, enable_pii: bool = True):
        self.enable_pii = enable_pii
        self._compiled_injection = [
            re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS
        ]
        self._compiled_pii = {
            name: re.compile(pattern)
            for name, pattern in self.PII_PATTERNS.items()
        }

    def scan_input(self, text: str) -> List[SecurityFlag]:
        """Scan input text for security concerns."""
        flags = []

        # Check for prompt injection attempts
        for pattern in self._compiled_injection:
            match = pattern.search(text)
            if match:
                flags.append(SecurityFlag(
                    flag_type="prompt_injection",
                    severity=AlertSeverity.CRITICAL,
                    description="Potential prompt injection detected in input",
                    evidence=match.group()[:100],
                ))

        # Check for PII in inputs
        if self.enable_pii:
            flags.extend(self._scan_pii(text, "input"))

        return flags

    def scan_output(self, text: str) -> List[SecurityFlag]:
        """Scan output text for security concerns."""
        flags = []

        # Check for PII leakage in outputs
        if self.enable_pii:
            flags.extend(self._scan_pii(text, "output"))

        # Check for suspicious output patterns
        if any(phrase in text.lower() for phrase in [
            "here is the password",
            "the api key is",
            "secret key:",
            "access token:",
        ]):
            flags.append(SecurityFlag(
                flag_type="credential_leak",
                severity=AlertSeverity.CRITICAL,
                description="Potential credential leakage detected in output",
            ))

        return flags

    def _scan_pii(self, text: str, context: str) -> List[SecurityFlag]:
        flags = []
        for pii_type, pattern in self._compiled_pii.items():
            if pattern.search(text):
                flags.append(SecurityFlag(
                    flag_type="pii_detected",
                    severity=AlertSeverity.WARNING,
                    description=f"Potential {pii_type} detected in {context}",
                ))
        return flags


class HallucinationDetector:
    """Heuristic-based hallucination detection."""

    # Hedging phrases that may indicate uncertainty
    HEDGING_PHRASES = [
        "i think", "i believe", "it's possible", "might be",
        "could be", "not entirely sure", "approximately",
        "if i recall", "i'm not certain", "to my knowledge",
        "as far as i know", "it seems like", "probably",
    ]

    # Confidence indicators (inverse of hallucination)
    CONFIDENCE_PHRASES = [
        "according to", "based on", "the documentation states",
        "as specified in", "the error message shows",
        "the data indicates", "from the source",
    ]

    REFUSAL_PHRASES = [
        "i cannot", "i can't", "i'm unable to",
        "i don't have access", "i'm not able to",
        "that's outside my", "i should not",
    ]

    def analyze(self, prompt: str, response: str) -> Tuple[float, float, bool]:
        """
        Analyze a response for hallucination likelihood.

        Returns:
            (hallucination_score, confidence_score, refusal_detected)
        """
        response_lower = response.lower()

        # Count hedging vs confidence indicators
        hedge_count = sum(
            1 for phrase in self.HEDGING_PHRASES
            if phrase in response_lower
        )
        confidence_count = sum(
            1 for phrase in self.CONFIDENCE_PHRASES
            if phrase in response_lower
        )

        # Check for refusals
        refusal = any(phrase in response_lower for phrase in self.REFUSAL_PHRASES)

        # Simple heuristic scoring
        word_count = len(response.split())
        if word_count == 0:
            return 0.0, 1.0, refusal

        # Hallucination score: more hedging + longer responses without sources = higher risk
        hedge_ratio = hedge_count / max(word_count / 50, 1)
        source_penalty = 0.0 if confidence_count > 0 else 0.2
        length_factor = min(word_count / 500, 0.3)  # Longer = slightly more risk

        hallucination_score = min(
            hedge_ratio * 0.5 + source_penalty + length_factor, 1.0
        )

        # Confidence score (inverse relationship but not direct)
        confidence_score = max(
            1.0 - hallucination_score * 0.8 - (0.2 if refusal else 0), 0.0
        )

        return round(hallucination_score, 3), round(confidence_score, 3), refusal


class DriftDetector:
    """Detects behavioral drift by comparing recent responses to baseline patterns."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._response_lengths: deque = deque(maxlen=window_size)
        self._refusal_rates: deque = deque(maxlen=window_size)
        self._tool_usage: deque = deque(maxlen=window_size)
        self._latencies: deque = deque(maxlen=window_size)
        self._baseline_set = False
        self._baseline_avg_length = 0.0
        self._baseline_refusal_rate = 0.0
        self._baseline_avg_latency = 0.0

    def record(
        self,
        response_length: int,
        refusal: bool,
        tool_calls: int,
        latency_ms: float,
    ) -> Optional[float]:
        """
        Record a new data point and return drift score if enough data.

        Returns None until we have enough data for baseline.
        """
        self._response_lengths.append(response_length)
        self._refusal_rates.append(1.0 if refusal else 0.0)
        self._tool_usage.append(tool_calls)
        self._latencies.append(latency_ms)

        if len(self._response_lengths) < 20:
            return None

        # Set baseline from first 20 observations
        if not self._baseline_set and len(self._response_lengths) >= 20:
            baseline_slice = list(self._response_lengths)[:20]
            self._baseline_avg_length = sum(baseline_slice) / len(baseline_slice)
            self._baseline_refusal_rate = (
                sum(list(self._refusal_rates)[:20]) / 20
            )
            self._baseline_avg_latency = (
                sum(list(self._latencies)[:20]) / 20
            )
            self._baseline_set = True

        if not self._baseline_set:
            return None

        # Compare recent window (last 10) to baseline
        recent = list(self._response_lengths)[-10:]
        recent_avg_length = sum(recent) / len(recent)
        recent_refusal = sum(list(self._refusal_rates)[-10:]) / 10
        recent_latency = sum(list(self._latencies)[-10:]) / 10

        # Calculate drift components
        length_drift = abs(recent_avg_length - self._baseline_avg_length) / max(
            self._baseline_avg_length, 1
        )
        refusal_drift = abs(recent_refusal - self._baseline_refusal_rate)
        latency_drift = abs(recent_latency - self._baseline_avg_latency) / max(
            self._baseline_avg_latency, 1
        )

        # Weighted drift score
        drift_score = min(
            length_drift * 0.4 + refusal_drift * 0.4 + latency_drift * 0.2,
            1.0,
        )

        return round(drift_score, 3)
