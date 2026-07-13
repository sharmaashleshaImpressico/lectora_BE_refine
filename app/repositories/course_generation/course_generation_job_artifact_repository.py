"""Repository for the course_generation_job_artifacts table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.job_artifact import CourseGenerationJobArtifact
from app.repositories.base_repository import BaseRepository


class CourseGenerationJobArtifactRepository(BaseRepository[CourseGenerationJobArtifact]):
    def __init__(self, db: Session) -> None:
        super().__init__(CourseGenerationJobArtifact, db)

    def list_by_job(self, job_id: str) -> list[CourseGenerationJobArtifact]:
        return self.db.query(self.model).filter_by(job_id=job_id).all()
