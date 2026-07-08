"""LO Refine Agent.

Receives the current objectives, the validator's issue report, and course
metadata. Fixes only the flagged objectives while preserving everything else.
"""
from __future__ import annotations

import json
import logging

from app.pipeline.agents.__lo1_learning_objective.Lo_refine_agent.config.llm import (
    make_config,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_refine_agent.models import (
    LORefinementInput,
    LORefinementOutput,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_refine_agent.prompts import (
    SYSTEM_PROMPT,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_validator.models import (
    LOValidationIssue,
)
from app.pipeline.agents.__lo1_learning_objective.models import CourseMetadata
from app.pipeline.shared_llm_config.llm import chat as llm_chat

logger = logging.getLogger(__name__)


def _build_user_message(
    objectives: list[str],
    issues: list[LOValidationIssue],
    meta: CourseMetadata,
) -> str:
    parts: list[str] = ["CURRENT OBJECTIVES:"]
    for i, obj in enumerate(objectives, 1):
        parts.append(f"  {i}. {obj}")

    parts.append("\nISSUES TO FIX:")
    for issue in issues:
        parts.append(
            f"  • [{issue.type}] {issue.message}"
            + (
                f"\n    Affected: {'; '.join(issue.affected_objectives)}"
                if issue.affected_objectives
                else ""
            )
            + (
                f"\n    Action: {issue.expected_action}"
                if issue.expected_action
                else ""
            )
        )

    parts.append("\nCOURSE METADATA (for alignment):")
    if meta.course_title:
        parts.append(f"  Title: {meta.course_title}")
    if meta.course_type:
        parts.append(f"  Type: {meta.course_type}")
    if meta.course_duration:
        parts.append(f"  Duration: {meta.course_duration}")
    if meta.target_audience:
        parts.append(f"  Target audience: {meta.target_audience}")
    if meta.skill_level:
        parts.append(f"  Skill level: {meta.skill_level}")

    if meta.required_topics:
        parts.append("\nREQUIRED TOPICS — use these to preserve broad course intent after refinement. Do not force every topic or subtopic to appear explicitly in the objectives.:")
        for topic in meta.required_topics:
            parts.append(f"  • {topic}")

    return "\n".join(parts)


class LORefinementAgent:
    """Refines flagged learning objectives while preserving good ones."""

    def run(self, input_data: LORefinementInput) -> LORefinementOutput:
        """Apply targeted fixes and return the refined objective list.

        Falls back to the original objectives if the LLM returns unparseable
        output so the pipeline is never hard-blocked by a refiner crash.
        """
        user_msg = _build_user_message(
            input_data.objectives, input_data.issues, input_data.metadata
        )
        config = make_config()

        logger.info(
            "[Lo_refine_agent] Refining %d objectives to fix %d issue(s)",
            len(input_data.objectives),
            len(input_data.issues),
        )

        try:
            raw = llm_chat(SYSTEM_PROMPT, user_msg, config, "LO_REFINE")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[Lo_refine_agent] JSON parse error — returning original objectives: %s",
                exc,
            )
            return LORefinementOutput(objectives=list(input_data.objectives))
        except Exception:
            logger.exception(
                "[Lo_refine_agent] LLM call failed — returning original objectives"
            )
            return LORefinementOutput(objectives=list(input_data.objectives))

        objectives: list[str] = data.get("learning_objectives") or []
        if not isinstance(objectives, list):
            objectives = []
        objectives = [str(o).strip() for o in objectives if o]

        if not objectives:
            logger.warning(
                "[Lo_refine_agent] LLM returned empty list — returning original objectives"
            )
            return LORefinementOutput(objectives=list(input_data.objectives))

        logger.info("[Lo_refine_agent] Refined to %d objectives", len(objectives))
        return LORefinementOutput(objectives=objectives)
