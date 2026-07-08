"""ORM model for the Course Run Rule Override feature."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseRunRuleOverride(Base):
    """A single rule-pack override applied to a course run."""

    __tablename__ = "course_run_rule_overrides"

    id: Mapped[int] = mapped_column(Integer, Identity(start=1, increment=1), primary_key=True)
    course_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_runs.id"), nullable=False
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
