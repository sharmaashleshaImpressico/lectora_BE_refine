"""Repository for the course_generation_job_logs table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.course_generation.course_generation_job.job_log import CourseGenerationJobLog
from app.repositories.base_repository import BaseRepository


class CourseGenerationJobLogRepository(BaseRepository[CourseGenerationJobLog]):
    def __init__(self, db: Session) -> None:
        super().__init__(CourseGenerationJobLog, db)

    def list_by_job(self, job_id: str) -> list[CourseGenerationJobLog]:
        return (
            self.db.query(self.model)
            .filter_by(job_id=job_id)
            .order_by(self.model.id.asc())
            .all()
        )

    def list_since(self, job_id: str, after_id: int) -> list[CourseGenerationJobLog]:
        """Logs with `id > after_id`, ascending — the delta the SSE stream sends."""
        return (
            self.db.query(self.model)
            .filter(self.model.job_id == job_id, self.model.id > after_id)
            .order_by(self.model.id.asc())
            .all()
        )

    def max_id_for_job(self, job_id: str) -> int:
        latest = (
            self.db.query(self.model)
            .filter_by(job_id=job_id)
            .order_by(self.model.id.desc())
            .first()
        )
        return latest.id if latest else 0
