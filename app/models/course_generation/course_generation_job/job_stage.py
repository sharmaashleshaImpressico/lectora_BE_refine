"""ORM model for the course_generation_job_stages table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseGenerationJobStage(Base):
    """Per-stage progress for a job's pipeline run (drives FE stage tracker + SSE)."""

    __tablename__ = "course_generation_job_stages"
    __table_args__ = (
        UniqueConstraint("job_id", "stage_code", name="uq_course_generation_job_stages_job_stage"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_generation_jobs.id"), nullable=False
    )
    stage_code: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blockers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
