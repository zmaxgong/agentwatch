# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in AgentWatch, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email us at **security@tandmlabs.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Scope

AgentWatch runs entirely locally — no data leaves your machine unless you explicitly configure an external backend. That said, we take the following seriously:

- **Session log parsing**: The Claude Code importer reads local JSONL files. We sanitize message content before storage (truncated previews only, no full prompts or responses stored in the database).
- **SQL injection**: All database queries use parameterized statements.
- **Dependency security**: The SDK has zero mandatory dependencies. The backend requires only FastAPI, Uvicorn, and Pydantic.
- **PII handling**: The SDK includes PII detection (email, phone, SSN, credit card patterns) as a monitoring feature, but does not store or transmit detected PII.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Features

AgentWatch includes built-in security monitoring for your AI agents:

- Prompt injection detection (17 patterns)
- PII leak detection in agent inputs/outputs
- Credential exposure detection
- Security alert events with severity levels
