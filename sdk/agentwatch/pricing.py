"""Auto-fetch and cache model pricing from provider APIs."""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("agentwatch.pricing")

# Fallback hardcoded pricing (as of March 2026)
FALLBACK_PRICING = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    # Google
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
}

CACHE_TTL_SECONDS = 86400  # 24 hours
CACHE_DIR = Path.home() / ".agentwatch"


def _get_cache_path() -> Path:
    """Get the pricing cache file path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "pricing_cache.json"


def _fetch_pricing_from_providers() -> Optional[Dict[str, Dict[str, float]]]:
    """Fetch model pricing from multiple provider APIs.

    Returns dict of {model_name: {input: $/1M, output: $/1M}} or None if fetch fails.
    For MVP, returns static known pricing. In production, this could fetch from:
    - anthropic.com/pricing
    - openai.com/api/pricing or their models API
    - ai.google.dev/pricing
    """
    try:
        # For MVP, we use static mappings of known models from each provider
        # This can be expanded to fetch from actual APIs
        pricing = {
            # Anthropic
            "claude-opus-4-6": {"input": 15.00, "output": 75.00},
            "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
            "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
            "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
            "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
            "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
            # OpenAI
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4-turbo": {"input": 10.00, "output": 30.00},
            "o1": {"input": 15.00, "output": 60.00},
            "o1-mini": {"input": 3.00, "output": 12.00},
            # Google
            "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
            "gemini-2.0-pro": {"input": 1.25, "output": 5.00},
        }
        logger.info(f"Loaded {len(pricing)} models from provider pricing")
        return pricing
    except Exception as e:
        logger.warning(f"Failed to fetch provider pricing: {e}")
        return None


def _load_cache() -> Optional[Dict]:
    """Load pricing cache if valid."""
    cache_path = _get_cache_path()
    if not cache_path.exists():
        return None

    try:
        with open(cache_path) as f:
            cache = json.load(f)

        # Check if cache is still fresh
        age = time.time() - cache.get("timestamp", 0)
        if age < CACHE_TTL_SECONDS:
            logger.info(f"Using cached pricing (age: {age:.0f}s)")
            return cache.get("pricing")

        logger.info(f"Pricing cache expired (age: {age:.0f}s)")
    except Exception as e:
        logger.warning(f"Failed to load pricing cache: {e}")

    return None


def _save_cache(pricing: Dict[str, Dict[str, float]]) -> None:
    """Save pricing to cache."""
    cache_path = _get_cache_path()
    try:
        cache = {"timestamp": time.time(), "pricing": pricing}
        with open(cache_path, "w") as f:
            json.dump(cache, f)
        logger.info("Pricing cached successfully")
    except Exception as e:
        logger.warning(f"Failed to save pricing cache: {e}")


def get_model_pricing() -> Dict[str, Dict[str, float]]:
    """Get current model pricing, fetching from providers if cache is stale.

    Returns dict of {model_name: {input: $/1M, output: $/1M}}.
    Falls back to hardcoded pricing on any failure.
    """
    # Try to load from cache
    cached = _load_cache()
    if cached is not None:
        return cached

    # Try to fetch from providers
    pricing = _fetch_pricing_from_providers()

    # If we got any pricing, use it and cache it
    if pricing:
        _save_cache(pricing)
        return pricing

    # Fall back to hardcoded
    logger.warning("Using fallback hardcoded pricing")
    return FALLBACK_PRICING
