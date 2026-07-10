"""Business logic for the Course Run Input API."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_input import CourseRunInput
from app.repositories.course_run.course_run_input_repository import CourseRunInputRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.schemas.onboarding.course_run.course_run_input import CourseRunInputCreate
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)


class CourseRunInputService:
    """Encapsulates course-run-input CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunInputRepository(db)
        self.course_run_repository = CourseRunRepository(db)

    def create_input(self, payload: CourseRunInputCreate) -> CourseRunInput:
        """Persist a new course-run-input record."""
        course_run = self.course_run_repository.get_by_id(payload.course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(f"Course run '{payload.course_run_id}' not found.")

        course_run_input = CourseRunInput(**payload.model_dump())
        created = self.repository.create(course_run_input)
        logger.info("Created course run input %s (run %s)", created.id, created.course_run_id)
        return created
