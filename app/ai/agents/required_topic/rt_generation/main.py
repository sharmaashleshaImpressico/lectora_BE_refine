"""RT Generation Agent.

Accepts course metadata and produces the initial list of required topics.
This agent is responsible solely for generation — it does not validate or refine.
"""
from __future__ import annotations

import json
import logging

from app.ai.agents.required_topic.models import RTPipelineMetadata
from app.ai.agents.required_topic.config.llm import (
    make_config,
)
from app.ai.agents.required_topic.rt_generation.models import (
    RTGenerationInput,
    RTGenerationOutput,
)
from app.ai.agents.required_topic.rt_generation.prompts import (
    SYSTEM_PROMPT,
)
from semantic_kernel import Kernel

from app.kernel.chat import chat_async

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

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run(self, input_data: RTGenerationInput) -> RTGenerationOutput:
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

        raw = await chat_async(
            self._kernel,
            SYSTEM_PROMPT,
            user_msg,
            config,
            "RT_GEN",
        )
        data = json.loads(raw)

        topics = data.get("required_topics") or []
        if not isinstance(topics, list):
            topics = []
        topics = [str(t).strip() for t in topics if t]

        logger.info("[rt_generation] Generated %d topics", len(topics))
        return RTGenerationOutput(topics=topics)
