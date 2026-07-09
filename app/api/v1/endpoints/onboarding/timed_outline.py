"""HTTP routes for Timed Outline generation during onboarding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from semantic_kernel import Kernel

from app.api.deps import get_kernel
from app.schemas.onboarding.timed_outline.timed_outline import (
    GenerateTimedOutlineRequest,
    GenerateTimedOutlineResponse,
    RegenerateTimedOutlineRequest,
    RegenerateTimedOutlineResponse,
    SuggestOutlineStructureRequest,
    SuggestOutlineStructureResponse,
)
from app.services.onboarding.timed_outline.timed_outline_service import (
    TimedOutlineService,
)

logger = logging.getLogger(__name__)

# Backend paths: /documents/... (Vite proxy strips /api from FE /api/documents/...)
router = APIRouter(prefix="/documents", tags=["Timed Outline"])


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


@router.post(
    "/generate-to/cancel",
    status_code=status.HTTP_200_OK,
)
def cancel_generate_to() -> dict[str, str]:
    """Cancel the in-flight timed-outline generation, if any (best-effort)."""
    TimedOutlineService.cancel_generate_to()
    return {"status": "cancelled"}


@router.post(
    "/regenerate-timed-outline",
    response_model=RegenerateTimedOutlineResponse,
    status_code=status.HTTP_200_OK,
)
def regenerate_timed_outline(
    payload: RegenerateTimedOutlineRequest,
    kernel: Kernel = Depends(get_kernel),
) -> RegenerateTimedOutlineResponse:
    """Revise an existing timed outline in place using a free-text prompt."""
    try:
        service = TimedOutlineService(kernel)
        return service.regenerate_timed_outline(payload)
    except Exception:
        logger.exception("Failed to regenerate timed outline")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not regenerate timed outline. Please try again.",
        )


@router.post(
    "/suggest-outline-structure",
    response_model=SuggestOutlineStructureResponse,
    status_code=status.HTTP_200_OK,
)
def suggest_outline_structure(
    payload: SuggestOutlineStructureRequest,
    kernel: Kernel = Depends(get_kernel),
) -> SuggestOutlineStructureResponse:
    """Suggest a preferred chapter count and lesson style for a course."""
    try:
        service = TimedOutlineService(kernel)
        return service.suggest_outline_structure(payload)
    except Exception:
        logger.exception("Failed to suggest outline structure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not suggest outline structure. Please try again.",
        )
