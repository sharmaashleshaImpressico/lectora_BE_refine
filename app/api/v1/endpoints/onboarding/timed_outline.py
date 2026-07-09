"""HTTP routes for Timed Outline generation during onboarding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from semantic_kernel import Kernel

from app.api.deps import get_kernel
from app.core.auth.dependencies import require_valid_token
from app.schemas.onboarding.timed_outline.timed_outline import (
    GenerateTimedOutlineRequest,
    GenerateTimedOutlineResponse,
)
from app.services.onboarding.timed_outline.timed_outline_service import (
    TimedOutlineService,
)

logger = logging.getLogger(__name__)

# Backend paths: /documents/... (Vite proxy strips /api from FE /api/documents/...)
router = APIRouter(
    prefix="/documents",
    tags=["Timed Outline"],
    dependencies=[Depends(require_valid_token)],
)


@router.post(
    "/generate-to",
    response_model=GenerateTimedOutlineResponse,
    status_code=status.HTTP_200_OK,
)
def generate_timed_outline(
    payload: GenerateTimedOutlineRequest,
    kernel: Kernel = Depends(get_kernel),
) -> GenerateTimedOutlineResponse:
    """Generate and validate a timed outline from course metadata and source documents."""
    try:
        service = TimedOutlineService(kernel)
        return service.generate_timed_outline(payload)
    except Exception:
        logger.exception("Failed to generate timed outline")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate timed outline. Please try again.",
        )
