"""Reusable AI HTTP endpoints (not nested under course-generation jobs)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from semantic_kernel import Kernel

from app.ai.agents.content_transformation_agent import ContentTransformationError
from app.api.deps import get_kernel
from app.core.auth.dependencies import require_valid_token
from app.schemas.ai.content_ai import CourseEditorAiRequest, CourseEditorAiResponse
from app.services.ai.course_editor_ai_service import CourseEditorAiService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["AI"],
    dependencies=[Depends(require_valid_token)],
)


@router.post(
    "/ai/content-transformations",
    response_model=CourseEditorAiResponse,
    response_model_by_alias=True,
)
def transform_content(
    payload: CourseEditorAiRequest,
    kernel: Kernel = Depends(get_kernel),
) -> CourseEditorAiResponse:
    """Transform editor section content via AI (preview only; no persistence).

    Uses the exact ``content`` from the request body. Does not load content from
    storage, save results, create versions, or update job status.
    """
    try:
        return CourseEditorAiService(kernel).transform(payload)
    except ContentTransformationError as exc:
        logger.exception(
            "Content transformation failed | section_id=%s operation=%s",
            payload.section_id,
            payload.operation.value,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not transform the section content. Please try again.",
        ) from exc
    except Exception:
        logger.exception(
            "Unexpected error transforming section content | section_id=%s operation=%s",
            payload.section_id,
            payload.operation.value,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not transform the section content. Please try again.",
        )
