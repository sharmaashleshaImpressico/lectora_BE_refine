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

Tracing
───────
Workflow context is owned by ``RequiredTopicsOrchestrator.regenerate_required_topics``.
The LLM call is traced automatically by the shared ``chat_async()`` wrapper.
"""
from __future__ import annotations

import json
import logging

from app.ai.agents.required_topic.config.llm import (
    make_config,
)
from app.ai.agents.required_topic.regenerate_required_topic_agent.models import (
    RTRegenerationInput,
    RTRegenerationOutput,
)
from semantic_kernel import Kernel

from app.kernel.chat import chat_async

logger = logging.getLogger(__name__)

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


async def _execute(
    kernel: Kernel,
    input_data: RTRegenerationInput,
) -> RTRegenerationOutput:
    """Core regeneration logic."""
    if not input_data.current_topics:
        logger.warning(
            "[rt_regenerate] No current topics supplied — returning empty")
        return RTRegenerationOutput(topics=[])

    if not input_data.regeneration_prompt.strip():
        logger.warning(
            "[rt_regenerate] Empty regeneration prompt — returning originals")
        return RTRegenerationOutput(topics=list(input_data.current_topics))

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
        return RTRegenerationOutput(topics=list(input_data.current_topics))
    except Exception:
        logger.exception(
            "[rt_regenerate] LLM call failed — returning original topics")
        return RTRegenerationOutput(topics=list(input_data.current_topics))

    topics: list[str] = data.get("required_topics") or []
    if not isinstance(topics, list):
        topics = []
    topics = [str(t).strip() for t in topics if t]

    if not topics:
        logger.warning(
            "[rt_regenerate] LLM returned empty list — returning original topics")
        return RTRegenerationOutput(topics=list(input_data.current_topics))

    logger.info("[rt_regenerate] Regenerated to %d topics", len(topics))
    return RTRegenerationOutput(topics=topics)


class RTRegenerationAgent:
    """Revises existing required topics based on a user prompt."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel

    async def run(self, input_data: RTRegenerationInput) -> RTRegenerationOutput:
        # Workflow context is owned by RequiredTopicsOrchestrator.regenerate_required_topics.
        return await _execute(self._kernel, input_data)
