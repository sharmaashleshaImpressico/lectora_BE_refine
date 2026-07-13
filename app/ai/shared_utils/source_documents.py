"""Source-document assignment helpers for TO sections."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def resolve_section_source_documents(to_sec: dict[str, Any]) -> list[str]:
    """Return source file references for a TO section, if any."""
    for key in ("source_documents", "source_files"):
        values = to_sec.get(key)
        if isinstance(values, list) and values:
            return [str(value).strip() for value in values if str(value).strip()]
    return []


def assign_source_documents_to_outline(
    outline: dict[str, Any],
    heading_tree: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Fuzzy-match outline sections to heading_tree entries for source_documents."""
    if not heading_tree:
        return outline, 0

    headings = [
        str(entry.get("text") or entry.get("heading") or "").strip()
        for entry in heading_tree
        if isinstance(entry, dict) and (entry.get("text") or entry.get("heading"))
    ]
    if not headings:
        return outline, 0

    assigned = 0
    for section in outline.get("sections") or []:
        if not isinstance(section, dict) or resolve_section_source_documents(section):
            continue
        title = (section.get("title") or section.get("heading") or "").strip()
        if not title:
            continue

        best_heading = ""
        best_score = 0.0
        for heading in headings:
            score = SequenceMatcher(None, title.lower(), heading.lower()).ratio()
            if score > best_score:
                best_score = score
                best_heading = heading

        if best_score >= 0.6 and best_heading:
            section["source_documents"] = [best_heading]
            assigned += 1

    return outline, assigned


__all__ = ["assign_source_documents_to_outline", "resolve_section_source_documents"]
