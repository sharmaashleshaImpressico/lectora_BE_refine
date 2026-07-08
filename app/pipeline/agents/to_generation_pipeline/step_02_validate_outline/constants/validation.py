"""Validation thresholds, field filters, and stop-word lists for S1 checks."""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Topic coverage thresholds (deterministic pre-check)
# ---------------------------------------------------------------------------

# Fraction of topic keywords that must match to be considered "covered".
COVERAGE_THRESHOLD: float = 0.60

# Fraction of topic keywords that must match to be considered "partial" (vs missing).
PARTIAL_THRESHOLD: float = 0.25

# Common English stop words excluded from keyword-overlap scoring.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "to",
        "for",
        "with",
        "that",
        "this",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "as",
        "at",
        "by",
        "from",
        "its",
        "it",
        "their",
        "they",
        "will",
        "shall",
        "about",
        "into",
        "through",
        "during",
    }
)

# ---------------------------------------------------------------------------
# S1 AI digest: text limits for Langfuse/LLM payload (subtopics must stay full)
# ---------------------------------------------------------------------------

S1_DIGEST_SECTION_TITLE_MAX_CHARS: int = 280
S1_DIGEST_SECTION_CONTENT_MAX_CHARS: int = 2000
# Subtopic titles are validated verbatim — never truncate (ellipsis causes false warnings).
S1_DIGEST_SUBTOPIC_MAX_CHARS: int | None = None

# Cap AI-emitted warnings per validation pass to keep refine cycles convergent.
MAX_S1_SEMANTIC_WARNINGS: int = 4

_SEC_FIELD_PATTERN = re.compile(r"^sec_(\d+)(\.subtopics(?:\[\d+\])?)?$", re.IGNORECASE)
_SECTIONS_FIELD_PATTERN = re.compile(r"^sections\[(\d+)\](\..+)?$")
_COURSE_OUTLINE_SECTION_PATTERN = re.compile(
    r"^course_outline\.sections\[(\d+)\](\..+)?$"
)


def normalize_s1_issue_field(field: str) -> str:
    """Map legacy S1 field paths to course_outline.sections[N] (1-based index)."""
    text = (field or "").strip()
    if not text:
        return text

    sec_match = _SEC_FIELD_PATTERN.match(text)
    if sec_match:
        suffix = sec_match.group(2) or ""
        return f"course_outline.sections[{sec_match.group(1)}]{suffix}"

    sections_match = _SECTIONS_FIELD_PATTERN.match(text)
    if sections_match:
        suffix = sections_match.group(2) or ""
        return f"course_outline.sections[{sections_match.group(1)}]{suffix}"

    return text


def section_index_from_field(field: str) -> int | None:
    """Return the 1-based section index from a field path, if present."""
    normalized = normalize_s1_issue_field(field)
    match = _COURSE_OUTLINE_SECTION_PATTERN.match(normalized)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def s1_warning_priority_key(field: str) -> tuple[int, int, str]:
    """Sort key for prioritizing S1 warnings (lower tuple sorts first)."""
    normalized = normalize_s1_issue_field(field)
    if normalized.startswith("required_topics.coverage."):
        return (0, 0, normalized)
    section_index = section_index_from_field(normalized)
    if section_index is not None and ".subtopics" in normalized:
        return (1, section_index, normalized)
    if normalized.startswith("course_outline.sections["):
        return (2, section_index or 0, normalized)
    return (3, 0, normalized)


def has_concrete_repair_target(field: str) -> bool:
    """True when an S1 warning maps to a specific outline location the refine agent can edit."""
    if field == "s1_ai_validator.retry":
        return True
    normalized = normalize_s1_issue_field(field)
    if normalized.startswith("required_topics.coverage."):
        return True
    if normalized in {"learning_objectives", "learning_objectives_coverage"}:
        return True
    if normalized.startswith("learning_objective_mapping."):
        return True
    return section_index_from_field(normalized) is not None


