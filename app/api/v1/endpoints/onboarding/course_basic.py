"""HTTP routes for the Course Basic API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.onboarding.course_basic.course import (
    CourseBasicCreate,
    CourseBasicData,
    CourseBasicResponse,
    CourseBasicUpdate,
)
from app.services.onboarding.course_basic.course_service import CourseBasicService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Course Basic"])


@router.post(
    "/course-basic",
    response_model=CourseBasicResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_course_basic(
    payload: CourseBasicCreate,
    db: Session = Depends(get_db),
) -> CourseBasicResponse:
    """Create a new course's basic details and auto-generate its id."""
    try:
        service = CourseBasicService(db)
        course = service.create_course(payload)
    except Exception:
        logger.exception("Failed to create course basic record")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the course. Please try again.",
        )

    return CourseBasicResponse(success=True, data=CourseBasicData.model_validate(course))


@router.get(
    "/course-basic/{course_id}",
    response_model=CourseBasicResponse,
)
def get_course_basic(
    course_id: int,
    db: Session = Depends(get_db),
) -> CourseBasicResponse:
    """Retrieve a course's basic details by id."""
    service = CourseBasicService(db)
    course = service.get_course(course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course '{course_id}' not found.",
        )

    return CourseBasicResponse(success=True, data=CourseBasicData.model_validate(course))


@router.put(
    "/course-basic/{course_id}",
    response_model=CourseBasicResponse,
)
def update_course_basic(
    course_id: int,
    payload: CourseBasicUpdate,
    db: Session = Depends(get_db),
) -> CourseBasicResponse:
    """Replace a course's basic details."""
    try:
        service = CourseBasicService(db)
        course = service.update_course(course_id, payload)
    except Exception:
        logger.exception("Failed to update course basic record %s", course_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the course. Please try again.",
        )

    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course '{course_id}' not found.",
        )

    return CourseBasicResponse(success=True, data=CourseBasicData.model_validate(course))
