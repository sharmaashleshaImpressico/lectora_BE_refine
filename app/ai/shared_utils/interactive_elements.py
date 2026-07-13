"""Interactive-element detection and normalization for TO sections."""

from __future__ import annotations

from typing import Any

_INTERACTIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "knowledge_check": ("knowledge check", "quiz", "assessment"),
    "case_study": ("case study", "case-study"),
    "activity": ("activity", "exercise", "hands-on"),
    "video": ("video",),
}


def collect_interactive_elements(
    paras: list[Any],
    *,
    initial: list[str] | None = None,
) -> list[str]:
    """Infer interactive element tags from paragraph text."""
    elements = list(initial or [])
    text = " ".join(str(paragraph) for paragraph in paras).lower()
    for element, keywords in _INTERACTIVE_KEYWORDS.items():
        if element not in elements and any(keyword in text for keyword in keywords):
            elements.append(element)
    return elements


def strip_knowledge_checks_from_outline(outline: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Remove knowledge_check tags from section interactive_elements."""
    count = 0
    for section in outline.get("sections") or []:
        if not isinstance(section, dict):
            continue
        elements = section.get("interactive_elements")
        if isinstance(elements, list) and "knowledge_check" in elements:
            section["interactive_elements"] = [
                element for element in elements if element != "knowledge_check"
            ]
            count += 1
    return outline, count


def resolve_section_assets(
    interactive_elements: list[str] | None,
    mapped_images: list[dict[str, Any]] | None,
    *,
    has_knowledge_check: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Merge interactive-element tags with mapped section images."""
    elements = list(interactive_elements or [])
    if has_knowledge_check and "knowledge_check" not in elements:
        elements.append("knowledge_check")
    return elements, list(mapped_images or [])


__all__ = [
    "collect_interactive_elements",
    "resolve_section_assets",
    "strip_knowledge_checks_from_outline",
]
