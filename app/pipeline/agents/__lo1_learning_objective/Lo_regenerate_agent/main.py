"""LO Regeneration Agent.

Called exclusively when the user clicks "Regenerate" on existing learning
objectives.  Receives the current objectives and the user's free-text prompt,
and returns a revised list.

Key differences from LOGenerationAgent:
- No LO-generation system prompt — the LLM receives only the user's intent
  and the current list, so existing validated structure is preserved.
- Does not use course metadata for generation; metadata is included only as
  lightweight alignment context.
- Falls back to the original objectives on any parse or LLM error.

Langfuse tracing
────────────────
Each run gets a unique run_id (``lo-regen-<8 hex chars>``).  The LLM call is
traced automatically by the shared ``chat()`` wrapper.  A parent span wraps
the full agent run and ``flush_langfuse()`` is called before returning.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from app.pipeline.agents.__lo1_learning_objective.Lo_regenerate_agent.config.llm import (
    make_config,
)
from app.pipeline.agents.__lo1_learning_objective.Lo_regenerate_agent.models import (
    LORegenerationInput,
    LORegenerationOutput,
)
from app.pipeline.shared_llm_config.llm import chat as llm_chat
from app.pipeline.shared_llm_config.tracer import (
    flush_langfuse,
    set_run_context,
    span_context,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an instructional design assistant. The user wants to revise an existing \
set of learning objectives for their course.

RULES:
1. Apply ONLY the changes described in the user's instruction below.
2. Keep every objective that is not affected by the instruction as-is.
3. Every objective must begin with a measurable Bloom's Taxonomy action verb.
4. Do not add, remove, or reorder objectives unless the instruction explicitly asks for it.
5. Return the full revised list — including unchanged objectives.

Return a JSON object with this exact structure:
{"learning_objectives": ["objective 1", "objective 2", ...]}\
"""


def _build_user_message(input_data: LORegenerationInput) -> str:
    parts: list[str] = ["CURRENT LEARNING OBJECTIVES:"]
    for i, obj in enumerate(input_data.current_objectives, 1):
        parts.append(f"  {i}. {obj}")

    parts.append(f"\nUSER INSTRUCTION:\n{input_data.regeneration_prompt.strip()}")

    context_parts: list[str] = []
    if input_data.course_title:
        context_parts.append(f"Course title: {input_data.course_title}")
    if input_data.course_type:
        context_parts.append(f"Course type: {input_data.course_type}")
    if input_data.course_duration:
        context_parts.append(f"Duration: {input_data.course_duration}")
    if input_data.target_audience:
        context_parts.append(f"Target audience: {input_data.target_audience}")
    if input_data.skill_level:
        context_parts.append(f"Skill level: {input_data.skill_level}")

    if context_parts:
        parts.append("\nCOURSE CONTEXT (for alignment only — do not regenerate from scratch):")
        parts.extend(f"  {c}" for c in context_parts)

    return "\n".join(parts)


def _build_input_data(input_data: LORegenerationInput) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "course_title": input_data.course_title or None,
        "course_type": input_data.course_type or None,
        "course_duration": input_data.course_duration or None,
        "target_audience": input_data.target_audience or None,
        "skill_level": input_data.skill_level or None,
        "current_objectives_count": len(input_data.current_objectives),
        "regeneration_prompt_length": len(input_data.regeneration_prompt.strip()),
    }
    return {k: v for k, v in raw.items() if v not in (None, "", 0)}


def _build_output_data(
    result: LORegenerationOutput | None,
    *,
    error: str | None,
    fell_back: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"fell_back_to_original": fell_back}
    if result is not None:
        out["objectives_count"] = len(result.objectives)
    if error:
        out["error"] = error
    return out


def _execute(input_data: LORegenerationInput) -> tuple[LORegenerationOutput, str | None, bool]:
    """Core regeneration logic. Returns (result, error_message, fell_back)."""
    if not input_data.current_objectives:
        logger.warning("[Lo_regenerate_agent] No current objectives supplied — returning empty")
        return LORegenerationOutput(objectives=[]), None, False

    if not input_data.regeneration_prompt.strip():
        logger.warning("[Lo_regenerate_agent] Empty regeneration prompt — returning originals")
        return LORegenerationOutput(objectives=list(input_data.current_objectives)), None, True

    user_msg = _build_user_message(input_data)
    config = make_config()

    logger.info(
        "[Lo_regenerate_agent] Regenerating %d objectives | prompt_length=%d",
        len(input_data.current_objectives),
        len(input_data.regeneration_prompt),
    )

    try:
        raw = llm_chat(_SYSTEM_PROMPT, user_msg, config, "LO_REGEN")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[Lo_regenerate_agent] JSON parse error — returning original objectives: %s", exc
        )
        return (
            LORegenerationOutput(objectives=list(input_data.current_objectives)),
            str(exc),
            True,
        )
    except Exception as exc:
        logger.exception("[Lo_regenerate_agent] LLM call failed — returning original objectives")
        return (
            LORegenerationOutput(objectives=list(input_data.current_objectives)),
            str(exc),
            True,
        )

    objectives: list[str] = data.get("learning_objectives") or []
    if not isinstance(objectives, list):
        objectives = []
    objectives = [str(o).strip() for o in objectives if o]

    if not objectives:
        logger.warning(
            "[Lo_regenerate_agent] LLM returned empty list — returning original objectives"
        )
        return (
            LORegenerationOutput(objectives=list(input_data.current_objectives)),
            "LLM returned empty objectives list",
            True,
        )

    logger.info("[Lo_regenerate_agent] Regenerated to %d objectives", len(objectives))
    return LORegenerationOutput(objectives=objectives), None, False


class LORegenerationAgent:
    """Revises existing learning objectives based on a user prompt."""

    def run(self, input_data: LORegenerationInput) -> LORegenerationOutput:
        run_id = f"lo-regen-{_uuid.uuid4().hex[:8]}"
        doc_name = (input_data.course_title or "").strip() or "lo-regen"
        set_run_context(run_id, doc_name)

        try:
            with span_context(
                name="LO Regeneration | revise objectives",
                agent="LO_REGEN",
                input_data=_build_input_data(input_data),
            ):
                result, _error, _fell_back = _execute(input_data)
                return result
        finally:
            flush_langfuse()
