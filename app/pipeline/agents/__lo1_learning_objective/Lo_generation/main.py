"""LO Generation Agent.

Accepts course metadata and produces the initial list of learning objectives.
This agent is responsible solely for generation — it does not validate or refine.
"""
from __future__ import annotations

import json
import logging

from app.pipeline.agents.__lo1_learning_objective.Lo_generation.config.llm import (
    make_config,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_generation.models import (
    LOGenerationInput,
    LOGenerationOutput,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_generation.prompts import (
    SYSTEM_PROMPT,
)
from app.pipeline.agents.__lo1_learning_objective.models import CourseMetadata
from app.pipeline.shared_llm_config.llm import chat as llm_chat

logger = logging.getLogger(__name__)


def _build_user_message(meta: CourseMetadata) -> str:
    """Assemble the user-turn prompt from all available course metadata."""
    parts: list[str] = []

    if meta.course_title:
        parts.append(f"Course title: {meta.course_title}")
    if meta.course_description:
        parts.append(f"Course description: {meta.course_description}")
    if meta.course_type:
        parts.append(f"Course type: {meta.course_type}")
    if meta.course_duration:
        parts.append(f"Course duration: {meta.course_duration}")
    if meta.target_audience:
        parts.append(f"Target audience: {meta.target_audience}")
    if meta.skill_level:
        parts.append(f"Difficulty level: {meta.skill_level}")
    if meta.desired_outcomes:
        parts.append(f"Desired outcomes: {meta.desired_outcomes}")
    if meta.certification_focus:
        parts.append(f"Certification/compliance focus: {meta.certification_focus}")
    if meta.additional_instructions:
        parts.append(f"Additional instructions: {meta.additional_instructions}")

    # Regeneration context — only present when user is editing existing objectives.
    if meta.current_objectives:
        lines = [
            "\nCURRENT OBJECTIVES (the list the user sees right now — modify these "
            "according to the regeneration guidance below; do not start from scratch):",
        ]
        for i, obj in enumerate(meta.current_objectives, 1):
            lines.append(f"  {i}. {obj}")
        parts.append("\n".join(lines))

    if meta.regeneration_prompt and meta.regeneration_prompt.strip():
        regen = meta.regeneration_prompt.strip()
        count_hint = (
            f" (the user currently has {len(meta.current_objectives)} objectives; "
            "adjust the total accordingly)"
            if meta.current_objectives
            else ""
        )
        parts.append(
            f"REGENERATION GUIDANCE — highest priority{count_hint}: {regen}"
        )

    if meta.required_topics:
        lines = [
            "\nREQUIRED TOPICS — Every generated objective must be traceable to "
            "at least one of these:",
        ]
        for topic in meta.required_topics:
            lines.append(f"  • {topic}")
        lines.append(
            "\nThe learning objective set as a whole should represent the required topics at the appropriate level for the course duration and skill level. Do not force every required topic to appear explicitly in the objectives. Group related topics by learner task and instructional purpose. Avoid creating overloaded objectives that read like compressed topic lists."
        )
        parts.append("\n".join(lines))

    if meta.source_analyses:
        lines = [
            "\nSOURCE ANALYSIS (use this to align objectives to the actual source content):",
        ]
        for sa in meta.source_analyses:
            lines.append(f"\n[{sa.get('source_name', '?')}]")
            if sa.get("extract_hint"):
                lines.append(f"  What to get: {sa['extract_hint']}")
            if sa.get("main_topics"):
                lines.append(f"  Topics: {', '.join(sa['main_topics'])}")
            if sa.get("supports_learning_objectives"):
                lines.append("  Suggested LOs from this source:")
                for lo in sa["supports_learning_objectives"]:
                    lines.append(f"    - {lo}")
            if sa.get("ignore_or_reduce"):
                lines.append(f"  Avoid/reduce: {', '.join(sa['ignore_or_reduce'])}")
        lines.extend([
            "\nGuidance for LO selection:",
            "  - Base objectives on each source's extraction focus and primary topics",
            "  - Do NOT write objectives for topics listed under Avoid/reduce above",
        ])
        parts.append("\n".join(lines))

    return (
        "\n".join(parts)
        or "Generate general learning objectives for this training course."
    )


class LOGenerationAgent:
    """Generates the initial list of learning objectives from course metadata."""

    def run(self, input_data: LOGenerationInput) -> LOGenerationOutput:
        """Call the LLM and return raw objectives.

        Raises:
            json.JSONDecodeError: If the model returns malformed JSON.
            Exception: Propagates any LLM/network error to the caller.
        """
        meta = input_data.metadata
        user_msg = _build_user_message(meta)
        config = make_config()

        logger.info(
            "[Lo_generation] Calling LLM | title=%r | topics=%d | regen=%s",
            meta.course_title,
            len(meta.required_topics),
            bool(meta.regeneration_prompt),
        )

        raw = llm_chat(SYSTEM_PROMPT, user_msg, config, "LO_GEN")
        data = json.loads(raw)

        objectives: list[str] = data.get("learning_objectives") or []
        if not isinstance(objectives, list):
            objectives = []
        objectives = [str(o).strip() for o in objectives if o]

        logger.info("[Lo_generation] Generated %d objectives", len(objectives))
        return LOGenerationOutput(objectives=objectives)
