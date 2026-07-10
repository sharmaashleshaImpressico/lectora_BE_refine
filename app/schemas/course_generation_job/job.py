"""Pydantic request/response schemas for the course generation job API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GenerateCourseRequest(BaseModel):
    """Payload accepted by `POST /course-runs/{course_run_id}/jobs`."""

    requested_by: str | None = Field(
        default=None,
        max_length=255,
        description="Who requested generation; defaults to 'system' if omitted",
    )


class CourseGenerationJobData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_run_id: str
    status_code: str
    requested_by: str
    shared_state_blob_path: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class CourseGenerationJobResponse(BaseModel):
    """Response envelope returned right after a job is queued."""

    success: bool
    data: CourseGenerationJobData
