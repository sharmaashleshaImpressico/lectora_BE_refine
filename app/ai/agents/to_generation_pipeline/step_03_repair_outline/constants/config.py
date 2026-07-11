"""Pipeline and validation constants for S1 TO refinement."""
from __future__ import annotations

import re

COURSE_CONFIG_KEYS: tuple[str, ...] = (
    "required_topics",
    "learning_objectives",
    "tone",
    "depth",
    "emphasis",
    "avoid",
    "duration_hours",
    "difficulty_level",
    "calculated_word_count",
    "preferred_chapters",
    "lesson_style",
    "experience_level",
    "learner_outcomes",
    "course_type_hint",
    "course_description",
    "include_case_studies",
    "include_examples",
)

LLM_CALL_PURPOSE = "S1_TO_REFINE"
DEFAULT_DIFFICULTY = "intermediate"
MAX_REFINE_WARNING_ISSUES_PER_CYCLE = 4

REFINE_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        "s1_ai_validator.metrics",
        "s1_ai_validator.summary",
    }
)

REFINE_SKIP_WARNING_FIELDS: frozenset[str] = frozenset(
    {
        "course_id",
        "content_sample",
        "llm_confidence",
        "images",
        "knowledge_check_count",
    }
)

REFINE_SKIP_WARNING_FIELD_PREFIXES: tuple[str, ...] = (
    "required_topics_precheck.",
)

COMPRESSED_LO_PREFIX = re.compile(
    r"(?i)^\s*(course purpose|learning objectives?)\b.*:",
)
