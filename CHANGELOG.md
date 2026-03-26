# Changelog

All notable changes to AgentWatch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-26

### Added

- Core SDK with zero mandatory dependencies
  - `AgentWatch` telemetry client with session management
  - `MonitoredClient` drop-in wrapper for the Anthropic SDK
  - Manual tracking for any LLM provider (OpenAI, Google, etc.)
  - Cost calculation with up-to-date model pricing
  - Configurable cost alerting (hourly/daily thresholds)
  - Local JSON log fallback
- Claude Code session log importer
  - Automatic discovery of local session logs (`~/.claude/projects/`)
  - Live watch mode for real-time monitoring
  - Cache-aware cost estimation (read/write token pricing)
  - Event deduplication
- Detection modules
  - Hallucination scoring (heuristic-based)
  - Prompt injection detection (17 patterns)
  - PII detection (email, phone, SSN, credit card, IP)
  - Credential leak detection
  - Behavioral drift tracking
- FastAPI backend
  - SQLite storage with WAL mode
  - REST API for dashboard data
  - Server-Sent Events (SSE) for real-time updates
  - Time-bucketed analytics and period comparison
  - Session replay endpoint
  - 5-hour billing window tracking (for Claude Max)
- Self-contained dashboard (single HTML file)
  - Overview tab with KPIs and cumulative cost chart
  - Cost & Savings tab with Max subscription savings calculator
  - Tools tab with usage breakdown
  - Sessions tab with replay
  - Events tab with filtering and sorting
  - Real-time updates via SSE
  - Dark theme with JetBrains Mono
- One-command setup (`./start.sh`)
- Demo data generator
- Examples for quickstart, manual tracking
