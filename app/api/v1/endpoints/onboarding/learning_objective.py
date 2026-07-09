"""HTTP routes for Learning Objective generation during onboarding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from semantic_kernel import Kernel

from app.api.deps import get_kernel
from app.schemas.onboarding.learning_objective.learning_objective import (
    GenerateLearningObjectivesRequest,
    GenerateLearningObjectivesResponse,
)
from app.services.onboarding.learning_objective.learning_objective_service import (
    LearningObjectiveService,
)

logger = logging.getLogger(__name__)

# Frontend contract path: POST /api/documents/generate-learning-objectives
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