def resolved_issues_from_refine_history(shared_state: dict[str, Any]) -> list[dict[str, str]]:
    """Recently resolved S1 issues — passed to the validator to avoid re-flagging."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for cycle in shared_state.get("s1_refine_metrics") or []:
        for item in cycle.get("resolved_issues") or []:
            field = str(item.get("field") or "")
            message = str(item.get("message") or "")
            key = f"{field}|{message}"
            if field and key not in seen:
                seen.add(key)
                entries.append({"field": field, "message": message})
    return entries[-12:]

# ---------------------------------------------------------------------------
# Semantic validator: A0-stage field downgrade filter
# ---------------------------------------------------------------------------

# Fields/messages containing any of these tokens must not be raised as blockers
# at the A0 TO validation stage — they are downgraded to warnings.
A0_NON_BLOCKING_FIELD_TOKENS: tuple[str, ...] = (
    "maps_to_objectives",
    "learning_objective_mapping",
)

KNOWLEDGE_CHECK_ISSUE_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        "knowledge_check_count",
        "has_knowledge_check",
        "is_knowledge_check",
    }
)

KNOWLEDGE_CHECK_ISSUE_FIELD_PREFIXES: tuple[str, ...] = (
    "knowledge_check",
    "kc_placement",
    "min_kc",
)

KNOWLEDGE_CHECK_ISSUE_TEXT_MARKERS: tuple[str, ...] = (
    "knowledge check",
    "knowledge_check",
    "in-lesson quiz",
    "lesson quiz",
    "min_kc_per_lesson",
    "kc count",
    "has_knowledge_check",
)


def is_knowledge_check_validation_issue(issue: dict[str, str | Any]) -> bool:
    """Return True when an S1 issue is about in-lesson knowledge checks."""
    field = str(issue.get("field") or "").lower()
    if field in KNOWLEDGE_CHECK_ISSUE_SKIP_FIELDS:
        return True
    if any(field.startswith(prefix) for prefix in KNOWLEDGE_CHECK_ISSUE_FIELD_PREFIXES):
        return True

    combined = " ".join(
        str(issue.get(key) or "")
        for key in ("field", "message", "expected", "remediation", "rule_source")
    ).lower()
    return any(marker in combined for marker in KNOWLEDGE_CHECK_ISSUE_TEXT_MARKERS)


EXAM_ISSUE_SKIP_FIELDS: frozenset[str] = frozenset(
    {
        "objective_coverage",
        "learning_objectives_coverage",
        "answer_options_count",
        "allow_true_false",
        "allow_all_of_the_above",
    }
)

EXAM_ISSUE_FIELD_PREFIXES: tuple[str, ...] = (
    "exam.",
    "assessment_rules.",
)

EXAM_ISSUE_TEXT_MARKERS: tuple[str, ...] = (
    "final exam",
    "exam readiness",
    "exam question",
    "assessment_rules",
    "objective_coverage_required",
    "final_exam_min_questions",
)


def is_exam_validation_issue(issue: dict[str, str | Any]) -> bool:
    """Return True when an S1 issue is about final-exam or assessment-rule validation."""
    field = str(issue.get("field") or "").lower()
    if field in EXAM_ISSUE_SKIP_FIELDS:
        return True
    if any(field.startswith(prefix) for prefix in EXAM_ISSUE_FIELD_PREFIXES):
        return True

    combined = " ".join(
        str(issue.get(key) or "")
        for key in ("field", "message", "expected", "remediation", "rule_source")
    ).lower()
    return any(marker in combined for marker in EXAM_ISSUE_TEXT_MARKERS)


def is_out_of_scope_to_validation_issue(issue: dict[str, str | Any]) -> bool:
    """Return True for KC or exam issues that S1 TO validation must not enforce."""
    return is_knowledge_check_validation_issue(issue) or is_exam_validation_issue(issue)

# ---------------------------------------------------------------------------
# S1 refinement agent: issue filter sets (canonical source: step_03 constants)
# ---------------------------------------------------------------------------

from lectora_backend.pipeline.agent.to_generation_pipeline.step_03_repair_outline.constants.config import (
    REFINE_SKIP_FIELDS,
    REFINE_SKIP_WARNING_FIELDS,
)
