#!/usr/bin/env python3
"""
Generate realistic demo data for the AgentWatch dashboard.

Simulates 30 days of heavy Claude Code usage across multiple projects,
showing what a power user's Claude Max subscription looks like at API rates.

Usage:
    python demo_data.py [--events 800] [--backend http://localhost:8100]
"""

import argparse
import json
import math
import random
import time
import urllib.request
import uuid
from typing import Dict, List, Tuple

# --- Realistic Claude Code simulation ---

# Models with (provider, model, input_price_per_M, output_price_per_M)
MODELS = [
    ("anthropic", "claude-sonnet-4-6", 3.00, 15.00),
    ("anthropic", "claude-opus-4-6", 15.00, 75.00),
    ("anthropic", "claude-haiku-4-5", 0.80, 4.00),
]

# Weighted model selection: opus is the default for Claude Max subscribers
MODEL_WEIGHTS = [30, 55, 15]

# Realistic Claude Code project names
PROJECTS = [
    "saas-dashboard",
    "ai-chatbot",
    "landing-page",
    "mobile-app-api",
    "internal-tools",
    "docs-site",
    "billing-service",
]

# Project weights (some projects get way more usage)
PROJECT_WEIGHTS = [25, 20, 15, 15, 10, 8, 7]

# Actual Claude Code tool names
TOOL_NAMES = [
    "Read", "Edit", "Write", "Bash", "Grep", "Glob",
    "Agent", "TodoWrite", "WebSearch", "WebFetch",
    "NotebookEdit",
]

# Tool usage weights (Read dominates, then Edit, Bash)
TOOL_WEIGHTS = [30, 22, 8, 18, 10, 8, 2, 1, 0.5, 0.3, 0.2]

# Work hour patterns (hour -> relative activity level)
# Simulates a developer who works 9am-midnight with peaks
HOUR_ACTIVITY = {
    0: 0.3, 1: 0.1, 2: 0.05, 3: 0.02, 4: 0.01, 5: 0.01,
    6: 0.05, 7: 0.1, 8: 0.3, 9: 0.7, 10: 0.9, 11: 1.0,
    12: 0.6, 13: 0.8, 14: 1.0, 15: 0.9, 16: 0.8, 17: 0.7,
    18: 0.5, 19: 0.6, 20: 0.8, 21: 0.9, 22: 0.7, 23: 0.5,
}

# Day of week activity (0=Mon, 6=Sun)
DOW_ACTIVITY = {0: 1.0, 1: 1.0, 2: 0.9, 3: 1.0, 4: 0.8, 5: 0.4, 6: 0.3}


def pick_model() -> Tuple[str, str, float, float]:
    return random.choices(MODELS, weights=MODEL_WEIGHTS, k=1)[0]


def pick_project() -> str:
    return "claude-code:" + random.choices(PROJECTS, weights=PROJECT_WEIGHTS, k=1)[0]


def pick_tool() -> str:
    return random.choices(TOOL_NAMES, weights=TOOL_WEIGHTS, k=1)[0]


def generate_timestamp(start: float, end: float) -> float:
    """Generate a timestamp weighted by work hour and day-of-week patterns."""
    for _ in range(50):
        ts = random.uniform(start, end)
        dt_tuple = time.localtime(ts)
        hour = dt_tuple.tm_hour
        dow = dt_tuple.tm_wday  # 0=Mon
        activity = HOUR_ACTIVITY.get(hour, 0.1) * DOW_ACTIVITY.get(dow, 0.5)
        if random.random() < activity:
            return ts
    return random.uniform(start, end)


