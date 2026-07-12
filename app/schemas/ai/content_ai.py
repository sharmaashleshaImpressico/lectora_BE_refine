"""Request/response schemas for POST /ai/content-transformations."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContentAiOperation(str, Enum):
    summarize = "summarize"
    expand = "expand"
    simplify = "simplify"
    rewrite = "rewrite"
    improve_tone = "improve_tone"


_PROMPT_REQUIRED_OPERATIONS = frozenset(
    {
        ContentAiOperation.rewrite,
        ContentAiOperation.improve_tone,
    }
)


class CourseEditorAiRequest(BaseModel):
    """Frontend Course Editor AI action payload.

    ``sectionId`` is for client-side result correlation only.
    When ``preserveStructure`` is true, ``paragraphs`` are the source of truth;
    ``content`` is a flat compatibility preview only.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    section_id: str = Field(..., alias="sectionId", min_length=1)
    operation: ContentAiOperation
    content: str = Field(default="")
    user_prompt: str | None = Field(default=None, alias="userPrompt")
    paragraphs: list[dict[str, Any]] = Field(default_factory=list)
    preserve_structure: bool = Field(default=False, alias="preserveStructure")

    @model_validator(mode="after")
    def validate_request(self) -> CourseEditorAiRequest:
        if self.operation in _PROMPT_REQUIRED_OPERATIONS:
            prompt = (self.user_prompt or "").strip()
            if not prompt:
                raise ValueError(
                    f"userPrompt is required for operation '{self.operation.value}'."
                )
            self.user_prompt = prompt
        elif self.user_prompt is not None:
            stripped = self.user_prompt.strip()
            self.user_prompt = stripped or None

        if self.preserve_structure:
            if not self.paragraphs:
                raise ValueError(
                    "paragraphs are required when preserveStructure is true."
                )
            for index, block in enumerate(self.paragraphs):
                if not isinstance(block, dict):
                    raise ValueError(f"paragraphs[{index}] must be an object.")
                block_id = str(block.get("id") or "").strip()
                block_type = str(block.get("type") or "").strip()
                if not block_id:
                    raise ValueError(
                        f"paragraphs[{index}] must include a non-empty id."
                    )
                if not block_type:
                    raise ValueError(
                        f"paragraphs[{index}] must include a non-empty type."
                    )
        elif not (self.content or "").strip() and not self.paragraphs:
            raise ValueError("content or paragraphs must be provided.")

        return self


class CourseEditorAiResponse(BaseModel):
    """Transformed section content returned to the editor (preview only).

    When structure was preserved, ``paragraphs`` are the source of truth and
    ``content`` is an optional flat compatibility field.
    """

    model_config = ConfigDict(populate_by_name=True)

    section_id: str = Field(..., serialization_alias="sectionId")
    operation: ContentAiOperation
    content: str | None = None
    paragraphs: list[dict[str, Any]] | None = None


__all__ = [
    "ContentAiOperation",
    "CourseEditorAiRequest",
    "CourseEditorAiResponse",
]
