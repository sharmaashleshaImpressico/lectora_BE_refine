"""ORM model for the course_generation_job_artifacts table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseGenerationJobArtifact(Base):
    """A single artifact (shared state, generated document, log, report...) produced by a job."""

    __tablename__ = "course_generation_job_artifacts"

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_generation_jobs.id"), nullable=False
    )
    course_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_runs.id"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    stage_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    blob_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
