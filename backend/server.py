"""
AgentWatch Backend Server

Lightweight FastAPI server that:
- Ingests telemetry events from the SDK
- Stores events in SQLite (zero-config)
- Serves aggregated analytics to the dashboard
- Provides real-time updates via SSE
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentwatch-server")

DB_PATH = Path(os.environ.get("AGENTWATCH_DB", "/tmp/agentwatch.db"))

# --- Database ---


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            timestamp REAL NOT NULL,
            project_id TEXT DEFAULT '',
            agent_name TEXT DEFAULT '',
            agent_version TEXT DEFAULT '',
            environment TEXT DEFAULT '',
            session_id TEXT DEFAULT '',
            trace_id TEXT DEFAULT '',
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            latency_ms REAL DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            input_cost REAL DEFAULT 0,
            output_cost REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            hallucination_score REAL,
            confidence_score REAL,
            refusal_detected INTEGER DEFAULT 0,
            drift_score REAL,
            error_type TEXT,
            error_message TEXT,
            tool_name TEXT,
            stop_reason TEXT,
            response_preview TEXT DEFAULT '',
            security_flags_json TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            tags_json TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_model ON events(model);
    """)
    conn.close()


# --- Models ---


class EventBatch(BaseModel):
    events: List[Dict[str, Any]]


# --- App ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"AgentWatch server started. DB: {DB_PATH}")
    yield
    logger.info("AgentWatch server shutting down.")


