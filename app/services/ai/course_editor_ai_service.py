"""Application service for Course Editor AI section transforms."""

from __future__ import annotations

from semantic_kernel import Kernel

from app.orchestrators.content_transformation.models import ContentTransformationInput
from app.orchestrators.content_transformation.orchestrator import (
    ContentTransformationOrchestrator,
)
from app.schemas.ai.content_ai import (
    CourseEditorAiRequest,
    CourseEditorAiResponse,
)


class CourseEditorAiService:
    """Map API ↔ content-transformation orchestrator.

    Uses the exact frontend ``content`` / ``paragraphs`` from the request.
    Does not load section text from storage, persist results, create versions,
    or touch the database.
    """

    def __init__(
        self,
        kernel: Kernel,
        *,
        orchestrator: ContentTransformationOrchestrator | None = None,
    ) -> None:
        self._orchestrator = orchestrator or ContentTransformationOrchestrator(kernel)

    def transform(self, request: CourseEditorAiRequest) -> CourseEditorAiResponse:
        result = self._orchestrator.transform(
            ContentTransformationInput(
                section_id=request.section_id,
                operation=request.operation,
                content=request.content or "",
                user_prompt=request.user_prompt,
                paragraphs=list(request.paragraphs or []),
                preserve_structure=request.preserve_structure,
            )
        )
        return CourseEditorAiResponse(
            section_id=result.section_id,
            operation=result.operation,
            content=result.content,
            paragraphs=result.paragraphs,
        )


__all__ = ["CourseEditorAiService"]
