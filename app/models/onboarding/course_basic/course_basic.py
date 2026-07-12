"""ORM model for the Course Basic feature."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseBasic(Base):
    """Persisted record for a course's basic details."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    course_code: Mapped[str] = mapped_column(String(32), nullable=False)
    course_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status_code: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