app = FastAPI(
    title="AgentWatch API",
    version="0.1.0",
    description="Observability backend for AI agents",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- SSE for real-time updates ---

_event_subscribers: List[asyncio.Queue] = []


async def notify_subscribers(event_data: Dict):
    for queue in _event_subscribers:
        await queue.put(event_data)


# --- Routes ---


@app.post("/api/v1/events")
async def ingest_events(batch: EventBatch):
    """Ingest a batch of telemetry events."""
    conn = get_db()
    inserted = 0
    for event in batch.events:
        try:
            tokens = event.get("tokens", {})
            cost = event.get("cost", {})
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    id, event_type, timestamp, project_id, agent_name,
                    agent_version, environment, session_id, trace_id,
                    provider, model, latency_ms,
                    input_tokens, output_tokens, total_tokens,
                    input_cost, output_cost, total_cost,
                    hallucination_score, confidence_score, refusal_detected,
                    drift_score, error_type, error_message,
                    tool_name, stop_reason, response_preview,
                    security_flags_json, metadata_json, tags_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """,
                (
                    event.get("event_id", ""),
                    event.get("event_type", ""),
                    event.get("timestamp", time.time()),
                    event.get("project_id", ""),
                    event.get("agent_name", ""),
                    event.get("agent_version", ""),
                    event.get("environment", ""),
                    event.get("session_id", ""),
                    event.get("trace_id", ""),
                    event.get("provider", ""),
                    event.get("model", ""),
                    event.get("latency_ms", 0),
                    tokens.get("input_tokens", 0),
                    tokens.get("output_tokens", 0),
                    tokens.get("input_tokens", 0) + tokens.get("output_tokens", 0),
                    cost.get("input_cost", 0),
                    cost.get("output_cost", 0),
                    cost.get("total_cost", 0),
                    event.get("hallucination_score"),
                    event.get("confidence_score"),
                    1 if event.get("refusal_detected") else 0,
                    event.get("drift_score"),
                    event.get("error_type"),
                    event.get("error_message"),
                    event.get("tool_name"),
                    event.get("stop_reason"),
                    event.get("response_text", "")[:500],
                    json.dumps(event.get("security_flags", [])),
                    json.dumps(event.get("metadata", {})),
                    json.dumps(event.get("tags", {})),
                ),
            )
            inserted += 1

            # Notify SSE subscribers
            await notify_subscribers(
                {
                    "type": event.get("event_type"),
                    "timestamp": event.get("timestamp"),
                    "model": event.get("model"),
                    "cost": cost.get("total_cost", 0),
                }
            )

        except Exception as e:
            logger.error(f"Failed to insert event: {e}")

    conn.commit()
    conn.close()
    return {"inserted": inserted, "total": len(batch.events)}


@app.get("/api/v1/dashboard/overview")
async def dashboard_overview(
    project_id: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
):
    """Get high-level dashboard metrics."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)
    where = "WHERE timestamp > ?"
    params: list = [cutoff]
    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)

    # Core metrics
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) as total_requests,
            COALESCE(SUM(total_cost), 0) as total_cost,
            COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
            COALESCE(AVG(latency_ms), 0) as avg_latency,
            COALESCE(AVG(hallucination_score), 0) as avg_hallucination,
            COALESCE(AVG(drift_score), 0) as avg_drift,
            COUNT(CASE WHEN error_type IS NOT NULL THEN 1 END) as error_count,
            COUNT(CASE WHEN refusal_detected = 1 THEN 1 END) as refusal_count
        FROM events
        {where} AND event_type = 'llm_response'
    """,
        params,
    ).fetchone()

    # Security alerts count
    security_row = conn.execute(
        f"""
        SELECT COUNT(*) as count FROM events
        {where} AND event_type = 'security_alert'
    """,
        params,
    ).fetchone()

    # Cost alerts count
    cost_alert_row = conn.execute(
        f"""
        SELECT COUNT(*) as count FROM events
        {where} AND event_type = 'cost_alert'
    """,
        params,
    ).fetchone()

    # Model breakdown
    models = conn.execute(
        f"""
        SELECT model,
            COUNT(*) as requests,
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens,
            COALESCE(AVG(latency_ms), 0) as avg_latency
        FROM events
        {where} AND event_type = 'llm_response' AND model != ''
        GROUP BY model
        ORDER BY requests DESC
    """,
        params,
    ).fetchall()

    # Active sessions
    sessions = conn.execute(
        f"""
        SELECT session_id,
            COUNT(*) as events,
            MIN(timestamp) as started,
            MAX(timestamp) as last_event,
            COALESCE(SUM(total_cost), 0) as cost
        FROM events
        {where} AND session_id != ''
        GROUP BY session_id
        ORDER BY last_event DESC
        LIMIT 10
    """,
        params,
    ).fetchall()

    conn.close()

    return {
        "period_hours": hours,
        "metrics": {
            "total_requests": row["total_requests"],
            "total_cost": round(row["total_cost"], 4),
            "total_tokens": row["total_tokens"],
            "avg_latency_ms": round(row["avg_latency"], 1),
            "avg_hallucination_score": round(row["avg_hallucination"], 3),
            "avg_drift_score": round(row["avg_drift"], 3),
            "error_count": row["error_count"],
            "error_rate": round(row["error_count"] / max(row["total_requests"], 1), 3),
            "refusal_count": row["refusal_count"],
            "security_alerts": security_row["count"],
            "cost_alerts": cost_alert_row["count"],
        },
        "models": [dict(m) for m in models],
        "recent_sessions": [dict(s) for s in sessions],
    }


@app.get("/api/v1/dashboard/timeseries")
async def dashboard_timeseries(
    project_id: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    bucket_minutes: int = Query(default=60, ge=1, le=1440),
):
    """Get time-bucketed metrics for charts."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)
    bucket_seconds = bucket_minutes * 60

    where = "WHERE timestamp > ?"
    params: list = [cutoff]
    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)

    rows = conn.execute(
        f"""
        SELECT
            CAST((timestamp / {bucket_seconds}) AS INTEGER) * {bucket_seconds} as bucket,
            COUNT(*) as requests,
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens,
            COALESCE(AVG(latency_ms), 0) as avg_latency,
            COALESCE(AVG(hallucination_score), 0) as avg_hallucination,
            COALESCE(AVG(drift_score), 0) as avg_drift,
            COUNT(CASE WHEN error_type IS NOT NULL THEN 1 END) as errors
        FROM events
        {where} AND event_type = 'llm_response'
        GROUP BY bucket
        ORDER BY bucket ASC
    """,
        params,
    ).fetchall()

    conn.close()

    return {
        "bucket_minutes": bucket_minutes,
        "data": [
            {
                "timestamp": r["bucket"],
                "time": datetime.fromtimestamp(r["bucket"]).isoformat(),
                "requests": r["requests"],
                "cost": round(r["cost"], 4),
                "tokens": r["tokens"],
                "avg_latency_ms": round(r["avg_latency"], 1),
                "avg_hallucination": round(r["avg_hallucination"], 3),
                "avg_drift": round(r["avg_drift"], 3),
                "errors": r["errors"],
            }
            for r in rows
        ],
    }


