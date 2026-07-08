"""Topic label normalization for S1 refine issue deduplication."""

from __future__ import annotations

import re

from app.ai.agents.to_generation_pipeline.step_02_validate_outline.constants.validation import (
    STOP_WORDS,
)

_REQUIRED_TOPIC_MESSAGE_PATTERN = re.compile(r"Required topic '([^']+)'")


def topic_keywords(text: str) -> list[str]:
    """Extract scoring keywords from a topic label."""
    raw = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [word for word in raw if word not in STOP_WORDS and len(word) > 1]


def normalize_topic_key(text: str) -> str:
    """Normalize a topic label for deduplication comparisons."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def extract_required_topic_label(field: str, message: str) -> str:
    """Resolve the full required-topic label from an S1 coverage issue."""
    match = _REQUIRED_TOPIC_MESSAGE_PATTERN.search(message or "")
    if match:
        return match.group(1).strip()
    suffix = field.removeprefix("required_topics.coverage.").replace("_", " ")
    return suffix.strip()


def refinement_issue_topic_key(field: str, message: str) -> str | None:
    """Return a dedupe key when an issue refers to a named topic, else None."""
    if field.startswith("required_topics.coverage."):
        label = extract_required_topic_label(field, message)
        return normalize_topic_key(label) or None
    if field.startswith("learning_objective_mapping."):
        label = field.split(".", 1)[1]
        return normalize_topic_key(label) or None
    if field in {"learning_objectives", "learning_objectives_coverage"}:
        return normalize_topic_key(message) or None
    return None
