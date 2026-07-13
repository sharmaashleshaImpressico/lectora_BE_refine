"""Content Transformation Agent for Course Editor AI actions.

Transforms a single section's frontend content for one of:
summarize | expand | simplify | rewrite | improve_tone.

Raises on empty output, JSON parse failure, structure validation failure,
or LLM/provider failure. Does not soft-return the original content.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from semantic_kernel import Kernel

from app.ai.agents.content_transformation_agent.config.llm import make_transform_config
from app.ai.agents.content_transformation_agent.errors import ContentTransformationError
from app.ai.agents.content_transformation_agent.models import (
    ContentTransformationAgentInput,
    ContentTransformationAgentOutput,
)
from app.ai.agents.content_transformation_agent.prompt_builder import (
    ContentTransformationPromptBuilder,
)
from app.ai.agents.content_transformation_agent.structure_validator import (
    paragraphs_to_flat_content,
    validate_preserved_paragraphs,
)
from app.kernel.chat import chat

logger = logging.getLogger(__name__)

AGENT_LABEL = "CONTENT_TRANSFORM"


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContentTransformationError(
            "Model returned invalid JSON for content transformation."
        ) from exc

    if not isinstance(data, dict):
        raise ContentTransformationError(
            "Model returned a non-object JSON payload for content transformation."
        )
    return data


def _parse_flat_content(data: dict[str, Any]) -> str:
    content = data.get("content")
    if not isinstance(content, str):
        raise ContentTransformationError(
            "Model JSON missing a string 'content' field."
        )
    transformed = content.strip()
    if not transformed:
        raise ContentTransformationError(
            "Model returned empty transformed content."
        )
    return transformed


def _parse_structured_paragraphs(
    data: dict[str, Any],
    *,
    source_paragraphs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    paragraphs = data.get("paragraphs")
    if paragraphs is None:
        raise ContentTransformationError(
            "Model JSON missing a 'paragraphs' array for structure-preserving mode."
        )
    validated = validate_preserved_paragraphs(source_paragraphs, paragraphs)
    if not validated:
        raise ContentTransformationError(
            "Model returned empty paragraphs for structure-preserving mode."
        )

    flat = data.get("content")
    if isinstance(flat, str) and flat.strip():
        compatibility = flat.strip()
    else:
        compatibility = paragraphs_to_flat_content(validated)
        if not compatibility:
            raise ContentTransformationError(
                "Transformed paragraphs produced empty compatibility content."
            )
    return validated, compatibility


class ContentTransformationAgent:
    """Single-shot section content transform via Semantic Kernel chat."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        prompt_builder: ContentTransformationPromptBuilder | None = None,
    ) -> None:
        self._kernel = kernel
        self._prompt_builder = prompt_builder or ContentTransformationPromptBuilder()

    def run(
        self,
        input_data: ContentTransformationAgentInput,
    ) -> ContentTransformationAgentOutput:
        if input_data.preserve_structure:
            if not input_data.paragraphs:
                raise ContentTransformationError(
                    "Structured transformation requires non-empty paragraphs."
                )
        elif not (input_data.content or "").strip():
            raise ContentTransformationError("Source content must not be empty.")

        system_prompt = self._prompt_builder.build_system_prompt(input_data)
        user_message = self._prompt_builder.build_user_message(input_data)
        config = make_transform_config()

        logger.info(
            "[content_transformation] operation=%s preserve_structure=%s "
            "content_chars=%d paragraphs=%d has_user_prompt=%s",
            input_data.operation.value,
            input_data.preserve_structure,
            len(input_data.content or ""),
            len(input_data.paragraphs or []),
            bool((input_data.user_prompt or "").strip()),
        )

        try:
            raw = chat(
                self._kernel,
                system_prompt,
                user_message,
                config,
                AGENT_LABEL,
            )
        except ContentTransformationError:
            raise
        except Exception as exc:
            logger.exception("[content_transformation] LLM call failed")
            raise ContentTransformationError(
                "Content transformation provider call failed."
            ) from exc

        if not (raw or "").strip():
            raise ContentTransformationError(
                "Model returned an empty response for content transformation."
            )

        data = _parse_json_object(raw)
        if input_data.preserve_structure:
            paragraphs, content = _parse_structured_paragraphs(
                data,
                source_paragraphs=list(input_data.paragraphs),
            )
            return ContentTransformationAgentOutput(
                content=content,
                paragraphs=paragraphs,
            )

        return ContentTransformationAgentOutput(
            content=_parse_flat_content(data),
            paragraphs=None,
        )


__all__ = [
    "AGENT_LABEL",
    "ContentTransformationAgent",
    "ContentTransformationError",
]