@app.get("/api/v1/dashboard/alerts")
async def dashboard_alerts(
    project_id: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get recent alerts (security, cost, hallucination, drift)."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)
    where = (
        "WHERE timestamp > ? AND event_type IN "
        "('security_alert', 'cost_alert', "
        "'hallucination_detected', 'drift_detected')"
    )
    params: list = [cutoff]
    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)

    rows = conn.execute(
        f"""
        SELECT * FROM events
        {where}
        ORDER BY timestamp DESC
        LIMIT ?
    """,
        params + [limit],
    ).fetchall()

    conn.close()
    return {"alerts": [dict(r) for r in rows]}


@app.get("/api/v1/dashboard/events")
async def dashboard_events(
    project_id: Optional[str] = None,
    event_type: Optional[str] = None,
    session_id: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Get raw events with filtering."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)
    where = "WHERE timestamp > ?"
    params: list = [cutoff]

    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)
    if event_type:
        where += " AND event_type = ?"
        params.append(event_type)
    if session_id:
        where += " AND session_id = ?"
        params.append(session_id)

    total = conn.execute(f"SELECT COUNT(*) as c FROM events {where}", params).fetchone()["c"]

    rows = conn.execute(
        f"""
        SELECT * FROM events
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """,
        params + [limit, offset],
    ).fetchall()

    conn.close()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [dict(r) for r in rows],
    }


