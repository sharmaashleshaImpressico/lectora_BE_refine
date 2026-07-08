"""Course-run-input repository, built on the generic `BaseRepository`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_input import CourseRunInput
from app.repositories.base_repository import BaseRepository


class CourseRunInputRepository(BaseRepository[CourseRunInput]):
    """CRUD helper scoped to the `CourseRunInput` model."""

    def __init__(self, db: Session) -> None:
        super().__init__(CourseRunInput, db)
