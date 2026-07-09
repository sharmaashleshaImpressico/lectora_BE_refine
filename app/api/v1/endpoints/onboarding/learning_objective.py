"""HTTP routes for Learning Objective generation and regeneration during onboarding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from semantic_kernel import Kernel

from app.api.deps import get_kernel
from app.schemas.onboarding.learning_objective.learning_objective import (
    GenerateLearningObjectivesRequest,
    GenerateLearningObjectivesResponse,
    RegenerateLearningObjectivesRequest,
    RegenerateLearningObjectivesResponse,
)
from app.services.onboarding.learning_objective.learning_objective_service import (
    LearningObjectiveService,
)

logger = logging.getLogger(__name__)

# Frontend contract paths under /api/documents
router = APIRouter(prefix="/api/documents", tags=["Learning Objective"])


@router.post(
    "/generate-learning-objectives",
    response_model=GenerateLearningObjectivesResponse,
    status_code=status.HTTP_200_OK,
)
def generate_learning_objectives(
    payload: GenerateLearningObjectivesRequest,
    kernel: Kernel = Depends(get_kernel),
) -> GenerateLearningObjectivesResponse:
    """Generate and validate learning objectives from course metadata."""
    try:
        service = LearningObjectiveService(kernel)
        return service.generate_learning_objectives(payload)
    except Exception:
        logger.exception("Failed to generate learning objectives")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate learning objectives. Please try again.",
        )


@router.post(
    "/regenerate-learning-objectives",
    response_model=RegenerateLearningObjectivesResponse,
    status_code=status.HTTP_200_OK,
)
def regenerate_learning_objectives(
    payload: RegenerateLearningObjectivesRequest,
    kernel: Kernel = Depends(get_kernel),
) -> RegenerateLearningObjectivesResponse:
    """Revise existing learning objectives based on user feedback."""
    try:
        service = LearningObjectiveService(kernel)
        return service.regenerate_learning_objectives(payload)
    except Exception:
        logger.exception("Failed to regenerate learning objectives")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not regenerate learning objectives. Please try again.",
        )