@app.get("/api/v1/dashboard/tools")
async def dashboard_tools(
    project_id: Optional[str] = None,
    hours: int = Query(default=720, ge=1, le=8760),
):
    """Get tool usage breakdown for heatmap."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)
    where = (
        "WHERE timestamp > ? AND event_type = 'tool_call' "
        "AND tool_name IS NOT NULL AND tool_name != ''"
    )
    params: list = [cutoff]
    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)

    # Tool counts
    tools = conn.execute(
        f"""
        SELECT tool_name,
            COUNT(*) as count,
            COALESCE(AVG(latency_ms), 0) as avg_latency
        FROM events
        {where}
        GROUP BY tool_name
        ORDER BY count DESC
    """,
        params,
    ).fetchall()

    # Tool usage by hour-of-day for heatmap
    heatmap = conn.execute(
        f"""
        SELECT tool_name,
            CAST(((timestamp % 86400) / 3600) AS INTEGER) as hour,
            COUNT(*) as count
        FROM events
        {where}
        GROUP BY tool_name, hour
        ORDER BY tool_name, hour
    """,
        params,
    ).fetchall()

    # Tool usage by project
    by_project = conn.execute(
        f"""
        SELECT tool_name, project_id, COUNT(*) as count
        FROM events
        {where}
        GROUP BY tool_name, project_id
        ORDER BY count DESC
    """,
        params,
    ).fetchall()

    conn.close()
    return {
        "tools": [dict(t) for t in tools],
        "heatmap": [dict(h) for h in heatmap],
        "by_project": [dict(b) for b in by_project],
    }


@app.get("/api/v1/dashboard/projection")
async def dashboard_projection(
    hours: int = Query(default=720, ge=1, le=8760),
    subscription_cost: float = Query(default=200.0),
):
    """Cost projection and Max savings calculation."""
    conn = get_db()
    now = time.time()
    cutoff = now - (hours * 3600)

    # Total cost and time span
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(total_cost), 0) as total_cost,
            COUNT(*) as total_requests,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            MIN(timestamp) as first_event,
            MAX(timestamp) as last_event
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
    """,
        [cutoff],
    ).fetchone()

    # Dynamic granularity: hourly for <= 48h, daily otherwise
    if hours <= 48:
        # Hourly buckets
        bucket_seconds = 3600
        trend = conn.execute(
            """
            SELECT
                CAST((timestamp / ?) AS INTEGER) * ? as bucket,
                COALESCE(SUM(total_cost), 0) as cost,
                COUNT(*) as requests,
                COALESCE(SUM(total_tokens), 0) as tokens
            FROM events
            WHERE timestamp > ? AND event_type = 'llm_response'
            GROUP BY bucket
            ORDER BY bucket ASC
        """,
            [bucket_seconds, bucket_seconds, cutoff],
        ).fetchall()
        trend_data = [
            {
                "label": datetime.fromtimestamp(r["bucket"]).strftime("%H:%M"),
                "timestamp": r["bucket"],
                "cost": round(r["cost"], 4),
                "requests": r["requests"],
                "tokens": r["tokens"],
            }
            for r in trend
        ]
        granularity = "hourly"
    else:
        # Daily buckets
        trend = conn.execute(
            """
            SELECT
                DATE(timestamp, 'unixepoch', 'localtime') as day,
                COALESCE(SUM(total_cost), 0) as cost,
                COUNT(*) as requests,
                COALESCE(SUM(total_tokens), 0) as tokens
            FROM events
            WHERE timestamp > ? AND event_type = 'llm_response'
            GROUP BY day
            ORDER BY day ASC
        """,
            [cutoff],
        ).fetchall()
        trend_data = [
            {
                "label": r["day"][5:],  # MM-DD
                "cost": round(r["cost"], 4),
                "requests": r["requests"],
                "tokens": r["tokens"],
            }
            for r in trend
        ]
        granularity = "daily"

    # Per-model cost breakdown
    model_costs = conn.execute(
        """
        SELECT model,
            COALESCE(SUM(total_cost), 0) as cost,
            COUNT(*) as requests
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response' AND model != ''
        GROUP BY model
        ORDER BY cost DESC
    """,
        [cutoff],
    ).fetchall()

    conn.close()

    total_cost = row["total_cost"]
    first_event = row["first_event"] or now
    last_event = row["last_event"] or now
    span_days = max((last_event - first_event) / 86400, 1)
    daily_avg = total_cost / span_days
    monthly_projected = daily_avg * 30
    savings = monthly_projected - subscription_cost
    savings_pct = (savings / max(monthly_projected, 0.01)) * 100

    return {
        "total_cost": round(total_cost, 4),
        "span_days": round(span_days, 1),
        "daily_avg": round(daily_avg, 4),
        "monthly_projected": round(monthly_projected, 2),
        "subscription_cost": subscription_cost,
        "savings": round(savings, 2),
        "savings_pct": round(savings_pct, 1),
        "trend": trend_data,
        "granularity": granularity,
        "model_costs": [dict(m) for m in model_costs],
    }


