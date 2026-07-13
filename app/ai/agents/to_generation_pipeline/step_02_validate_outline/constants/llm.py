"""LLM retry and backoff configuration for S1 validators."""
from __future__ import annotations

# Maximum number of LLM call retries before raising.
MAX_LLM_RETRIES: int = 3

# Initial backoff delay in seconds; multiplied by attempt number on each retry.
RETRY_BACKOFF_SECONDS: float = 0.75
