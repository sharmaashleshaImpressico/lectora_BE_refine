"""LO Validator Agent.

After objectives are generated, this agent checks them against eight quality
criteria and returns a structured pass/fail report. The validator has no side
effects — it only reads and reports.
"""
from __future__ import annotations

import json
import logging

from app.pipeline.agents.__lo1_learning_objective.Lo_validator.config.llm import (
    make_config,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_validator.models import (
    LOValidationInput,
    LOValidationIssue,
    LOValidationOutput,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_validator.prompts import (
    SYSTEM_PROMPT,
)
from app.pipeline.agents.__lo1_learning_objective.models import CourseMetadata
from app.pipeline.shared_llm_config.llm import chat as llm_chat

logger = logging.getLogger(__name__)


def _build_user_message(objectives: list[str], meta: CourseMetadata) -> str:
    parts: list[str] = ["LEARNING OBJECTIVES TO VALIDATE:"]
    for i, obj in enumerate(objectives, 1):
        parts.append(f"  {i}. {obj}")

    parts.append("\nCOURSE METADATA:")
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
    if meta.course_description:
        parts.append(f"  Description: {meta.course_description}")
    if meta.desired_outcomes:
        parts.append(f"  Desired outcomes: {meta.desired_outcomes}")

    if meta.required_topics:
        parts.append(
            "\nREQUIRED TOPICS — use these to judge whether the objective set broadly represents the course intent. Do not require exact phrase coverage or explicit mention of every subtopic.:"
        )
        for topic in meta.required_topics:
            parts.append(f"  • {topic}")

    return "\n".join(parts)


def _parse_issues(raw_issues: list) -> list[LOValidationIssue]:
    issues: list[LOValidationIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(LOValidationIssue(
            type=str(item.get("type") or ""),
            message=str(item.get("message") or ""),
            affected_objectives=list(item.get("affected_objectives") or []),
            expected_action=str(item.get("expected_action") or ""),
        ))
    return issues


class LOValidatorAgent:
    """Validates a list of learning objectives and returns a pass/fail report."""

    def run(self, input_data: LOValidationInput) -> LOValidationOutput:
        """Call the LLM validator and return a structured report.

        Falls back to a permissive pass if the LLM returns unparseable output so
        the pipeline is never hard-blocked by a validator crash.
        """
        user_msg = _build_user_message(input_data.objectives, input_data.metadata)
        config = make_config()

        logger.info(
            "[Lo_validator] Validating %d objectives", len(input_data.objectives)
        )

        try:
            raw = llm_chat(SYSTEM_PROMPT, user_msg, config, "LO_VALIDATOR")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[Lo_validator] JSON parse error — treating as pass: %s", exc
            )
            return LOValidationOutput(status="pass")
        except Exception:
            logger.exception("[Lo_validator] LLM call failed — treating as pass")
            return LOValidationOutput(status="pass")

        status = str(data.get("status") or "pass").lower().strip()
        if status not in ("pass", "fail"):
            status = "pass"

        raw_issues = data.get("issues") or []
        issues = _parse_issues(raw_issues) if isinstance(raw_issues, list) else []

        # Normalise: status=pass must have no issues; status=fail must have issues.
        if status == "fail" and not issues:
            status = "pass"
        if status == "pass" and issues:
            issues = []

        logger.info(
            "[Lo_validator] Result: %s | issues: %d", status, len(issues)
        )
        return LOValidationOutput(status=status, issues=issues)
