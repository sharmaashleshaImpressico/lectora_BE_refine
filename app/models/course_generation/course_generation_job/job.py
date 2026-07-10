"""ORM model for the course_generation_jobs table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.course_generation.course_generation_job.constants import JOB_STATUS_QUEUED


class CourseGenerationJob(Base):
    """A single content-generation run for a `course_run`, driven by a Service Bus message."""

    __tablename__ = "course_generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_runs.id"), nullable=False
    )
    status_code: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("course_generation_job_status.code"),
        nullable=False,
        default=JOB_STATUS_QUEUED,
    )
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    shared_state_blob_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
