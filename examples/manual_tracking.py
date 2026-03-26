#!/usr/bin/env python3
"""
AgentWatch Manual Tracking Example

Shows how to use AgentWatch without the wrapper — useful for
custom agents, multi-model setups, or non-Anthropic providers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from agentwatch import AgentWatch, AgentWatchConfig


def main():
    config = AgentWatchConfig(
        project_id="multi-model-project",
        agent_name="research-agent",
        environment="staging",
    )

    aw = AgentWatch(config)
    aw.start_session()

    # Simulate an LLM call and record it manually
    aw.record_llm_call(
        provider="anthropic",
        model="claude-sonnet-4-6",
        messages=[
            {"role": "user", "content": "Analyze the quarterly earnings report"},
        ],
        response_text="Based on the Q1 2026 earnings report, revenue increased 23% YoY...",
        input_tokens=2500,
        output_tokens=800,
        latency_ms=1340.5,
        stop_reason="end_turn",
    )

    # Record a tool call
    aw.record_tool_call(
        tool_name="database_query",
        tool_input={"query": "SELECT * FROM earnings WHERE quarter = 'Q1-2026'"},
        tool_output="[3 rows returned]",
        latency_ms=45.2,
    )

    # Record another LLM call (different model)
    aw.record_llm_call(
        provider="openai",
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "Summarize these findings in bullet points"},
        ],
        response_text=(
            "- Revenue up 23%\n- Operating margin improved to 18%\n- Customer growth at 15%"
        ),
        input_tokens=1200,
        output_tokens=350,
        latency_ms=890.3,
        stop_reason="stop",
    )

    # Record a custom event
    aw.record_custom(
        name="pipeline_complete",
        data={"steps_completed": 3, "total_duration_ms": 2275},
        tags={"pipeline": "earnings-analysis"},
    )

    print(f"Session stats: {aw.stats}")
    aw.end_session()


if __name__ == "__main__":
    main()
