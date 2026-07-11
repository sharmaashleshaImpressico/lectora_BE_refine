"""Course-run-spec repository, built on the generic `BaseRepository`."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run_spec import CourseRunSpec
from app.repositories.base_repository import BaseRepository


class CourseRunSpecRepository(BaseRepository[CourseRunSpec]):
    """CRUD helper scoped to the `CourseRunSpec` model."""

    def __init__(self, db: Session) -> None:
        super().__init__(CourseRunSpec, db)
