"""Builds layered prompts for ContentTransformationAgent."""

from __future__ import annotations

import json

from app.ai.agents.content_transformation_agent.models import (
    ContentTransformationAgentInput,
)
from app.ai.agents.content_transformation_agent.prompts import (
    COMMON_INSTRUCTIONS,
    OPERATION_INSTRUCTIONS,
    STRUCTURE_PRESERVATION_INSTRUCTIONS,
)


class ContentTransformationPromptBuilder:
    """Compose system + user messages from prompt layers."""

    def build_system_prompt(self, input_data: ContentTransformationAgentInput) -> str:
        operation_block = OPERATION_INSTRUCTIONS[input_data.operation]
        parts = [
            "COMMON INSTRUCTIONS",
            (
                STRUCTURE_PRESERVATION_INSTRUCTIONS.strip()
                if input_data.preserve_structure
                else COMMON_INSTRUCTIONS.strip()
            ),
            "OPERATION INSTRUCTIONS",
            operation_block.strip(),
        ]
        return "\n\n".join(parts)

    def build_user_message(self, input_data: ContentTransformationAgentInput) -> str:
        parts: list[str] = []
        prompt = (input_data.user_prompt or "").strip()
        if prompt:
            parts.append(f"<user_instruction>\n{prompt}\n</user_instruction>")

        if input_data.preserve_structure:
            payload = json.dumps(input_data.paragraphs, ensure_ascii=False, indent=2)
            parts.append(f"<source_paragraphs>\n{payload}\n</source_paragraphs>")
            flat = (input_data.content or "").strip()
            if flat:
                parts.append(
                    "<source_content_preview>\n"
                    f"{flat}\n"
                    "</source_content_preview>"
                )
        else:
            parts.append(f"<source_content>\n{input_data.content}\n</source_content>")
        return "\n\n".join(parts)


__all__ = ["ContentTransformationPromptBuilder"]