@app.get("/api/v1/dashboard/billing-window")
async def dashboard_billing_window():
    """Get 5-hour rolling window usage for Claude Max billing."""
    conn = get_db()
    now = time.time()
    cutoff = now - (5 * 3600)

    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens,
            COUNT(*) as requests,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
    """,
        [cutoff],
    ).fetchone()

    # Hourly breakdown within the 5h window
    hourly = conn.execute(
        """
        SELECT
            CAST((timestamp / 3600) AS INTEGER) * 3600 as bucket,
            COALESCE(SUM(total_cost), 0) as cost,
            COUNT(*) as requests
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
        GROUP BY bucket
        ORDER BY bucket ASC
    """,
        [cutoff],
    ).fetchall()

    conn.close()
    return {
        "cost": round(row["cost"], 4),
        "tokens": row["tokens"],
        "requests": row["requests"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "hourly": [
            {
                "label": datetime.fromtimestamp(h["bucket"]).strftime("%H:%M"),
                "cost": round(h["cost"], 4),
                "requests": h["requests"],
            }
            for h in hourly
        ],
    }


@app.get("/api/v1/dashboard/cumulative-cost")
async def dashboard_cumulative_cost(
    hours: int = Query(default=720, ge=1, le=8760),
):
    """Get cumulative cost over time for area chart."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)

    # Use appropriate bucket size based on time window
    if hours <= 6:
        bucket_seconds = 300  # 5 min
    elif hours <= 48:
        bucket_seconds = 3600  # 1 hour
    else:
        bucket_seconds = 86400  # 1 day

    rows = conn.execute(
        """
        SELECT
            CAST((timestamp / ?) AS INTEGER) * ? as bucket,
            COALESCE(SUM(total_cost), 0) as cost
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
        GROUP BY bucket
        ORDER BY bucket ASC
    """,
        [bucket_seconds, bucket_seconds, cutoff],
    ).fetchall()

    conn.close()

    # Build cumulative series
    cumulative = []
    running = 0.0
    fmt = "%H:%M" if hours <= 48 else "%m/%d"
    for r in rows:
        running += r["cost"]
        cumulative.append(
            {
                "label": datetime.fromtimestamp(r["bucket"]).strftime(fmt),
                "timestamp": r["bucket"],
                "cost": round(r["cost"], 4),
                "cumulative": round(running, 4),
            }
        )

    return {"data": cumulative, "total": round(running, 4)}


