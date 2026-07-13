"""Outline Structure Suggestion Agent.

Called when the user clicks "Suggest structure" while setting outline
preferences during onboarding. Given course metadata (title, description,
type, audience, skill level, objectives), suggests a preferred chapter count
and lesson style with a short rationale.

Langfuse tracing
────────────────
Each run gets a unique run_id (``outline-suggest-<8 hex chars>``). The LLM
call is traced automatically by the shared ``chat()`` wrapper. A parent span
wraps the full agent run; root ``traced_workflow`` flushes on exit.
"""
from __future__ import annotations

import json
import logging
import re
import uuid as _uuid

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.suggest_outline_structure.config.llm import (
    make_config,
)
from app.ai.agents.to_generation_pipeline.suggest_outline_structure.models import (
    OutlineStructureSuggestionInput,
    OutlineStructureSuggestionOutput,
)
from app.ai.agents.to_generation_pipeline.suggest_outline_structure.prompts import (
    SYSTEM_PROMPT,
)
from app.kernel.chat import chat as llm_chat
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)

_DEFAULT_PREFERRED_CHAPTERS = 6
_DEFAULT_LESSON_STYLE = "detailed"
_VALID_LESSON_STYLES = {"short", "detailed"}


def _build_user_message(input_data: OutlineStructureSuggestionInput) -> str:
    lines = [
        f"Course title: {input_data.course_title or '(not provided)'}",
        f"Course description: {input_data.course_description or '(not provided)'}",
        f"Course type: {input_data.course_type or '(not provided)'}",
        f"Target audience: {input_data.target_audience or '(not provided)'}",
        f"Skill level: {input_data.skill_level or '(not provided)'}",
    ]
    if input_data.learning_objectives:
        objectives = "\n".join(f"  - {obj}" for obj in input_data.learning_objectives)
        lines.append(f"Learning objectives:\n{objectives}")
    else:
        lines.append("Learning objectives: (not provided)")
    return "\n".join(lines)


def _strip_markdown_fences(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
    return re.sub(r"\n?```$", "", stripped.rstrip())


def _fallback_output(reason: str) -> OutlineStructureSuggestionOutput:
    return OutlineStructureSuggestionOutput(
        preferred_chapters=_DEFAULT_PREFERRED_CHAPTERS,
        lesson_style=_DEFAULT_LESSON_STYLE,
        reasoning=reason,
    )


def _execute(
    kernel: Kernel, input_data: OutlineStructureSuggestionInput
) -> OutlineStructureSuggestionOutput:
    """Core suggestion logic. Falls back to sensible defaults on any failure."""
    user_msg = _build_user_message(input_data)
    config = make_config()

    logger.info(
        "[suggest_outline_structure_agent] Suggesting outline structure | title=%r",
        input_data.course_title,
    )

    try:
        raw = llm_chat(kernel, SYSTEM_PROMPT, user_msg, config, "SUGGEST_OUTLINE_STRUCTURE")
        parsed = json.loads(_strip_markdown_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning(
            "[suggest_outline_structure_agent] JSON parse error — using defaults: %s", exc
        )
        return _fallback_output("Using default structure — could not parse AI suggestion.")
    except Exception:
        logger.exception(
            "[suggest_outline_structure_agent] LLM call failed — using defaults"
        )
        return _fallback_output("Using default structure — AI suggestion unavailable.")

    if not isinstance(parsed, dict):
        logger.warning("[suggest_outline_structure_agent] LLM returned non-object — using defaults")
        return _fallback_output("Using default structure — could not parse AI suggestion.")

    preferred_chapters = parsed.get("preferredChapters")
    if not isinstance(preferred_chapters, int) or not (1 <= preferred_chapters <= 20):
        preferred_chapters = _DEFAULT_PREFERRED_CHAPTERS

    lesson_style = parsed.get("lessonStyle")
    if lesson_style not in _VALID_LESSON_STYLES:
        lesson_style = _DEFAULT_LESSON_STYLE

    reasoning = parsed.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = "Recommended based on the provided course details."

    logger.info("[suggest_outline_structure_agent] Suggestion complete")
    return OutlineStructureSuggestionOutput(
        preferred_chapters=preferred_chapters,
        lesson_style=lesson_style,
        reasoning=reasoning.strip(),
    )


class OutlineStructureSuggestionAgent:
    """Suggests a preferred chapter count and lesson style for a course."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    def run(
        self, input_data: OutlineStructureSuggestionInput
    ) -> OutlineStructureSuggestionOutput:
        run_id = f"outline-suggest-{_uuid.uuid4().hex[:8]}"
        doc_name = input_data.course_title or "outline-suggestion"
        with traced_workflow(
            "suggest_outline_structure",
            run_id=run_id,
            doc_name=doc_name,
            input_data={
                "course_title": input_data.course_title,
                "course_type": input_data.course_type,
                "skill_level": input_data.skill_level,
            },
        ):
            return _execute(self._kernel, input_data)
