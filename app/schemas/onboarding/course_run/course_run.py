"""Pydantic request/response schemas for the Course Run API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CREATED_BY = "system"

CourseRunStatus = Literal["DRAFT", "GENERATING", "GENERATED", "FAILED", "CANCELLED"]


class CourseRunCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_id: int = Field(..., description="Id of the course this run belongs to")
    created_from_run_id: str | None = Field(
        default=None,
        max_length=64,
        description="Id of the run this one was branched from, if any",
    )
    created_by: str | None = Field(
        default=None,
        max_length=255,
        description="Who created this run; defaults to 'system' if omitted",
    )


class CourseRunInternal(BaseModel):
    """Server-side record ready to persist."""

    course_id: int
    version_number: int
    created_from_run_id: str | None = None
    status_code: CourseRunStatus = Field(default="DRAFT")
    created_by: str = Field(default=DEFAULT_CREATED_BY)

    @field_validator("created_by", mode="before")
    @classmethod
    def default_created_by(cls, value: str | None) -> str:
        return value or DEFAULT_CREATED_BY


class CourseRunData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # or UUID, depending on your DB column type
    course_id: int
    version_number: int
    created_from_run_id: str | None
    status_code: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class CourseRunResponse(BaseModel):
    """Standard API response envelope for the Course Run endpoint."""

    success: bool
    data: CourseRunData
