"""Repository for the course_generation_validation_runs table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.validation_run import CourseGenerationValidationRun
from app.repositories.base_repository import BaseRepository


class CourseGenerationValidationRunRepository(BaseRepository[CourseGenerationValidationRun]):
    def __init__(self, db: Session) -> None:
        super().__init__(CourseGenerationValidationRun, db)

    def list_by_job(self, job_id: str) -> list[CourseGenerationValidationRun]:
        return self.db.query(self.model).filter_by(job_id=job_id).all()
