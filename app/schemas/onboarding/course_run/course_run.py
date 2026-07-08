"""Pydantic request/response schemas for the Course Run API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PREFIX = "RUN-"
DEFAULT_CREATED_BY = "system"

CourseRunStatus = Literal["DRAFT", "GENERATING", "GENERATED", "FAILED", "CANCELLED"]


def generate_id() -> str:
    """Generate a unique, readable course-run id, e.g. RUN-9F3A1C2B."""
    return f"{ID_PREFIX}{uuid.uuid4().hex[:8].upper()}"


class CourseRunCreate(BaseModel):
    """Payload accepted from the frontend. `id` is never supplied here."""

    course_id: int = Field(..., description="Id of the course this run belongs to")
    created_from_run_id: str | None = Field(
        default=None, max_length=64, description="Id of the run this one was branched from, if any"
    )
    created_by: str | None = Field(
        default=None, max_length=255, description="Who created this run; defaults to 'system' if omitted"
    )


class CourseRunInternal(BaseModel):
    """Server-side record with auto-generated fields, ready to persist."""

    id: str = Field(default_factory=generate_id)
    course_id: str
    version_number: int
    created_from_run_id: str | None = None
    status_code: CourseRunStatus = Field(default="DRAFT")
    created_by: str = Field(default=DEFAULT_CREATED_BY)

    @field_validator("created_by", mode="before")
    @classmethod
    def default_created_by(cls, value: str | None) -> str:
        return value or DEFAULT_CREATED_BY


class CourseRunData(BaseModel):
    """Course-run record as returned to the frontend."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
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
