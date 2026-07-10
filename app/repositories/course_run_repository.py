"""Course-run repository, built on the generic `BaseRepository`."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.onboarding.course_run.course_run import CourseRun
from app.repositories.base_repository import BaseRepository


class CourseRunRepository(BaseRepository[CourseRun]):
    """CRUD helper scoped to the `CourseRun` model."""

    def __init__(self, db: Session) -> None:
        super().__init__(CourseRun, db)

    def latest_version_number(self, course_id: int) -> int:
        """Return the highest `version_number` recorded for a course, or 0 if none exist."""
        latest = (
            self.db.query(CourseRun)
            .filter(CourseRun.course_id == course_id)
            .order_by(CourseRun.version_number.desc())
            .first()
        )
        return latest.version_number if latest else 0

    def count_all(self) -> int:
        """Return the total number of course-run records."""
        return self.db.query(CourseRun).count()

    def count_by_statuses(self, status_codes: Sequence[str]) -> int:
        """Return how many course runs match any of the given status codes."""
        if not status_codes:
            return 0
        return (
            self.db.query(CourseRun)
            .filter(CourseRun.status_code.in_(list(status_codes)))
            .count()
        )
