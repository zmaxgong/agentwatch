"""
Claude Code Session Log Importer for AgentWatch.

Reads local Claude Code JSONL session logs and imports them into
the AgentWatch backend for cost tracking, hallucination detection,
and usage analytics — works with Claude Max subscriptions.

Usage:
    python -m agentwatch.claude_code_import
    python -m agentwatch.claude_code_import --project blackjack-bot --hours 48
    python -m agentwatch.claude_code_import --watch  # live tail mode
"""

import json
import glob
import time
import uuid
import logging
import hashlib
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("agentwatch.claude_code")

CLAUDE_DIR = Path.home() / ".claude" / "projects"

# Pricing per million tokens (for estimating what Max usage would cost at API rates)
MODEL_PRICING = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
}


@dataclass
class ClaudeCodeSession:
    """Parsed session info."""
    project_path: str
    project_name: str
    session_id: str
    log_path: Path


def discover_sessions(claude_dir: Path = CLAUDE_DIR) -> List[ClaudeCodeSession]:
    """Find all Claude Code session logs."""
    sessions = []
    if not claude_dir.exists():
        logger.warning(f"Claude Code directory not found: {claude_dir}")
        return sessions

    for project_dir in claude_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        # Convert path-encoded name back to readable form
        # e.g. "-Users-alice-projects-myapp" -> "myapp"
        parts = project_name.split("-")
        readable_name = parts[-1] if parts else project_name

        for jsonl_file in project_dir.glob("*.jsonl"):
            session_id = jsonl_file.stem
            sessions.append(ClaudeCodeSession(
                project_path=project_name,
                project_name=readable_name,
                session_id=session_id,
                log_path=jsonl_file,
            ))

    return sessions


def parse_session_log(
    session: ClaudeCodeSession,
    since_timestamp: Optional[float] = None,
    seen_ids: Optional[set] = None,
) -> List[Dict]:
    """Parse a Claude Code JSONL session log into AgentWatch events."""
    events = []
    if seen_ids is None:
        seen_ids = set()

    # Collect text content from assistant messages for hallucination analysis
    # We need to correlate streaming text blocks with their parent assistant message
    assistant_texts: Dict[str, str] = {}  # uuid -> accumulated text

    with open(session.log_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")

            # Accumulate text content from assistant responses
            if entry_type == "assistant":
                msg = entry.get("message", {})
                content_blocks = msg.get("content", [])
                text = ""
                tool_uses = []
                for block in content_blocks:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text += block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_uses.append({
                                "name": block.get("name", ""),
                                "id": block.get("id", ""),
                            })
                entry_uuid = entry.get("uuid", "")
                if entry_uuid:
                    assistant_texts[entry_uuid] = text

                # Only process assistant messages with usage data
                usage = msg.get("usage")
                if not usage:
                    continue

                timestamp_str = entry.get("timestamp", "")
                if timestamp_str:
                    try:
                        ts = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        ).timestamp()
                    except (ValueError, TypeError):
                        ts = time.time()
                else:
                    ts = time.time()

                # Skip entries before cutoff
                if since_timestamp and ts < since_timestamp:
                    continue

                # Deduplicate: hash the key fields
                dedup_key = hashlib.md5(
                    f"{session.session_id}:{entry_uuid}:{ts}".encode()
                ).hexdigest()
                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)

                # Skip streaming partial messages (stop_reason=null with tiny output)
                stop_reason = msg.get("stop_reason")
                output_tokens = usage.get("output_tokens", 0)
                if stop_reason is None and output_tokens < 20:
                    continue

                model = msg.get("model", "unknown")
                input_tokens = usage.get("input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                # Calculate estimated cost (what this would cost at API rates)
                # Cache pricing: writes = 1.25x input, reads = 0.1x input
                pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
                base_input_cost = (input_tokens / 1_000_000) * pricing["input"]
                cache_write_cost = (cache_creation / 1_000_000) * pricing["input"] * 1.25
                cache_read_cost = (cache_read / 1_000_000) * pricing["input"] * 0.1
                input_cost = base_input_cost + cache_write_cost + cache_read_cost
                output_cost = (output_tokens / 1_000_000) * pricing["output"]
                total_cost = input_cost + output_cost

                # Build the AgentWatch event
                event = {
                    "event_id": dedup_key,
                    "event_type": "llm_response",
                    "timestamp": ts,
                    "project_id": f"claude-code:{session.project_name}",
                    "agent_name": "claude-code",
                    "agent_version": entry.get("version", ""),
                    "environment": "claude-max",
                    "session_id": session.session_id,
                    "trace_id": entry_uuid,
                    "provider": "anthropic",
                    "model": model,
                    "stop_reason": stop_reason,
                    "response_text": text[:500] if text else "",
                    "tokens": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_tokens": cache_read,
                        "cache_write_tokens": cache_creation,
                    },
                    "cost": {
                        "input_cost": round(input_cost, 6),
                        "output_cost": round(output_cost, 6),
                        "total_cost": round(total_cost, 6),
                        "currency": "USD",
                    },
                    "latency_ms": 0,  # Not available from logs
                    "metadata": {
                        "source": "claude_code_import",
                        "estimated_cost": True,
                        "cache_creation_tokens": cache_creation,
                        "cache_read_tokens": cache_read,
                        "service_tier": usage.get("service_tier", ""),
                        "git_branch": entry.get("gitBranch", ""),
                        "cwd": entry.get("cwd", ""),
                    },
                    "tags": {
                        "source": "claude-code",
                        "project": session.project_name,
                    },
                }

                # Tool use events
                if tool_uses:
                    event["tool_name"] = tool_uses[0]["name"]
                    event["metadata"]["tool_count"] = len(tool_uses)
                    event["metadata"]["tools_used"] = [
                        t["name"] for t in tool_uses
                    ]

                events.append(event)

                # Also emit individual tool call events
                for tc in tool_uses:
                    tool_event = {
                        "event_id": str(uuid.uuid4()),
                        "event_type": "tool_call",
                        "timestamp": ts + 0.01,
                        "project_id": f"claude-code:{session.project_name}",
                        "agent_name": "claude-code",
                        "environment": "claude-max",
                        "session_id": session.session_id,
                        "trace_id": entry_uuid,
                        "tool_name": tc["name"],
                        "metadata": {"source": "claude_code_import"},
                    }
                    events.append(tool_event)

    return events


