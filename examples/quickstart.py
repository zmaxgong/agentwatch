#!/usr/bin/env python3
"""
AgentWatch Quickstart Example

Shows how to integrate AgentWatch with an existing Anthropic agent.
Requires: pip install anthropic

Usage:
    export ANTHROPIC_API_KEY="your-key"
    python quickstart.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from agentwatch import AgentWatch, MonitoredClient, AgentWatchConfig


def main():
    # 1. Configure AgentWatch
    config = AgentWatchConfig(
        project_id="my-first-project",
        agent_name="quickstart-agent",
        environment="development",
        cost_alert_threshold_hourly=2.00,
        cost_alert_threshold_daily=20.00,
        local_log_path="./agentwatch_events.jsonl",  # Also log locally
    )

    # 2. Initialize the monitoring client
    aw = AgentWatch(config)
    session_id = aw.start_session()
    print(f"AgentWatch session started: {session_id}")

    # 3. Create a monitored Anthropic client (drop-in replacement)
    client = MonitoredClient(aw)

    # 4. Use it exactly like the normal Anthropic client
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": "What are the top 3 benefits of monitoring AI agents in production?"}
            ],
        )
        print(f"\nResponse:\n{response.content[0].text}\n")
    except Exception as e:
        print(f"Error (expected if no API key): {e}")

    # 5. Check stats
    print(f"Session stats: {aw.stats}")

    # 6. Clean up
    aw.end_session()
    print("Session ended. Check the dashboard at http://localhost:8100")


if __name__ == "__main__":
    main()
