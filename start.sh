#!/bin/bash
# AgentWatch — Quick Start Script
# Starts the backend and loads data into the dashboard.
#
# Usage:
#   ./start.sh              # Start with demo data
#   ./start.sh --claude     # Import real Claude Code session logs
#   ./start.sh --watch      # Import Claude Code logs + live tail mode

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
DASHBOARD_DIR="$SCRIPT_DIR/dashboard"
EXAMPLES_DIR="$SCRIPT_DIR/examples"
SDK_DIR="$SCRIPT_DIR/sdk"

MODE="demo"
if [[ "$1" == "--claude" || "$1" == "--claude-code" ]]; then
    MODE="claude"
elif [[ "$1" == "--watch" ]]; then
    MODE="watch"
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║         AgentWatch v0.1.0            ║"
echo "  ║   AI Agent Observability Dashboard   ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  Error: Python 3 is required. Install it first."
    exit 1
fi

# Install backend deps
echo "  [1/4] Installing dependencies..."
pip3 install fastapi uvicorn --break-system-packages -q 2>/dev/null || pip3 install fastapi uvicorn -q

# Start backend
echo "  [2/4] Starting backend on port 8100..."
echo "         Data stored in: ${AGENTWATCH_DB:-$HOME/.agentwatch/data.db}"
cd "$BACKEND_DIR"
python3 -m uvicorn server:app --host 0.0.0.0 --port 8100 --log-level warning &
BACKEND_PID=$!
echo "         Backend PID: $BACKEND_PID"

# Wait for backend to be ready
sleep 2

if [[ "$MODE" == "demo" ]]; then
    echo "  [3/4] Loading demo data..."
    cd "$EXAMPLES_DIR"
    python3 demo_data.py --events 200 --hours 24
elif [[ "$MODE" == "claude" || "$MODE" == "watch" ]]; then
    echo "  [3/4] Importing Claude Code session logs..."
    cd "$SDK_DIR"
    python3 -m agentwatch.claude_code_import --backend http://localhost:8100
fi

echo "  [4/4] Dashboard ready!"
echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │  Dashboard: file://$DASHBOARD_DIR/index.html"
echo "  │  API:       http://localhost:8100/docs"
echo "  │  Health:    http://localhost:8100/health"
echo "  └──────────────────────────────────────┘"
echo ""

if [[ "$MODE" == "watch" ]]; then
    echo "  Live watch mode: tailing Claude Code sessions..."
    echo "  New events will appear on the dashboard in real-time."
    echo "  Press Ctrl+C to stop."
    echo ""
    cd "$SDK_DIR"
    python3 -m agentwatch.claude_code_import --watch --backend http://localhost:8100 &
    WATCH_PID=$!
    trap "kill $BACKEND_PID $WATCH_PID 2>/dev/null" EXIT
    wait $BACKEND_PID
else
    echo "  Press Ctrl+C to stop."
    echo ""
    trap "kill $BACKEND_PID 2>/dev/null" EXIT
    wait $BACKEND_PID
fi
