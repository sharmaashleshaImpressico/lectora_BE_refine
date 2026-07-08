"""S1 Validator constants — central registry for all configuration values."""
from __future__ import annotations

from .llm import MAX_LLM_RETRIES, RETRY_BACKOFF_SECONDS
from .naic import DEFAULT_WPM, DIFFICULTY_MULTIPLIERS
from .prompts import (
    REFINE_SYSTEM_PROMPT,
    RESPONSE_SCHEMA,
    SEMANTIC_SYSTEM_PROMPT,
    SEVERITY_POLICY,
    VALIDATION_RULES,
)
from .validation import (
    A0_NON_BLOCKING_FIELD_TOKENS,
    COVERAGE_THRESHOLD,
    PARTIAL_THRESHOLD,
    REFINE_SKIP_FIELDS,
    REFINE_SKIP_WARNING_FIELDS,
    STOP_WORDS,
)

__all__ = [
    # naic
    "DEFAULT_WPM",
    "DIFFICULTY_MULTIPLIERS",
    # llm
    "MAX_LLM_RETRIES",
    "RETRY_BACKOFF_SECONDS",
    # prompts
    "SEMANTIC_SYSTEM_PROMPT",
    "VALIDATION_RULES",
    "SEVERITY_POLICY",
    "RESPONSE_SCHEMA",
    "REFINE_SYSTEM_PROMPT",
    # validation
    "COVERAGE_THRESHOLD",
    "PARTIAL_THRESHOLD",
    "STOP_WORDS",
    "A0_NON_BLOCKING_FIELD_TOKENS",
    "REFINE_SKIP_FIELDS",
    "REFINE_SKIP_WARNING_FIELDS",
]
