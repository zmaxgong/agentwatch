"""
Drop-in wrapper for the Anthropic client that automatically monitors all calls.

Usage:
    from agentwatch import AgentWatch, MonitoredClient, AgentWatchConfig

    aw = AgentWatch(AgentWatchConfig(project_id="my-app"))
    aw.start_session()

    # Option 1: Let MonitoredClient create the Anthropic client (uses ANTHROPIC_API_KEY env var)
    client = MonitoredClient(aw)

    # Option 2: Pass an API key directly
    client = MonitoredClient(aw, api_key="sk-ant-...")

    # Option 3: Wrap an existing Anthropic client you already configured
    import anthropic
    existing = anthropic.Anthropic(api_key="sk-ant-...", base_url="...")
    client = MonitoredClient(aw, client=existing)

    # Then use it exactly like the Anthropic client
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}]
    )
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agentwatch.client import AgentWatch

logger = logging.getLogger("agentwatch")


class MonitoredMessages:
    """Wraps the Anthropic messages API to auto-record telemetry."""

    def __init__(self, watch: "AgentWatch", anthropic_client: Any):
        self._watch = watch
        self._client = anthropic_client

    def create(self, **kwargs) -> Any:
        """Monitored version of messages.create()."""
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages", [])

        start = time.time()
        error_msg = None
        response = None

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            error_msg = str(e)
            latency_ms = (time.time() - start) * 1000
            self._watch.record_llm_call(
                provider="anthropic",
                model=model,
                messages=messages,
                response_text="",
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                error=error_msg,
            )
            raise

        latency_ms = (time.time() - start) * 1000

        # Extract response data
        response_text = ""
        tool_calls = []

        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        # Record the call
        usage = response.usage
        self._watch.record_llm_call(
            provider="anthropic",
            model=model,
            messages=messages,
            response_text=response_text,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
            tool_calls=tool_calls if tool_calls else None,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )

        # Record individual tool calls
        for tc in tool_calls:
            self._watch.record_tool_call(
                tool_name=tc["name"],
                tool_input=tc["input"],
            )

        return response


class MonitoredClient:
    """
    Drop-in replacement wrapper around the Anthropic client.

    Intercepts all messages.create() calls and records telemetry
    through AgentWatch.
    """

    def __init__(
        self,
        watch: "AgentWatch",
        api_key: Optional[str] = None,
        client: Any = None,
    ):
        """
        Initialize with an AgentWatch instance.

        Args:
            watch: AgentWatch telemetry client
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
            client: An existing anthropic.Anthropic() instance to wrap.
                    If provided, api_key is ignored and this client is used as-is.
        """
        if client is not None:
            self._client = client
        else:
            try:
                import anthropic
            except ImportError:
                raise ImportError(
                    "The 'anthropic' package is required for MonitoredClient. "
                    "Install it with: pip install anthropic"
                )

            if api_key:
                self._client = anthropic.Anthropic(api_key=api_key)
            else:
                self._client = anthropic.Anthropic()

        self._watch = watch
        self.messages = MonitoredMessages(watch, self._client)

    def __getattr__(self, name):
        """Proxy all other attributes to the underlying Anthropic client."""
        return getattr(self._client, name)
