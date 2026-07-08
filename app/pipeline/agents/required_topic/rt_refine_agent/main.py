"""RT Refine Agent.

Receives the current topics, the validator's issue report, and course metadata.
Fixes only the flagged topics while preserving everything else.
"""
from __future__ import annotations

import json
import logging
import time

from app.pipeline.agents.required_topic.models import RTPipelineMetadata
from app.pipeline.agents.required_topic.rt_refine_agent.config.llm import (
    make_config,
)
from app.pipeline.agents.required_topic.rt_refine_agent.models import (
    RTRefinementInput,
    RTRefinementOutput,
)
from app.pipeline.agents.required_topic.rt_refine_agent.prompts import (
    SYSTEM_PROMPT,
)
from app.pipeline.agents.required_topic.rt_validator.models import (
    RTValidationIssue,
)
from app.pipeline.shared_llm_config.llm import chat as llm_chat
from app.pipeline.shared_llm_config.tracer import write_span

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

    def run(self, input_data: RTRefinementInput) -> RTRefinementOutput:
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

        t_start = time.perf_counter()
        _output_topics: list[str] = []
        _fell_back = False
        _error: str | None = None

        try:
            try:
                raw = llm_chat(SYSTEM_PROMPT, user_msg, config, "RT_REFINE")
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "[rt_refine_agent] JSON parse error — returning original topics: %s",
                    exc,
                )
                _fell_back = True
                return RTRefinementOutput(topics=list(input_data.topics))
            except Exception:
                logger.exception(
                    "[rt_refine_agent] LLM call failed — returning original topics"
                )
                _fell_back = True
                return RTRefinementOutput(topics=list(input_data.topics))

            topics: list[str] = data.get("required_topics") or []
            if not isinstance(topics, list):
                topics = []
            topics = [str(t).strip() for t in topics if t]

            if not topics:
                logger.warning(
                    "[rt_refine_agent] LLM returned empty list — returning original topics"
                )
                _fell_back = True
                return RTRefinementOutput(topics=list(input_data.topics))

            _output_topics = topics
            logger.info("[rt_refine_agent] Refined to %d topics", len(topics))
            return RTRefinementOutput(topics=topics)
        except Exception as exc:
            _error = str(exc)
            raise
        finally:
            write_span(
                name="RT Refine | fix flagged topics",
                agent="RT_REFINE",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                input_data={
                    "topics_count": len(input_data.topics),
                    "issues_count": len(input_data.issues),
                },
                output_data={
                    "refined_topics_count": len(_output_topics) or len(input_data.topics),
                    "fell_back_to_original": _fell_back,
                    "error": _error,
                },
                error=_error,
            )
