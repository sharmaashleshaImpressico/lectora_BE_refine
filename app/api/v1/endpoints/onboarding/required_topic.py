"""HTTP routes for Required Topics generation during onboarding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from semantic_kernel import Kernel

from app.api.deps import get_kernel
from app.schemas.onboarding.required_topic.required_topic import (
    GenerateRequiredTopicsRequest,
    GenerateRequiredTopicsResponse,
)
from app.services.onboarding.required_topic.required_topic_service import (
    RequiredTopicService,
)

logger = logging.getLogger(__name__)

# Backend paths: /documents/... (Vite proxy strips /api from FE /api/documents/...)
router = APIRouter(prefix="/documents", tags=["Required Topics"])


@router.post(
    "/required-topics",
    response_model=GenerateRequiredTopicsResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_required_topics(
    payload: GenerateRequiredTopicsRequest,
    kernel: Kernel = Depends(get_kernel),
) -> GenerateRequiredTopicsResponse:
    """Generate and validate required course topics from onboarding metadata."""
    try:
        service = RequiredTopicService(kernel)
        return await service.generate_required_topics(payload)
    except Exception:
        logger.exception("Failed to generate required topics")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate required topics. Please try again.",
        )
