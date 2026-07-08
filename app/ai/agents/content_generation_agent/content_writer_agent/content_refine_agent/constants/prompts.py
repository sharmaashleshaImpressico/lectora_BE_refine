"""Prompt strings for the content refinement agent."""

from __future__ import annotations

import json
from typing import Any

REFINEMENT_SYSTEM_PROMPT: str = (
    "You are the Content Refinement agent for generated course study guides. "
    "Revise ONLY the provided sections so they pass Stage-2 validation. "
    "Preserve compliant sections unchanged. "
    "Return ONLY valid JSON matching the response schema exactly."
)

REFINEMENT_USER_PREAMBLE: str = (
    "Refine the existing generated content below to resolve the validation issues. "
    "Do NOT regenerate the course from scratch. "
    "Keep each section heading unchanged unless an issue explicitly requires a heading fix. "
    "Preserve section order and metadata fields outside body_paragraphs."
)

REFINEMENT_RESPONSE_SCHEMA: str = """
{
  "sections": [
    {
      "heading": "<exact existing heading>",
      "body_paragraphs": [
        { "type": "text", "content": "..." }
      ]
    }
  ]
}
"""


def _get_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def format_validation_feedback(report: Any) -> str:
    """Format validation issues into refinement instructions."""
    buckets: dict[str, list[str]] = {"blocker": [], "critical": [], "warning": []}
    for issue in _get_value(report, "issues", []) or []:
        field = str(_get_value(issue, "field", "?") or "?")
        message = str(_get_value(issue, "message", "") or "").strip()
        rule_source = str(_get_value(issue, "rule_source", "?") or "?")
        severity = str(_get_value(issue, "severity", "warning") or "warning")
        failure_reason = str(_get_value(issue, "failure_reason", "") or "").strip()
        remediation = str(_get_value(issue, "remediation", "") or "").strip()
        detail = f"  - [{field}] {message} (rule: {rule_source})"
        if failure_reason:
            detail += f"\n    Why: {failure_reason}"
        if remediation:
            detail += f"\n    Fix: {remediation}"
        buckets.setdefault(severity, []).append(detail)

    lines: list[str] = []
    for label, key in (
        ("Blockers (must fix):", "blocker"),
        ("Critical issues (must address):", "critical"),
        ("Warnings (please address):", "warning"),
    ):
        if buckets.get(key):
            lines.append(label)
            lines.extend(buckets[key])
    return "\n".join(lines)


def build_refinement_user_message(
    *,
    report: Any,
    sections_payload: list[dict[str, Any]],
    generation_context: dict[str, Any],
) -> str:
    """Build the LLM user message for in-place content refinement."""
    issue_feedback = format_validation_feedback(report).strip()
    summary = str(_get_value(report, "message", "") or "").strip()
    status = str(_get_value(report, "status", "") or "").strip()
    blockers = int(_get_value(report, "blockers", 0) or 0)
    criticals = int(_get_value(report, "criticals", 0) or 0)
    warnings = int(_get_value(report, "warnings", 0) or 0)

    lines = [
        REFINEMENT_USER_PREAMBLE,
        (
            f"Current validation status: {status or 'unknown'} "
            f"(blockers={blockers}, criticals={criticals}, warnings={warnings})."
        ),
    ]
    if summary:
        lines.append(f"Validator summary: {summary}")
    if issue_feedback:
        lines.append(issue_feedback)

    lines.extend(
        [
            "",
            "Generation context (preserve tone, audience, and rule-pack intent):",
            json.dumps(generation_context, ensure_ascii=False, indent=2),
            "",
            "Sections to refine (update body_paragraphs only where needed):",
            json.dumps({"sections": sections_payload}, ensure_ascii=False, indent=2),
            "",
            "Response schema:",
            REFINEMENT_RESPONSE_SCHEMA.strip(),
        ]
    )
    return "\n".join(lines)
