"""Pydantic response schema for the job detail endpoint."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.course_generation_job.job import CourseGenerationJobData
from app.schemas.course_generation_job.job_artifact import CourseGenerationJobArtifactData
from app.schemas.course_generation_job.validation_run import CourseGenerationValidationRunData


class CourseGenerationJobDetailData(BaseModel):
    job: CourseGenerationJobData
    artifacts: list[CourseGenerationJobArtifactData]
    validation_runs: list[CourseGenerationValidationRunData]


class CourseGenerationJobDetailResponse(BaseModel):
    success: bool
    data: CourseGenerationJobDetailData
