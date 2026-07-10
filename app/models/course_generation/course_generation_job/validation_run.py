"""ORM model for the course_generation_validation_runs table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseGenerationValidationRun(Base):
    """A single validation attempt against generated content for a job."""

    __tablename__ = "course_generation_validation_runs"

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_generation_jobs.id"), nullable=False
    )
    course_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_runs.id"), nullable=False
    )
    validation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    report_artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("course_generation_job_artifacts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
