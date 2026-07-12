"""Service-to-orchestrator contracts for content transformation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.ai.content_ai import ContentAiOperation


@dataclass(frozen=True)
class ContentTransformationInput:
    section_id: str
    operation: ContentAiOperation
    content: str = ""
    user_prompt: str | None = None
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    preserve_structure: bool = False


@dataclass(frozen=True)
class ContentTransformationResult:
    section_id: str
    operation: ContentAiOperation
    content: str | None = None
    paragraphs: list[dict[str, Any]] | None = None


__all__ = [
    "ContentTransformationInput",
    "ContentTransformationResult",
]