def generate_events(
    num_events: int = 800,
    hours_span: int = 720,  # 30 days
) -> List[Dict]:
    """Generate realistic Claude Code telemetry events."""
    events = []
    now = time.time()
    start_time = now - (hours_span * 3600)

    # Create multiple sessions (realistic: 2-5 sessions per day)
    num_sessions = max(num_events // 15, 20)
    sessions = []
    for _ in range(num_sessions):
        sid = str(uuid.uuid4())
        project = pick_project()
        session_start = generate_timestamp(start_time, now - 600)
        session_duration = random.uniform(600, 7200)  # 10min to 2h
        sessions.append({
            "id": sid,
            "project": project,
            "start": session_start,
            "end": min(session_start + session_duration, now),
        })

    # Track running cost to hit target
    running_cost = 0.0
    target_monthly = 5200.0  # Target ~$5200 at API rates over 30 days
    _ = target_monthly / num_events  # per-event target (unused)

    for i in range(num_events):
        session = random.choice(sessions)
        ts = random.uniform(session["start"], session["end"])
        provider, model, input_price, output_price = pick_model()

        # Realistic Claude Code token counts for a power user
        # Real sessions have huge context windows and long code outputs
        # Opus at $75/M output is the cost driver — big file writes are 10-50K tokens
        if model == "claude-opus-4-6":
            input_tokens = random.randint(5000, 30000)
            # Mix of short responses and long file writes
            if random.random() < 0.35:  # 35% are big file writes / refactors
                output_tokens = random.randint(18000, 60000)
            else:
                output_tokens = random.randint(3000, 18000)
            cache_read = random.randint(100000, 400000)
            cache_write = random.randint(2000, 15000) if random.random() < 0.35 else 0
        elif model == "claude-sonnet-4-6":
            input_tokens = random.randint(3000, 20000)
            if random.random() < 0.2:
                output_tokens = random.randint(10000, 30000)
            else:
                output_tokens = random.randint(500, 10000)
            cache_read = random.randint(60000, 250000)
            cache_write = random.randint(1000, 8000) if random.random() < 0.3 else 0
        else:  # haiku
            input_tokens = random.randint(1000, 10000)
            output_tokens = random.randint(200, 5000)
            cache_read = random.randint(20000, 120000)
            cache_write = random.randint(0, 4000) if random.random() < 0.2 else 0

        # Cost calculation
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        total_cost = input_cost + output_cost
        running_cost += total_cost

        # Latency
        base_latency = {
            "claude-opus-4-6": 3000,
            "claude-sonnet-4-6": 1200,
            "claude-haiku-4-5": 400,
        }
        latency = base_latency.get(model, 1000) + (output_tokens * 0.3) + random.uniform(-200, 500)
        latency = max(200, latency)

        # Quality scores (Claude Code is generally reliable)
        hallucination_score = (
            round(random.uniform(0.0, 0.15), 3)
            if random.random() > 0.05
            else round(random.uniform(0.4, 0.8), 3)
        )
        drift_score = (
            round(random.uniform(0.0, 0.2), 3)
            if random.random() > 0.03
            else round(random.uniform(0.3, 0.6), 3)
        )

        # Stop reasons
        stop_reason = random.choices(
            ["end_turn", "tool_use", "max_tokens"],
            weights=[50, 45, 5],
            k=1,
        )[0]

        # Errors (2% rate)
        error_type = None
        error_message = None
        if random.random() < 0.02:
            error_type = random.choice(["rate_limit", "timeout", "context_overflow"])
            error_message = {
                "rate_limit": "Rate limit exceeded. Retry after 30s.",
                "timeout": "Request timed out after 30000ms",
                "context_overflow": "Input exceeds maximum context length",
            }[error_type]

        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "llm_response",
            "timestamp": ts,
            "project_id": session["project"],
            "agent_name": "claude-code",
            "agent_version": "1.0.0",
            "environment": "local",
            "session_id": session["id"],
            "trace_id": str(uuid.uuid4()),
            "provider": provider,
            "model": model,
            "stop_reason": stop_reason if not error_type else None,
            "tokens": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
            },
            "cost": {
                "input_cost": round(input_cost, 6),
                "output_cost": round(output_cost, 6),
                "total_cost": round(total_cost, 6),
                "currency": "USD",
            },
            "latency_ms": round(latency, 1),
            "hallucination_score": hallucination_score,
            "drift_score": drift_score,
            "refusal_detected": False,
            "security_flags": [],
            "metadata": {
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": cache_write,
                "demo": True,
            },
            "tags": {"env": "local"},
        }

        if error_type:
            event["error_type"] = error_type
            event["error_message"] = error_message

        events.append(event)

        # Add tool call events (Claude Code makes 1-3 tool calls per LLM response)
        num_tools = random.choices([0, 1, 2, 3], weights=[10, 40, 35, 15], k=1)[0]
        for j in range(num_tools):
            tool = pick_tool()
            tool_event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "tool_call",
                "timestamp": ts + (j + 1) * random.uniform(0.5, 3.0),
                "project_id": session["project"],
                "agent_name": "claude-code",
                "agent_version": "1.0.0",
                "environment": "local",
                "session_id": session["id"],
                "trace_id": event["trace_id"],
                "tool_name": tool,
                "latency_ms": round(random.uniform(10, 3000), 1),
                "metadata": {"demo": True},
            }
            events.append(tool_event)

    # Sort by timestamp
    events.sort(key=lambda e: e["timestamp"])

    # Calculate actual totals for display
    total_cost = sum(
        e.get("cost", {}).get("total_cost", 0)
        for e in events
        if e["event_type"] == "llm_response"
    )

    return events, total_cost


