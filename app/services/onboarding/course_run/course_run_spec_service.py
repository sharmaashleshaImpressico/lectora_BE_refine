"""Business logic for the Course Run Spec API."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_spec import CourseRunSpec
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.repositories.course_run.course_run_spec_repository import CourseRunSpecRepository
from app.schemas.onboarding.course_run.course_run_spec import CourseRunSpecCreate
from app.services.onboarding.course_run.course_run_service import CourseRunNotFoundError

logger = logging.getLogger(__name__)


class CourseRunSpecService:
    """Encapsulates course-run-spec CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunSpecRepository(db)
        self.course_run_repository = CourseRunRepository(db)

    def create_spec(self, payload: CourseRunSpecCreate) -> CourseRunSpec:
        """Persist a new course-run-spec record."""
        course_run = self.course_run_repository.get_by_id(payload.course_run_id)
        if course_run is None:
            raise CourseRunNotFoundError(
                f"Course run '{payload.course_run_id}' not found."
            )

        spec = CourseRunSpec(**payload.model_dump())

        created = self.repository.create(spec)

        logger.info(
            "Created course run spec %s (run %s)",
            created.id,
            created.course_run_id,
        )

        return created