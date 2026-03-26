# Contributing to AgentWatch

Thanks for your interest in contributing! AgentWatch is a young project and we welcome all kinds of help.

## Ways to contribute

- Report bugs via [GitHub Issues](https://github.com/zmaxgong/agentwatch/issues)
- Suggest features or improvements
- Submit pull requests
- Improve documentation
- Share how you're using AgentWatch

## Development setup

```bash
# Clone the repo
git clone https://github.com/zmaxgong/agentwatch.git
cd agentwatch

# Install backend deps
pip install -r backend/requirements.txt

# Install SDK in development mode
cd sdk && pip install -e ".[all]" && cd ..

# (Optional) Install dev tools
pip install ruff pytest

# Start with demo data
./start.sh
```

## Pull requests

1. Fork the repo and create a branch from `main`
2. If you've added code, add or update tests where appropriate
3. Make sure the backend starts cleanly (`python -m uvicorn backend.server:app`)
4. Run the linter: `ruff check sdk/ backend/ examples/`
5. Keep PRs focused — one feature or fix per PR
6. Write a clear description of what changed and why

## Code style

- Python: Follow PEP 8. Use type hints where practical. We use [Ruff](https://docs.astral.sh/ruff/) for linting.
- JavaScript: Keep it vanilla (no frameworks in the dashboard).
- Keep dependencies minimal. The SDK has zero mandatory dependencies — let's keep it that way.

## Architecture decisions

- **No external services**: Everything runs locally. If a feature requires a cloud service, it should be optional.
- **Zero mandatory SDK dependencies**: The SDK uses only Python standard library. Optional extras (like `anthropic`) are in `extras_require`.
- **Single-file dashboard**: The dashboard is one self-contained HTML file. No build step, no npm, no bundler.
- **SQLite for storage**: Simple, portable, zero-config. No Postgres, no Redis.

## Reporting bugs

Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version, OS, and any relevant environment details

## Security

If you find a security vulnerability, please see [SECURITY.md](SECURITY.md) for responsible disclosure instructions. Do not open a public issue.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
