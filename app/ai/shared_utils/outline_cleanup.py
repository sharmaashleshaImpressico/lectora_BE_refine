"""Strip deprecated paragraph-index fields from TO outlines."""

from __future__ import annotations

from typing import Any

_PARA_IDX_KEYS: tuple[str, ...] = (
    "para_idx",
    "para_idx_start",
    "para_idx_end",
    "para_start",
    "para_end",
)


def _strip_para_indices_from_item(item: dict[str, Any]) -> bool:
    removed = False
    for key in _PARA_IDX_KEYS:
        if key in item:
            del item[key]
            removed = True
    for key in ("subtopics", "topics"):
        children = item.get(key)
        if not isinstance(children, list):
            continue
        for child in children:
            if isinstance(child, dict):
                for para_key in _PARA_IDX_KEYS:
                    if para_key in child:
                        del child[para_key]
                        removed = True
    return removed


def strip_para_indices_from_sections(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Remove deprecated para_idx fields from a section list."""
    count = 0
    for section in sections:
        if isinstance(section, dict) and _strip_para_indices_from_item(section):
            count += 1
    return sections, count


def strip_para_indices_from_outline(outline: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Remove deprecated para_idx fields from all section lists on an outline."""
    total = 0
    for key in ("sections", "lessons", "modules", "table_of_contents"):
        sections = outline.get(key)
        if isinstance(sections, list):
            _, removed = strip_para_indices_from_sections(sections)
            total += removed
    return outline, total


__all__ = ["strip_para_indices_from_outline", "strip_para_indices_from_sections"]
