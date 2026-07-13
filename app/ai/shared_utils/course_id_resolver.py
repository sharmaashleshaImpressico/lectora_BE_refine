"""Course-ID extraction and resolution helpers."""

from __future__ import annotations

import re
from typing import Any

_COURSE_ID_LABEL_RE = re.compile(
    r"(?:course\s*(?:id|#|number)|coursenumber)\s*[:#]?\s*(\d{4,})",
    re.IGNORECASE,
)
_NUMERIC_ID_RE = re.compile(r"\b(\d{5,})\b")


def extract_course_id_from_text(text: str) -> str | None:
    """Extract a numeric course ID from free text."""
    if not text:
        return None
    match = _COURSE_ID_LABEL_RE.search(text)
    if match:
        return match.group(1)
    match = _NUMERIC_ID_RE.search(text)
    if match:
        return match.group(1)
    return None


def extract_course_id_from_table_rows(rows: list[list[str]]) -> str | None:
    """Scan DOCX table rows for a course ID."""
    for row in rows:
        for cell in row:
            found = extract_course_id_from_text(cell)
            if found:
                return found
    return None


def normalize_course_id(value: Any) -> str | None:
    """Return digits-only course ID when present."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value).strip())
    return digits or None


def resolve_course_id(doc_id: Any, outline_id: Any) -> str | None:
    """Prefer document-extracted ID, then outline course_id."""
    for candidate in (doc_id, outline_id):
        normalized = normalize_course_id(candidate)
        if normalized:
            return normalized
    return None


def derive_course_id_from_title(title: str) -> str | None:
    """Derive a slug-style fallback ID from a course title."""
    if not title:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:64] if slug else None


def resolve_course_id_from_shared_state(shared_state: dict[str, Any]) -> str | None:
    """Resolve course ID from an in-memory shared_state dict."""
    extracted = shared_state.get("extracted_inputs") or {}
    course_id = normalize_course_id(extracted.get("course_id"))
    if course_id:
        return course_id
    outline = shared_state.get("llm_to_outline_classification") or {}
    return normalize_course_id(outline.get("course_id"))


__all__ = [
    "derive_course_id_from_title",
    "extract_course_id_from_table_rows",
    "extract_course_id_from_text",
    "normalize_course_id",
    "resolve_course_id",
    "resolve_course_id_from_shared_state",
]
