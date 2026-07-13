"""ORM model for the course_generation_job_logs table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseGenerationJobLog(Base):
    """One activity-feed log entry for a job. `id` doubles as the SSE event/cursor id."""

    __tablename__ = "course_generation_job_logs"

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_generation_jobs.id"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stage_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
