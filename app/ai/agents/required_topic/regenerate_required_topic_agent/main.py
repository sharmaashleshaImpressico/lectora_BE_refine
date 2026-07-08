"""RT Regeneration Agent.

Called exclusively when the user clicks "Regenerate" on existing required topics.
Receives the current topics and the user's free-text prompt, and returns a
revised list.

Key differences from RTGenerationAgent:
- No RT-generation system prompt — the LLM receives only the user's intent
  and the current list, so existing validated structure is preserved.
- Does not run the full generate → validate → repair pipeline.
- Course metadata is not used — only the current topic list and user prompt are sent.
- Falls back to the original topics on any parse or LLM error.

Langfuse tracing
────────────────
Each run gets a unique run_id (``rt-regen-<8 hex chars>``).  The LLM call is
traced automatically by the shared ``chat()`` wrapper.  A parent span wraps
the full agent run and ``flush_langfuse()`` is called before returning.
"""
from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from typing import Any

from app.ai.agents.required_topic.config.llm import (
    make_config,
)
from app.ai.agents.required_topic.regenerate_required_topic_agent.models import (
    RTRegenerationInput,
    RTRegenerationOutput,
)
from semantic_kernel import Kernel

from app.kernel.chat import chat_async
from app.ai.shared_llm_config.tracer import (
    flush_langfuse,
    set_run_context,
    write_span,
)

logger = logging.getLogger(__name__)

_LANGFUSE_DOC_NAME = "rt-regen"

_SYSTEM_PROMPT = """\
You are an instructional design assistant. The user wants to revise an existing \
set of required course topics.

RULES:
1. Apply ONLY the changes described in the user's instruction below.
2. Keep every topic that is not affected by the instruction as-is.
3. Each topic must be a specific, concrete instructional focus (5–15 words).
4. Do not add, remove, or reorder topics unless the instruction explicitly asks for it.
5. Return the full revised list — including unchanged topics.

Return a JSON object with this exact structure:
{"required_topics": ["Topic 1", "Topic 2", ...]}\
"""


def _build_user_message(input_data: RTRegenerationInput) -> str:
    parts: list[str] = ["CURRENT REQUIRED TOPICS:"]
    for i, topic in enumerate(input_data.current_topics, 1):
        parts.append(f"  {i}. {topic}")

    parts.append(
        f"\nUSER INSTRUCTION:\n{input_data.regeneration_prompt.strip()}")
    return "\n".join(parts)


def _build_input_data(input_data: RTRegenerationInput) -> dict[str, Any]:
    return {
        "current_topics_count": len(input_data.current_topics),
        "regeneration_prompt_length": len(input_data.regeneration_prompt.strip()),
    }


def _build_output_data(
    result: RTRegenerationOutput | None,
    *,
    error: str | None,
    fell_back: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"fell_back_to_original": fell_back}
    if result is not None:
        out["topics_count"] = len(result.topics)
    if error:
        out["error"] = error
    return out


async def _execute(
    kernel: Kernel,
    input_data: RTRegenerationInput,
) -> tuple[RTRegenerationOutput, str | None, bool]:
    """Core regeneration logic. Returns (result, error_message, fell_back)."""
    if not input_data.current_topics:
        logger.warning(
            "[rt_regenerate] No current topics supplied — returning empty")
        return RTRegenerationOutput(topics=[]), None, False

    if not input_data.regeneration_prompt.strip():
        logger.warning(
            "[rt_regenerate] Empty regeneration prompt — returning originals")
        return RTRegenerationOutput(topics=list(input_data.current_topics)), None, True

    user_msg = _build_user_message(input_data)
    config = make_config()

    logger.info(
        "[rt_regenerate] Regenerating %d topics | prompt_length=%d",
        len(input_data.current_topics),
        len(input_data.regeneration_prompt),
    )

    try:
        raw = await chat_async(kernel, _SYSTEM_PROMPT, user_msg, config, "RT_REGEN")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[rt_regenerate] JSON parse error — returning original topics: %s", exc
        )
        return RTRegenerationOutput(topics=list(input_data.current_topics)), str(exc), True
    except Exception as exc:
        logger.exception(
            "[rt_regenerate] LLM call failed — returning original topics")
        return RTRegenerationOutput(topics=list(input_data.current_topics)), str(exc), True

    topics: list[str] = data.get("required_topics") or []
    if not isinstance(topics, list):
        topics = []
    topics = [str(t).strip() for t in topics if t]

    if not topics:
        logger.warning(
            "[rt_regenerate] LLM returned empty list — returning original topics")
        return (
            RTRegenerationOutput(topics=list(input_data.current_topics)),
            "LLM returned empty topics list",
            True,
        )

    logger.info("[rt_regenerate] Regenerated to %d topics", len(topics))
    return RTRegenerationOutput(topics=topics), None, False


class RTRegenerationAgent:
    """Revises existing required topics based on a user prompt."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run(self, input_data: RTRegenerationInput) -> RTRegenerationOutput:
        run_id = f"rt-regen-{_uuid.uuid4().hex[:8]}"
        set_run_context(run_id, _LANGFUSE_DOC_NAME)

        t_start = time.perf_counter()
        _result: RTRegenerationOutput | None = None
        _error: str | None = None
        _fell_back = False

        try:
            _result, _error, _fell_back = await _execute(self._kernel, input_data)
            return _result
        except Exception as exc:
            _error = str(exc)
            raise
        finally:
            write_span(
                name="RT Regeneration | revise required topics",
                agent="RT_REGEN",
                latency_ms=(time.perf_counter() - t_start) * 1000,
                input_data=_build_input_data(input_data),
                output_data=_build_output_data(
                    _result, error=_error, fell_back=_fell_back),
                error=_error,
            )
            flush_langfuse()
