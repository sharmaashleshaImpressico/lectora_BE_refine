"""Deterministic checks driven by ``GENERAL_TIMED_OUTLINE_RULES``."""

from __future__ import annotations

from typing import Any

from app.ai.agents.to_generation_pipeline.to_rule_pack import (
    GENERAL_TIMED_OUTLINE_RULES,
    TO_RULE_PACK_ID,
)

RULE_SOURCE = f"to_rule_pack.{TO_RULE_PACK_ID}"


def _normalize_severity(raw: str) -> str:
    value = (raw or "warning").strip().lower()
    if value in {"blocking", "blocker"}:
        return "blocker"
    if value == "info":
        return "info"
    return "warning"


def _field_present(section: dict[str, Any], field_name: str) -> bool:
    if field_name not in section:
        return False
    value = section.get(field_name)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


class ToOutlineChecks:
    """Validate A0 TO outlines against the general timed-outline rule pack."""

    @staticmethod
    def check_required_fields(shared_state: dict[str, Any]) -> list[dict[str, Any]]:
        rule = GENERAL_TIMED_OUTLINE_RULES.get("required_fields") or {}
        required_fields: list[str] = list(rule.get("fields") or [])
        if not required_fields:
            return []

        severity = _normalize_severity(str(rule.get("severity", "blocking")))
        action = str(rule.get("action") or "regenerate_affected_section")
        outline = shared_state.get("llm_to_outline_classification") or {}
        sections = outline.get("sections") or outline.get("course_outline", {}).get("sections") or []

        issues: list[dict[str, Any]] = []
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_label = section.get("title") or section.get("heading") or f"section_{index + 1}"
            for field_name in required_fields:
                if _field_present(section, field_name):
                    continue
                issues.append(
                    {
                        "field": f"sections[{index}].{field_name}",
                        "expected": f"non-empty {field_name}",
                        "found": repr(section.get(field_name)),
                        "severity": severity,
                        "message": (
                            f"Section {index + 1} ({section_label!r}) is missing required "
                            f"field {field_name!r}."
                        ),
                        "rule_source": RULE_SOURCE,
                        "remediation": action,
                    }
                )
        return issues


def check_to_required_fields(shared_state: dict[str, Any]) -> list[dict[str, Any]]:
    return ToOutlineChecks.check_required_fields(shared_state)