def send_events(events: List[Dict], backend_url: str, batch_size: int = 50):
    """Send events to the backend in batches."""
    total = len(events)
    sent = 0

    for i in range(0, total, batch_size):
        batch = events[i:i + batch_size]
        data = json.dumps({"events": batch}).encode()

        try:
            req = urllib.request.Request(
                f"{backend_url}/api/v1/events",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            sent += result.get("inserted", 0)
            batch_num = i // batch_size + 1
            total_batches = math.ceil(total / batch_size)
            print(f"  [{batch_num}/{total_batches}] Sent {result.get('inserted', 0)} events")
        except Exception as e:
            print(f"  Error sending batch: {e}")

    return sent


def main():
    parser = argparse.ArgumentParser(description="Generate demo data for AgentWatch")
    parser.add_argument("--events", type=int, default=5000, help="Number of LLM events to generate")
    parser.add_argument(
        "--hours", type=int, default=720,
        help="Time span in hours (default: 720 = 30 days)",
    )
    parser.add_argument("--backend", type=str, default="http://localhost:8100", help="Backend URL")
    args = parser.parse_args()

    print("\n  AgentWatch Demo Data Generator")
    print("  ================================")
    print(f"  Simulating {args.events} Claude Code interactions over {args.hours // 24}d...")
    print()

    events, total_cost = generate_events(num_events=args.events, hours_span=args.hours)
    llm_events = [e for e in events if e["event_type"] == "llm_response"]
    tool_events = [e for e in events if e["event_type"] == "tool_call"]

    print("  Generated:")
    print(f"    {len(llm_events)} LLM responses")
    print(f"    {len(tool_events)} tool calls")
    print(f"    {len(events)} total events")
    print(f"    ${total_cost:,.2f} estimated API cost")
    print(f"    ~${total_cost / max(args.hours / 24, 1) * 30:,.0f}/month projected")
    print()

    # Project breakdown
    project_costs = {}
    for e in llm_events:
        p = e["project_id"].replace("claude-code:", "")
        project_costs[p] = project_costs.get(p, 0) + e["cost"]["total_cost"]
    print("  By project:")
    for p, c in sorted(project_costs.items(), key=lambda x: -x[1]):
        print(f"    {p:24s} ${c:,.2f}")
    print()

    print(f"  Sending to {args.backend}...")
    sent = send_events(events, args.backend)
    print(f"\n  Done! {sent} events ingested.")
    print("  Open dashboard/index.html to see your data.\n")


if __name__ == "__main__":
    main()
