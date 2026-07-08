"""
Content Validation (Stage 2) — pure, kernel-based; no ``shared_state.json``.

Validates A2 generated content against the active rule pack BEFORE the
study guide DOCX is rendered. Validation is split into:

  1. Deterministic validation — structure, emptiness, counts, compliance scans
  2. AI-based validation — tone, audience, style, subjective quality

``context`` is a plain dict assembled by the caller (the content generation
orchestrator) carrying whatever course metadata the checks need — see
``run_deterministic_validation``/``run_ai_validation`` for the recognized keys
(at minimum: ``extracted_inputs.learning_objectives``, ``course_title``,
``course_audience``, ``course_difficulty``, ``special_instructions``).
"""

from __future__ import annotations

import logging
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.content_generation_agent.models import (
    A2Output,
    S2Status,
    S2ValidationReport,
    ValidationIssue,
)
from app.ai.agents.content_generation_agent.shared.s2_refine_routing import (
    s2_content_refine_routing_reason,
    s2_requires_content_refine,
)

from .ai_validation import run_ai_validation
from .deterministic import run_deterministic_validation

logger = logging.getLogger(__name__)


def _filter_sections_for_lesson(sections: list[dict], lesson_title: str | None) -> list[dict]:
    """Return only generated sections belonging to one TO lesson."""
    normalized = str(lesson_title or "").strip()
    if not normalized:
        return sections
    return [
        section
        for section in sections
        if str(section.get("outline_lesson") or "").strip() == normalized
    ]


def validate_content(
    kernel: Kernel,
    *,
    sections: list[dict],
    a2_output: dict[str, Any] | A2Output,
    rule_pack: dict[str, Any],
    context: dict[str, Any],
    run_id: str,
    phase: str = "full",
    lesson_title: str | None = None,
) -> S2ValidationReport:
    """Run deterministic + AI-based content validation and return a typed report."""
    logger.info(
        "[S2] Running %s validation%s...",
        phase,
        f" (lesson={lesson_title!r})" if lesson_title else "",
    )

    a2_dict = (
        a2_output.model_dump(mode="json") if isinstance(a2_output, A2Output) else dict(a2_output)
    )
    if a2_dict.get("status") not in ("complete", "partial"):
        issue = ValidationIssue(
            field="a2_output.status",
            expected="'complete' or 'partial'",
            found=a2_dict.get("status", "missing"),
            severity="blocker",
            message="A2 must complete before S2 validation.",
            rule_source="pipeline",
        )
        return S2ValidationReport(
            status=S2Status.blocked,
            run_id=run_id,
            message="A2 output not found or incomplete. Cannot validate.",
            issues=[issue],
            blockers=1,
            phase=phase,
            lesson_title=lesson_title,
        )

    target_sections = sections
    if lesson_title:
        target_sections = _filter_sections_for_lesson(sections, lesson_title)
        if not target_sections:
            issue = ValidationIssue(
                field="a2_output.sections.lesson",
                expected=f"sections for lesson {lesson_title!r}",
                found=0,
                severity="blocker",
                message=(
                    f"No generated sections found for lesson {lesson_title!r}. "
                    "Content generation must produce lesson output before S2 can validate it."
                ),
                rule_source="pipeline",
            )
            return S2ValidationReport(
                status=S2Status.blocked,
                run_id=run_id,
                message=f"Lesson {lesson_title!r} has no generated sections.",
                issues=[issue],
                blockers=1,
                phase=phase,
                lesson_title=lesson_title,
            )

    scoped_a2_output = dict(a2_dict)
    if lesson_title:
        scoped_a2_output = {**a2_dict, "sections": target_sections}

    logger.info(
        "[S2] Validating A2 content against rule pack: %s %s",
        rule_pack.get("family"),
        rule_pack.get("version"),
    )

    raw_issues = run_deterministic_validation(
        phase=phase,
        scoped_a2_output=scoped_a2_output,
        sections=target_sections,
        a2_output=a2_dict,
        shared_state=context,
        rule_pack=rule_pack,
    )

    logger.info("[S2][ai] Running AI-based content validation...")
    raw_issues.extend(
        run_ai_validation(
            kernel,
            sections=target_sections,
            rule_pack=rule_pack,
            context=context,
            phase=phase,
            lesson_title=lesson_title,
        )
    )

    all_issues: list[ValidationIssue] = [ValidationIssue.model_validate(i) for i in raw_issues]

    blockers = [i for i in all_issues if i.severity == "blocker"]
    criticals = [i for i in all_issues if i.severity == "critical"]
    warnings = [i for i in all_issues if i.severity == "warning"]
    infos = [i for i in all_issues if i.severity == "info"]

    if blockers:
        status = S2Status.blocked
    elif criticals or warnings:
        status = S2Status.pass_with_warnings
    else:
        status = S2Status.pass_

    logger.info("[S2] Validation complete: %s", status.value.upper())
    logger.info(
        "     Blockers: %s  |  Criticals: %s  |  Warnings: %s  |  Info: %s",
        len(blockers),
        len(criticals),
        len(warnings),
        len(infos),
    )

    blocked_msg = None
    if blockers:
        blocked_msg = (
            f"{len(blockers)} blocker(s): study_guide.docx will not be built."
            if phase != "lesson"
            else f"{len(blockers)} blocker(s) found during lesson checkpoint validation."
        )
    elif criticals:
        blocked_msg = f"{len(criticals)} critical(s): mandatory review required before publishing."

    report = S2ValidationReport(
        status=status,
        run_id=run_id,
        issues=all_issues,
        blockers=len(blockers),
        criticals=len(criticals),
        warnings=len(warnings),
        infos=len(infos),
        report_path=None,
        message=blocked_msg,
        lesson_title=lesson_title,
        phase=phase,
    )

    routing_reason = s2_content_refine_routing_reason(report)
    if s2_requires_content_refine(report):
        logger.warning("[S2] Refine routing: %s", routing_reason)
    else:
        logger.info("[S2] Refine routing: %s", routing_reason)

    return report


__all__ = ["validate_content"]
