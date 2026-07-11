"""Repository for the course_generation_job_stages table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.job_stage import CourseGenerationJobStage
from app.repositories.base_repository import BaseRepository


class CourseGenerationJobStageRepository(BaseRepository[CourseGenerationJobStage]):
    def __init__(self, db: Session) -> None:
        super().__init__(CourseGenerationJobStage, db)

    def list_by_job(self, job_id: str) -> list[CourseGenerationJobStage]:
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id)
            .order_by(self.model.id.asc())
            .all()
        )

    def get_by_job_and_stage(self, job_id: str, stage_code: str) -> CourseGenerationJobStage | None:
        return self.db.query(self.model).filter_by(job_id=job_id, stage_code=stage_code).first()
