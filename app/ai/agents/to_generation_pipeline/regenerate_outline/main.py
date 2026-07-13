"""TO Regeneration Agent.

Called when the user clicks "Revise with AI" in the three-panel view.
Receives the current Training Outline JSON and a user revision prompt,
and returns a revised outline in place — without re-running A0 or
regenerating from source documents.

Langfuse tracing
────────────────
Each run gets a unique run_id (``to-regen-<8 hex chars>``).  The LLM call is
traced automatically by the shared ``chat()`` wrapper.  A parent span wraps
the full agent run; root ``traced_workflow`` flushes on exit.
"""
from __future__ import annotations

import json
import logging
import re
import uuid as _uuid
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.to_generation_pipeline.regenerate_outline.config.llm import make_config
from app.ai.agents.to_generation_pipeline.regenerate_outline.models import (
    TORegenerationInput,
    TORegenerationOutput,
)
from app.ai.agents.to_generation_pipeline.regenerate_outline.prompts import SYSTEM_PROMPT
from app.kernel.chat import chat as llm_chat
from app.tracing import traced_workflow

logger = logging.getLogger(__name__)


def _build_user_message(input_data: TORegenerationInput) -> str:
    current_to_json = json.dumps(input_data.current_to, indent=2)
    return (
        f"Current Training Outline:\n{current_to_json}\n\n"
        f"---\n\n"
        f"Revision instructions:\n{input_data.revision_prompt.strip()}"
    )


def _strip_markdown_fences(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
    return re.sub(r"\n?```$", "", stripped.rstrip())


def _section_count(current_to: dict[str, Any]) -> int:
    sections = current_to.get("sections", current_to.get("modules", []))
    return len(sections) if isinstance(sections, list) else 0


def _course_name(current_to: dict[str, Any]) -> str:
    for key in ("course_name", "courseName", "title", "name"):
        value = current_to.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_input_data(input_data: TORegenerationInput) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "course_name": _course_name(input_data.current_to) or None,
        "section_count": _section_count(input_data.current_to),
        "revision_prompt_length": len(input_data.revision_prompt.strip()),
    }
    return {k: v for k, v in raw.items() if v not in (None, "", 0)}


def _build_output_data(
    result: TORegenerationOutput | None,
    *,
    error: str | None,
    fell_back: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"fell_back_to_original": fell_back}
    if result is not None:
        out["section_count"] = _section_count(result.to)
    if error:
        out["error"] = error
    return out


def _execute(kernel: Kernel, input_data: TORegenerationInput) -> tuple[TORegenerationOutput, str | None, bool]:
    """Core revision logic. Returns (result, error_message, fell_back)."""
    if not input_data.current_to:
        logger.warning("[regenerate_to_agent] No current TO supplied — returning empty")
        return TORegenerationOutput(to={}), None, False

    if not input_data.revision_prompt.strip():
        logger.warning("[regenerate_to_agent] Empty revision prompt — returning original TO")
        return TORegenerationOutput(to=dict(input_data.current_to)), None, True

    user_msg = _build_user_message(input_data)
    config = make_config()

    logger.info(
        "[regenerate_to_agent] Revising TO | prompt_length=%d | sections=%d",
        len(input_data.revision_prompt),
        _section_count(input_data.current_to),
    )

    try:
        raw = llm_chat(kernel, SYSTEM_PROMPT, user_msg, config, "REVISE_TO")
        revised_to = json.loads(_strip_markdown_fences(raw))
    except json.JSONDecodeError as exc:
        logger.warning(
            "[regenerate_to_agent] JSON parse error — returning original TO: %s", exc
        )
        return TORegenerationOutput(to=dict(input_data.current_to)), str(exc), True
    except Exception as exc:
        logger.exception("[regenerate_to_agent] LLM call failed — returning original TO")
        return TORegenerationOutput(to=dict(input_data.current_to)), str(exc), True

    if not isinstance(revised_to, dict):
        logger.warning("[regenerate_to_agent] LLM returned non-object — returning original TO")
        return (
            TORegenerationOutput(to=dict(input_data.current_to)),
            "LLM returned non-object JSON",
            True,
        )

    logger.info("[regenerate_to_agent] Revision complete")
    return TORegenerationOutput(to=revised_to), None, False


class TORegenerationAgent:
    """Revises an existing Training Outline based on a user prompt."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    def run(self, input_data: TORegenerationInput) -> TORegenerationOutput:
        run_id = f"to-regen-{_uuid.uuid4().hex[:8]}"
        doc_name = _course_name(input_data.current_to) or "to-regen"
        with traced_workflow(
            "topic_outline_regenerate",
            run_id=run_id,
            doc_name=doc_name,
            input_data=_build_input_data(input_data),
        ):
            result, _error, _fell_back = _execute(self._kernel, input_data)
            return result
