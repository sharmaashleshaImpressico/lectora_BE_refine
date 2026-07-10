"""Pydantic response schema for course generation job artifacts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CourseGenerationJobArtifactData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    course_run_id: str
    artifact_type: str
    stage_name: str
    file_name: str
    blob_path: str
    content_type: str | None
    created_at: datetime
