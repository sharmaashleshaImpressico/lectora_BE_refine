"""ORM model for immutable per-job course-content / study-guide versions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.course_generation.course_generation_job.constants import (
    CONTENT_VERSION_STATUS_CREATING,
)


class CourseContentVersion(Base):
    """One immutable study-guide / course-content revision for a generation job.

    Version numbers are scoped to ``job_id`` and are never reused. Latest
    published content is resolved as the highest ``version_number`` with
    ``status_code == AVAILABLE`` (no ``is_latest`` pointer).
    """

    __tablename__ = "course_content_versions"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "version_number",
            name="uq_course_content_versions_job_id_version_number",
        ),
        # Ascending composites: SQLite/Azure SQL portable. Callers ORDER BY
        # version_number DESC when resolving newest / latest-available.
        Index(
            "ix_course_content_versions_job_id_version_number",
            "job_id",
            "version_number",
        ),
        Index(
            "ix_course_content_versions_job_id_status_version",
            "job_id",
            "status_code",
            "version_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_generation_jobs.id"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id"), nullable=False
    )
    course_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_runs.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(50), nullable=False, default=CONTENT_VERSION_STATUS_CREATING
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_json_blob_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    docx_blob_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
