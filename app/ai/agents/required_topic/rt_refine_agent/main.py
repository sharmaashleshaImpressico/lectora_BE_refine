"""RT Refine Agent.

Receives the current topics, the validator's issue report, and course metadata.
Fixes only the flagged topics while preserving everything else.
"""
from __future__ import annotations

import json
import logging

from app.ai.agents.required_topic.models import RTPipelineMetadata
from app.ai.agents.required_topic.config.llm import (
    make_config,
)
from app.ai.agents.required_topic.rt_refine_agent.models import (
    RTRefinementInput,
    RTRefinementOutput,
)
from app.ai.agents.required_topic.rt_refine_agent.prompts import (
    SYSTEM_PROMPT,
)
from app.ai.agents.required_topic.rt_validator.models import (
    RTValidationIssue,
)
from semantic_kernel import Kernel

from app.kernel.chat import chat_async

logger = logging.getLogger(__name__)


def _build_user_message(
    topics: list[str],
    issues: list[RTValidationIssue],
    meta: RTPipelineMetadata,
) -> str:
    parts: list[str] = ["CURRENT REQUIRED TOPICS:"]
    for i, topic in enumerate(topics, 1):
        parts.append(f"  {i}. {topic}")

    parts.append("\nISSUES TO FIX:")
    for issue in issues:
        parts.append(
            f"  • [{issue.type}] {issue.message}"
            + (
                f"\n    Affected: {'; '.join(issue.affected_topics)}"
                if issue.affected_topics
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
    if meta.learner_outcomes:
        parts.append(f"  Desired learner outcomes: {meta.learner_outcomes}")

    return "\n".join(parts)


class RTRefinementAgent:
    """Refines flagged required topics while preserving well-defined ones."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run(self, input_data: RTRefinementInput) -> RTRefinementOutput:
        """Apply targeted fixes and return the refined topics list.

        Falls back to the original topics if the LLM returns unparseable output
        so the pipeline is never hard-blocked by a refiner crash.
        """
        user_msg = _build_user_message(
            input_data.topics, input_data.issues, input_data.metadata
        )
        config = make_config()

        logger.info(
            "[rt_refine_agent] Refining %d topics to fix %d issue(s)",
            len(input_data.topics),
            len(input_data.issues),
        )

        try:
            raw = await chat_async(
                self._kernel,
                SYSTEM_PROMPT,
                user_msg,
                config,
                "RT_REFINE",
            )
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[rt_refine_agent] JSON parse error — returning original topics: %s",
                exc,
            )
            return RTRefinementOutput(topics=list(input_data.topics))
        except Exception:
            logger.exception(
                "[rt_refine_agent] LLM call failed — returning original topics"
            )
            return RTRefinementOutput(topics=list(input_data.topics))

        topics: list[str] = data.get("required_topics") or []
        if not isinstance(topics, list):
            topics = []
        topics = [str(t).strip() for t in topics if t]

        if not topics:
            logger.warning(
                "[rt_refine_agent] LLM returned empty list — returning original topics"
            )
            return RTRefinementOutput(topics=list(input_data.topics))

        logger.info("[rt_refine_agent] Refined to %d topics", len(topics))
        return RTRefinementOutput(topics=topics)
