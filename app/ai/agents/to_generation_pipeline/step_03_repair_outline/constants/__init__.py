"""S1 TO refinement constants."""
from __future__ import annotations

from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.config import (
    COMPRESSED_LO_PREFIX,
    COURSE_CONFIG_KEYS,
    DEFAULT_DIFFICULTY,
    LLM_CALL_PURPOSE,
    REFINE_SKIP_FIELDS,
    REFINE_SKIP_WARNING_FIELDS,
)
from app.ai.agents.to_generation_pipeline.step_03_repair_outline.constants.prompts import (
    REPAIR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)

__all__ = [
    "COMPRESSED_LO_PREFIX",
    "COURSE_CONFIG_KEYS",
    "DEFAULT_DIFFICULTY",
    "LLM_CALL_PURPOSE",
    "REFINE_SKIP_FIELDS",
    "REFINE_SKIP_WARNING_FIELDS",
    "REPAIR_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
]