@app.get("/api/v1/dashboard/sessions")
async def dashboard_sessions(
    hours: int = Query(default=720, ge=1, le=8760),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get session details for session replay."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)

    sessions = conn.execute(
        """
        SELECT
            session_id,
            project_id,
            MIN(timestamp) as started,
            MAX(timestamp) as ended,
            COUNT(*) as total_events,
            COUNT(CASE WHEN event_type = 'llm_response' THEN 1 END) as llm_calls,
            COUNT(CASE WHEN event_type = 'tool_call' THEN 1 END) as tool_calls,
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens,
            GROUP_CONCAT(DISTINCT model) as models_used
        FROM events
        WHERE timestamp > ? AND session_id != ''
        GROUP BY session_id
        ORDER BY ended DESC
        LIMIT ?
    """,
        [cutoff, limit],
    ).fetchall()

    conn.close()
    return {"sessions": [dict(s) for s in sessions]}


@app.get("/api/v1/dashboard/session/{session_id}")
async def dashboard_session_detail(session_id: str):
    """Get all events for a single session (for replay view)."""
    conn = get_db()

    events = conn.execute(
        """
        SELECT * FROM events
        WHERE session_id = ?
        ORDER BY timestamp ASC
    """,
        [session_id],
    ).fetchall()

    conn.close()
    return {"session_id": session_id, "events": [dict(e) for e in events]}


@app.get("/api/v1/dashboard/comparison")
async def dashboard_comparison(
    hours: int = Query(default=168, ge=1, le=8760),
):
    """Compare current period vs previous period."""
    conn = get_db()
    now = time.time()
    current_start = now - (hours * 3600)
    prev_start = current_start - (hours * 3600)

    def get_period_stats(start, end):
        row = conn.execute(
            """
            SELECT
                COUNT(*) as requests,
                COALESCE(SUM(total_cost), 0) as cost,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(AVG(latency_ms), 0) as avg_latency,
                COALESCE(AVG(hallucination_score), 0) as avg_hallucination,
                COALESCE(AVG(drift_score), 0) as avg_drift,
                COUNT(CASE WHEN error_type IS NOT NULL THEN 1 END) as errors,
                COUNT(DISTINCT session_id) as sessions
            FROM events
            WHERE timestamp > ? AND timestamp <= ? AND event_type = 'llm_response'
        """,
            [start, end],
        ).fetchone()
        return dict(row) if row else {}

    current = get_period_stats(current_start, now)
    previous = get_period_stats(prev_start, current_start)

    # Calculate deltas
    def delta(curr, prev):
        if prev == 0:
            return 100.0 if curr > 0 else 0.0
        return round(((curr - prev) / prev) * 100, 1)

    conn.close()
    return {
        "period_hours": hours,
        "current": {k: round(v, 4) if isinstance(v, float) else v for k, v in current.items()},
        "previous": {k: round(v, 4) if isinstance(v, float) else v for k, v in previous.items()},
        "deltas": {
            "requests": delta(current.get("requests", 0), previous.get("requests", 0)),
            "cost": delta(current.get("cost", 0), previous.get("cost", 0)),
            "tokens": delta(current.get("tokens", 0), previous.get("tokens", 0)),
            "avg_latency": delta(current.get("avg_latency", 0), previous.get("avg_latency", 0)),
            "avg_hallucination": delta(
                current.get("avg_hallucination", 0),
                previous.get("avg_hallucination", 0),
            ),
            "errors": delta(current.get("errors", 0), previous.get("errors", 0)),
        },
    }


@app.get("/api/v1/stream")
async def event_stream():
    """SSE endpoint for real-time dashboard updates."""
    queue: asyncio.Queue = asyncio.Queue()
    _event_subscribers.append(queue)

    async def generate():
        try:
            while True:
                data = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _event_subscribers.remove(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/v1/dashboard/cache-efficiency")
async def dashboard_cache_efficiency(
    hours: int = Query(default=720, ge=1, le=8760),
):
    """Cache efficiency metrics — how much prompt caching saves."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)

    rows = conn.execute(
        """
        SELECT metadata_json FROM events
        WHERE timestamp > ? AND event_type = 'llm_response' AND metadata_json != '{}'
    """,
        [cutoff],
    ).fetchall()

    total_cache_read = 0
    total_cache_write = 0
    total_input = 0
    total_output = 0
    events_with_cache = 0

    for row in rows:
        try:
            meta = json.loads(row["metadata_json"])
            cr = meta.get("cache_read_tokens", 0)
            cw = meta.get("cache_creation_tokens", 0)
            if cr > 0 or cw > 0:
                events_with_cache += 1
            total_cache_read += cr
            total_cache_write += cw
        except (json.JSONDecodeError, TypeError):
            pass

    # Get total token counts from the events table
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(input_tokens), 0) as total_input,
            COALESCE(SUM(output_tokens), 0) as total_output,
            COUNT(*) as total_events
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
    """,
        [cutoff],
    ).fetchone()

    total_input = totals["total_input"]
    total_output = totals["total_output"]
    total_events = totals["total_events"]

    # Cache hit rate: what % of input tokens came from cache
    total_possible = total_input + total_cache_read
    cache_hit_rate = (total_cache_read / max(total_possible, 1)) * 100

    # Estimated savings: cache reads cost 0.1x, cache writes cost 1.25x
    # Without caching, all cache_read tokens would be full-price input tokens
    # Savings = cache_read_tokens * 0.9 * avg_input_price_per_token
    # Using a blended rate of ~$3/M (sonnet-level)
    blended_rate = 3.0 / 1_000_000
    cache_savings = total_cache_read * 0.9 * blended_rate

    conn.close()
    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "cache_hit_rate": round(cache_hit_rate, 1),
        "events_with_cache": events_with_cache,
        "total_events": total_events,
        "estimated_cache_savings": round(cache_savings, 4),
    }


