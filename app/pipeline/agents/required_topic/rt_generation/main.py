"""RT Generation Agent.

Accepts course metadata and produces the initial list of required topics.
This agent is responsible solely for generation — it does not validate or refine.
"""
from __future__ import annotations

import json
import logging
import time

from app.pipeline.agents.required_topic.models import RTPipelineMetadata
from app.pipeline.agents.required_topic.rt_generation.config.llm import (
    make_config,
)
from app.pipeline.agents.required_topic.rt_generation.models import (
    RTGenerationInput,
    RTGenerationOutput,
)
from app.pipeline.agents.required_topic.rt_generation.prompts import (
    SYSTEM_PROMPT,
)
from app.pipeline.shared_llm_config.llm import chat as llm_chat
from app.pipeline.shared_llm_config.tracer import write_span

logger = logging.getLogger(__name__)


def _build_user_message(meta: RTPipelineMetadata) -> str:
    parts: list[str] = []
    if meta.course_title:
        parts.append(f"Course title: {meta.course_title}")
    if meta.course_description:
        parts.append(f"Description: {meta.course_description}")
    if meta.course_type:
        parts.append(f"Course type: {meta.course_type}")
    if meta.course_duration:
        parts.append(f"Duration: {meta.course_duration}")
    if meta.target_audience:
        parts.append(f"Target audience: {meta.target_audience}")
    if meta.skill_level:
        parts.append(f"Skill level: {meta.skill_level}")
    if meta.learner_outcomes:
        parts.append(f"Desired learner outcomes: {meta.learner_outcomes}")
    return (
        "\n".join(parts)
        or "Suggest required topics for a standard regulatory training course."
    )


class RTGenerationAgent:
    """Generates the initial list of required topics from course metadata."""

    def run(self, input_data: RTGenerationInput) -> RTGenerationOutput:
        """Call the LLM and return raw topics.

        Raises:
            json.JSONDecodeError: If the model returns malformed JSON.
            Exception: Propagates any LLM/network error to the caller.
        """
        meta = input_data.metadata
        user_msg = _build_user_message(meta)
        config = make_config()

        logger.info(
            "[rt_generation] Calling LLM | title=%r | type=%r",
            meta.course_title,
            meta.course_type,
        )

        t_start = time.perf_counter()
        _error: str | None = None
        topics: list[str] = []

        try:
            raw = llm_chat(SYSTEM_PROMPT, user_msg, config, "RT_GEN")
            data = json.loads(raw)

            topics = data.get("required_topics") or []
            if not isinstance(topics, list):
                topics = []
            topics = [str(t).strip() for t in topics if t]

            logger.info("[rt_generation] Generated %d topics", len(topics))
            return RTGenerationOutput(topics=topics)
        except Exception as exc:
            _error = str(exc)
            raise
        finally:
            write_span(
                name="RT Generation | generate required topics",
                agent="RT_GEN",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                input_data={
                    "course_title": meta.course_title or None,
                    "course_type": meta.course_type or None,
                    "course_duration": meta.course_duration or None,
                    "target_audience": meta.target_audience or None,
                    "skill_level": meta.skill_level or None,
                },
                output_data={"topics_count": len(topics), "error": _error},
                error=_error,
            )