def send_to_backend(
    events: List[Dict],
    backend_url: str = "http://localhost:8100",
    batch_size: int = 50,
) -> int:
    """Send parsed events to the AgentWatch backend."""
    total_sent = 0

    for i in range(0, len(events), batch_size):
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
            total_sent += result.get("inserted", 0)
        except Exception as e:
            logger.error(f"Failed to send batch: {e}")

    return total_sent


def import_all(
    backend_url: str = "http://localhost:8100",
    hours: Optional[int] = None,
    project_filter: Optional[str] = None,
    claude_dir: Path = CLAUDE_DIR,
) -> Dict[str, Any]:
    """Import all Claude Code session logs into AgentWatch."""
    since = time.time() - (hours * 3600) if hours else None
    sessions = discover_sessions(claude_dir)

    if project_filter:
        sessions = [
            s for s in sessions
            if project_filter.lower() in s.project_name.lower()
            or project_filter.lower() in s.project_path.lower()
        ]

    seen_ids: set = set()
    total_events = 0
    total_sent = 0
    project_stats: Dict[str, Dict] = {}

    for session in sessions:
        events = parse_session_log(session, since_timestamp=since, seen_ids=seen_ids)
        if not events:
            continue

        sent = send_to_backend(events, backend_url)
        total_events += len(events)
        total_sent += sent

        # Track per-project stats
        proj = session.project_name
        if proj not in project_stats:
            project_stats[proj] = {"events": 0, "sessions": 0, "est_cost": 0.0}
        project_stats[proj]["events"] += len(events)
        project_stats[proj]["sessions"] += 1
        project_stats[proj]["est_cost"] += sum(
            e.get("cost", {}).get("total_cost", 0) for e in events
        )

    return {
        "sessions_found": len(sessions),
        "total_events": total_events,
        "total_sent": total_sent,
        "projects": project_stats,
    }


def watch_mode(
    backend_url: str = "http://localhost:8100",
    poll_interval: float = 5.0,
    claude_dir: Path = CLAUDE_DIR,
):
    """Live tail mode: continuously watch for new Claude Code activity."""
    print("  Watching Claude Code sessions for new activity...")
    print(f"  Polling every {poll_interval}s. Press Ctrl+C to stop.\n")

    seen_ids: set = set()
    # Initial scan to mark everything as seen
    for session in discover_sessions(claude_dir):
        parse_session_log(session, seen_ids=seen_ids)
    print(f"  Baseline: {len(seen_ids)} existing events marked as seen.")
    print("  Waiting for new activity...\n")

    try:
        while True:
            time.sleep(poll_interval)
            for session in discover_sessions(claude_dir):
                events = parse_session_log(session, seen_ids=seen_ids)
                if events:
                    sent = send_to_backend(events, backend_url)
                    est_cost = sum(
                        e.get("cost", {}).get("total_cost", 0) for e in events
                    )
                    print(
                        f"  [{datetime.now().strftime('%H:%M:%S')}] "
                        f"{session.project_name}: "
                        f"{len(events)} events, "
                        f"~${est_cost:.4f} est. cost "
                        f"({sent} sent to dashboard)"
                    )
    except KeyboardInterrupt:
        print("\n  Watch mode stopped.")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Import Claude Code session logs into AgentWatch"
    )
    parser.add_argument(
        "--backend", default="http://localhost:8100",
        help="AgentWatch backend URL",
    )
    parser.add_argument(
        "--hours", type=int, default=None,
        help="Only import events from the last N hours (default: all)",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Filter by project name (partial match)",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Live tail mode: watch for new Claude Code activity",
    )
    parser.add_argument(
        "--claude-dir", type=str, default=None,
        help="Override Claude Code projects directory",
    )
    args = parser.parse_args()

    claude_dir = Path(args.claude_dir) if args.claude_dir else CLAUDE_DIR

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   AgentWatch: Claude Code Importer   ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    if args.watch:
        watch_mode(
            backend_url=args.backend,
            claude_dir=claude_dir,
        )
    else:
        result = import_all(
            backend_url=args.backend,
            hours=args.hours,
            project_filter=args.project,
            claude_dir=claude_dir,
        )

        print(f"  Sessions found: {result['sessions_found']}")
        print(f"  Events parsed:  {result['total_events']}")
        print(f"  Events sent:    {result['total_sent']}")
        print()

        if result["projects"]:
            print("  Per-project breakdown:")
            print("  " + "-" * 55)
            for proj, stats in sorted(
                result["projects"].items(),
                key=lambda x: x[1]["est_cost"],
                reverse=True,
            ):
                print(
                    f"  {proj:<30} "
                    f"{stats['events']:>5} events  "
                    f"~${stats['est_cost']:.4f}"
                )
            print()

            total_est = sum(s["est_cost"] for s in result["projects"].values())
            print(f"  Total estimated cost (at API rates): ${total_est:.4f}")
        else:
            print("  No events found. Try --hours to adjust the time window.")

        print()
        print("  Open your dashboard to see the data!")
        print()


if __name__ == "__main__":
    main()