@app.get("/api/v1/dashboard/usage-patterns")
async def dashboard_usage_patterns(
    hours: int = Query(default=720, ge=1, le=8760),
):
    """Usage patterns — hour of day and day of week breakdowns."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)

    # Hour of day (local time)
    hourly = conn.execute(
        """
        SELECT
            CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) as hour,
            COUNT(*) as requests,
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
        GROUP BY hour
        ORDER BY hour ASC
    """,
        [cutoff],
    ).fetchall()

    # Day of week (0=Sunday, 6=Saturday)
    daily = conn.execute(
        """
        SELECT
            CAST(strftime('%w', timestamp, 'unixepoch', 'localtime') AS INTEGER) as dow,
            COUNT(*) as requests,
            COALESCE(SUM(total_cost), 0) as cost,
            COALESCE(SUM(total_tokens), 0) as tokens
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
        GROUP BY dow
        ORDER BY dow ASC
    """,
        [cutoff],
    ).fetchall()

    # Tool usage by hour (for heatmap)
    tool_hourly = conn.execute(
        """
        SELECT
            tool_name,
            CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) as hour,
            COUNT(*) as count
        FROM events
        WHERE timestamp > ?
            AND event_type = 'tool_call'
            AND tool_name IS NOT NULL
            AND tool_name != ''
        GROUP BY tool_name, hour
        ORDER BY tool_name, hour
    """,
        [cutoff],
    ).fetchall()

    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    conn.close()
    return {
        "hourly": [
            {
                "hour": r["hour"],
                "label": f"{r['hour']:02d}:00",
                "requests": r["requests"],
                "cost": round(r["cost"], 4),
                "tokens": r["tokens"],
            }
            for r in hourly
        ],
        "daily": [
            {
                "dow": r["dow"],
                "label": day_names[r["dow"]],
                "requests": r["requests"],
                "cost": round(r["cost"], 4),
                "tokens": r["tokens"],
            }
            for r in daily
        ],
        "tool_heatmap": [dict(r) for r in tool_hourly],
    }


@app.get("/api/v1/dashboard/share-stats")
async def dashboard_share_stats(
    hours: int = Query(default=720, ge=1, le=8760),
    subscription_cost: float = Query(default=200.0),
):
    """Pre-computed stats for the shareable card."""
    conn = get_db()
    cutoff = time.time() - (hours * 3600)

    row = conn.execute(
        """
        SELECT
            COUNT(*) as total_requests,
            COALESCE(SUM(total_cost), 0) as total_cost,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(input_tokens), 0) as input_tokens,
            COALESCE(SUM(output_tokens), 0) as output_tokens,
            COUNT(DISTINCT session_id) as sessions,
            COUNT(DISTINCT model) as models_used,
            MIN(timestamp) as first_event,
            MAX(timestamp) as last_event
        FROM events
        WHERE timestamp > ? AND event_type = 'llm_response'
    """,
        [cutoff],
    ).fetchone()

    # Top model
    top_model = conn.execute(
        """
        SELECT model, COUNT(*) as c FROM events
        WHERE timestamp > ? AND event_type = 'llm_response' AND model != ''
        GROUP BY model ORDER BY c DESC LIMIT 1
    """,
        [cutoff],
    ).fetchone()

    # Top project
    top_project = conn.execute(
        """
        SELECT project_id, COALESCE(SUM(total_cost), 0) as cost FROM events
        WHERE timestamp > ? AND event_type = 'llm_response' AND project_id != ''
        GROUP BY project_id ORDER BY cost DESC LIMIT 1
    """,
        [cutoff],
    ).fetchone()

    # Tool count
    tool_count = conn.execute(
        """
        SELECT COUNT(DISTINCT tool_name) as c FROM events
        WHERE timestamp > ? AND event_type = 'tool_call' AND tool_name IS NOT NULL
    """,
        [cutoff],
    ).fetchone()

    total_cost = row["total_cost"]
    first_event = row["first_event"] or time.time()
    last_event = row["last_event"] or time.time()
    span_days = max((last_event - first_event) / 86400, 1)
    daily_avg = total_cost / span_days
    monthly_projected = daily_avg * 30
    savings = monthly_projected - subscription_cost

    conn.close()
    return {
        "period_days": round(span_days, 1),
        "total_requests": row["total_requests"],
        "total_cost": round(total_cost, 2),
        "total_tokens": row["total_tokens"],
        "sessions": row["sessions"],
        "monthly_projected": round(monthly_projected, 2),
        "subscription_cost": subscription_cost,
        "savings": round(savings, 2),
        "savings_pct": round((savings / max(monthly_projected, 0.01)) * 100, 0),
        "daily_avg": round(daily_avg, 2),
        "top_model": top_model["model"] if top_model else "N/A",
        "top_project": (
            (top_project["project_id"] or "").replace("claude-code:", "") if top_project else "N/A"
        ),
        "unique_tools": tool_count["c"] if tool_count else 0,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
