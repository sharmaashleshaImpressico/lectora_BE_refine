"""Business logic for the Course Basic API."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.onboarding.course_basic.course_basic import CourseBasic
from app.repositories.course_repository import CourseRepository
from app.schemas.onboarding.course_basic.course import (
    CourseBasicCreate,
    CourseBasicInternal,
    CourseBasicUpdate,
)

logger = logging.getLogger(__name__)


class CourseBasicService:
    """Encapsulates course-basic CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = CourseRepository(db)

    def create_course(self, payload: CourseBasicCreate) -> CourseBasic:
        """Persist a new course record; the database assigns `id` on insert."""
        record = CourseBasicInternal(**payload.model_dump())
        course = CourseBasic(
            title=record.course_title,
            course_code=record.course_code,
            course_type=record.course_type,
            status_code=record.status_code,
            created_by=record.created_by,
        )
        created = self.repository.create(course)
        logger.info("Created course %s", created.id)
        return created

    def get_course(self, course_id: int) -> CourseBasic | None:
        """Return a course by id, or None if it does not exist."""
        return self.repository.get_by(id=course_id)

    def update_course(self, course_id: int, payload: CourseBasicUpdate) -> CourseBasic | None:
        """Replace a course's basic details. Returns None if the course is not found."""
        course = self.get_course(course_id)
        if course is None:
            return None

        course.title = payload.course_title
        course.course_type = payload.course_type
        course.status_code = payload.status_code
        course.created_by = payload.created_by

        self.db.flush()
        self.db.refresh(course)
        logger.info("Updated course %s", course_id)
        return course
