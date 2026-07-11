"""RT Validator Agent.

After topics are generated, this agent checks them against five quality
criteria and returns a structured pass/fail report. The validator has no side
effects — it only reads and reports.
"""
from __future__ import annotations

import json
import logging

from app.ai.agents.required_topic.models import RTPipelineMetadata
from app.ai.agents.required_topic.config.llm import (
    make_config,
)
from app.ai.agents.required_topic.rt_validator.models import (
    RTValidationInput,
    RTValidationIssue,
    RTValidationOutput,
)
from app.ai.agents.required_topic.rt_validator.prompts import (
    SYSTEM_PROMPT,
)
from semantic_kernel import Kernel

from app.kernel.chat import chat_async

logger = logging.getLogger(__name__)


def _build_user_message(topics: list[str], meta: RTPipelineMetadata) -> str:
    parts: list[str] = ["REQUIRED TOPICS TO VALIDATE:"]
    for i, topic in enumerate(topics, 1):
        parts.append(f"  {i}. {topic}")

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
    if meta.learner_outcomes:
        parts.append(f"  Desired learner outcomes: {meta.learner_outcomes}")

    return "\n".join(parts)


def _parse_issues(raw_issues: list) -> list[RTValidationIssue]:
    issues: list[RTValidationIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(RTValidationIssue(
            type=str(item.get("type") or ""),
            message=str(item.get("message") or ""),
            affected_topics=list(item.get("affected_topics") or []),
            expected_action=str(item.get("expected_action") or ""),
        ))
    return issues


class RTValidatorAgent:
    """Validates a required topics list and returns a pass/fail report."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run(self, input_data: RTValidationInput) -> RTValidationOutput:
        """Call the LLM validator and return a structured report.

        Falls back to a permissive pass if the LLM returns unparseable output
        so the pipeline is never hard-blocked by a validator crash.
        """
        user_msg = _build_user_message(input_data.topics, input_data.metadata)
        config = make_config()

        logger.info(
            "[rt_validator] Validating %d topics", len(input_data.topics)
        )

        try:
            raw = await chat_async(
                self._kernel,
                SYSTEM_PROMPT,
                user_msg,
                config,
                "RT_VALIDATOR",
            )
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[rt_validator] JSON parse error — treating as pass: %s", exc
            )
            return RTValidationOutput(status="pass")
        except Exception:
            logger.exception("[rt_validator] LLM call failed — treating as pass")
            return RTValidationOutput(status="pass")

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

        logger.info("[rt_validator] Result: %s | issues: %d", status, len(issues))
        return RTValidationOutput(status=status, issues=issues)
