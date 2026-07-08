"""ORM model for the Course Run Spec feature."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CourseRunSpec(Base):
    """The generation parameters captured for a single course run."""

    __tablename__ = "course_run_specs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_runs.id"), nullable=False
    )
    course_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    learner_experience_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    learner_outcomes: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_topics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_objectives_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    depth: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emphasis: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_case_studies: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    include_examples: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    course_structure_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uploaded_outline_blob_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rule_pack_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_pack_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_rule_pack_blob_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outline_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
