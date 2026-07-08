"""Course-specific repository, built on the generic `BaseRepository`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.onboarding.course_basic.course_basic import CourseBasic
from app.repositories.base_repository import BaseRepository


class CourseRepository(BaseRepository[CourseBasic]):
    """CRUD helper scoped to the `CourseBasic` model."""

    def __init__(self, db: Session) -> None:
        super().__init__(CourseBasic, db)
