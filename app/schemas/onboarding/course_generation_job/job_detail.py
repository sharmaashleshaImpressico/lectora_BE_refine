"""Pydantic response schema for the job detail endpoint.

Shape matches the frontend's `JobDetail` type exactly
(course_generation_frontend/src/modules/course-generation/types/index.ts) —
this is a REST snapshot of the same stage/log data the SSE stream at
`GET /jobs/{job_id}/events` streams incrementally.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class JobStageProgressData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stage: str
    status: str
    started_at: str | None = Field(alias="startedAt")
    completed_at: str | None = Field(alias="completedAt")
    outcome: str | None


class JobErrorDetailData(BaseModel):
    code: str
    message: str
    stage: str | None
    retryable: bool


class JobDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: str
    created_at: str | None = Field(alias="createdAt")
    updated_at: str | None = Field(alias="updatedAt")
    stages: list[JobStageProgressData]
    error: JobErrorDetailData | None
