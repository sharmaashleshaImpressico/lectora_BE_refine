"""Pydantic response schema for course generation validation runs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CourseGenerationValidationRunData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    course_run_id: str
    validation_type: str
    attempt_number: int
    status: str
    blocker_count: int
    warning_count: int
    info_count: int
    score: float | None
    report_artifact_id: int | None
    created_at: datetime
