"""Business logic for the Course Run API."""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run import CourseRun
from app.repositories.course_basic.course_repository import CourseRepository
from app.repositories.course_run.course_run_repository import CourseRunRepository
from app.schemas.onboarding.course_run.course_run import (
    CourseRunCreate,
    CourseRunInternal,
)

logger = logging.getLogger(__name__)

MAX_ID_COLLISION_RETRIES = 3


class CourseNotFoundError(Exception):
    """Raised when the referenced course does not exist."""


class CourseRunNotFoundError(Exception):
    """Raised when the referenced parent course run does not exist."""


class CourseRunIdCollisionError(Exception):
    """Raised when a unique course-run id could not be generated after retrying."""


class CourseRunService:
    """Encapsulates course-run CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRunRepository(db)
        self.course_repository = CourseRepository(db)

    def create_course_run(self, payload: CourseRunCreate) -> CourseRun:
        """Persist a new course-run record, assigning the next version number."""
        course = self.course_repository.get_by(id=payload.course_id)
        if course is None:
            raise CourseNotFoundError(f"Course '{payload.course_id}' not found.")

        if payload.created_from_run_id is not None:
            parent_run = self.repository.get_by_id(payload.created_from_run_id)
            if parent_run is None:
                raise CourseRunNotFoundError(
                    f"Course run '{payload.created_from_run_id}' not found."
                )

        next_version = self.repository.latest_version_number(payload.course_id) + 1

        for attempt in range(1, MAX_ID_COLLISION_RETRIES + 1):
            record = CourseRunInternal(
                course_id=payload.course_id,
                version_number=next_version,
                created_from_run_id=payload.created_from_run_id,
                created_by=payload.created_by,
            )

            course_run = CourseRun(
                course_id=record.course_id,
                version_number=record.version_number,
                created_from_run_id=record.created_from_run_id,
                status_code=record.status_code,
                created_by=record.created_by,
            )

            try:
                created = self.repository.create(course_run)
            except IntegrityError:
                self.db.rollback()
                logger.warning(
                    "Course run insert collided on attempt %s; regenerating.", attempt
                )
                continue

            logger.info(
                "Created course run %s (course %s, v%s)",
                created.id,
                created.course_id,
                created.version_number,
            )

            return created

        raise CourseRunIdCollisionError(
            f"Could not generate a unique course-run id after {MAX_ID_COLLISION_RETRIES} attempts."
        )
