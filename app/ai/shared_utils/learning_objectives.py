"""Learning-objective normalization and resolution helpers."""

from __future__ import annotations

from typing import Any


def normalize_learning_objectives(raw: Any) -> list[str]:
    """Coerce heterogeneous LO payloads into a deduplicated list of strings."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = (
                item.get("text")
                or item.get("objective")
                or item.get("title")
                or ""
            ).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def resolve_learning_objectives(data: dict[str, Any]) -> list[str]:
    """Resolve LOs from shared_state — prefer extracted_inputs, then TO outline."""
    extracted = data.get("extracted_inputs") or {}
    los = normalize_learning_objectives(extracted.get("learning_objectives"))
    if los:
        return los

    outline = data.get("llm_to_outline_classification") or {}
    return normalize_learning_objectives(outline.get("learning_objectives"))


__all__ = ["normalize_learning_objectives", "resolve_learning_objectives"]
