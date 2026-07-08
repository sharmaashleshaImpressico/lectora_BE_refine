"""Normalize heterogeneous LLM TO JSON into the canonical llm_to_outline schema.

Canonical shape mirrors ``rule_pack_config.timed_outline.TO_outline_format`` and
``models.to_outline.TOOutline`` — the same structure used for AI-generated and
uploaded Timed Outlines after A0 finalization.
"""

from __future__ import annotations

from typing import Any

from lectora_backend.pipeline.rule_pack_config.timed_outline import TO_outline_format
from lectora_backend.pipeline.shared_utils.learning_objectives import normalize_learning_objectives

_SECTION_LIST_KEYS: tuple[str, ...] = (
    "sections",
    "lessons",
    "modules",
    "table_of_contents",
    "recommended_scope",
)
_SUBTOPIC_KEYS: tuple[str, ...] = ("subtopics", "topics")
_WRAPPER_KEYS: tuple[str, ...] = (
    "outline",
    "course_outline",
    "timed_outline",
    "to",
    "result",
    "llm_to_outline",
)
_TITLE_KEYS: tuple[str, ...] = ("course_title", "generated_course_title", "course_name")
_CONTENT_KEYS: tuple[str, ...] = ("content", "content_summary", "content_objective")
_CREDIT_KEYS: tuple[str, ...] = ("credit_hour", "credit_hours")


def _unwrap_outline(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return {}
    inner = raw.get("llm_to_outline")
    if isinstance(inner, dict):
        return dict(inner)
    for wrapper_key in _WRAPPER_KEYS:
        wrapped = raw.get(wrapper_key)
        if isinstance(wrapped, dict):
            return dict(wrapped)
    return dict(raw)


def _pick_sections(outline: dict[str, Any]) -> list[dict[str, Any]]:
    for key in _SECTION_LIST_KEYS:
        sections = outline.get(key)
        if isinstance(sections, list) and sections:
            return [s for s in sections if isinstance(s, dict)]
    return []


def _coerce_metric(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _normalize_subtopic(entry: Any) -> str | dict[str, Any]:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        title = (entry.get("title") or entry.get("name") or "").strip()
        normalized: dict[str, Any] = {
            "title": title,
            "content": (entry.get("content") or entry.get("content_summary") or "").strip(),
            "word_count": _coerce_metric(entry.get("word_count")),
            "minutes": _coerce_metric(entry.get("minutes")),
            "credit_hour": _coerce_metric(
                entry.get("credit_hour") if entry.get("credit_hour") is not None else entry.get("credit_hours")
            ),
            "interactive_elements": [
                str(item).strip()
                for item in (entry.get("interactive_elements") or [])
                if str(item).strip()
            ],
        }
        return normalized
    text = str(entry).strip()
    return text


def _normalize_subtopics(section: dict[str, Any]) -> list[str | dict[str, Any]]:
    raw_subtopics: list[Any] = []
    for key in _SUBTOPIC_KEYS:
        value = section.get(key)
        if isinstance(value, list) and value:
            raw_subtopics = value
            break

    normalized: list[str | dict[str, Any]] = []
    for entry in raw_subtopics:
        item = _normalize_subtopic(entry)
        if isinstance(item, str):
            if item:
                normalized.append(item)
            continue
        if item.get("title") or item.get("content"):
            normalized.append(item)
    return normalized


def _normalize_section(section: dict[str, Any], index: int) -> dict[str, Any]:
    title = ""
    for key in ("title", "lesson_title", "heading", "name"):
        candidate = section.get(key)
        if isinstance(candidate, str) and candidate.strip():
            title = candidate.strip()
            break
    if not title:
        title = f"Section {index + 1}"

    content = ""
    for key in _CONTENT_KEYS:
        candidate = section.get(key)
        if isinstance(candidate, str) and candidate.strip():
            content = candidate.strip()
            break

    credit_value = None
    for key in _CREDIT_KEYS:
        if section.get(key) is not None:
            credit_value = section.get(key)
            break

    return {
        "title": title,
        "content": content,
        "subtopics": _normalize_subtopics(section),
        "word_count": _coerce_metric(section.get("word_count")),
        "minutes": _coerce_metric(section.get("minutes")),
        "credit_hour": _coerce_metric(credit_value),
        "interactive_elements": [
            str(item).strip()
            for item in (section.get("interactive_elements") or [])
            if str(item).strip()
        ],
    }


def _sum_section_metrics(sections: list[dict[str, Any]], field: str) -> str:
    total = 0.0
    has_value = False
    for section in sections:
        parsed = section.get(field)
        if parsed in (None, ""):
            continue
        try:
            total += float(parsed)
            has_value = True
        except (TypeError, ValueError):
            continue
    return str(int(round(total))) if field == "word_count" and has_value else (
        str(round(total, 4)) if has_value else ""
    )


def _normalize_totals(
    totals: Any,
    sections: list[dict[str, Any]],
) -> dict[str, str]:
    base = TO_outline_format["totals"]
    normalized = {
        "word_count": "",
        "minutes": "",
        "credit_hours": "",
    }
    if isinstance(totals, dict):
        normalized["word_count"] = _coerce_metric(totals.get("word_count"))
        normalized["minutes"] = _coerce_metric(totals.get("minutes"))
        normalized["credit_hours"] = _coerce_metric(
            totals.get("credit_hours")
            if totals.get("credit_hours") is not None
            else totals.get("credit_hour")
        )

    if not normalized["word_count"]:
        normalized["word_count"] = _sum_section_metrics(sections, "word_count")
    if not normalized["minutes"]:
        normalized["minutes"] = _sum_section_metrics(sections, "minutes")
    if not normalized["credit_hours"]:
        normalized["credit_hours"] = _sum_section_metrics(sections, "credit_hour")

    for key, default in base.items():
        normalized.setdefault(key, default)
    return normalized


def _resolve_course_title(outline: dict[str, Any]) -> str:
    for key in _TITLE_KEYS:
        value = outline.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_llm_to_outline_schema(
    raw: dict[str, Any] | None,
    *,
    require_sections: bool = True,
) -> dict[str, Any]:
    """Map extracted or generated TO JSON to the canonical llm_to_outline schema."""
    outline = _unwrap_outline(raw or {})
    sections = [_normalize_section(section, idx) for idx, section in enumerate(_pick_sections(outline))]

    if require_sections and not sections:
        top_keys = sorted(outline.keys()) if outline else []
        raise ValueError(
            "Timed Outline extraction produced no sections. "
            "The uploaded file may not contain a recognizable outline structure. "
            f"Top-level keys: {top_keys}"
        )

    normalized: dict[str, Any] = {
        "course_title": _resolve_course_title(outline),
        "course_id": str(outline.get("course_id") or "").strip(),
        "description": str(outline.get("description") or "").strip(),
        "learning_objectives": normalize_learning_objectives(outline.get("learning_objectives") or []),
        "sections": sections,
        "totals": _normalize_totals(outline.get("totals"), sections),
    }

    for passthrough_key in (
        "audience",
        "course_type",
        "topic",
        "category",
        "source_documents",
    ):
        if outline.get(passthrough_key) not in (None, "", []):
            normalized[passthrough_key] = outline[passthrough_key]

    for key, value in outline.items():
        if key.startswith("_") and key not in normalized:
            normalized[key] = value

    return normalized
