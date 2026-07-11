"""Repository for the course_generation_jobs table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.job import CourseGenerationJob
from app.repositories.base_repository import BaseRepository


class CourseGenerationJobRepository(BaseRepository[CourseGenerationJob]):
    def __init__(self, db: Session) -> None:
        super().__init__(CourseGenerationJob, db)

    def get_by_id(self, record_id: str) -> CourseGenerationJob | None:  # type: ignore[override]
        return self.db.get(self.model, record_id)

    def list_by_course_run(self, course_run_id: str) -> list[CourseGenerationJob]:
        return (
            self.db.query(self.model)
            .filter_by(course_run_id=course_run_id)
            .order_by(self.model.created_at.desc())
            .all()
        )
